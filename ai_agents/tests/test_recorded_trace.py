"""Tests for ai_agents/recorded_trace.py -- offline, SEED path only.

Do NOT invoke the real recorder in these tests. All tests use the fixture
at docs/fixtures/sample_trace.json and the blobs at docs/fixtures/blobs/.

Run from the repo root:
    python -m pytest ai_agents/tests/test_recorded_trace.py -q
"""
from __future__ import annotations

import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "docs" / "fixtures" / "sample_trace.json"
BLOBS_DIR = str(REPO_ROOT / "docs" / "fixtures" / "blobs")


# ---------------------------------------------------------------------------
# Shared pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fixture_trace() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A fresh, empty TraceStore with CASSETTE_BLOB_DIR set."""
    monkeypatch.setenv("CASSETTE_BLOB_DIR", BLOBS_DIR)

    from trace_store.store import TraceStore

    db_path = tmp_path / "cassette_test.sqlite3"
    ts = TraceStore(db_path=str(db_path))
    yield ts
    ts.close()


# ---------------------------------------------------------------------------
# Test 1: seed_store_from_fixture round-trip
# ---------------------------------------------------------------------------


class TestSeedStoreFromFixture:

    def test_returns_fixture_run_id(self, store):
        from ai_agents.recorded_trace import seed_store_from_fixture

        run_id = seed_store_from_fixture(store, FIXTURE_PATH)
        assert run_id == "run-fixture-001"

    def test_run_exists_in_store(self, store):
        from ai_agents.recorded_trace import seed_store_from_fixture

        run_id = seed_store_from_fixture(store, FIXTURE_PATH)
        trace = store.get_run(run_id)
        assert trace["run_id"] == run_id

    def test_all_four_steps_stored(self, store):
        from ai_agents.recorded_trace import seed_store_from_fixture

        run_id = seed_store_from_fixture(store, FIXTURE_PATH)
        trace = store.get_run(run_id)
        assert len(trace["steps"]) == 4

    def test_causal_parents_preserved_step3(self, store):
        """Step 3 must have causal_parents == [1, 2]."""
        from ai_agents.recorded_trace import seed_store_from_fixture

        run_id = seed_store_from_fixture(store, FIXTURE_PATH)
        trace = store.get_run(run_id)
        step3 = next(s for s in trace["steps"] if s["step_id"] == 3)
        assert step3.get("causal_parents") == [1, 2]

    def test_causal_parents_preserved_step4(self, store):
        """Step 4 must have causal_parents == [3]."""
        from ai_agents.recorded_trace import seed_store_from_fixture

        run_id = seed_store_from_fixture(store, FIXTURE_PATH)
        trace = store.get_run(run_id)
        step4 = next(s for s in trace["steps"] if s["step_id"] == 4)
        assert step4.get("causal_parents") == [3]

    def test_run_status_preserved(self, store):
        from ai_agents.recorded_trace import seed_store_from_fixture

        run_id = seed_store_from_fixture(store, FIXTURE_PATH)
        trace = store.get_run(run_id)
        assert trace["status"] == "error"


# ---------------------------------------------------------------------------
# Test 2: obtain_recorded_trace(prefer_record=False) returns fixture
# ---------------------------------------------------------------------------


class TestObtainRecordedTrace:

    def test_returns_fixture_run_id(self):
        from ai_agents.recorded_trace import obtain_recorded_trace

        trace, blob_dir = obtain_recorded_trace(
            prefer_record=False,
            fixture_path=FIXTURE_PATH,
        )
        assert trace["run_id"] == "run-fixture-001"

    def test_returns_blob_dir_string(self):
        from ai_agents.recorded_trace import obtain_recorded_trace

        trace, blob_dir = obtain_recorded_trace(
            prefer_record=False,
            fixture_path=FIXTURE_PATH,
        )
        assert blob_dir is not None
        assert pathlib.Path(blob_dir).is_dir()

    def test_blob_dir_points_at_fixture_blobs(self):
        from ai_agents.recorded_trace import obtain_recorded_trace

        trace, blob_dir = obtain_recorded_trace(
            prefer_record=False,
            fixture_path=FIXTURE_PATH,
        )
        assert pathlib.Path(blob_dir).resolve() == (
            REPO_ROOT / "docs" / "fixtures" / "blobs"
        ).resolve()

    def test_trace_has_four_steps(self):
        from ai_agents.recorded_trace import obtain_recorded_trace

        trace, _ = obtain_recorded_trace(
            prefer_record=False,
            fixture_path=FIXTURE_PATH,
        )
        assert len(trace["steps"]) == 4


# ---------------------------------------------------------------------------
# Test 3: analyze_recorded returns correct BlameGraph
# ---------------------------------------------------------------------------


class TestAnalyzeRecorded:

    def test_root_cause_step_id_is_2(self, fixture_trace):
        from ai_agents.recorded_trace import analyze_recorded

        graph = analyze_recorded(fixture_trace, blob_dir=BLOBS_DIR)
        assert graph.root_cause_step_id == 2

    def test_verdict_names_step_2(self, fixture_trace):
        from ai_agents.recorded_trace import analyze_recorded

        graph = analyze_recorded(fixture_trace, blob_dir=BLOBS_DIR)
        assert "2" in graph.verdict

    def test_step2_rationale_contains_medium(self, fixture_trace):
        """Content blob for step 2 resolves to {priority: medium}; rationale must mention it."""
        from ai_agents.recorded_trace import analyze_recorded

        graph = analyze_recorded(fixture_trace, blob_dir=BLOBS_DIR)
        step2_score = next(s for s in graph.steps if s.step_id == 2)
        assert "medium" in step2_score.rationale

    def test_returns_blame_graph_type(self, fixture_trace):
        from ai_agents.recorded_trace import analyze_recorded
        from ai_agents.root_cause import BlameGraph

        graph = analyze_recorded(fixture_trace, blob_dir=BLOBS_DIR)
        assert isinstance(graph, BlameGraph)

    def test_failed_step_id_is_4(self, fixture_trace):
        from ai_agents.recorded_trace import analyze_recorded

        graph = analyze_recorded(fixture_trace, blob_dir=BLOBS_DIR)
        assert graph.failed_step_id == 4
