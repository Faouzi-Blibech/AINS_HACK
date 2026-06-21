"""In-process recording session: single source of truth for an SDK-aware run.

A contextvar holds the active session. The HTTP/MCP proxy (a separate thread)
and the @record_tool decorator both read it / share its step-id allocator so all
three transports land in ONE trace with one collision-free step sequence.
"""
from __future__ import annotations

import contextvars
import json
import threading
import time

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
                 replayer=None, register_run: bool = True) -> None:
        self.mode = mode
        self.store = store
        self.run_id = run_id
        self.policy = policy
        self.replayer = replayer
        self._counter = 0
        self._lock = threading.Lock()
        self._token = None
        self._t0 = time.time()
        self._register_run = register_run
        # replay tallies (sdk only; merged with the proxy report by the driver)
        self.served = self.divergences = self.side_effecting_served = 0

    # lifecycle ---------------------------------------------------------
    def start(self) -> "RecordingSession":
        if self.mode == "record" and self._register_run:
            self.store.start_run(self.run_id, agent="", mode="record",
                                 created_at_ms=int(self._t0 * 1000))
        self._token = _active.set(self)
        return self

    def __enter__(self) -> "RecordingSession":
        return self if self._token is not None else self.start()

    def __exit__(self, *exc) -> None:
        if self.mode == "record" and self._register_run:
            self.store.finish_run(self.run_id, status="ok",
                                  duration_ms=int((time.time() - self._t0) * 1000))
        if self._token is not None:
            _active.reset(self._token)
            self._token = None

    # shared step-id allocator -----------------------------------------
    def next_step_id(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    # record ------------------------------------------------------------
    def record_sdk(self, *, tool, args, result, side_effecting, latency_ms, ts_ms) -> None:
        sid = self.next_step_id()
        step = build_sdk_step(step_id=sid, prev_step_id=sid - 1 if sid > 1 else None,
                              tool=tool, args=args, result=result,
                              side_effecting=side_effecting, latency_ms=latency_ms,
                              ts_ms=ts_ms, policy=self.policy)
        try:
            self.store.append_step(self.run_id, step)
        except Exception as exc:  # record is best-effort, never crash the agent
            print(f"[cassette] failed to record sdk step for {tool!r}: {exc}")

    # replay ------------------------------------------------------------
    def replay_sdk(self, *, tool, args, side_effecting):
        ident = sdk_identity(tool, args or {}, self.policy.volatile_fields())
        resp = self.replayer.response_for(ident) if self.replayer else None
        if resp is None:
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
