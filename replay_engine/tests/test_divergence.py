"""Tests for replay_engine/divergence.py and replay_engine/snapshot.py."""
from __future__ import annotations

import json
import os
import pathlib
import tempfile

import pytest

os.environ.setdefault("CASSETTE_BLOB_DIR", tempfile.mkdtemp())

from trace_store.store import TraceStore
from trace_store.blob_store import store_blob, fetch_blob
from replay_engine.divergence import Divergence, DivergenceError
from replay_engine.snapshot import snapshot, resume, SnapshotError

FIXTURE_PATH = (
    pathlib.Path(__file__).parents[2] / "docs" / "fixtures" / "sample_trace.json"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fixture_trace() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def store(tmp_path, monkeypatch):
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()
    monkeypatch.setenv("CASSETTE_BLOB_DIR", str(blob_dir))
    ts = TraceStore(db_path=str(tmp_path / "test.sqlite3"))
    yield ts
    ts.close()


@pytest.fixture()
def populated_store(store, fixture_trace, tmp_path):
    """Store pre-loaded with fixture using real blobs."""
    # Store real blobs for every blob field in the fixture
    real_steps = []
    for step in fixture_trace["steps"]:
        patched = dict(step)
        for field in ("prompt_blob", "response_blob", "args_blob", "result_blob"):
            if field in patched:
                dummy = json.dumps({"data": field, "step_id": step["step_id"]})
                patched[field] = store_blob(dummy)
        real_steps.append(patched)

    store.start_run(
        run_id=fixture_trace["run_id"],
        agent=fixture_trace.get("agent", ""),
        mode=fixture_trace.get("mode", "record"),
        created_at_ms=fixture_trace["created_at_ms"],
    )
    for step in real_steps:
        store.append_step(fixture_trace["run_id"], step)
    store._real_steps = real_steps
    return store


# ---------------------------------------------------------------------------
# Divergence tests
# ---------------------------------------------------------------------------

class TestDivergenceFork:
    def test_fork_creates_new_run(self, populated_store, fixture_trace):
        div = Divergence(populated_store)
        new_id = div.fork(
            run_id=fixture_trace["run_id"],
            fork_step_id=2,
            edit={"_result_content": '{"priority": "critical"}'},
            new_run_id="forked-run-001",
        )
        assert new_id == "forked-run-001"
        runs = populated_store.list_runs()
        run_ids = {r["run_id"] for r in runs}
        assert "forked-run-001" in run_ids

    def test_fork_mode_is_record_over(self, populated_store, fixture_trace):
        div = Divergence(populated_store)
        new_id = div.fork(fixture_trace["run_id"], fork_step_id=2,
                          edit={"_result_content": '{"priority": "critical"}'})
        forked = populated_store.get_run(new_id)
        assert forked["mode"] == "record-over"
        assert forked["parent_run_id"] == fixture_trace["run_id"]
        assert forked["fork_step_id"] == 2

    def test_fork_copies_steps_before_fork(self, populated_store, fixture_trace):
        div = Divergence(populated_store)
        new_id = div.fork(fixture_trace["run_id"], fork_step_id=3,
                          edit={"_result_content": '{"ok": true, "assigned_to": "Backend"}'})
        forked = populated_store.get_run(new_id)
        # Steps 1, 2 copied + step 3 edited = 3 total
        assert len(forked["steps"]) == 3
        assert forked["steps"][0]["step_id"] == 1
        assert forked["steps"][1]["step_id"] == 2

    def test_fork_applies_edit_at_fork_step(self, populated_store, fixture_trace):
        new_result = '{"priority": "critical"}'
        div = Divergence(populated_store)
        new_id = div.fork(fixture_trace["run_id"], fork_step_id=2,
                          edit={"_result_content": new_result})
        forked = populated_store.get_run(new_id)
        fork_step = next(s for s in forked["steps"] if s["step_id"] == 2)
        # The result_blob should now resolve to the new content
        assert json.loads(fetch_blob(fork_step["result_blob"])) == {"priority": "critical"}

    def test_fork_does_not_copy_steps_after_fork(self, populated_store, fixture_trace):
        """Steps after the fork point must NOT be in the forked run — agent continues live."""
        div = Divergence(populated_store)
        new_id = div.fork(fixture_trace["run_id"], fork_step_id=2,
                          edit={"_result_content": '{"priority": "critical"}'})
        forked = populated_store.get_run(new_id)
        step_ids = [s["step_id"] for s in forked["steps"]]
        assert 3 not in step_ids
        assert 4 not in step_ids

    def test_fork_with_invalid_step_id_raises(self, populated_store, fixture_trace):
        div = Divergence(populated_store)
        with pytest.raises(DivergenceError, match="step_id 99 not found"):
            div.fork(fixture_trace["run_id"], fork_step_id=99,
                     edit={"_result_content": "{}"})

    def test_fork_at_step_1_has_no_prefix_steps(self, populated_store, fixture_trace):
        """Fork at step 1 → only the edited step 1, nothing before it."""
        div = Divergence(populated_store)
        new_id = div.fork(fixture_trace["run_id"], fork_step_id=1,
                          edit={"_response_content": '{"intent": "escalate"}'})
        forked = populated_store.get_run(new_id)
        assert len(forked["steps"]) == 1
        assert forked["steps"][0]["step_id"] == 1


class TestDivergenceCompare:
    def test_compare_detects_edited_fields(self, populated_store, fixture_trace):
        div = Divergence(populated_store)
        new_id = div.fork(fixture_trace["run_id"], fork_step_id=2,
                          edit={"_result_content": '{"priority": "critical"}'})
        diff = div.compare(fixture_trace["run_id"], new_id)
        assert diff["fork_step_id"] == 2
        assert "result_blob" in diff["edited_fields"]

    def test_compare_step_counts(self, populated_store, fixture_trace):
        div = Divergence(populated_store)
        new_id = div.fork(fixture_trace["run_id"], fork_step_id=2,
                          edit={"_result_content": '{"priority": "critical"}'})
        diff = div.compare(fixture_trace["run_id"], new_id)
        assert diff["original_steps"] == 4
        assert diff["forked_steps"] == 2  # step 1 (copy) + step 2 (edited)


# ---------------------------------------------------------------------------
# Snapshot tests
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_returns_snapshot_ref(self, populated_store, fixture_trace):
        ref = snapshot(populated_store, fixture_trace["run_id"], step_id=2)
        assert ref.startswith("snapshot:")

    def test_snapshot_resume_round_trip(self, populated_store, fixture_trace):
        ref = snapshot(populated_store, fixture_trace["run_id"], step_id=2)
        ctx = resume(ref)
        assert ctx["run_id"] == fixture_trace["run_id"]
        assert ctx["snapshot_at_step"] == 2

    def test_snapshot_only_captures_steps_up_to_step_id(self, populated_store, fixture_trace):
        ref = snapshot(populated_store, fixture_trace["run_id"], step_id=2)
        ctx = resume(ref)
        step_ids = [s["step_id"] for s in ctx["steps"]]
        assert step_ids == [1, 2]
        assert 3 not in step_ids
        assert 4 not in step_ids

    def test_snapshot_all_steps(self, populated_store, fixture_trace):
        ref = snapshot(populated_store, fixture_trace["run_id"], step_id=4)
        ctx = resume(ref)
        assert len(ctx["steps"]) == 4

    def test_resume_invalid_ref_raises(self, populated_store):
        with pytest.raises(SnapshotError, match="Invalid snapshot ref"):
            resume("sha256:not-a-snapshot-ref")

    def test_two_snapshots_at_different_steps_differ(self, populated_store, fixture_trace):
        ref2 = snapshot(populated_store, fixture_trace["run_id"], step_id=2)
        ref4 = snapshot(populated_store, fixture_trace["run_id"], step_id=4)
        assert ref2 != ref4
