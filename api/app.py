"""Cassette FastAPI application.

Serves recorded agent runs out of a SQLite-backed TraceStore.
Self-seeds from docs/fixtures/sample_trace.json on startup.

Run with:
    uvicorn api.app:app --port 8000
"""
from __future__ import annotations

import json
import os
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
from api.failure_memory import FAILURE_MEMORY
from api.seed import seed_store
from trace_store.store import TraceStore
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

# Maps run_id -> set of step_ids whose correction resolves the failure.
# This is the seam for the real divergence engine: once available, replace
# ScriptedReplay with replay_engine.Replayer and remove the entries below.
RESOLVES_AT: dict[str, set[int]] = {
    "run-fixture-001": {2},
}


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
                parent_run_id=None,
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

    Uses ScriptedReplay as the perturbation oracle. RESOLVES_AT is the seam
    for the real divergence engine: once available, replace ScriptedReplay
    with replay_engine.Replayer and populate RESOLVES_AT from it.
    """
    try:
        doc = store.get_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found")

    resolves_at = RESOLVES_AT.get(run_id, set())
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
    entries = FAILURE_MEMORY
    if q:
        q_lower = q.lower()
        entries = [
            e for e in entries
            if q_lower in e["failure_pattern"].lower()
            or q_lower in e["fix_that_worked"].lower()
        ]
    parsed = [FailureLibraryEntry(**e) for e in entries]
    return FailureLibraryResponse(entries=parsed, total=len(parsed))


@app.get("/metrics", response_model=MetricsResponse, tags=["metrics"])
def get_metrics() -> MetricsResponse:
    """Return top-level metric cards computed from the current run store.

    contained_pct is always 100 (side effects are always mocked on replay).
    determinism_rate is stubbed at 1.0 (seam: wire to real replay divergence
    tracking once the divergence engine is available).
    """
    runs = store.list_runs()
    runs_24h = len(runs)
    ok_count = sum(1 for r in runs if r.get("status") == "ok")
    pass_rate = ok_count / max(runs_24h, 1)

    return MetricsResponse(
        runs_24h=runs_24h,
        pass_rate=pass_rate,
        contained_pct=100,
        determinism_rate=1.0,  # stub: seam for real replay divergence metric
    )


@app.get("/eval", response_model=EvalReport, tags=["eval"])
def get_eval_report() -> EvalReport:
    """Return the eval harness results.

    Reads the results JSON written by eval/harness.py. If the file is missing
    or cannot be parsed, returns an EvalReport with available=False and empty
    metrics/caveats (the UI renders a 'not run yet' state). Never returns 404
    or 500 for a missing results file.
    """
    _unavailable = EvalReport(available=False, metrics=[], caveats=[])
    try:
        path = Path(EVAL_RESULTS_PATH)
        if not path.exists():
            return _unavailable
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return EvalReport(**data)
    except Exception:
        return _unavailable


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


@app.post("/runs/{run_id}/diverge", response_model=DivergeResponse, tags=["dock"])
def diverge(run_id: str, body: DivergeRequest) -> DivergeResponse:
    """Fork the run at step_id with the given edit, diff the result.

    Works offline without any LLM key. side_effect_count is always 0.
    """
    try:
        store.get_run(run_id)
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

    # Resolve step_id: use body value, or fall back to RESOLVES_AT seam, or step 1
    step_id = body.step_id
    if step_id is None:
        resolves_set = RESOLVES_AT.get(run_id, set())
        step_id = min(resolves_set) if resolves_set else 1

    n = body.n if body.n is not None else 4

    resolves_at = RESOLVES_AT.get(run_id, set())
    engine = ScriptedReplay(doc, resolves_at)

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
