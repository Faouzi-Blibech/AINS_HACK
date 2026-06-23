"""Failure-library store backed by SQLite.

Persists diagnosed failure entries produced by Blibech's AI analysis layer.
Each entry describes a root-cause pattern, which step is to blame, and the
fix that resolved it -- so future runs can query this library and receive a
preventive warning before they hit the same failure again (Layer 2).

SQLite table schema:
--------------------
    CREATE TABLE IF NOT EXISTS failure_library (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        failure_pattern  TEXT         NOT NULL,
        blame_step       INTEGER      NOT NULL,
        fix_that_worked  TEXT         NOT NULL,
        agent_config     TEXT,
        determinism_rate REAL,
        created_at       TEXT         NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || 'Z')
    );

Environment variables:
----------------------
    CASSETTE_DB_PATH -- optional override for the SQLite database path

Public API
----------
write_entry(failure_pattern, blame_step, fix_that_worked, ...)  -- insert entry.
query(pattern_fragment, blame_step, limit)                       -- filtered list.
get_all(limit)                                                   -- unfiltered list.
close()                                                          -- close connection.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

class FailureLibraryError(Exception):
    """Raised when a SQLite database operation fails.

    Callers in the replay engine should catch this and log rather than crash
    so that a transient DB issue never kills a replay session.
    """


class FailureLibraryStore:
    """SQLite-backed store for diagnosed failure entries.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file. Defaults to CASSETTE_DB_PATH
        env var, or './cassette.sqlite3'.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        resolved_path = db_path or os.environ.get("CASSETTE_DB_PATH") or "./cassette.sqlite3"
        self.db_path = str(resolved_path)
        self._lock = threading.Lock()
        
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._init_db()
        except sqlite3.Error as exc:
            raise FailureLibraryError(f"Failed to connect to SQLite database at {self.db_path}: {exc}") from exc

    def _init_db(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS failure_library (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            failure_pattern  TEXT         NOT NULL,
            blame_step       INTEGER      NOT NULL,
            fix_that_worked  TEXT         NOT NULL,
            agent_config     TEXT,
            determinism_rate REAL,
            created_at       TEXT         NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now') || 'Z')
        );
        """
        with self._lock:
            try:
                self._conn.execute(ddl)
                self._conn.commit()
            except sqlite3.Error as exc:
                raise FailureLibraryError(f"Failed to initialize failure_library table: {exc}") from exc

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def write_entry(
        self,
        failure_pattern: str,
        blame_step: int,
        fix_that_worked: str,
        agent_config: str | None = None,
        determinism_rate: float | None = None,
    ) -> dict[str, Any]:
        """Insert a diagnosed failure entry and return the created row.

        Parameters
        ----------
        failure_pattern:
            Human-readable description of the failure.
        blame_step:
            The step_id identified as the root cause.
        fix_that_worked:
            Description of the fix that resolved the failure.
        agent_config:
            Optional agent version / config label.
        determinism_rate:
            Optional 0..1 determinism score measured on the replay.

        Returns
        -------
        dict
            The full row as inserted (including id and created_at).

        Raises
        ------
        FailureLibraryError
            On any database/write error.
        """
        query = """
        INSERT INTO failure_library (
            failure_pattern, blame_step, fix_that_worked, agent_config, determinism_rate
        ) VALUES (?, ?, ?, ?, ?)
        """
        with self._lock:
            try:
                cursor = self._conn.execute(
                    query,
                    (failure_pattern, blame_step, fix_that_worked, agent_config, determinism_rate),
                )
                self._conn.commit()
                row_id = cursor.lastrowid
                
                # Fetch and return the newly created row
                row = self._conn.execute(
                    "SELECT id, failure_pattern, blame_step, fix_that_worked, agent_config, determinism_rate, created_at "
                    "FROM failure_library WHERE id = ?",
                    (row_id,),
                ).fetchone()
                
                if row is None:
                    raise FailureLibraryError("Failed to fetch newly created row")
                
                res = dict(row)
                log.info(
                    "failure_library: wrote entry id=%s blame_step=%s pattern=%r",
                    res.get("id"), blame_step, failure_pattern[:80],
                )
                return res
            except sqlite3.Error as exc:
                raise FailureLibraryError(f"write_entry failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def query(
        self,
        pattern_fragment: str | None = None,
        blame_step: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return entries filtered by pattern text and/or blame step.

        Parameters
        ----------
        pattern_fragment:
            Case-insensitive substring that failure_pattern must contain.
        blame_step:
            If given, only entries with this exact blame_step are returned.
        limit:
            Maximum number of rows returned; defaults to 50.

        Returns
        -------
        list[dict]
            Matching entries, newest first.

        Raises
        ------
        FailureLibraryError
            On any query error.
        """
        sql = "SELECT id, failure_pattern, blame_step, fix_that_worked, agent_config, determinism_rate, created_at FROM failure_library"
        where_clauses = []
        params = []
        
        if pattern_fragment is not None:
            where_clauses.append("(failure_pattern LIKE ? OR fix_that_worked LIKE ?)")
            params.append(f"%{pattern_fragment}%")
            params.append(f"%{pattern_fragment}%")
            
        if blame_step is not None:
            where_clauses.append("blame_step = ?")
            params.append(blame_step)
            
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
            
        # Order by created_at DESC, and use id DESC as a stable fallback for simultaneous entries
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        
        with self._lock:
            try:
                rows = self._conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.Error as exc:
                raise FailureLibraryError(f"query failed: {exc}") from exc

    def get_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return all entries, newest first.

        Parameters
        ----------
        limit:
            Maximum rows returned; defaults to 100.
        """
        return self.query(limit=limit)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the SQLite database connection."""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    def __enter__(self) -> FailureLibraryStore:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"FailureLibraryStore(db_path={self.db_path!r})"
