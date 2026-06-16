"""Deterministic replay runner (Play mode).

Re-executes a recorded run step-by-step. Tool calls are intercepted and served
from the tape; no live endpoint is hit. side_effecting calls are ALWAYS mocked.

Skeleton only.
"""
from __future__ import annotations


class ReplayResult:
    """Outcome of a replay: final state, executed steps, side-effect count."""


class Replayer:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.side_effect_count = 0  # invariant: must stay 0 on replay

    def replay(self) -> ReplayResult:
        """Deterministically re-run the recorded trajectory."""
        raise NotImplementedError
