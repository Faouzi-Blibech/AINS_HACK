"""Adapter: StoreReplayEngine wraps B's Replayer + TraceStore to satisfy the
ReplayEngine protocol used by the blame graph.

replay()              -- drives B's real sequential playback (baseline).
replay_with_injection -- swap-ready; raises DivergenceNotReady until
                         replay_engine.Divergence.fork is implemented.
"""
from __future__ import annotations

from ai_agents.replay_interface import Injection, ReplayOutcome
from replay_engine.replay import Replayer
from replay_engine.divergence import Divergence
from trace_store.store import TraceStore


class DivergenceNotReady(NotImplementedError):
    """Raised until replay_engine.Divergence.fork is implemented by the replay owner."""


class StoreReplayEngine:
    """Adapts B's sequential Replayer + TraceStore to the ReplayEngine protocol.

    replay() drives B's real deterministic playback and returns a ReplayOutcome
    (baseline). final_status and failed_step_id are derived from the RECORDED
    trace step statuses, not from Replayer.finish().status, which only reflects
    cursor completion.

    replay_with_injection() is swap-ready: it calls Divergence.fork and will
    return the forked run's outcome once fork is implemented. Until then it
    raises DivergenceNotReady so callers can fall back to ScriptedReplay for
    perturbation.
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

        SWAP POINT: once Divergence.fork returns a real new run_id, replace the
        body below with:
            fork_run_id = Divergence().fork(run_id, injection.step_id, edit)
            outcome = self.replay(fork_run_id)
            outcome.replay_run_id = fork_run_id
            return outcome
        """
        edit = {injection.target: injection.value}
        try:
            Divergence().fork(run_id, injection.step_id, edit)
        except NotImplementedError:
            raise DivergenceNotReady(
                "Divergence.fork is not yet implemented by the replay owner; "
                "injection-path replay is not available. "
                "Use ScriptedReplay for perturbation until fork is ready."
            ) from None
