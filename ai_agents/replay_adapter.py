"""Adapter: StoreReplayEngine wraps B's Replayer + TraceStore to satisfy the
ReplayEngine protocol used by the blame graph.

replay()              -- drives B's real sequential playback (baseline).
replay_with_injection -- forks at the injection step via Divergence.fork, then
                         replays the forked run and returns a ReplayOutcome.
"""
from __future__ import annotations

import json

from ai_agents.replay_interface import Injection, ReplayOutcome
from replay_engine.replay import Replayer
from replay_engine.divergence import Divergence, DivergenceError
from trace_store.store import TraceStore
from trace_store.blob_store import store_blob


def _json_safe(value) -> str:
    """Return a JSON-parseable form of value (the replay engine json.loads every blob)."""
    if not isinstance(value, str):
        return json.dumps(value)
    try:
        json.loads(value)
        return value
    except json.JSONDecodeError:
        return json.dumps(value)


class DivergenceNotReady(NotImplementedError):
    """Raised when a fork cannot be created (kept for backward compatibility)."""


class StoreReplayEngine:
    """Adapts B's sequential Replayer + TraceStore to the ReplayEngine protocol.

    replay() drives B's real deterministic playback and returns a ReplayOutcome
    (baseline). final_status and failed_step_id are derived from the RECORDED
    trace step statuses, not from Replayer.finish().status, which only reflects
    cursor completion.

    replay_with_injection() forks the run at injection.step_id via
    Divergence.fork, replays the forked run, and returns the outcome with
    replay_run_id set to the fork's run_id.
    """

    def __init__(self, store: TraceStore) -> None:
        self._store = store

    def replay(self, run_id: str) -> ReplayOutcome:
        """Deterministically replay the recorded run as-is (the baseline).

        Drives every step through B's Replayer so that blob resolution and the
        mocked-side-effect logic run through B's code. side_effect_count comes
        from the Replayer result and MUST be 0. final_status and failed_step_id
        are derived from the recorded trace statuses (not from finish().status).
        """
        trace = self._store.get_run(run_id)
        steps = trace["steps"]

        replayer = Replayer(self._store, run_id)

        key_outputs: dict = {}
        for step in steps:
            response = replayer.get_next_response(step["type"])
            key_outputs[f"step{step['step_id']}"] = response["payload"]

        result = replayer.finish()
        side_effect_count = result.side_effect_count  # invariant: must be 0

        # Derive outcome from the RECORDED trace, not from finish().status
        errored = [s["step_id"] for s in steps if s.get("status") == "error"]
        final_status = "error" if errored else "ok"
        # Matches root_cause.infer_failed_step semantics: "visibly failed" = last/highest errored step.
        failed_step_id = max(errored) if errored else None

        return ReplayOutcome(
            run_id=run_id,
            final_status=final_status,
            failed_step_id=failed_step_id,
            side_effect_count=side_effect_count,
            key_outputs=key_outputs,
        )

    def replay_with_injection(self, run_id: str, injection: Injection) -> ReplayOutcome:
        """Fork at injection.step_id with the edit applied; replay onward.

        Translates the Injection into Divergence's edit dict, forks the run,
        replays the fork, and returns the outcome with replay_run_id set.

        Raises DivergenceNotReady (wrapping DivergenceError) when the fork
        cannot be created (e.g. invalid step_id).
        """
        # Build the edit dict using Divergence's convenience keys. The replay
        # engine json.loads every blob it serves, so the injected content must
        # be valid JSON (a bare string like "high" is wrapped into "high").
        target = injection.target
        content = _json_safe(injection.value)

        if target == "result":
            edit: dict = {"_result_content": content}
        elif target == "response":
            edit = {"_response_content": content}
        elif target == "args":
            edit = {"args_blob": store_blob(content)}
        elif target == "prompt":
            edit = {"prompt_blob": store_blob(content)}
        else:
            edit = {target: injection.value}

        try:
            fork_run_id = Divergence(self._store).fork(run_id, injection.step_id, edit)
        except DivergenceError as exc:
            raise DivergenceNotReady(
                f"Divergence.fork could not create a fork: {exc}"
            ) from exc

        outcome = self.replay(fork_run_id)
        outcome.replay_run_id = fork_run_id
        return outcome
