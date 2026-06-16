"""Append-only trace store.

Persists steps of a run keyed by run_id / step_id, following
../docs/trace_schema.json. SQLite for the prototype. Steps hold only small
structured fields; large payloads are pushed to the blob store and referenced
by their sha256 hash.

Skeleton only.
"""
from __future__ import annotations


class TraceStore:
    def __init__(self, db_path: str = "./cassette.sqlite3") -> None:
        self.db_path = db_path

    def start_run(self, run_id: str, agent: str, mode: str = "record") -> None:
        raise NotImplementedError

    def append_step(self, run_id: str, step: dict) -> None:
        """Append one step (llm_call or tool_call) to the run."""
        raise NotImplementedError

    def get_run(self, run_id: str) -> dict:
        """Return the full trace document for a run."""
        raise NotImplementedError

    def list_runs(self) -> list[dict]:
        raise NotImplementedError
