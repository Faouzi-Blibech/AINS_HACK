"""Deterministic replay runner (Play mode).

Re-executes a recorded run step-by-step. Tool calls are intercepted and served
from the tape; no live endpoint is hit. side_effecting calls are ALWAYS mocked.

Three matching strategies
-------------------------
Hash matching (primary, Day 3+ — Derbal):
    Abdelhedi's proxy hashes the outbound request the same way the recorder
    did at record time and passes that sha256:... ref here.
    ``get_response_for_hash(request_blob_ref)`` looks up the step with the
    matching ``args_blob`` (tool_call) or ``prompt_blob`` (llm_call) and
    returns the recorded response. Order-independent, robust against LLM
    step reordering.

Request-identity matching (proxy hook — Abdelhedi):
    ``response_for(request_identity)`` is the hook called by the HTTP proxy.
    Each step is indexed by its ``request_identity`` field (set by the recorder
    at record time). Returns None on divergence (unrecorded call path).

Sequential matching (fallback / testing — Derbal):
    ``get_next_response(expected_type)`` hands back steps in tape order.
    Simple and fast; safe only when the agent is strictly deterministic.
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
    """Raised when replay diverges unexpectedly (no recorded step for a hash,
    tape exhausted, or step-type mismatch)."""


class Replayer:
    """Deterministic replay runner (Play mode)."""

    def __init__(self, trace_store: TraceStore, run_id: str) -> None:
        self.store = trace_store
        self.run_id = run_id

        self.trace_doc = self.store.get_run(self.run_id)
        self.steps: list[dict[str, Any]] = self.trace_doc["steps"]

        # --- hash index (Derbal, Day 3+) ---
        # Maps args_blob / prompt_blob → step. O(1) lookup by content hash.
        self._hash_index: dict[str, dict[str, Any]] = {}
        for step in self.steps:
            key = step.get("args_blob") or step.get("prompt_blob")
            if key:
                self._hash_index[key] = step

        # --- request-identity index (Abdelhedi's HTTP proxy hook) ---
        # Maps request_identity → deque of matching steps (FIFO for duplicate
        # identical calls, e.g. two get_priority calls with the same args).
        self.side_effecting_served = 0
        self._index: dict[str, deque] = {}
        for step in self.steps:
            ident = step.get("request_identity")
            if ident is not None:
                self._index.setdefault(ident, deque()).append(step)

        # --- sequential cursor (fallback / tests) ---
        self._cursor = 0

        # Core safety counter — must remain 0 for the whole replay session.
        self.side_effect_count = 0

    # ------------------------------------------------------------------
    # Primary API — hash matching (Derbal)
    # ------------------------------------------------------------------

    def get_response_for_hash(self, request_blob_ref: str) -> dict[str, Any]:
        """Look up and return the recorded response for a given request hash.

        Called by Abdelhedi's proxy at replay time. The proxy hashes the
        outbound HTTP / MCP request body the exact same way the recorder did
        at record time, passes the resulting ``sha256:...`` ref here, and we
        return the payload that was recorded for it.

        Parameters
        ----------
        request_blob_ref:
            The ``sha256:...`` ref computed from the live request's body/args.
            This must match either an ``args_blob`` (tool_call) or a
            ``prompt_blob`` (llm_call) stored in the trace.
        """
        step = self._hash_index.get(request_blob_ref)
        if step is None:
            raise ReplayError(
                f"No recorded step found for request hash {request_blob_ref!r}. "
                "The agent may be making a call that was not recorded."
            )
        return self._build_response(step)

    # ------------------------------------------------------------------
    # HTTP proxy hook — request-identity matching (Abdelhedi)
    # ------------------------------------------------------------------

    def response_for(self, request_identity: str) -> dict | None:
        """Serve the recorded response for a request identity, or None (divergence).

        Used by the HTTP proxy hook and by single-step mini-replays. Never
        executes a side effect: side-effecting steps are served from tape and
        counted via ``side_effecting_served``; ``side_effect_count`` stays 0.

        Returns None when no recorded step matches (divergence signal to the
        proxy — it can then hand off to Blibech's mock synthesizer).
        """
        queue = self._index.get(request_identity)
        if not queue:
            return None
        step = queue.popleft()
        ref = (
            step.get("response_blob")
            if step["type"] == "llm_call"
            else step.get("result_blob")
        )
        body = fetch_blob(ref) if ref else ""
        if step.get("side_effecting"):
            self.side_effecting_served += 1
        return {
            "status_code": int(step.get("status_code", 200)),
            "body": body,
            "side_effecting": bool(step.get("side_effecting")),
        }

    # ------------------------------------------------------------------
    # Sequential fallback (Derbal / tests)
    # ------------------------------------------------------------------

    def get_next_response(self, expected_type: str) -> dict[str, Any]:
        """Hand back the next step in tape order (sequential fallback).

        Useful for unit tests and for the simple single-path agent where
        step order is strictly deterministic.
        """
        if self._cursor >= len(self.steps):
            raise ReplayError(
                "Agent requested a step, but tape is out of recorded steps."
            )

        step = self.steps[self._cursor]
        self._cursor += 1

        if step["type"] != expected_type:
            raise ReplayError(
                f"Expected {expected_type}, but tape has {step['type']} "
                f"at step index {self._cursor}"
            )

        return self._build_response(step)

    # ------------------------------------------------------------------
    # Finish
    # ------------------------------------------------------------------

    def finish(self) -> ReplayResult:
        """Complete the replay session and return the summary."""
        return ReplayResult(
            run_id=self.run_id,
            steps_replayed=self._cursor,
            side_effect_count=self.side_effect_count,
            status="ok" if self._cursor == len(self.steps) else "incomplete",
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_payload(self, step: dict[str, Any]) -> dict[str, Any]:
        """Fetch the response blob for a step and return it as a dict."""
        blob_ref = (
            step.get("response_blob")  # llm_call
            if step["type"] == "llm_call"
            else step.get("result_blob")  # tool_call
        )
        if not blob_ref:
            return {}
        return json.loads(fetch_blob(blob_ref))

    def _build_response(self, step: dict[str, Any]) -> dict[str, Any]:
        """Apply the safety invariant and return the response envelope."""
        # Core safety invariant:
        # If this step is side-effecting the real-world action is NEVER taken.
        # We do NOT increment side_effect_count because no side effect fires.
        mocked = bool(step.get("side_effecting"))
        payload = self._resolve_payload(step)
        return {
            "step_id": step["step_id"],
            "mocked_side_effect": mocked,
            "payload": payload,
        }
