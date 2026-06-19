"""Deterministic replay runner (Play mode).

Re-executes a recorded run step-by-step. Tool calls are intercepted and served
from the tape; no live endpoint is hit. side_effecting calls are ALWAYS mocked.

Skeleton only.
"""
from __future__ import annotations


import json
from collections import deque
from dataclasses import dataclass
from typing import Any

from trace_store.store import TraceStore
from trace_store.blob_store import fetch_blob


@dataclass
class ReplayResult:
    """Outcome of a replay: final state, executed steps, side-effect count."""
    run_id: str
    steps_replayed: int
    side_effect_count: int
    status: str


class ReplayError(Exception):
    """Raised when replay diverges unexpectedly."""


class Replayer:
    """Deterministic replay runner (Play mode).
    
    Re-executes a recorded run step-by-step. Tool calls are intercepted and served
    from the tape; no live endpoint is hit. side_effecting calls are ALWAYS mocked.
    """

    def __init__(self, trace_store: TraceStore, run_id: str) -> None:
        self.store = trace_store
        self.run_id = run_id
        
        # Load the trace into memory for sequential playback
        self.trace_doc = self.store.get_run(self.run_id)
        self.steps = self.trace_doc["steps"]
        
        self.cursor = 0
        self.side_effect_count = 0  # invariant: must stay 0 on replay

        self.side_effecting_served = 0
        self._index: dict[str, deque] = {}
        for step in self.steps:
            ident = step.get("request_identity")
            if ident is not None:
                self._index.setdefault(ident, deque()).append(step)

    def response_for(self, request_identity: str) -> dict | None:
        """Serve the recorded response for a request identity, or None (divergence).

        Used by the HTTP proxy hook and by single-step mini-replays. Never
        executes a side effect: side-effecting steps are served from tape and
        counted via side_effecting_served; side_effect_count stays 0.
        """
        queue = self._index.get(request_identity)
        if not queue:
            return None
        step = queue.popleft()
        ref = step.get("response_blob") if step["type"] == "llm_call" else step.get("result_blob")
        body = fetch_blob(ref) if ref else ""
        if step.get("side_effecting"):
            self.side_effecting_served += 1
        return {"status_code": int(step.get("status_code", 200)),
                "body": body, "side_effecting": bool(step.get("side_effecting"))}

    def get_next_response(self, expected_type: str) -> dict[str, Any]:
        """Simulate proxy interception: get the response for the next step.
        
        Day 2 implementation: purely sequential matching. 
        Day 3 upgrade: match on prompt/args hashes from real proxy traffic.
        """
        if self.cursor >= len(self.steps):
            raise ReplayError("Agent requested a step, but tape is out of recorded steps.")

        step = self.steps[self.cursor]
        self.cursor += 1

        if step["type"] != expected_type:
            raise ReplayError(f"Expected {expected_type}, but tape has {step['type']} at step {self.cursor}")

        # Core safety invariant: side-effecting tools are ALWAYS mocked
        if step.get("side_effecting"):
            # We explicitly do NOT increment self.side_effect_count
            # In a real environment, the actual proxy ensures the HTTP request never fires.
            # Here, we just acknowledge it's mocked.
            pass

        # Resolve the blob to return the actual payload
        payload = {}
        if step["type"] == "llm_call":
            if "response_blob" in step:
                payload = json.loads(fetch_blob(step["response_blob"]))
        elif step["type"] == "tool_call":
            if "result_blob" in step:
                payload = json.loads(fetch_blob(step["result_blob"]))

        return {
            "step_id": step["step_id"],
            "mocked_side_effect": bool(step.get("side_effecting")),
            "payload": payload
        }

    def finish(self) -> ReplayResult:
        """Complete the replay session and return the summary."""
        return ReplayResult(
            run_id=self.run_id,
            steps_replayed=self.cursor,
            side_effect_count=self.side_effect_count,
            status="ok" if self.cursor == len(self.steps) else "incomplete"
        )
