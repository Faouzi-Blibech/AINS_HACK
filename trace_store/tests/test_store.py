"""Tests for trace_store/store.py against the sample fixture.

Run with:
    pytest trace_store/tests/test_store.py -v
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

# Locate the fixture relative to this file (works from any cwd)
FIXTURE_PATH = (
    pathlib.Path(__file__).parents[2] / "docs" / "fixtures" / "sample_trace.json"
)


@pytest.fixture()
def fixture_trace() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def store(tmp_path):
    """Return a fresh TraceStore pointing at a temp SQLite file."""
    from trace_store.store import TraceStore
    db = tmp_path / "test.sqlite3"
    ts = TraceStore(db_path=str(db))
    yield ts
    ts.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture_into_store(store, trace: dict) -> None:
    """Write a trace dict into the store the same way the recorder would."""
    store.start_run(
        run_id=trace["run_id"],
        agent=trace.get("agent", ""),
        mode=trace.get("mode", "record"),
        created_at_ms=trace["created_at_ms"],
        schema_version=trace.get("schema_version", "1.0"),
        parent_run_id=trace.get("parent_run_id"),
        fork_step_id=trace.get("fork_step_id"),
    )
    for step in trace["steps"]:
        store.append_step(trace["run_id"], step)
    store.finish_run(
        trace["run_id"],
        status=trace.get("status", "ok"),
        duration_ms=trace.get("duration_ms"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStartRun:
    def test_start_run_appears_in_list_runs(self, store, fixture_trace):
        store.start_run(fixture_trace["run_id"], agent="test-agent")
        runs = store.list_runs()
        assert len(runs) == 1
        assert runs[0]["run_id"] == fixture_trace["run_id"]

    def test_duplicate_run_id_raises(self, store, fixture_trace):
        store.start_run(fixture_trace["run_id"])
        with pytest.raises(Exception):  # sqlite3.IntegrityError
            store.start_run(fixture_trace["run_id"])


class TestAppendStep:
    def test_append_step_requires_existing_run(self, store, fixture_trace):
        with pytest.raises(Exception):  # FK violation or missing run
            store.append_step("nonexistent-run", fixture_trace["steps"][0])

    def test_append_step_persists(self, store, fixture_trace):
        store.start_run(fixture_trace["run_id"])
        store.append_step(fixture_trace["run_id"], fixture_trace["steps"][0])
        doc = store.get_run(fixture_trace["run_id"])
        assert len(doc["steps"]) == 1


class TestGetRun:
    def test_unknown_run_raises_key_error(self, store):
        with pytest.raises(KeyError):
            store.get_run("does-not-exist")

    def test_full_round_trip_fixture(self, store, fixture_trace):
        """Write the fixture, read it back, compare every field."""
        _load_fixture_into_store(store, fixture_trace)
        doc = store.get_run(fixture_trace["run_id"])

        # --- run-level fields ---
        assert doc["run_id"] == fixture_trace["run_id"]
        assert doc["schema_version"] == fixture_trace["schema_version"]
        assert doc["agent"] == fixture_trace["agent"]
        assert doc["created_at_ms"] == fixture_trace["created_at_ms"]
        assert doc["mode"] == fixture_trace["mode"]
        assert doc["parent_run_id"] == fixture_trace["parent_run_id"]
        assert doc["fork_step_id"] == fixture_trace["fork_step_id"]
        assert doc["status"] == fixture_trace["status"]
        assert doc["duration_ms"] == fixture_trace["duration_ms"]

        # --- steps ---
        assert len(doc["steps"]) == len(fixture_trace["steps"])

    def test_step_order_preserved(self, store, fixture_trace):
        # Insert in reverse order to verify ORDER BY step_id in get_run
        store.start_run(fixture_trace["run_id"])
        for step in reversed(fixture_trace["steps"]):
            store.append_step(fixture_trace["run_id"], step)
        doc = store.get_run(fixture_trace["run_id"])
        ids = [s["step_id"] for s in doc["steps"]]
        assert ids == sorted(ids)

    def test_step_scalar_fields_round_trip(self, store, fixture_trace):
        _load_fixture_into_store(store, fixture_trace)
        doc = store.get_run(fixture_trace["run_id"])

        orig_by_id = {s["step_id"]: s for s in fixture_trace["steps"]}
        for step in doc["steps"]:
            orig = orig_by_id[step["step_id"]]
            for field in (
                "step_id", "type", "timestamp_ms", "latency_ms",
                "side_effecting", "status",
            ):
                if field in orig:
                    assert step[field] == orig[field], (
                        f"step {step['step_id']}.{field}: "
                        f"got {step[field]!r}, want {orig[field]!r}"
                    )

    def test_side_effecting_is_bool(self, store, fixture_trace):
        _load_fixture_into_store(store, fixture_trace)
        doc = store.get_run(fixture_trace["run_id"])
        for step in doc["steps"]:
            assert isinstance(step["side_effecting"], bool)

    def test_causal_parents_round_trip(self, store, fixture_trace):
        _load_fixture_into_store(store, fixture_trace)
        doc = store.get_run(fixture_trace["run_id"])

        orig_by_id = {s["step_id"]: s for s in fixture_trace["steps"]}
        for step in doc["steps"]:
            orig = orig_by_id[step["step_id"]]
            assert step.get("causal_parents") == orig.get("causal_parents")

    def test_blob_refs_round_trip(self, store, fixture_trace):
        _load_fixture_into_store(store, fixture_trace)
        doc = store.get_run(fixture_trace["run_id"])

        orig_by_id = {s["step_id"]: s for s in fixture_trace["steps"]}
        for step in doc["steps"]:
            orig = orig_by_id[step["step_id"]]
            for blob_field in (
                "prompt_blob", "response_blob", "args_blob", "result_blob"
            ):
                if blob_field in orig:
                    assert step.get(blob_field) == orig[blob_field], blob_field

    def test_llm_call_specific_fields(self, store, fixture_trace):
        _load_fixture_into_store(store, fixture_trace)
        doc = store.get_run(fixture_trace["run_id"])

        llm_step = next(s for s in doc["steps"] if s["type"] == "llm_call")
        orig_llm = next(
            s for s in fixture_trace["steps"] if s["type"] == "llm_call"
        )
        assert llm_step.get("model") == orig_llm.get("model")
        assert llm_step.get("token_usage") == orig_llm.get("token_usage")
        assert llm_step.get("confidence") == orig_llm.get("confidence")

    def test_tool_call_specific_fields(self, store, fixture_trace):
        _load_fixture_into_store(store, fixture_trace)
        doc = store.get_run(fixture_trace["run_id"])

        tool_steps = [s for s in doc["steps"] if s["type"] == "tool_call"]
        orig_by_id = {s["step_id"]: s for s in fixture_trace["steps"]}
        for step in tool_steps:
            orig = orig_by_id[step["step_id"]]
            assert step.get("tool") == orig.get("tool")
            assert step.get("transport") == orig.get("transport")


class TestListRuns:
    def test_empty(self, store):
        assert store.list_runs() == []

    def test_multiple_runs_listed(self, store, fixture_trace):
        store.start_run("run-a")
        store.start_run("run-b")
        runs = store.list_runs()
        assert {r["run_id"] for r in runs} == {"run-a", "run-b"}


class TestContextManager:
    def test_context_manager_closes_cleanly(self, tmp_path):
        from trace_store.store import TraceStore
        with TraceStore(tmp_path / "ctx.sqlite3") as ts:
            ts.start_run("r1")
        # Connection is closed; no exception


class TestFinishRun:
    def test_finish_run_updates_status_and_duration(self, store, fixture_trace):
        store.start_run(fixture_trace["run_id"])
        store.finish_run(fixture_trace["run_id"], status="error", duration_ms=1540)
        doc = store.get_run(fixture_trace["run_id"])
        assert doc["status"] == "error"
        assert doc["duration_ms"] == 1540
