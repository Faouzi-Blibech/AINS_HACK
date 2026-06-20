"""State snapshot and resume.

Serialize the agent's accumulated context at any step so a run can be resumed
from that exact state, or inspected later (auditing). For the hackathon the
"agent context" is the trace steps up to that point — enough for Blibech's
mini-replays and for the UI's step inspector.

Snapshot ref format:  ``snapshot:<sha256>``
"""
from __future__ import annotations

import json
from typing import Any

from trace_store.store import TraceStore
from trace_store.blob_store import store_blob, fetch_blob


class SnapshotError(Exception):
    """Raised when snapshot/resume encounters a bad ref or missing data."""


def snapshot(store: TraceStore, run_id: str, step_id: int) -> str:
    """Serialize agent context at step_id and return a snapshot ref.

    The snapshot captures:
      - The run header (run_id, agent, mode, parent_run_id, fork_step_id)
      - All steps from step 1 up to and including step_id

    Parameters
    ----------
    store:
        The TraceStore holding the run.
    run_id:
        Which run to snapshot.
    step_id:
        Capture context up to and including this step.

    Returns
    -------
    str
        A ``snapshot:<sha256>`` reference stored in the blob store.
    """
    trace = store.get_run(run_id)
    steps_up_to = [s for s in trace["steps"] if s["step_id"] <= step_id]

    if not steps_up_to and step_id > 0:
        raise SnapshotError(
            f"No steps found up to step_id={step_id} in run {run_id!r}."
        )

    context: dict[str, Any] = {
        "run_id": trace["run_id"],
        "agent": trace.get("agent"),
        "mode": trace.get("mode"),
        "parent_run_id": trace.get("parent_run_id"),
        "fork_step_id": trace.get("fork_step_id"),
        "schema_version": trace.get("schema_version", "1.0"),
        "snapshot_at_step": step_id,
        "steps": steps_up_to,
    }

    blob_ref = store_blob(json.dumps(context, separators=(",", ":")))
    # Replace the sha256: prefix with snapshot: for clarity
    snap_ref = "snapshot:" + blob_ref.split(":", 1)[1]
    return snap_ref


def resume(snap_ref: str) -> dict[str, Any]:
    """Restore agent context from a snapshot ref.

    Parameters
    ----------
    snap_ref:
        A ``snapshot:<sha256>`` ref returned by :func:`snapshot`.

    Returns
    -------
    dict
        The serialized context dict with keys: run_id, agent, mode,
        snapshot_at_step, steps (all steps up to the snapshotted step).
    """
    if not snap_ref.startswith("snapshot:"):
        raise SnapshotError(
            f"Invalid snapshot ref {snap_ref!r}. Expected 'snapshot:<sha256>'."
        )
    blob_ref = "sha256:" + snap_ref.split(":", 1)[1]
    raw = fetch_blob(blob_ref)
    return json.loads(raw)
