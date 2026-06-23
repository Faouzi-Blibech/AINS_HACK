"""Tests for trace_store/failure_library.py.

Tests that run against a temporary SQLite database.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def temp_db_path(tmp_path) -> Path:
    """Return a path to a temporary SQLite database file."""
    return tmp_path / "test_cassette.sqlite3"


@pytest.fixture()
def store(temp_db_path):
    """Return a FailureLibraryStore connected to a temporary SQLite database."""
    from trace_store.failure_library import FailureLibraryStore
    with FailureLibraryStore(db_path=temp_db_path) as s:
        yield s


@pytest.fixture()
def unique_pattern() -> str:
    """A unique failure-pattern string so tests don't cross-contaminate."""
    return f"test-pattern-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tests — write path
# ---------------------------------------------------------------------------

class TestWriteEntry:
    def test_write_returns_row_with_id(self, store, unique_pattern):
        row = store.write_entry(
            failure_pattern=unique_pattern,
            blame_step=2,
            fix_that_worked="explicit enum constraint",
            agent_config="v1.0",
            determinism_rate=0.95,
        )
        assert "id" in row, "SQLite must assign an id"
        assert row["failure_pattern"] == unique_pattern
        assert row["blame_step"] == 2
        assert row["fix_that_worked"] == "explicit enum constraint"
        assert row["agent_config"] == "v1.0"
        assert abs(row["determinism_rate"] - 0.95) < 1e-6

    def test_write_without_optional_fields(self, store, unique_pattern):
        row = store.write_entry(
            failure_pattern=unique_pattern,
            blame_step=5,
            fix_that_worked="tighten prompt",
        )
        assert row["agent_config"] is None
        assert row["determinism_rate"] is None

    def test_write_returns_created_at(self, store, unique_pattern):
        row = store.write_entry(
            failure_pattern=unique_pattern,
            blame_step=1,
            fix_that_worked="fix",
        )
        assert "created_at" in row and row["created_at"], "SQLite must set created_at"


# ---------------------------------------------------------------------------
# Tests — read path
# ---------------------------------------------------------------------------

class TestQuery:
    def test_query_by_pattern_fragment(self, store):
        sentinel = f"sentinel-{uuid.uuid4().hex[:8]}"
        store.write_entry(
            failure_pattern=f"ambiguous priority {sentinel} caused routing error",
            blame_step=2,
            fix_that_worked="explicit enum",
        )

        rows = store.query(pattern_fragment=sentinel)
        assert len(rows) >= 1, f"Expected at least one row matching {sentinel!r}"
        for row in rows:
            assert sentinel in row["failure_pattern"]

    def test_query_by_blame_step(self, store):
        sentinel = f"sentinel-{uuid.uuid4().hex[:8]}"
        store.write_entry(
            failure_pattern=f"step-filter test {sentinel}",
            blame_step=7,
            fix_that_worked="fix step 7",
        )

        rows = store.query(blame_step=7, pattern_fragment=sentinel)
        assert all(r["blame_step"] == 7 for r in rows)

    def test_query_combined_filters(self, store):
        sentinel = f"sentinel-{uuid.uuid4().hex[:8]}"
        store.write_entry(
            failure_pattern=f"combined filter {sentinel}",
            blame_step=3,
            fix_that_worked="fix",
        )
        store.write_entry(
            failure_pattern=f"combined filter {sentinel}",
            blame_step=9,
            fix_that_worked="other fix",
        )

        rows = store.query(pattern_fragment=sentinel, blame_step=3)
        assert all(r["blame_step"] == 3 for r in rows)
        assert all(sentinel in r["failure_pattern"] for r in rows)

    def test_query_limit_is_respected(self, store):
        sentinel = f"sentinel-{uuid.uuid4().hex[:8]}"
        for i in range(5):
            store.write_entry(
                failure_pattern=f"limit test {sentinel} item {i}",
                blame_step=1,
                fix_that_worked="fix",
            )

        rows = store.query(pattern_fragment=sentinel, limit=3)
        assert len(rows) <= 3

    def test_query_newest_first(self, store):
        sentinel = f"sentinel-{uuid.uuid4().hex[:8]}"
        for i in range(3):
            store.write_entry(
                failure_pattern=f"order test {sentinel}",
                blame_step=i,
                fix_that_worked="fix",
            )
            time.sleep(0.01)
        rows = store.query(pattern_fragment=sentinel)
        assert len(rows) >= 3
        created_ats = [r["created_at"] for r in rows[:3]]
        # created_at strings are ISO-8601 and sort lexicographically.
        assert created_ats == sorted(created_ats, reverse=True)


class TestGetAll:
    def test_get_all_returns_list(self, store):
        rows = store.get_all(limit=5)
        assert isinstance(rows, list)

    def test_get_all_limit(self, store):
        sentinel = f"sentinel-{uuid.uuid4().hex[:8]}"
        for i in range(5):
            store.write_entry(
                failure_pattern=f"get_all limit test {sentinel}",
                blame_step=1,
                fix_that_worked="fix",
            )
        rows = store.get_all(limit=3)
        assert len(rows) <= 3


# ---------------------------------------------------------------------------
# Tests — error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_invalid_db_path_raises(self):
        from trace_store.failure_library import FailureLibraryStore, FailureLibraryError
        # In SQLite, attempting to connect to a directory as a file raises sqlite3.OperationalError
        # or similar, which should be wrapped in FailureLibraryError.
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FailureLibraryError):
                FailureLibraryStore(db_path=tmpdir)
