"""Failure-library store backed by Supabase.

Persists diagnosed failure entries produced by Blibech's AI analysis layer.
Each entry describes a root-cause pattern, which step is to blame, and the
fix that resolved it -- so future runs can query this library and receive a
preventive warning before they hit the same failure again (Layer 2).

Supabase table DDL (run once in the Supabase SQL editor):
---------------------------------------------------------
    CREATE TABLE IF NOT EXISTS failure_library (
        id               BIGSERIAL PRIMARY KEY,
        failure_pattern  TEXT         NOT NULL,
        blame_step       INTEGER      NOT NULL,
        fix_that_worked  TEXT         NOT NULL,
        agent_config     TEXT,
        determinism_rate REAL,
        created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
    );

Environment variables (add to .env, see .env.example):
-------------------------------------------------------
    SUPABASE_URL  -- your project URL, e.g. https://abc123.supabase.co
    SUPABASE_KEY  -- anon or service-role key

Public API
----------
write_entry(failure_pattern, blame_step, fix_that_worked, ...)  -- insert entry.
query(pattern_fragment, blame_step, limit)                       -- filtered list.
get_all(limit)                                                   -- unfiltered list.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

# Table name; change here if the Supabase project uses a different name.
_TABLE = "failure_library"

# Columns returned on every fetch (order mirrors the schema).
_SELECT_COLS = "id, failure_pattern, blame_step, fix_that_worked, agent_config, determinism_rate, created_at"


class FailureLibraryError(Exception):
    """Raised when a Supabase operation fails.

    Callers in the replay engine should catch this and log rather than crash
    so that a transient network issue never kills a replay session.
    """


class FailureLibraryStore:
    """Supabase-backed store for diagnosed failure entries.

    Parameters
    ----------
    url:
        Supabase project URL.  Defaults to the ``SUPABASE_URL`` env var.
    key:
        Supabase API key (anon or service-role).  Defaults to
        ``SUPABASE_KEY`` env var.

    Raises
    ------
    FailureLibraryError
        On construction if neither ``url``/``key`` arguments nor the
        corresponding env vars are set, or if the supabase-py client
        cannot be imported.
    """

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
    ) -> None:
        resolved_url = url or os.environ.get("SUPABASE_URL", "")
        resolved_key = key or os.environ.get("SUPABASE_KEY", "")

        if not resolved_url or not resolved_key:
            raise FailureLibraryError(
                "SUPABASE_URL and SUPABASE_KEY must be set (env vars or constructor args). "
                "Add them to .env (see .env.example)."
            )

        try:
            from supabase import create_client  # type: ignore[import]
        except ImportError as exc:
            raise FailureLibraryError(
                "supabase-py is not installed. Run: pip install 'supabase>=2.0,<3'"
            ) from exc

        self._client = create_client(resolved_url, resolved_key)
        log.debug("FailureLibraryStore connected to %s", resolved_url)

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
            Human-readable description of the failure (e.g. ``"ambiguous
            priority field caused wrong routing"``).  Used by Blibech's
            semantic matcher when checking relevance for future runs.
        blame_step:
            The ``step_id`` identified as the root cause by the blame graph.
        fix_that_worked:
            Description of the fix that resolved the failure (e.g.
            ``"explicit priority enum constraint at step 2"``).
        agent_config:
            Optional agent version / config label (e.g. ``"v1.2"``).
        determinism_rate:
            Optional 0..1 determinism score measured on the replay that
            confirmed the fix worked.

        Returns
        -------
        dict
            The full row as inserted (including ``id`` and ``created_at``
            assigned by Supabase).

        Raises
        ------
        FailureLibraryError
            On any Supabase / network error.
        """
        payload: dict[str, Any] = {
            "failure_pattern": failure_pattern,
            "blame_step": blame_step,
            "fix_that_worked": fix_that_worked,
        }
        if agent_config is not None:
            payload["agent_config"] = agent_config
        if determinism_rate is not None:
            payload["determinism_rate"] = determinism_rate

        try:
            response = (
                self._client.table(_TABLE)
                .insert(payload)
                .execute()
            )
            rows = response.data
            if not rows:
                raise FailureLibraryError(
                    "Supabase insert returned no data -- check RLS policies or table name."
                )
            row = rows[0]
            log.info(
                "failure_library: wrote entry id=%s blame_step=%s pattern=%r",
                row.get("id"), blame_step, failure_pattern[:80],
            )
            return row
        except FailureLibraryError:
            raise
        except Exception as exc:
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
            Case-insensitive substring that ``failure_pattern`` must contain.
            Uses Supabase's PostgREST ``ilike`` operator (``%fragment%``).
        blame_step:
            If given, only entries with this exact ``blame_step`` are returned.
        limit:
            Maximum number of rows returned; defaults to 50.

        Returns
        -------
        list[dict]
            Matching entries, newest first.

        Raises
        ------
        FailureLibraryError
            On any Supabase / network error.
        """
        try:
            q = (
                self._client.table(_TABLE)
                .select(_SELECT_COLS)
                .order("created_at", desc=True)
                .limit(limit)
            )
            if pattern_fragment is not None:
                q = q.ilike("failure_pattern", f"%{pattern_fragment}%")
            if blame_step is not None:
                q = q.eq("blame_step", blame_step)

            response = q.execute()
            return response.data or []
        except FailureLibraryError:
            raise
        except Exception as exc:
            raise FailureLibraryError(f"query failed: {exc}") from exc

    def get_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return all entries, newest first.

        Convenience wrapper used by Blibech's semantic matcher to retrieve
        the full library for relevance scoring.

        Parameters
        ----------
        limit:
            Maximum rows returned; defaults to 100.

        Raises
        ------
        FailureLibraryError
            On any Supabase / network error.
        """
        return self.query(limit=limit)

    def __repr__(self) -> str:
        return f"FailureLibraryStore(table={_TABLE!r})"
