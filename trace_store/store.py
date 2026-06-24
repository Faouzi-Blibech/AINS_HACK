"""Append-only trace store backed by SQLite.

Persists agent runs following ``docs/trace_schema.json``.

Two tables
----------
runs  – one row per run (all run-level header fields).
steps – one row per step; structured fields are columns, everything
        else lives in a JSON ``extras`` column so the store stays
        forward-compatible when the schema gains new optional fields.

Public API
----------
start_run(run_id, agent, mode, ...)  – open a new run.
append_step(run_id, step)            – append one step dict.
get_run(run_id)                      – return the full trace document.
list_runs()                          – return run-level summaries.
close()                              – close the DB connection.

Steps are intentionally *never* updated in place (append-only);
run-level mutable fields (status, duration_ms) are updated via
``finish_run()``.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """\
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    schema_version  TEXT NOT NULL DEFAULT '1.0',
    agent           TEXT,
    created_at_ms   INTEGER NOT NULL,
    mode            TEXT NOT NULL DEFAULT 'record',
    parent_run_id   TEXT,
    fork_step_id    INTEGER,
    status          TEXT,
    duration_ms     INTEGER
);

CREATE TABLE IF NOT EXISTS steps (
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    step_id         INTEGER NOT NULL,
    type            TEXT NOT NULL,
    timestamp_ms    INTEGER NOT NULL,
    latency_ms      INTEGER,
    status          TEXT,
    side_effecting  INTEGER,           -- 0/1 (SQLite has no BOOLEAN)
    confidence      REAL,
    -- blob refs
    prompt_blob     TEXT,
    response_blob   TEXT,
    args_blob       TEXT,
    result_blob     TEXT,
    -- tool / llm-specific scalars
    tool            TEXT,
    transport       TEXT,
    model           TEXT,
    -- everything else (causal_parents, token_usage, params, ...)
    extras          TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (run_id, step_id)
);
"""

# Step fields that get their own column (fast filtering / ordering).
_STEP_COLUMNS = frozenset({
    "step_id", "type", "timestamp_ms", "latency_ms", "status",
    "side_effecting", "confidence",
    "prompt_blob", "response_blob", "args_blob", "result_blob",
    "tool", "transport", "model",
})


class TraceStore:
    """SQLite-backed, append-only trace store."""

    def __init__(self, db_path: str | Path = "./cassette.sqlite3") -> None:
        self.db_path = str(db_path)
        # check_same_thread=False lets the connection be used from the FastAPI
        # threadpool; _lock serializes access so concurrent requests cannot
        # misuse the single connection (sqlite raises SQLITE_MISUSE otherwise).
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def start_run(
        self,
        run_id: str,
        agent: str = "",
        mode: str = "record",
        *,
        created_at_ms: int | None = None,
        schema_version: str = "1.0",
        parent_run_id: str | None = None,
        fork_step_id: int | None = None,
    ) -> None:
        """Register a new run.  Must be called before ``append_step``."""
        import time as _time
        ts = created_at_ms if created_at_ms is not None else int(_time.time() * 1000)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO runs (
                    run_id, schema_version, agent, created_at_ms,
                    mode, parent_run_id, fork_step_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, schema_version, agent, ts, mode, parent_run_id, fork_step_id),
            )
            self._conn.commit()

    def append_step(self, run_id: str, step: dict[str, Any]) -> None:
        """Append one step (llm_call or tool_call) dict to the run.

        The step dict must include at minimum ``step_id``, ``type``, and
        ``timestamp_ms`` (per the schema).  All other fields are optional.
        """
        cols = {}
        extras: dict[str, Any] = {}

        for key, val in step.items():
            if key in _STEP_COLUMNS:
                # Coerce booleans to int for SQLite
                cols[key] = int(val) if isinstance(val, bool) else val
            else:
                extras[key] = val

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO steps (
                    run_id, step_id, type, timestamp_ms, latency_ms, status,
                    side_effecting, confidence,
                    prompt_blob, response_blob, args_blob, result_blob,
                    tool, transport, model, extras
                ) VALUES (
                    :run_id, :step_id, :type, :timestamp_ms, :latency_ms, :status,
                    :side_effecting, :confidence,
                    :prompt_blob, :response_blob, :args_blob, :result_blob,
                    :tool, :transport, :model, :extras
                )
                """,
                {
                    "run_id": run_id,
                    "extras": json.dumps(extras),
                    **{k: cols.get(k) for k in (
                        "step_id", "type", "timestamp_ms", "latency_ms", "status",
                        "side_effecting", "confidence",
                        "prompt_blob", "response_blob", "args_blob", "result_blob",
                        "tool", "transport", "model",
                    )},
                },
            )
            self._conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: str = "ok",
        duration_ms: int | None = None,
    ) -> None:
        """Update run-level status and duration once the run completes."""
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET status=?, duration_ms=? WHERE run_id=?",
                (status, duration_ms, run_id),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Return the full trace document for *run_id*.

        The returned dict matches the shape of ``docs/trace_schema.json``
        and can be round-tripped through ``json.dumps``/``json.loads``
        without loss.

        Raises
        ------
        KeyError
            If *run_id* does not exist in the store.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"run_id not found: {run_id!r}")
            step_rows = self._conn.execute(
                "SELECT * FROM steps WHERE run_id=? ORDER BY step_id",
                (run_id,),
            ).fetchall()

        doc: dict[str, Any] = {
            "schema_version": row["schema_version"],
            "run_id": row["run_id"],
            "agent": row["agent"],
            "created_at_ms": row["created_at_ms"],
            "mode": row["mode"],
            "parent_run_id": row["parent_run_id"],
            "fork_step_id": row["fork_step_id"],
            "status": row["status"],
            "duration_ms": row["duration_ms"],
            "steps": [],
        }

        for sr in step_rows:
            step: dict[str, Any] = {}

            # Restore typed scalar columns
            step["step_id"] = sr["step_id"]
            step["type"] = sr["type"]
            step["timestamp_ms"] = sr["timestamp_ms"]

            for opt_col in (
                "latency_ms", "status", "confidence",
                "prompt_blob", "response_blob",
                "args_blob", "result_blob",
                "tool", "transport", "model",
            ):
                val = sr[opt_col]
                if val is not None:
                    step[opt_col] = val

            # Restore side_effecting as bool (stored as int in SQLite)
            if sr["side_effecting"] is not None:
                step["side_effecting"] = bool(sr["side_effecting"])

            # Merge extras (causal_parents, token_usage, params, ...)
            extras = json.loads(sr["extras"] or "{}")
            step.update(extras)

            doc["steps"].append(step)

        return doc

    def delete_run(self, run_id: str) -> None:
        """Remove a run and its steps if present (idempotent). Lets a run be
        re-recorded under an existing run_id without a UNIQUE collision."""
        with self._lock:
            self._conn.execute("DELETE FROM steps WHERE run_id = ?", (run_id,))
            self._conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            self._conn.commit()

    def list_runs(self) -> list[dict[str, Any]]:
        """Return a list of run-level summary dicts (no steps)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, agent, created_at_ms, mode, status, parent_run_id "
                "FROM runs ORDER BY created_at_ms DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "TraceStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"TraceStore(db_path={self.db_path!r})"
