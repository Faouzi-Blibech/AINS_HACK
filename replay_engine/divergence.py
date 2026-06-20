"""Divergence (Record-over): fork-at-step-N logic.

A developer edits a prompt or tool result at step N. That edit changes the
call's identity, so the recorded response no longer matches. The engine forks
a new branch: steps 1..N-1 are copied from the original tape, step N is
re-written with the edit applied, and steps N+1 onwards are left empty so the
agent continues live (served by Abdelhedi's proxy in record-over mode).

For Blibech's blame-graph mini-replays the fork is used differently:
- fork() creates the branch and returns the new run_id.
- Blibech's blame engine replays the forked run and scores how the outcome
  changes compared to the original.

Usage
-----
    from replay_engine.divergence import Divergence
    from trace_store.store import TraceStore

    store = TraceStore()
    div = Divergence(store)

    # Change get_priority result at step 2 to "critical"
    new_result_ref = store_blob('{"priority": "critical"}')
    new_run_id = div.fork(
        run_id="original-run-123",
        fork_step_id=2,
        edit={"result_blob": new_result_ref}
    )

    # new_run_id now has steps 1 (copied) + step 2 (edited) in the store.
    # The Replayer on new_run_id can drive Blibech's mini-replay.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from trace_store.store import TraceStore
from trace_store.blob_store import store_blob, fetch_blob


class DivergenceError(Exception):
    """Raised when a fork cannot be created."""


class Divergence:
    """Fork a recorded run at a specific step with an edited payload."""

    def __init__(self, store: TraceStore) -> None:
        self.store = store

    def fork(
        self,
        run_id: str,
        fork_step_id: int,
        edit: dict[str, Any],
        new_run_id: str | None = None,
    ) -> str:
        """Apply edit at fork_step_id, create a forked run, return new run_id.

        Parameters
        ----------
        run_id:
            The original run to fork from.
        fork_step_id:
            The step_id at which to apply the edit. Steps 1..fork_step_id-1
            are copied verbatim. Step fork_step_id is re-written with the
            edit merged in. Steps after fork_step_id are NOT copied (the agent
            will continue live or Blibech's engine will score the divergence).
        edit:
            Dict of fields to override on the fork step. Common edits:
              - ``result_blob``: override a tool call's result payload
              - ``response_blob``: override an LLM call's response
              - ``args_blob``: override a tool call's arguments
              - ``prompt_blob``: override an LLM call's prompt
            You can also pass raw content via the helper keys:
              - ``_result_content``: JSON string → stored as blob → result_blob
              - ``_response_content``: JSON string → stored as blob → response_blob
        new_run_id:
            Optional explicit run_id for the fork. Auto-generated if not given.

        Returns
        -------
        str
            The run_id of the newly created forked run.
        """
        original = self.store.get_run(run_id)
        steps = original["steps"]

        # Validate fork_step_id is in range
        step_ids = {s["step_id"] for s in steps}
        if fork_step_id not in step_ids:
            raise DivergenceError(
                f"step_id {fork_step_id} not found in run {run_id!r}. "
                f"Available step_ids: {sorted(step_ids)}"
            )

        # Auto-generate a forked run_id if not provided
        forked_id = new_run_id or f"fork-{uuid.uuid4().hex[:8]}"

        # Register the forked run in the store
        self.store.start_run(
            run_id=forked_id,
            agent=original.get("agent", ""),
            mode="record-over",
            created_at_ms=int(time.time() * 1000),
            schema_version=original.get("schema_version", "1.0"),
            parent_run_id=run_id,
            fork_step_id=fork_step_id,
        )

        # Copy steps 1 .. fork_step_id-1 verbatim
        for step in steps:
            if step["step_id"] < fork_step_id:
                self.store.append_step(forked_id, step)

        # Build the edited step
        fork_step = next(s for s in steps if s["step_id"] == fork_step_id)
        edited_step = dict(fork_step)

        # Handle convenience content keys — store blob, set ref
        if "_result_content" in edit:
            edit = dict(edit)
            edit["result_blob"] = store_blob(edit.pop("_result_content"))
        if "_response_content" in edit:
            edit = dict(edit)
            edit["response_blob"] = store_blob(edit.pop("_response_content"))

        edited_step.update(edit)
        self.store.append_step(forked_id, edited_step)

        return forked_id

    def compare(self, original_run_id: str, forked_run_id: str) -> dict[str, Any]:
        """Return a simple structural diff between two runs.

        Used by Blibech's blame engine to score how much the outcome changed.

        Returns
        -------
        dict with keys:
            fork_step_id    – where the fork was applied
            original_steps  – number of steps in the original
            forked_steps    – number of steps in the fork so far
            edited_fields   – which fields differ at the fork step
        """
        orig = self.store.get_run(original_run_id)
        fork = self.store.get_run(forked_run_id)

        fork_step_id = fork.get("fork_step_id")
        orig_step = next(
            (s for s in orig["steps"] if s["step_id"] == fork_step_id), {}
        )
        fork_step = next(
            (s for s in fork["steps"] if s["step_id"] == fork_step_id), {}
        )

        edited_fields = [
            k for k in set(list(orig_step.keys()) + list(fork_step.keys()))
            if orig_step.get(k) != fork_step.get(k)
        ]

        return {
            "fork_step_id": fork_step_id,
            "original_steps": len(orig["steps"]),
            "forked_steps": len(fork["steps"]),
            "edited_fields": edited_fields,
        }
