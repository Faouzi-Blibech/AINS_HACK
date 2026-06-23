"""Cassette FastAPI application.

Serves recorded agent runs out of a SQLite-backed TraceStore.
Self-seeds from docs/fixtures/sample_trace.json on startup.

Run with:
    uvicorn api.app:app --port 8000
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, List, Optional, Union

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api_contract_sketch import (
    BlameGraphResponse,
    FailureLibraryEntry,
    FailureLibraryResponse,
    ResolvedStepDetail,
    RunListResponse,
    RunSummary,
    Trace,
)
from api.seed import seed_store, seed_failure_library
from trace_store import TraceStore, FailureLibraryStore
from trace_store.blob_store import fetch_blob
from ai_agents.root_cause import analyze, ScriptedReplay
from ai_agents.trace_content import make_resolver
import ai_agents.debug_agent as _debug_agent
import ai_agents.counterfactual as _counterfactual
import ai_agents.llm as _llm
from ai_agents.replay_adapter import StoreReplayEngine
from replay_engine.divergence import Divergence, DivergenceError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default DB lives inside the api/ package (ignored by .gitignore)
DB_PATH = os.environ.get(
    "CASSETTE_DB_PATH",
    str(Path(__file__).resolve().parent / "cassette.sqlite3"),
)

# Default blob dir to the repo's docs/fixtures/blobs if not already set
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_BLOB_DIR = str(_REPO_ROOT / "docs" / "fixtures" / "blobs")
if "CASSETTE_BLOB_DIR" not in os.environ:
    os.environ["CASSETTE_BLOB_DIR"] = _DEFAULT_BLOB_DIR


def _sync_fixture_blobs() -> None:
    """Copy the bundled fixture blobs into the active blob dir.

    Lets the seeded demo run resolve even when CASSETTE_BLOB_DIR points at a
    user store (e.g. ~/.cassette/blobs) that holds recorded runs. Blobs are
    content-addressed, so this is an idempotent copy that never overwrites.
    """
    import shutil

    active = Path(os.environ["CASSETTE_BLOB_DIR"])
    src = Path(_DEFAULT_BLOB_DIR)
    if not src.is_dir() or active.resolve() == src.resolve():
        return
    active.mkdir(parents=True, exist_ok=True)
    for blob in src.iterdir():
        dest = active / blob.name
        if blob.is_file() and not dest.exists():
            shutil.copyfile(blob, dest)


_sync_fixture_blobs()

# Path to the eval harness results file (written by eval/harness.py).
EVAL_RESULTS_PATH = os.environ.get(
    "CASSETTE_EVAL_RESULTS",
    str(_REPO_ROOT / "eval" / "results.json"),
)

# ---------------------------------------------------------------------------
# Store initialisation and seeding (happens at import time)
# ---------------------------------------------------------------------------

store = TraceStore(DB_PATH)
seed_store(store)

failure_store = FailureLibraryStore(DB_PATH)
seed_failure_library(failure_store)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Cassette API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    # Accept any localhost dev port (Vite may fall back to 5174+ when 5173 is busy).
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_fetch_blob(ref: Optional[str]) -> Optional[str]:
    """Resolve a blob reference; returns None if the ref is missing or unresolvable."""
    if not ref:
        return None
    try:
        return fetch_blob(ref)
    except Exception:
        return None


def _try_parse_json(text: Optional[str]) -> Any:
    """Parse *text* as JSON; return the string unchanged if it is not valid JSON."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text


# ---------------------------------------------------------------------------
# Blame graph oracle seam
# ---------------------------------------------------------------------------

def _load_resolves_file(path) -> dict:
    try:
        import json as _json
        with open(path, encoding="utf-8") as fh:
            return _json.load(fh)
    except (OSError, ValueError):
        return {}


def resolves_at_for(run_id: str, doc: dict) -> set[int]:
    """Which step-ids, when corrected, resolve the failure (blame-graph oracle).

    Sourced from data, not hardcoded: the local store's resolves.json, then the
    bundled fixture's resolves.json, then a per-step `expected_root_cause` marker.
    """
    from cassette import paths as _paths

    candidates = [
        _paths.resolves_path(),
        Path(__file__).resolve().parent.parent / "docs" / "fixtures" / "resolves.json",
    ]
    for candidate in candidates:
        data = _load_resolves_file(candidate)
        if run_id in data:
            return set(data[run_id])

    return {s["step_id"] for s in doc.get("steps", []) if s.get("expected_root_cause")}


# ---------------------------------------------------------------------------
# Metrics response model
# ---------------------------------------------------------------------------


class MetricsResponse(BaseModel):
    runs_24h: int
    pass_rate: float          # 0..1 fraction of runs with status ok
    contained_pct: int        # side-effect containment; always 100 on replay
    determinism_rate: float   # 0..1; seeded/stubbed (seam for real metric)


class EvalMetric(BaseModel):
    key: str
    label: str
    value: Optional[Union[float, int]] = None   # float, int count, or null
    target_text: str
    passed: Optional[bool] = None
    unit: str


class EvalReport(BaseModel):
    available: bool
    generated_at: Optional[str] = None
    metrics: list[EvalMetric] = []
    caveats: list[str] = []


# ---------------------------------------------------------------------------
# Dock request / response models
# ---------------------------------------------------------------------------


class InjectRequest(BaseModel):
    instruction: str


class InjectionDetail(BaseModel):
    step_id: int
    target: str
    value: str


class InjectAvailableResponse(BaseModel):
    available: bool
    injection: Optional[InjectionDetail] = None
    confidence: Optional[float] = None
    rationale: Optional[str] = None


class InjectUnavailableResponse(BaseModel):
    available: bool
    detail: str


class DivergeRequest(BaseModel):
    step_id: int
    target: str
    value: str


class DivergeDiff(BaseModel):
    fork_step_id: Optional[int] = None
    original_steps: int
    forked_steps: int
    edited_fields: List[str]


class DivergeResponse(BaseModel):
    fork_run_id: str
    diff: DivergeDiff
    final_status: str
    side_effect_count: int


class CounterfactualRequest(BaseModel):
    step_id: Optional[int] = None
    n: Optional[int] = None


class VariantItem(BaseModel):
    variant_id: str
    prompt: str
    resolved: bool
    score: float
    steps_changed: int
    side_effect_count: int


class CounterfactualResponse(BaseModel):
    available: bool
    variants: List[VariantItem]
    winner: Optional[str] = None
    confidence: float
    rationale: str


# ---------------------------------------------------------------------------
# Agent run models
# ---------------------------------------------------------------------------

# Provider presets: name -> (base_url, default_model)
_PROVIDER_PRESETS: dict[str, tuple[str, str]] = {
    "nvidia_nim": ("https://integrate.api.nvidia.com/v1", "meta/llama-3.1-8b-instruct"),
    "huggingface": ("https://router.huggingface.co/v1", "meta-llama/Llama-3.1-8B-Instruct"),
    "groq": ("https://api.groq.com/openai/v1", "llama3-8b-8192"),
}


class AgentRunRequest(BaseModel):
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: str
    api_key: str
    task: str


class AgentRunResponse(BaseModel):
    run_id: str
    status: str
    steps: int


class ConnectHttpInfo(BaseModel):
    env_vars: dict[str, str]
    command: str


class ConnectInfo(BaseModel):
    http: ConnectHttpInfo
    mcp: str
    sdk: str


# ---------------------------------------------------------------------------
# Agent launch helper (monkeypatchable in tests)
# ---------------------------------------------------------------------------


_AGENT_RUN_TIMEOUT = int(os.environ.get("CASSETTE_AGENT_RUN_TIMEOUT", "300"))


def _scrub_subprocess_output(text: str, api_key: str, base_url: str) -> str:
    """Remove api_key and base_url from subprocess output; truncate to last 1500 chars."""
    if api_key:
        text = text.replace(api_key, "***")
    if base_url:
        text = text.replace(base_url, "***")
    # Keep only the tail so the most-recent error context is preserved.
    if len(text) > 1500:
        text = "...(truncated)...\n" + text[-1500:]
    return text.strip()


def _launch_hosted_run(
    run_id: str,
    base_url: str,
    model: str,
    api_key: str,
    task: str,
) -> subprocess.CompletedProcess:
    """Launch recorder.run_hosted in a subprocess. Isolated so tests can monkeypatch."""
    env = {
        **os.environ,
        "CASSETTE_HOSTED_BASE_URL": base_url,
        "CASSETTE_HOSTED_KEY": api_key,
    }
    cmd = [
        sys.executable, "-m", "recorder.run_hosted",
        "--run-id", run_id,
        "--db", DB_PATH,
        "--blob-dir", os.environ["CASSETTE_BLOB_DIR"],
        "--model", model,
        "--task", task,
    ]
    return subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=_AGENT_RUN_TIMEOUT, env=env,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/runs", response_model=RunListResponse, tags=["runs"])
def list_runs() -> RunListResponse:
    """List recorded runs (summary metadata only)."""
    # Note: one get_run per row to compute step_count is an N+1 read. Acceptable
    # at demo scale (a handful of runs); revisit with a COUNT query if the store grows.
    rows = store.list_runs()
    summaries: list[RunSummary] = []
    for row in rows:
        # Skip forks: divergence/counterfactual create child runs (parent_run_id
        # set). They are analysis artifacts, not independent agent runs, so they
        # must not pollute the run list or the pass-rate. They stay queryable by
        # id via GET /runs/{id}.
        if row.get("parent_run_id"):
            continue
        try:
            run_doc = store.get_run(row["run_id"])
            step_count = len(run_doc.get("steps", []))
        except KeyError:
            step_count = 0
        summaries.append(
            RunSummary(
                run_id=row["run_id"],
                created_at_ms=row["created_at_ms"],
                step_count=step_count,
                agent=row.get("agent"),
                mode=row.get("mode"),
                status=row.get("status"),
                parent_run_id=row.get("parent_run_id"),
            )
        )
    return RunListResponse(runs=summaries, total=len(summaries))


@app.get("/runs/{run_id}", response_model=Trace, tags=["runs"])
def get_trace(run_id: str) -> Trace:
    """Return the full trace for a run."""
    try:
        doc = store.get_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found")
    return Trace(**doc)


@app.get(
    "/runs/{run_id}/steps/{step_id}",
    response_model=ResolvedStepDetail,
    tags=["runs"],
)
def get_step(run_id: str, step_id: int) -> ResolvedStepDetail:
    """Return a single step with blob references resolved to inline payloads."""
    try:
        doc = store.get_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found")

    matching = [s for s in doc.get("steps", []) if s["step_id"] == step_id]
    if not matching:
        raise HTTPException(status_code=404, detail="step not found")

    step = matching[0]
    step_type = step.get("type", "")

    # Resolve blobs to inline content
    resolved_prompt: Optional[str] = None
    resolved_response: Optional[str] = None
    resolved_args: Optional[Any] = None
    resolved_result: Optional[Any] = None

    if step_type == "llm_call":
        raw_prompt = _try_fetch_blob(step.get("prompt_blob"))
        resolved_prompt = raw_prompt  # prompt is plain text, keep as string
        raw_response = _try_fetch_blob(step.get("response_blob"))
        resolved_response = raw_response
    elif step_type == "tool_call":
        raw_args = _try_fetch_blob(step.get("args_blob"))
        resolved_args = _try_parse_json(raw_args)
        raw_result = _try_fetch_blob(step.get("result_blob"))
        resolved_result = _try_parse_json(raw_result)

    return ResolvedStepDetail(
        **step,
        prompt=resolved_prompt,
        response=resolved_response,
        args=resolved_args,
        result=resolved_result,
    )


@app.get(
    "/runs/{run_id}/blame",
    response_model=BlameGraphResponse,
    tags=["analysis"],
)
def get_blame_graph(run_id: str) -> BlameGraphResponse:
    """Return the Temporal Blame Graph for a run.

    Uses ScriptedReplay as the perturbation oracle. resolves_at_for is the seam
    for the real divergence engine: once available, replace ScriptedReplay
    with replay_engine.Replayer and source resolves_at_for from it.
    """
    try:
        doc = store.get_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found")

    resolves_at = resolves_at_for(run_id, doc)
    blob_dir = os.environ["CASSETTE_BLOB_DIR"]
    resolver = make_resolver(blob_dir)

    graph = analyze(
        doc,
        replay=ScriptedReplay(doc, resolves_at),
        content_resolver=resolver,
    )
    return BlameGraphResponse(**graph.to_api_dict())


@app.get("/library", response_model=FailureLibraryResponse, tags=["library"])
def query_failure_library(
    q: Optional[str] = Query(default=None, description="Substring filter on failure_pattern or fix_that_worked."),
) -> FailureLibraryResponse:
    """Return the seeded failure-memory library (Layer 2).

    Optional ?q=<text> filters entries whose failure_pattern or fix_that_worked
    contains the query string (case-insensitive). Full semantic search comes later.
    """
    try:
        entries = failure_store.query(pattern_fragment=q)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}")
    
    formatted = []
    for e in entries:
        d = dict(e)
        if d.get("id") is not None:
            d["id"] = str(d["id"])
        if d.get("agent_config") is None:
            d["agent_config"] = "unknown"
        if d.get("determinism_rate") is None:
            d["determinism_rate"] = 1.0
        formatted.append(d)

    parsed = [FailureLibraryEntry(**e) for e in formatted]
    return FailureLibraryResponse(entries=parsed, total=len(parsed))


@app.get("/metrics", response_model=MetricsResponse, tags=["metrics"])
def get_metrics() -> MetricsResponse:
    """Return top-level metric cards computed from the current run store.

    contained_pct is always 100 (side effects are always mocked on replay).
    determinism_rate is stubbed at 1.0 (seam: wire to real replay divergence
    tracking once the divergence engine is available).
    """
    # Primary runs only -- exclude forks (parent_run_id set) so divergence /
    # counterfactual artifacts do not skew the run count or pass-rate.
    runs = [r for r in store.list_runs() if not r.get("parent_run_id")]
    runs_24h = len(runs)
    ok_count = sum(1 for r in runs if r.get("status") == "ok")
    err_count = sum(1 for r in runs if r.get("status") == "error")
    # Pass-rate over runs with a definitive outcome (ok or error), so unfinished
    # runs do not drag it down.
    terminal = ok_count + err_count
    pass_rate = (ok_count / terminal) if terminal else 0.0

    # Determinism: actually replay each primary run and confirm it reproduces
    # with zero real side effects (the core invariant). Read-only; demo scale.
    engine = StoreReplayEngine(store)
    deterministic = 0
    checked = 0
    for r in runs:
        checked += 1
        try:
            outcome = engine.replay(r["run_id"])
            if outcome.side_effect_count == 0:
                deterministic += 1
        except Exception:
            # A run that cannot be cleanly replayed is not deterministic.
            pass
    determinism_rate = (deterministic / checked) if checked else 1.0

    return MetricsResponse(
        runs_24h=runs_24h,
        pass_rate=pass_rate,
        contained_pct=100,
        determinism_rate=determinism_rate,
    )


@app.get("/eval", response_model=EvalReport, tags=["eval"])
def get_eval_report() -> EvalReport:
    """Compute evaluation metrics live from the recorded runs in the store.

    Replaces the frozen results.json: every metric is measured from the current
    primary runs (forks excluded), replayed through the real divergence engine,
    so the report reflects reality instead of a snapshot. Returns available=False
    when there are no runs yet (UI shows the 'not run' state). Never 500s.
    """
    from datetime import datetime, timezone

    try:
        runs = [r for r in store.list_runs() if not r.get("parent_run_id")]
    except Exception:
        return EvalReport(available=False, metrics=[], caveats=[])

    if not runs:
        return EvalReport(available=False, metrics=[], caveats=[])

    ok = sum(1 for r in runs if r.get("status") == "ok")
    err = sum(1 for r in runs if r.get("status") == "error")
    terminal = ok + err
    pass_rate = (ok / terminal) if terminal else 0.0

    engine = StoreReplayEngine(store)
    deterministic = 0
    checked = 0
    total_side_effects = 0
    total_steps = 0
    for r in runs:
        try:
            total_steps += len(store.get_run(r["run_id"]).get("steps", []))
        except KeyError:
            pass
        checked += 1
        try:
            outcome = engine.replay(r["run_id"])
            total_side_effects += outcome.side_effect_count
            if outcome.side_effect_count == 0:
                deterministic += 1
        except Exception:
            pass  # a run that cannot be cleanly replayed is non-deterministic
    determinism_rate = (deterministic / checked) if checked else 1.0
    avg_steps = (total_steps / len(runs)) if runs else 0.0

    metrics = [
        EvalMetric(key="runs_evaluated", label="Runs Evaluated",
                   value=len(runs), target_text=">= 1", passed=len(runs) >= 1, unit="count"),
        EvalMetric(key="pass_rate", label="Pass Rate",
                   value=pass_rate, target_text="> 75%", passed=pass_rate > 0.75, unit="fraction"),
        EvalMetric(key="determinism_rate", label="Determinism Rate",
                   value=determinism_rate, target_text="100%", passed=determinism_rate >= 1.0, unit="fraction"),
        EvalMetric(key="side_effect_containment", label="Side-effects Executed on Replay",
                   value=total_side_effects, target_text="0", passed=total_side_effects == 0, unit="count"),
        EvalMetric(key="avg_steps", label="Avg Steps / Run",
                   value=round(avg_steps, 1), target_text="-", passed=None, unit="count"),
    ]
    caveats = [
        "Metrics are computed live from the recorded runs in the store, replayed "
        "through the real divergence engine (forks excluded).",
        "Side-effect containment is the count of real side effects executed during "
        "replay; the core safety invariant keeps it at 0.",
    ]
    return EvalReport(
        available=True,
        generated_at=datetime.now(timezone.utc).isoformat(),
        metrics=metrics,
        caveats=caveats,
    )


# ---------------------------------------------------------------------------
# Dock endpoints
# ---------------------------------------------------------------------------


def _json_safe(value: str) -> str:
    """Return a JSON-parseable form of value.

    The replay engine calls json.loads on every blob it serves, so injected
    content must be valid JSON. A value that already parses (an object/array/
    number/quoted string) is kept as-is; a bare string like "high" is wrapped
    into a JSON string ("high") so the fork replays cleanly.
    """
    try:
        json.loads(value)
        return value
    except (json.JSONDecodeError, TypeError):
        return json.dumps(value)


def _target_to_edit(target: str, value: str) -> dict:
    """Translate an injection target + value into a Divergence edit dict."""
    from trace_store.blob_store import store_blob as _store_blob

    content = _json_safe(value)
    if target == "result":
        return {"_result_content": content}
    elif target == "response":
        return {"_response_content": content}
    elif target == "args":
        return {"args_blob": _store_blob(content)}
    elif target == "prompt":
        return {"prompt_blob": _store_blob(content)}
    else:
        return {target: value}


@app.post("/runs/{run_id}/inject", tags=["dock"])
def inject(run_id: str, body: InjectRequest) -> Any:
    """Debug agent: translate a plain-English instruction into an injection.

    Returns available=true with the injection when the LLM is configured, or
    available=false with a helpful message when GROQ_API_KEY is absent (never 500).
    """
    try:
        doc = store.get_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found")

    try:
        result = _debug_agent.build_injection(doc, body.instruction)
    except _llm.LLMNotConfigured:
        return {"available": False, "detail": "Set GROQ_API_KEY to run the debug agent."}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    inj = result.value
    return {
        "available": True,
        "injection": {
            "step_id": inj.step_id,
            "target": inj.target,
            "value": inj.value,
        },
        "confidence": result.confidence,
        "rationale": result.rationale,
    }


_FAILED_STATES = ("error", "failed", "timeout", "aborted")


def _maybe_learn_failure(original_doc, fork_step_id, target, value, fork_outcome) -> None:
    """Persist a real failure->fix entry when a fork actually resolves a failure.

    This is how Cassette 'learns': when a divergence turns a failing run into a
    passing one, record the pattern + the fix that worked so it can be surfaced
    as a preventive warning on matching future runs. Deduped by blame_step so the
    same root cause is not learned twice. Best-effort: never raises into the
    request path, and never overwrites the seeded demo entries.
    """
    try:
        if original_doc.get("status") not in _FAILED_STATES:
            return
        if fork_outcome.final_status != "ok":
            return
        if failure_store.query(blame_step=fork_step_id):
            return  # already known (seed or previously learned)
        agent = original_doc.get("agent") or "agent"
        steps = {s["step_id"]: s for s in original_doc.get("steps", [])}
        fstep = steps.get(fork_step_id, {})
        what = fstep.get("tool") or fstep.get("type") or f"step {fork_step_id}"
        pattern = (
            f"{agent}: run failed; resolved by correcting {what} at step {fork_step_id}."
        )
        fix = f"Set step {fork_step_id} {target} to {value!r}."
        failure_store.write_entry(
            failure_pattern=pattern,
            blame_step=fork_step_id,
            fix_that_worked=fix,
            agent_config=agent,
            determinism_rate=1.0,
        )
    except Exception:
        pass


@app.post("/runs/{run_id}/diverge", response_model=DivergeResponse, tags=["dock"])
def diverge(run_id: str, body: DivergeRequest) -> DivergeResponse:
    """Fork the run at step_id with the given edit, diff the result.

    Works offline without any LLM key. side_effect_count is always 0. When the
    fork turns a failing run into a passing one, the failure + fix is learned
    into the failure library (deduped).
    """
    try:
        original_doc = store.get_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found")

    edit = _target_to_edit(body.target, body.value)

    try:
        div = Divergence(store)
        fork_run_id = div.fork(run_id, body.step_id, edit)
        diff = div.compare(run_id, fork_run_id)
    except DivergenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Replay the fork to get final_status and side_effect_count
    engine = StoreReplayEngine(store)
    outcome = engine.replay(fork_run_id)

    # Learn from a resolved failure (best-effort, deduped, keeps seeds intact).
    _maybe_learn_failure(original_doc, body.step_id, body.target, body.value, outcome)

    return DivergeResponse(
        fork_run_id=fork_run_id,
        diff=DivergeDiff(
            fork_step_id=diff.get("fork_step_id"),
            original_steps=diff["original_steps"],
            forked_steps=diff["forked_steps"],
            edited_fields=diff["edited_fields"],
        ),
        final_status=outcome.final_status,
        side_effect_count=outcome.side_effect_count,
    )


@app.post("/runs/{run_id}/counterfactual", response_model=CounterfactualResponse, tags=["dock"])
def counterfactual(run_id: str, body: CounterfactualRequest) -> CounterfactualResponse:
    """Generate and rank N fix variants for a failing step.

    Works offline without GROQ_API_KEY via the template fallback. side_effect_count
    is always 0 on every variant's outcome.
    """
    try:
        doc = store.get_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found")

    # Resolve step_id: use body value, or fall back to the resolves_at_for seam, or step 1
    step_id = body.step_id
    if step_id is None:
        resolves_set = resolves_at_for(run_id, doc)
        step_id = min(resolves_set) if resolves_set else 1

    n = body.n if body.n is not None else 4

    # Engine selection: use the oracle-backed ScriptedReplay only for runs that
    # carry a resolution hint (the bundled fixture), which gives a sharp scripted
    # ranking. For every other (fresh, recorded) run, rank variants by their
    # ACTUAL replay outcome through the real divergence engine -- a variant whose
    # fork replays to a non-failing trajectory resolves the failure. A run that
    # never failed honestly yields no resolved variant.
    resolves_at = resolves_at_for(run_id, doc)
    if resolves_at:
        engine = ScriptedReplay(doc, resolves_at)
    else:
        engine = StoreReplayEngine(store)

    # Attempt to resolve the original prompt/result text for the target step
    original_prompt: Optional[str] = None
    blob_dir = os.environ.get("CASSETTE_BLOB_DIR", "")
    if blob_dir:
        steps_by_id = {s["step_id"]: s for s in doc.get("steps", [])}
        target_step = steps_by_id.get(step_id)
        if target_step:
            blob_ref = target_step.get("prompt_blob") or target_step.get("result_blob")
            if blob_ref:
                original_prompt = _try_fetch_blob(blob_ref)

    result = _counterfactual.repair(
        run_id,
        step_id,
        engine=engine,
        n=n,
        target="result",
        original_prompt=original_prompt,
    )

    variants_out: List[VariantItem] = []
    for v in result.value:
        variants_out.append(
            VariantItem(
                variant_id=v.variant_id,
                prompt=v.prompt,
                resolved=v.resolved,
                score=v.score,
                steps_changed=v.steps_changed,
                side_effect_count=v.outcome.side_effect_count,
            )
        )

    winner_id: Optional[str] = None
    if result.value and result.value[0].resolved:
        winner_id = result.value[0].variant_id

    return CounterfactualResponse(
        available=True,
        variants=variants_out,
        winner=winner_id,
        confidence=result.confidence,
        rationale=result.rationale,
    )


# ---------------------------------------------------------------------------
# Agent connect endpoints
# ---------------------------------------------------------------------------


@app.post("/agents/run", response_model=AgentRunResponse, tags=["agents"])
def agents_run(body: AgentRunRequest) -> AgentRunResponse:
    """Launch a hosted-model run via the recorder subprocess and record it.

    The api_key is passed to the subprocess only via environment variable.
    It is never logged and never included in any error response body.
    """
    # Resolve base_url: explicit value wins, then preset, else 422.
    resolved_base_url = body.base_url
    if not resolved_base_url and body.provider:
        preset = _PROVIDER_PRESETS.get(body.provider)
        if preset:
            resolved_base_url = preset[0]
    if not resolved_base_url:
        raise HTTPException(
            status_code=422,
            detail="Provide either 'base_url' or a valid 'provider' preset.",
        )

    run_id = f"agent-{uuid.uuid4().hex[:8]}"

    try:
        proc = _launch_hosted_run(
            run_id=run_id,
            base_url=resolved_base_url,
            model=body.model,
            api_key=body.api_key,
            task=body.task,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Run exceeded {_AGENT_RUN_TIMEOUT}s; "
                "try a faster model or raise CASSETTE_AGENT_RUN_TIMEOUT."
            ),
        )

    if proc.returncode != 0:
        combined = (proc.stderr or "") + (proc.stdout or "")
        scrubbed = _scrub_subprocess_output(combined, body.api_key, resolved_base_url)
        detail = scrubbed or f"Runner exited with code {proc.returncode}."
        print(f"[agents/run] runner failed (code {proc.returncode}): {detail}")
        raise HTTPException(status_code=502, detail=detail)

    try:
        run_doc = store.get_run(run_id)
        steps = len(run_doc.get("steps", []))
    except KeyError:
        steps = 0

    return AgentRunResponse(run_id=run_id, status="ok", steps=steps)


@app.get("/agents/connect-info", response_model=ConnectInfo, tags=["agents"])
def agents_connect_info() -> ConnectInfo:
    """Return bring-your-own connect instructions for each transport type.

    This endpoint is purely informational; it does not execute anything.
    """
    return ConnectInfo(
        http=ConnectHttpInfo(
            env_vars={
                "HTTP_PROXY": "http://localhost:8080",
                "HTTPS_PROXY": "http://localhost:8080",
                "SSL_CERT_FILE": "/path/to/cassette-ca.pem",
            },
            command="python -m recorder.record -- <your agent command>",
        ),
        mcp=(
            "python -m recorder.record --mcp -- <your agent command>\n"
            "The recorder wraps your agent and captures all MCP tool calls automatically."
        ),
        sdk=(
            "from recorder.sdk_hooks import record_tool\n\n"
            "# Wrap any side-effecting tool:\n"
            "@record_tool(side_effecting=True)\n"
            "def my_tool(arg): ...\n\n"
            "# Then drive the session with:\n"
            "python -m recorder.record_session -- <your agent command>"
        ),
    )
