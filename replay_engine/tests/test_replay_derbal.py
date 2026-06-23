"""Tests for Derbal's hash-matching and sequential-matching APIs in replay.py.

Abdelhedi's test_replay.py covers the response_for() proxy-hook path.
This file covers get_response_for_hash() and get_next_response().
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile

import pytest

os.environ.setdefault("CASSETTE_BLOB_DIR", tempfile.mkdtemp())

from trace_store.store import TraceStore
from trace_store.blob_store import store_blob
from replay_engine.replay import Replayer, ReplayError

FIXTURE_PATH = (
    pathlib.Path(__file__).parents[2] / "docs" / "fixtures" / "sample_trace.json"
)


@pytest.fixture()
def fixture_trace() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def populated_store(tmp_path, monkeypatch, fixture_trace):
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()
    monkeypatch.setenv("CASSETTE_BLOB_DIR", str(blob_dir))

    # Build a mapping: fake ref → real ref (from store_blob).
    # Each dummy payload gets stored as a real blob so its hash = filename.
    # We then patch the steps so they point to the real refs.
    real_steps = []
    for step in fixture_trace["steps"]:
        patched = dict(step)
        for field in ("prompt_blob", "response_blob", "args_blob", "result_blob"):
            if field in patched:
                dummy_content = json.dumps(
                    {"mocked_data_for": field, "step_id": step["step_id"]}
                )
                real_ref = store_blob(dummy_content)   # real hash = content hash
                patched[field] = real_ref
        real_steps.append(patched)

    db = tmp_path / "test.sqlite3"
    ts = TraceStore(db_path=str(db))
    ts.start_run(
        run_id=fixture_trace["run_id"],
        agent=fixture_trace.get("agent", ""),
        mode=fixture_trace.get("mode", "record"),
        created_at_ms=fixture_trace["created_at_ms"],
    )
    for step in real_steps:
        ts.append_step(fixture_trace["run_id"], step)

    # Expose the patched steps so tests can look up real refs
    ts._test_steps = real_steps
    yield ts
    ts.close()


class TestHashMatching:
    def test_llm_call_matched_by_prompt_blob(self, populated_store, fixture_trace):
        replayer = Replayer(populated_store, fixture_trace["run_id"])
        prompt_ref = populated_store._test_steps[0]["prompt_blob"]  # real ref
        resp = replayer.get_response_for_hash(prompt_ref)
        assert resp["step_id"] == 1
        assert resp["mocked_side_effect"] is False

    def test_readonly_tool_not_mocked(self, populated_store, fixture_trace):
        replayer = Replayer(populated_store, fixture_trace["run_id"])
        args_ref = populated_store._test_steps[1]["args_blob"]  # real ref
        resp = replayer.get_response_for_hash(args_ref)
        assert resp["step_id"] == 2
        assert resp["mocked_side_effect"] is False

    def test_side_effecting_tool_mocked(self, populated_store, fixture_trace):
        replayer = Replayer(populated_store, fixture_trace["run_id"])
        args_ref = populated_store._test_steps[2]["args_blob"]  # real ref
        resp = replayer.get_response_for_hash(args_ref)
        assert resp["step_id"] == 3
        assert resp["mocked_side_effect"] is True

    def test_side_effect_count_stays_zero(self, populated_store, fixture_trace):
        replayer = Replayer(populated_store, fixture_trace["run_id"])
        for step in populated_store._test_steps:  # real refs
            key = step.get("args_blob") or step.get("prompt_blob")
            replayer.get_response_for_hash(key)
        assert replayer.side_effect_count == 0

    def test_unknown_hash_raises(self, populated_store, fixture_trace):
        # synthesize_on_miss=False: a miss must raise ReplayError.
        # (With the default True a miss would call the mock synthesizer instead.)
        replayer = Replayer(populated_store, fixture_trace["run_id"], synthesize_on_miss=False)
        with pytest.raises(ReplayError, match="No recorded step found"):
            replayer.get_response_for_hash("sha256:" + "dead" * 16)


    def test_order_independent(self, populated_store, fixture_trace):
        replayer = Replayer(populated_store, fixture_trace["run_id"])
        for step in reversed(populated_store._test_steps):  # real refs
            key = step.get("args_blob") or step.get("prompt_blob")
            resp = replayer.get_response_for_hash(key)
            assert resp["step_id"] == step["step_id"]

    # ------------------------------------------------------------------
    # EC-3 regression: duplicate blob refs served in recorded order
    # ------------------------------------------------------------------

    def test_duplicate_hash_served_in_order(self, tmp_path, monkeypatch):
        """Two tool_call steps sharing the same args_blob are served FIFO.

        Before the EC-3 fix _hash_index[key] = step overwrote the first step;
        both replay calls returned step 2's response. After the fix step 1 is
        returned first and step 2 is returned second.
        """
        blob_dir = tmp_path / "blobs"
        blob_dir.mkdir()
        monkeypatch.setenv("CASSETTE_BLOB_DIR", str(blob_dir))

        shared_args_ref = store_blob(json.dumps({"ticket_id": "JIRA-42"}))
        result_ref_1 = store_blob(json.dumps({"priority": "high"}))
        result_ref_2 = store_blob(json.dumps({"priority": "critical"}))

        db = tmp_path / "dup.sqlite3"
        ts = TraceStore(db_path=str(db))
        ts.start_run("dup-run", agent="test", mode="record")
        ts.append_step("dup-run", {
            "step_id": 1, "type": "tool_call", "timestamp_ms": 1000,
            "args_blob": shared_args_ref, "result_blob": result_ref_1,
            "side_effecting": False,
        })
        ts.append_step("dup-run", {
            "step_id": 2, "type": "tool_call", "timestamp_ms": 2000,
            "args_blob": shared_args_ref, "result_blob": result_ref_2,
            "side_effecting": False,
        })

        replayer = Replayer(ts, "dup-run")

        resp1 = replayer.get_response_for_hash(shared_args_ref)
        resp2 = replayer.get_response_for_hash(shared_args_ref)

        assert resp1["step_id"] == 1, "first duplicate call must return step 1"
        assert resp2["step_id"] == 2, "second duplicate call must return step 2"
        ts.close()

    def test_duplicate_hash_exhausted_deque_raises(self, tmp_path, monkeypatch):
        """A (N+1)-th call on an N-step duplicate deque is treated as a miss.

        With synthesize_on_miss=False this means ReplayError is raised, not
        a silent wrong response.
        """
        blob_dir = tmp_path / "blobs"
        blob_dir.mkdir()
        monkeypatch.setenv("CASSETTE_BLOB_DIR", str(blob_dir))

        shared_args_ref = store_blob(json.dumps({"ticket_id": "JIRA-42"}))
        result_ref = store_blob(json.dumps({"priority": "high"}))

        db = tmp_path / "exhaust.sqlite3"
        ts = TraceStore(db_path=str(db))
        ts.start_run("exhaust-run", agent="test", mode="record")
        for sid in (1, 2):
            ts.append_step("exhaust-run", {
                "step_id": sid, "type": "tool_call", "timestamp_ms": sid * 1000,
                "args_blob": shared_args_ref, "result_blob": result_ref,
                "side_effecting": False,
            })

        replayer = Replayer(ts, "exhaust-run", synthesize_on_miss=False)
        replayer.get_response_for_hash(shared_args_ref)  # step 1
        replayer.get_response_for_hash(shared_args_ref)  # step 2
        with pytest.raises(ReplayError, match="No recorded step found"):
            replayer.get_response_for_hash(shared_args_ref)  # 3rd call — miss
        ts.close()



class TestSequentialMatching:
    def test_full_loop_side_effect_counter(self, populated_store, fixture_trace):
        replayer = Replayer(populated_store, fixture_trace["run_id"])
        replayer.get_next_response("llm_call")
        replayer.get_next_response("tool_call")
        replayer.get_next_response("tool_call")
        replayer.get_next_response("tool_call")
        result = replayer.finish()
        assert result.steps_replayed == 4
        assert result.side_effect_count == 0
        assert result.status == "ok"

    def test_wrong_type_raises(self, populated_store, fixture_trace):
        replayer = Replayer(populated_store, fixture_trace["run_id"])
        with pytest.raises(ReplayError, match="Expected tool_call, but tape has llm_call"):
            replayer.get_next_response("tool_call")

    def test_tape_exhausted_raises(self, populated_store, fixture_trace):
        replayer = Replayer(populated_store, fixture_trace["run_id"])
        for step in fixture_trace["steps"]:
            replayer.get_next_response(step["type"])
        with pytest.raises(ReplayError, match="tape is out of recorded steps"):
            replayer.get_next_response("llm_call")

    def test_incomplete_finish(self, populated_store, fixture_trace):
        replayer = Replayer(populated_store, fixture_trace["run_id"])
        replayer.get_next_response("llm_call")
        result = replayer.finish()
        assert result.steps_replayed == 1
        assert result.status == "incomplete"
