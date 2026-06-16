"""Divergence (Record-over): fork-at-step-N logic.

A developer edits a prompt or tool result at step N. That edit changes the
call's identity, so the recorded response no longer matches. The engine forks a
new branch from step N and lets the agent continue with live LLM calls
downstream (everything still mocked for side-effecting tools), producing a new
trajectory the UI diffs against the original.

Skeleton only.
"""
from __future__ import annotations


class Divergence:
    def fork(self, run_id: str, step_id: int, edit: dict) -> str:
        """Apply the edit at step_id, fork, and return the new run_id."""
        raise NotImplementedError
