"""Counterfactual repair agent (the wow feature).

Once the root cause is identified, this agent generates N reworded variants of
the failing step's prompt, replays each from that step onward (everything
downstream safely mocked), and ranks them by outcome: did the agent complete?
how many steps changed? cost delta? Output: "Variant 3 succeeded, an explicit
priority-enum constraint resolved the failure."

Turns the debugger from a passive observer into an active problem-solver.

Skeleton only.
"""
from __future__ import annotations


class Variant:
    """prompt, replay outcome, steps_changed, cost_delta, score, confidence."""


def repair(run_id: str, step_id: int, n: int = 5) -> list[Variant]:
    """Generate, replay, and rank N fix variants for the failing step."""
    raise NotImplementedError
