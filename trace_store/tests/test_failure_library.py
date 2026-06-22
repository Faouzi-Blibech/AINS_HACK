"""Tests for trace_store/failure_library.py.

Integration tests that talk to a real Supabase project.
They are skipped automatically when SUPABASE_URL / SUPABASE_KEY are not set
so the test suite stays green in CI without credentials.

Before running these tests:
1. Create the ``failure_library`` table (DDL in failure_library.py docstring).
2. Set SUPABASE_URL and SUPABASE_KEY in your .env or shell.

Run with:
    pytest trace_store/tests/test_failure_library.py -v
"""
from __future__ import annotations

import os
import time
import uuid

import pytest

# ---------------------------------------------------------------------------
# Skip guard — skip the whole module when credentials are absent.
# ---------------------------------------------------------------------------

_MISSING_CREDS = not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))

pytestmark = pytest.mark.skipif(
    _MISSING_CREDS,
    reason=(
        "SUPABASE_URL and SUPABASE_KEY are not set. "
        "Add them to .env to run the failure_library integration tests."
    ),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def store():
    """Return a FailureLibraryStore connected to the real Supabase project."""
    from trace_store.failure_library import FailureLibraryStore
    return FailureLibraryStore()


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
        assert "id" in row, "Supabase must assign an id"
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
        assert "created_at" in row and row["created_at"], "Supabase must set created_at"


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
        # Allow a moment for write to propagate (Supabase is fast but not
        # instantaneous in some regions).
        time.sleep(0.3)

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
        time.sleep(0.3)

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
        time.sleep(0.3)

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
        time.sleep(0.3)

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
            time.sleep(0.1)  # ensure distinct created_at values
        rows = store.query(pattern_fragment=sentinel)
        assert len(rows) >= 3
        # created_at strings are ISO-8601 and sort lexicographically.
        created_ats = [r["created_at"] for r in rows[:3]]
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
        time.sleep(0.3)
        rows = store.get_all(limit=3)
        assert len(rows) <= 3


# ---------------------------------------------------------------------------
# Tests — error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_missing_credentials_raises(self):
        from trace_store.failure_library import FailureLibraryStore, FailureLibraryError
        with pytest.raises(FailureLibraryError, match="SUPABASE_URL"):
            FailureLibraryStore(url="", key="")
