"""State snapshot and resume.

Serialize the agent's full context/memory at any step so a run can be resumed
from that exact state or inspected later (auditing). Useful for long runs where
you want to fast-forward to the interesting step.

Skeleton only.
"""
from __future__ import annotations


def snapshot(run_id: str, step_id: int) -> str:
    """Serialize agent state at a step; return a snapshot ref."""
    raise NotImplementedError


def resume(snapshot_ref: str):
    """Restore agent state from a snapshot ref."""
    raise NotImplementedError
