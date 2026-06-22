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
import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

from trace_store.store import TraceStore
from trace_store.blob_store import fetch_blob


@dataclass
class ReplayResult:
    """Outcome of a replay: final state, executed steps, side-effect count."""
    run_id: str
    steps_replayed: int
    side_effect_count: int
    status: str
    synthesized_count: int = 0
    error_step_count: int = 0


class ReplayError(Exception):
    """Raised when replay diverges unexpectedly (no recorded step for a hash,
    tape exhausted, or step-type mismatch)."""


class TapeExhaustedForFork(ReplayError):
    """Raised when a record-over forked run runs out of tape.

    This is an expected condition: the fork only contains steps up to the
    edited step; the agent is now in un-recorded territory. Callers should
    either switch to live mode (record-over proxy path) or, if
    ``synthesize_on_miss=True``, use the mock synthesizer to continue
    (blame-graph mini-replay path). Carries ``fork_step_id`` for diagnostics.
    """

    def __init__(self, run_id: str, fork_step_id: int | None) -> None:
        self.run_id = run_id
        self.fork_step_id = fork_step_id
        super().__init__(
            f"Tape exhausted on a record-over fork of run {run_id!r} "
            f"(fork_step_id={fork_step_id}). "
            "The agent is now past the recorded segment and should go live."
        )


class Replayer:
    """Deterministic replay runner (Play mode)."""

    def __init__(
        self,
        trace_store: TraceStore,
        run_id: str,
        synthesize_on_miss: bool = True,
        error_step_mode: str = "faithful",
    ) -> None:
        """Create a Replayer for the given run.

        Parameters
        ----------
        synthesize_on_miss:
            When True (default) a tape miss calls the mock synthesizer to
            fabricate a plausible response so replay can continue. When False
            the original behaviour is kept: ``response_for`` returns None and
            ``get_response_for_hash`` raises ReplayError. Set False when the
            caller (e.g. Abdelhedi's HTTP proxy) needs to detect divergence
            itself and handle it (e.g. return a 504 or increment a counter).
        error_step_mode:
            Controls behaviour when a recorded step has status_code >= 400 or
            step status == "error".
            - ``"faithful"`` (default): replay the error exactly as recorded so
              the agent sees the same failure it saw during the original run.
              Use for deterministic failure reproduction.
            - ``"suppress"``: replace the error payload with an empty success
              (``{}``, status_code=200) so the agent can continue downstream.
              Use for counterfactual / blame-graph mini-replays where the goal
              is scoring the new trajectory, not re-crashing on the old error.
        """
        self.store = trace_store
        self.run_id = run_id
        self.synthesize_on_miss = synthesize_on_miss
        self.error_step_mode = error_step_mode

        self.trace_doc = self.store.get_run(self.run_id)
        self.steps: list[dict[str, Any]] = self.trace_doc["steps"]

        # --- hash index (Derbal, Day 3+) ---
        # Maps args_blob / prompt_blob → FIFO deque of matching steps.
        # A deque handles duplicate identical calls (e.g. two get_priority
        # calls with the same ticket ID) without silent overwrite — the first
        # recorded step is served first, then the second, etc.
        self._hash_index: dict[str, deque] = {}
        for step in self.steps:
            key = step.get("args_blob") or step.get("prompt_blob")
            if key:
                if key in self._hash_index:
                    existing_ids = [s["step_id"] for s in self._hash_index[key]]
                    log.debug(
                        "hash_index: duplicate blob key %s — step %s shares "
                        "the same blob ref as step(s) %s; all will be served "
                        "in recorded order.",
                        key, step["step_id"], existing_ids,
                    )
                self._hash_index.setdefault(key, deque()).append(step)

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

        # Detect record-over fork — tape exhaustion is expected on these runs.
        self._is_record_over: bool = self.trace_doc.get("mode") == "record-over"
        self._fork_step_id: int | None = self.trace_doc.get("fork_step_id")

        # Core safety counter — must remain 0 for the whole replay session.
        self.side_effect_count = 0

        # Number of steps served by the mock synthesizer (tape miss path).
        self.synthesized_count = 0

        # Number of error steps encountered (status_code >= 400 or status=error).
        self.error_step_count = 0

    # ------------------------------------------------------------------
    # Primary API — hash matching (Derbal)
    # ------------------------------------------------------------------

    def get_response_for_hash(self, request_blob_ref: str) -> dict[str, Any]:
        """Look up and return the recorded response for a given request hash.

        Called by Abdelhedi's proxy at replay time. The proxy hashes the
        outbound HTTP / MCP request body the exact same way the recorder did
        at record time, passes the resulting ``sha256:...`` ref here, and we
        return the payload that was recorded for it.

        On a miss, behaviour depends on ``synthesize_on_miss``:
          - True (default): delegates to the mock synthesizer and returns a
            synthesized response envelope (``synthesized: True``).
          - False: raises ReplayError (original behaviour).

        Parameters
        ----------
        request_blob_ref:
            The ``sha256:...`` ref computed from the live request's body/args.
            This must match either an ``args_blob`` (tool_call) or a
            ``prompt_blob`` (llm_call) stored in the trace.
        """
        queue = self._hash_index.get(request_blob_ref)
        if not queue:
            # Miss: either the hash was never recorded, or this call is the
            # (N+1)-th duplicate and the deque is now exhausted.
            if not self.synthesize_on_miss:
                raise ReplayError(
                    f"No recorded step found for request hash {request_blob_ref!r}. "
                    "The agent may be making a call that was not recorded."
                )
            # Best-effort: try to recover the original args from the blob store
            # so the synthesizer has richer context. The blob may not exist if
            # the call was truly novel (never stored by the recorder).
            arguments: dict = {}
            try:
                raw = fetch_blob(request_blob_ref)
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    arguments = parsed
            except (OSError, json.JSONDecodeError):  # blob missing or not JSON
                pass
            except Exception as exc:  # unexpected error (network, codec, …) — log and continue
                log.warning(
                    "get_response_for_hash: unexpected error fetching blob %r: %s; "
                    "falling back to synthesizer with empty args.",
                    request_blob_ref, exc,
                )
            return self._synthesize_response(tool="unknown_tool", arguments=arguments)
        step = queue.popleft()
        return self._build_response(step)

    # ------------------------------------------------------------------
    # HTTP proxy hook — request-identity matching (Abdelhedi)
    # ------------------------------------------------------------------

    def response_for(self, request_identity: str) -> dict | None:
        """Serve the recorded response for a request identity.

        Used by the HTTP proxy hook and by single-step mini-replays. Never
        executes a side effect: side-effecting steps are served from tape and
        counted via ``side_effecting_served``; ``side_effect_count`` stays 0.

        On a miss, behaviour depends on ``synthesize_on_miss``:
          - True (default): delegates to the mock synthesizer and returns a
            synthesized response envelope (``synthesized: True``).
          - False: returns None (original divergence signal for the HTTP proxy
            so it can count the divergence and return a 504 itself).
        """
        queue = self._index.get(request_identity)
        if not queue:
            if not self.synthesize_on_miss:
                return None
            tool = self._tool_from_identity(request_identity)
            return self._synthesize_response(tool=tool, arguments={})
        step = queue.popleft()
        ref = (
            step.get("response_blob")
            if step["type"] == "llm_call"
            else step.get("result_blob")
        )
        body = fetch_blob(ref) if ref else ""
        if step.get("side_effecting"):
            self.side_effecting_served += 1
        status_code = int(step.get("status_code", 200))
        is_error = status_code >= 400 or step.get("status") == "error"
        if is_error:
            # error_step_count is NOT incremented here.
            # _build_response is the single place that owns the counter so that
            # callers mixing response_for() and get_response_for_hash() /
            # get_next_response() on the same Replayer do not double-count.
            if self.error_step_mode == "suppress":
                return {
                    "status_code": 200,
                    "body": "{}",
                    "side_effecting": bool(step.get("side_effecting")),
                    "is_error_step": True,
                }
        return {
            "status_code": status_code,
            "body": body,
            "side_effecting": bool(step.get("side_effecting")),
            "is_error_step": is_error,
        }

    # ------------------------------------------------------------------
    # Sequential fallback (Derbal / tests)
    # ------------------------------------------------------------------

    def get_next_response(self, expected_type: str) -> dict[str, Any]:
        """Hand back the next step in tape order (sequential fallback).

        Useful for unit tests and for the simple single-path agent where
        step order is strictly deterministic.

        Tape exhaustion is handled differently depending on the run mode:
          - Normal ``play`` run: raises ``ReplayError`` (the agent made more
            calls than were recorded — this is a genuine mismatch).
          - ``record-over`` fork + ``synthesize_on_miss=True`` (default):
            delegates to the mock synthesizer so the blame graph / mini-replay
            can continue without hitting any live endpoint.
          - ``record-over`` fork + ``synthesize_on_miss=False``: raises
            ``TapeExhaustedForFork`` so the record-over proxy knows to switch
            the agent to live mode.
        """
        if self._cursor >= len(self.steps):
            if self._is_record_over:
                if self.synthesize_on_miss:
                    return self._synthesize_response(tool="unknown_tool", arguments={})
                raise TapeExhaustedForFork(self.run_id, self._fork_step_id)
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
        if self._is_record_over and self._cursor >= len(self.steps):
            status = "fork-live"  # expected: agent went past the tape end
        elif self._cursor == len(self.steps):
            status = "ok"
        else:
            status = "incomplete"  # agent stopped before consuming all tape
        return ReplayResult(
            run_id=self.run_id,
            steps_replayed=self._cursor,
            side_effect_count=self.side_effect_count,
            status=status,
            synthesized_count=self.synthesized_count,
            error_step_count=self.error_step_count,
        )

    @property
    def counterfactual_mode(self) -> bool:
        """True when error_step_mode is 'suppress' (alias for Blibech's blame engine)."""
        return self.error_step_mode == "suppress"

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
        """Apply the safety invariant and return the response envelope.

        Always returns a dict with ``payload`` as a dict (never a raw string
        or None) so callers can safely do ``resp['payload'].get(...)`` without
        a type check.  Error steps in ``faithful`` mode still carry the
        recorded payload (coerced to dict if needed) and set
        ``is_error_step=True``.
        """
        # Core safety invariant:
        # If this step is side-effecting the real-world action is NEVER taken.
        # We do NOT increment side_effect_count because no side effect fires.
        mocked = bool(step.get("side_effecting"))
        status_code = int(step.get("status_code", 200))
        is_error = status_code >= 400 or step.get("status") == "error"

        if is_error:
            self.error_step_count += 1
            if self.error_step_mode == "suppress":
                # Counterfactual / blame-graph mode: return an empty success so
                # the agent can continue and be scored on its new trajectory.
                # The is_error_step flag is still True so callers know.
                return {
                    "step_id": step["step_id"],
                    "mocked_side_effect": mocked,
                    "synthesized": False,
                    "is_error_step": True,
                    "status_code": 200,
                    "payload": {},
                }
            # faithful mode: replay the error exactly, but guarantee payload is
            # a dict so callers never receive a raw string from a recorded error
            # body.  A non-dict payload (plain string, list, …) is wrapped.
            raw_payload = self._resolve_payload(step)
            payload: dict[str, Any] = (
                raw_payload if isinstance(raw_payload, dict)
                else {"_raw": raw_payload}
            )
            log.debug(
                "replay: faithful error step %s status_code=%s",
                step["step_id"], status_code,
            )
            return {
                "step_id": step["step_id"],
                "mocked_side_effect": mocked,
                "synthesized": False,
                "is_error_step": True,
                "status_code": status_code,
                "payload": payload,
            }

        payload = self._resolve_payload(step)
        return {
            "step_id": step["step_id"],
            "mocked_side_effect": mocked,
            "synthesized": False,
            "is_error_step": is_error,
            "status_code": status_code,
            "payload": payload,
        }

    def _synthesize_response(self, *, tool: str, arguments: dict) -> dict[str, Any]:
        """Delegate to the mock synthesizer and return a normal response envelope.

        Called when ``synthesize_on_miss=True`` and no tape entry matches the
        incoming request. The synthesizer never raises: it falls back to a
        schema-shaped skeleton when the LLM is unavailable.
        """
        from ai_agents.mock_synthesizer import synthesize  # lazy import to avoid hard dep
        result = synthesize(
            tool=tool,
            arguments=arguments,
            schema=None,          # no schema registry at replay time
            context={"run_id": self.run_id},
        )
        self.synthesized_count += 1
        return {
            "step_id": None,
            "mocked_side_effect": False,
            "synthesized": True,
            "confidence": result.confidence,
            "rationale": result.rationale,
            "payload": result.value,
        }

    @staticmethod
    def _tool_from_identity(request_identity: str) -> str:
        """Best-effort extraction of a tool name from a request identity string.

        HTTP identity format:  ``"POST /get_priority\n<hash>"``.  The last
        path segment is used as the tool name.
        MCP identity format:   ``"mcp tools/call get_priority\n<hash>"``.
        Unknown formats fall back to the full first line.
        """
        first_line = request_identity.split("\n", 1)[0]
        # HTTP: "METHOD /path/tool_name"
        if "/" in first_line:
            return first_line.rsplit("/", 1)[-1]
        # MCP: "mcp tools/call tool_name" — last space-delimited token
        parts = first_line.split()
        return parts[-1] if parts else first_line
