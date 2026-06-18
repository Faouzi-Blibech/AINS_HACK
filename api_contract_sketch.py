"""
Cassette API contract sketch (Day 1).

FastAPI routing and Pydantic schemas only — no backend logic.
Models align with docs/trace_schema.json.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(
    title="Cassette API",
    description="Flight recorder and deterministic replay engine for AI agents.",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Enums (mirror docs/trace_schema.json)
# ---------------------------------------------------------------------------


class TraceMode(str, Enum):
    record = "record"
    play = "play"
    record_over = "record-over"


class RunStatus(str, Enum):
    ok = "ok"
    error = "error"
    timeout = "timeout"
    aborted = "aborted"


class StepType(str, Enum):
    llm_call = "llm_call"
    tool_call = "tool_call"


class StepStatus(str, Enum):
    ok = "ok"
    error = "error"


class Transport(str, Enum):
    http = "http"
    mcp = "mcp"
    sdk = "sdk"


# ---------------------------------------------------------------------------
# Trace schema models (docs/trace_schema.json)
# ---------------------------------------------------------------------------


class TokenUsage(BaseModel):
    prompt: Optional[int] = None
    completion: Optional[int] = None


class Step(BaseModel):
    step_id: int
    type: StepType
    timestamp_ms: int
    latency_ms: Optional[int] = None
    status: Optional[StepStatus] = None
    causal_parents: list[int] = Field(
        default_factory=list,
        description="step_ids whose outputs caused this step.",
    )
    side_effecting: Optional[bool] = None
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Self-reported confidence at this step (0..1).",
    )
    # llm_call fields
    model: Optional[str] = None
    params: Optional[dict[str, Any]] = None
    prompt_blob: Optional[str] = None
    response_blob: Optional[str] = None
    token_usage: Optional[TokenUsage] = None
    # tool_call fields
    tool: Optional[str] = None
    transport: Optional[Transport] = None
    args_blob: Optional[str] = None
    result_blob: Optional[str] = None


class Trace(BaseModel):
    schema_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    run_id: str
    created_at_ms: int
    steps: list[Step]
    agent: Optional[str] = None
    mode: Optional[TraceMode] = None
    parent_run_id: Optional[str] = None
    fork_step_id: Optional[int] = None
    status: Optional[RunStatus] = None
    duration_ms: Optional[int] = None


# ---------------------------------------------------------------------------
# API-specific response / request models
# ---------------------------------------------------------------------------


class RunSummary(BaseModel):
    run_id: str
    created_at_ms: int
    step_count: int
    agent: Optional[str] = None
    mode: Optional[TraceMode] = None
    status: Optional[RunStatus] = None
    parent_run_id: Optional[str] = None


class RunListResponse(BaseModel):
    runs: list[RunSummary]
    total: int


class ResolvedStepDetail(Step):
    """Step with blob references resolved to inline payloads."""

    prompt: Optional[str] = Field(
        default=None,
        description="Resolved content of prompt_blob (llm_call only).",
    )
    response: Optional[str] = Field(
        default=None,
        description="Resolved content of response_blob (llm_call only).",
    )
    args: Optional[dict[str, Any]] = Field(
        default=None,
        description="Resolved content of args_blob (tool_call only).",
    )
    result: Optional[Any] = Field(
        default=None,
        description="Resolved content of result_blob (tool_call only).",
    )


class ReplayRequest(BaseModel):
    mode: TraceMode = Field(
        default=TraceMode.play,
        description="Replay mode; play returns recorded responses with side effects mocked.",
    )


class ReplayResponse(BaseModel):
    run_id: str
    replay_run_id: str
    status: str = Field(description="e.g. queued, running, completed")
    side_effect_count: int = Field(
        default=0,
        description="Must remain 0 during replay (core safety invariant).",
    )


class DivergeRequest(BaseModel):
    step_id: int = Field(description="Step at which to inject the edit.")
    instruction: Optional[str] = Field(
        default=None,
        description="Plain-English fix for the debug agent to translate into an injection.",
    )
    injection: Optional[dict[str, Any]] = Field(
        default=None,
        description="Direct JSON injection (prompt or tool result override).",
    )


class DivergeResponse(BaseModel):
    parent_run_id: str
    fork_run_id: str
    fork_step_id: int
    status: str = Field(description="e.g. queued, running, completed")


class BlameStepScore(BaseModel):
    step_id: int
    blame_score: float = Field(ge=0.0, le=1.0)
    rationale: Optional[str] = None


class BlameGraphResponse(BaseModel):
    run_id: str
    failed_step_id: Optional[int] = None
    root_cause_step_id: Optional[int] = None
    verdict: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    steps: list[BlameStepScore]


class CounterfactualVariant(BaseModel):
    rank: int
    variant_id: str
    prompt_variant: str
    outcome: str
    score: float = Field(ge=0.0, le=1.0)


class CounterfactualResponse(BaseModel):
    run_id: str
    variants: list[CounterfactualVariant]
    winner_variant_id: Optional[str] = None


class FailureLibraryEntry(BaseModel):
    failure_pattern: str
    blame_step: int
    fix_that_worked: str
    agent_config: str
    determinism_rate: float = Field(ge=0.0, le=1.0)


class FailureLibraryResponse(BaseModel):
    entries: list[FailureLibraryEntry]
    total: int


# ---------------------------------------------------------------------------
# Routes (contract only — raise 501 until implemented)
# ---------------------------------------------------------------------------

_NOT_IMPLEMENTED = HTTPException(
    status_code=501,
    detail="Endpoint defined in API contract; implementation pending.",
)


@app.get("/runs", response_model=RunListResponse, tags=["runs"])
def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> RunListResponse:
    """List recorded runs (summary metadata only)."""
    raise _NOT_IMPLEMENTED


@app.get("/runs/{run_id}", response_model=Trace, tags=["runs"])
def get_trace(run_id: str) -> Trace:
    """Get the full trace for a run."""
    raise _NOT_IMPLEMENTED


@app.get(
    "/runs/{run_id}/steps/{step_id}",
    response_model=ResolvedStepDetail,
    tags=["runs"],
)
def get_step(run_id: str, step_id: int) -> ResolvedStepDetail:
    """Get a single step with blob references resolved to inline payloads."""
    raise _NOT_IMPLEMENTED


@app.post("/runs/{run_id}/replay", response_model=ReplayResponse, tags=["replay"])
def trigger_replay(run_id: str, body: ReplayRequest) -> ReplayResponse:
    """Trigger deterministic replay of a recorded run."""
    raise _NOT_IMPLEMENTED


@app.post("/runs/{run_id}/diverge", response_model=DivergeResponse, tags=["replay"])
def trigger_diverge(run_id: str, body: DivergeRequest) -> DivergeResponse:
    """Trigger a record-over fork / divergence injection at a step."""
    raise _NOT_IMPLEMENTED


@app.get("/runs/{run_id}/blame", response_model=BlameGraphResponse, tags=["analysis"])
def get_blame_graph(run_id: str) -> BlameGraphResponse:
    """Get the Temporal Blame Graph for a run."""
    raise _NOT_IMPLEMENTED


@app.get(
    "/runs/{run_id}/counterfactual",
    response_model=CounterfactualResponse,
    tags=["analysis"],
)
def get_counterfactual(run_id: str) -> CounterfactualResponse:
    """Get ranked counterfactual prompt variants for a failing run."""
    raise _NOT_IMPLEMENTED


@app.get("/library", response_model=FailureLibraryResponse, tags=["library"])
def query_failure_library(
    q: Optional[str] = Query(default=None, description="Free-text relevance query."),
    agent_config: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> FailureLibraryResponse:
    """Query the persistent failure library (Layer 2)."""
    raise _NOT_IMPLEMENTED
