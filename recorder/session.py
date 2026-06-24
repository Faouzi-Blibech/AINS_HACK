"""In-process recording session: single source of truth for an SDK-aware run.

A contextvar holds the active session. The HTTP/MCP proxy (a separate thread)
and the @record_tool decorator both read it / share its step-id allocator so all
three transports land in ONE trace with one collision-free step sequence.
"""
from __future__ import annotations

import contextvars
import inspect
import json
import threading
import time
import uuid

from recorder.capture import build_sdk_step, sdk_identity
from recorder.policy import Policy
from trace_store.store import TraceStore

_active: contextvars.ContextVar = contextvars.ContextVar("cassette_session", default=None)


def current_session():
    return _active.get()


class ReplayDivergence(Exception):
    """Replay hit a call with no recorded step (fail closed for side effects)."""


class RecordingSession:
    def __init__(self, *, mode: str, store: TraceStore, run_id: str, policy: Policy,
                 replayer=None, register_run: bool = True,
                 schema_version: str = "1.0", agent: str = "",
                 parent_run_id: str | None = None, fork_step_id: int | None = None) -> None:
        self.mode = mode
        self.store = store
        self.run_id = run_id
        self.policy = policy
        self.replayer = replayer
        self.schema_version = schema_version
        self.agent = agent
        self.parent_run_id = parent_run_id
        self.fork_step_id = fork_step_id
        self._counter = 0
        self._lock = threading.Lock()
        self._token = None
        self._t0 = time.time()
        self._register_run = register_run
        # replay tallies (sdk only; merged with the proxy report by the driver)
        self.served = self.divergences = self.side_effecting_served = 0
        # parallel tool-call grouping (schema v1.1). record_llm arms a group
        # when it sees >=2 tool_calls in one model response; record_sdk consumes
        # it so the batched tool_call steps share one parallel_group UUID and
        # point causal_parents at the dispatching llm_call. The next (fan-in)
        # llm_call consumes the collected sibling step_ids as its parents.
        self.pending_parallel_group: str | None = None
        self._parallel_remaining = 0
        self._parallel_dispatch_step_id: int | None = None
        self._parallel_siblings: list[int] = []

    # lifecycle ---------------------------------------------------------
    def start(self) -> "RecordingSession":
        if self.mode == "record" and self._register_run:
            self.store.start_run(self.run_id, agent=self.agent,
                                 mode="record-over" if self.parent_run_id else "record",
                                 created_at_ms=int(self._t0 * 1000),
                                 schema_version=self.schema_version,
                                 parent_run_id=self.parent_run_id,
                                 fork_step_id=self.fork_step_id)
        self._token = _active.set(self)
        return self

    def __enter__(self) -> "RecordingSession":
        return self if self._token is not None else self.start()

    def __exit__(self, *exc) -> None:
        if self.mode == "record" and self._register_run:
            # Run status reflects the recorded steps: error if any step errored.
            status = "ok"
            try:
                doc = self.store.get_run(self.run_id)
                if any(s.get("status") == "error" for s in doc.get("steps", [])):
                    status = "error"
            except Exception:
                pass
            self.store.finish_run(self.run_id, status=status,
                                  duration_ms=int((time.time() - self._t0) * 1000))
        if self._token is not None:
            _active.reset(self._token)
            self._token = None

    # shared step-id allocator -----------------------------------------
    def next_step_id(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    # parallel tool-call grouping (schema v1.1) -------------------------
    def arm_parallel_group(self, n_tool_calls: int, dispatch_step_id: int) -> None:
        """Arm a parallel batch after recording a model response.

        Called by record_llm. When the response dispatched >=2 tool calls they
        ran concurrently and share one parallel_group UUID; a single (or zero)
        tool call is sequential and gets no group.
        """
        with self._lock:
            if n_tool_calls >= 2:
                self.pending_parallel_group = f"pg-{uuid.uuid4().hex[:12]}"
                self._parallel_remaining = n_tool_calls
                self._parallel_dispatch_step_id = dispatch_step_id
                self._parallel_siblings = []
            else:
                self.pending_parallel_group = None
                self._parallel_remaining = 0
                self._parallel_dispatch_step_id = None

    def take_parallel_for_tool(self, step_id: int, default_parents: list):
        """Return (parallel_group, causal_parents) for the next tool_call step.

        While a batch is armed each tool joins the group, its causal parent is
        the dispatching llm_call (not the previous sibling), and its step_id is
        collected for the fan-in llm_call. Otherwise returns (None, default).
        """
        with self._lock:
            if self.pending_parallel_group and self._parallel_remaining > 0:
                group = self.pending_parallel_group
                parents = ([self._parallel_dispatch_step_id]
                           if self._parallel_dispatch_step_id is not None
                           else default_parents)
                self._parallel_siblings.append(step_id)
                self._parallel_remaining -= 1
                if self._parallel_remaining == 0:
                    self.pending_parallel_group = None
                return group, parents
        return None, default_parents

    def consume_fanin_parents(self):
        """Return the collected parallel sibling step_ids (then clear), else None.

        The first llm_call after a parallel batch synthesises the siblings'
        results, so its causal_parents are all the sibling step_ids.
        """
        with self._lock:
            if self._parallel_siblings:
                parents = list(self._parallel_siblings)
                self._parallel_siblings = []
                return parents
        return None

    # record ------------------------------------------------------------
    def record_sdk(self, *, tool, args, result, side_effecting, latency_ms, ts_ms,
                   status: str = "ok") -> None:
        sid = self.next_step_id()
        default_parents = [sid - 1] if sid > 1 else []
        parallel_group, causal_parents = self.take_parallel_for_tool(sid, default_parents)
        step = build_sdk_step(step_id=sid, prev_step_id=sid - 1 if sid > 1 else None,
                              tool=tool, args=args, result=result,
                              side_effecting=side_effecting, latency_ms=latency_ms,
                              ts_ms=ts_ms, policy=self.policy,
                              parallel_group=parallel_group,
                              causal_parents=causal_parents, status=status)
        try:
            self.store.append_step(self.run_id, step)
        except Exception as exc:  # record is best-effort, never crash the agent
            print(f"[cassette] failed to record sdk step for {tool!r}: {exc}")

    # replay ------------------------------------------------------------
    def _replayer_response_for(self, ident: str, tool: str):
        """Ask the replayer for a recorded response, passing the tool name as a
        ``tool_hint`` when the replayer's response_for accepts it.

        The hint lets a parallel-aware replayer recover the correct recorded
        response from a sibling in the same parallel_group when an args hash
        drifts. Replayers whose response_for has no tool_hint parameter are
        called unchanged, so behaviour is identical for them.
        """
        replayer = self.replayer
        try:
            accepts_hint = "tool_hint" in inspect.signature(replayer.response_for).parameters
        except (TypeError, ValueError):
            accepts_hint = False
        if accepts_hint:
            return replayer.response_for(ident, tool_hint=tool)
        return replayer.response_for(ident)

    def replay_sdk(self, *, tool, args, side_effecting):
        ident = sdk_identity(tool, args or {}, self.policy.volatile_fields())
        resp = self._replayer_response_for(ident, tool) if self.replayer else None
        # A None response, or a synthesized envelope (B's Replayer fabricates one
        # when synthesize_on_miss=True), both mean a genuine tape miss. The
        # recorder's SDK replay is a divergence-detecting caller, so a miss must
        # fail closed -- never serve a fabricated response (side-effecting or
        # not), preserving the core safety invariant.
        if resp is None or resp.get("synthesized"):
            self.divergences += 1
            raise ReplayDivergence(f"no recorded sdk step for {tool!r}")
        self.served += 1
        if resp.get("side_effecting"):
            self.side_effecting_served += 1
        body = resp.get("body")
        if body in (None, ""):
            return None
        try:
            return json.loads(body)
        except (ValueError, TypeError):
            return body

    def replay_report(self) -> dict:
        return {"served": self.served, "divergences": self.divergences,
                "side_effecting_served": self.side_effecting_served,
                "live_executed": 0}
