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
from typing import Any, Optional

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
    allow_methods=["GET"],
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
