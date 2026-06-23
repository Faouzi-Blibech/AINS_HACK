"""Edge-case hardening tests for replay_engine/replay.py (Day 5).

Covers:
  - synthesize_on_miss=True: unknown hash / request_identity never crashes;
    synthesized_count is incremented.
  - Unexpected exception during blob fetch falls back to synthesizer.
  - Error-step faithful mode: payload is always a dict with is_error_step=True.
  - Error-step suppress mode: empty success payload returned.

Run with:
    pytest replay_engine/tests/test_replay_hardening.py -v
"""
from __future__ import annotations

import json
import os
import tempfile
import pathlib
from unittest.mock import patch, MagicMock

import pytest

# Point blob store at a temp dir before importing anything that uses it.
os.environ.setdefault("CASSETTE_BLOB_DIR", tempfile.mkdtemp())

from trace_store.store import TraceStore
from trace_store.blob_store import store_blob
from replay_engine.replay import Replayer, ReplayError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path, steps: list[dict], *, run_id: str = "test-run") -> TraceStore:
    """Build a TraceStore pre-populated with *steps* for *run_id*."""
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir(exist_ok=True)
    os.environ["CASSETTE_BLOB_DIR"] = str(blob_dir)

    db = tmp_path / "test.sqlite3"
    ts = TraceStore(db_path=str(db))
    ts.start_run(run_id, agent="test", mode="record")
    for step in steps:
        ts.append_step(run_id, step)
    ts.finish_run(run_id, status="ok")
    return ts


def _stored_blob(tmp_path, payload: dict) -> str:
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir(exist_ok=True)
    os.environ["CASSETTE_BLOB_DIR"] = str(blob_dir)
    return store_blob(json.dumps(payload))


# ---------------------------------------------------------------------------
# 1. Hash-miss → synthesizer (synthesize_on_miss=True default)
# ---------------------------------------------------------------------------

class TestMissSynthesizer:
    def test_unknown_hash_no_crash(self, tmp_path):
        """A call with an unrecorded hash must not raise; synthesized_count goes up."""
        args_ref = _stored_blob(tmp_path, {"ticket_id": "JIRA-1"})
        result_ref = _stored_blob(tmp_path, {"priority": "high"})
        ts = _make_store(tmp_path, [
            {
                "step_id": 1, "type": "tool_call", "timestamp_ms": 1000,
                "args_blob": args_ref, "result_blob": result_ref,
                "side_effecting": False,
            }
        ])

        replayer = Replayer(ts, "test-run", synthesize_on_miss=True)

        unknown_hash = "sha256:" + "ab" * 32
        with patch("ai_agents.mock_synthesizer.synthesize") as mock_synth:
            mock_synth.return_value = MagicMock(
                value={"synthesized_field": True},
                confidence=0.5,
                rationale="test synthesizer",
            )
            resp = replayer.get_response_for_hash(unknown_hash)

        assert resp["synthesized"] is True, "response must be marked synthesized"
        assert replayer.synthesized_count == 1

    def test_synthesize_false_raises(self, tmp_path):
        """With synthesize_on_miss=False an unknown hash raises ReplayError."""
        args_ref = _stored_blob(tmp_path, {"ticket_id": "JIRA-2"})
        result_ref = _stored_blob(tmp_path, {"priority": "low"})
        ts = _make_store(tmp_path, [
            {
                "step_id": 1, "type": "tool_call", "timestamp_ms": 1000,
                "args_blob": args_ref, "result_blob": result_ref,
                "side_effecting": False,
            }
        ])

        replayer = Replayer(ts, "test-run", synthesize_on_miss=False)
        with pytest.raises(ReplayError, match="No recorded step found"):
            replayer.get_response_for_hash("sha256:" + "cd" * 32)

    def test_unexpected_blob_exception_falls_back(self, tmp_path):
        """An unexpected exception during blob fetch must log and fall back
        to the synthesizer rather than crashing (Day 5 hardening)."""
        args_ref = _stored_blob(tmp_path, {"ticket_id": "JIRA-3"})
        ts = _make_store(tmp_path, [
            {
                "step_id": 1, "type": "tool_call", "timestamp_ms": 1000,
                "args_blob": args_ref, "result_blob": args_ref,
                "side_effecting": False,
            }
        ])

        replayer = Replayer(ts, "test-run", synthesize_on_miss=True)

        unknown_hash = "sha256:" + "ef" * 32
        # Simulate an unexpected exception coming out of fetch_blob
        with patch("replay_engine.replay.fetch_blob", side_effect=RuntimeError("network down")):
            with patch("ai_agents.mock_synthesizer.synthesize") as mock_synth:
                mock_synth.return_value = MagicMock(
                    value={},
                    confidence=0.1,
                    rationale="fallback",
                )
                resp = replayer.get_response_for_hash(unknown_hash)

        assert resp["synthesized"] is True
        assert replayer.synthesized_count == 1

    def test_response_for_miss_synthesizes(self, tmp_path):
        """response_for() with an unrecorded request_identity synthesizes instead of returning None."""
        ts = _make_store(tmp_path, [
            {
                "step_id": 1, "type": "tool_call", "timestamp_ms": 1000,
                "request_identity": "POST /get_priority\nabc123",
                "args_blob": _stored_blob(tmp_path, {}),
                "result_blob": _stored_blob(tmp_path, {"priority": "high"}),
                "side_effecting": False,
            }
        ])

        replayer = Replayer(ts, "test-run", synthesize_on_miss=True)

        with patch("ai_agents.mock_synthesizer.synthesize") as mock_synth:
            mock_synth.return_value = MagicMock(
                value={"ok": True}, confidence=0.7, rationale="synthesized",
            )
            resp = replayer.response_for("POST /unknown_endpoint\ndeadbeef")

        assert resp is not None
        assert resp["synthesized"] is True


# ---------------------------------------------------------------------------
# 2. Error-step envelope guarantee
# ---------------------------------------------------------------------------

class TestErrorStepEnvelope:
    def _make_error_store(self, tmp_path, *, mode: str = "faithful") -> tuple[TraceStore, str]:
        """Store with one error step (status=error, no response blob)."""
        args_ref = _stored_blob(tmp_path, {"ticket_id": "JIRA-99"})
        ts = _make_store(tmp_path, [
            {
                "step_id": 1, "type": "tool_call", "timestamp_ms": 1000,
                "args_blob": args_ref,
                "status": "error",
                "side_effecting": False,
            }
        ])
        return ts

    def test_faithful_error_step_is_dict(self, tmp_path):
        """faithful mode: payload must be a dict (never a raw string or None)."""
        ts = self._make_error_store(tmp_path)
        replayer = Replayer(ts, "test-run", error_step_mode="faithful")
        resp = replayer.get_next_response("tool_call")

        assert resp["is_error_step"] is True
        assert isinstance(resp["payload"], dict), (
            f"payload must be dict, got {type(resp['payload'])!r}: {resp['payload']!r}"
        )

    def test_faithful_error_step_counter(self, tmp_path):
        """faithful mode: error_step_count increments."""
        ts = self._make_error_store(tmp_path)
        replayer = Replayer(ts, "test-run", error_step_mode="faithful")
        replayer.get_next_response("tool_call")
        assert replayer.error_step_count == 1

    def test_suppress_error_step_returns_empty_success(self, tmp_path):
        """suppress mode: error step returns empty payload with status_code=200."""
        ts = self._make_error_store(tmp_path)
        replayer = Replayer(ts, "test-run", error_step_mode="suppress")
        resp = replayer.get_next_response("tool_call")

        assert resp["is_error_step"] is True
        assert resp["status_code"] == 200
        assert resp["payload"] == {}

    def test_non_dict_error_payload_wrapped(self, tmp_path):
        """faithful mode: a raw-string error payload is wrapped in {'_raw': ...}."""
        # Point blob store at tmp_path BEFORE writing any blobs.
        blob_dir = tmp_path / "blobs"
        blob_dir.mkdir(exist_ok=True)
        os.environ["CASSETTE_BLOB_DIR"] = str(blob_dir)

        # Store a blob that decodes to a plain string (not a dict)
        blob_ref = store_blob('"some raw error string"')
        ts = _make_store(tmp_path, [
            {
                "step_id": 1, "type": "tool_call", "timestamp_ms": 1000,
                "args_blob": _stored_blob(tmp_path, {}),
                "result_blob": blob_ref,
                "status": "error",
                "side_effecting": False,
            }
        ])
        replayer = Replayer(ts, "test-run", error_step_mode="faithful")
        resp = replayer.get_next_response("tool_call")

        assert isinstance(resp["payload"], dict)
        assert "_raw" in resp["payload"]

    def test_side_effect_count_stays_zero_on_error_step(self, tmp_path):
        """side_effect_count must remain 0 even when replaying an error step."""
        ts = self._make_error_store(tmp_path)
        replayer = Replayer(ts, "test-run")
        replayer.get_next_response("tool_call")
        assert replayer.side_effect_count == 0


# ---------------------------------------------------------------------------
# 3. Parallel group support
# ---------------------------------------------------------------------------

PG_ID = "pg-test-001"


def _make_parallel_store(tmp_path, *, run_id: str = "parallel-run") -> tuple[TraceStore, dict]:
    """Build a store with one LLM call and three parallel tool calls sharing PG_ID."""
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir(exist_ok=True)
    os.environ["CASSETTE_BLOB_DIR"] = str(blob_dir)

    def _b(payload: dict) -> str:
        return store_blob(json.dumps(payload))

    llm_args_ref  = _b({"prompt": "triage ticket"})
    llm_resp_ref  = _b({"content": "calling 3 tools in parallel"})
    tk_args_ref   = _b({"ticket_id": "JIRA-10"})
    tk_result_ref = _b({"title": "Login broken"})
    us_args_ref   = _b({"user_id": "u-99"})
    us_result_ref = _b({"name": "Alice"})
    pr_args_ref   = _b({"ticket_id": "JIRA-10"})
    pr_result_ref = _b({"priority": "high"})

    steps = [
        {
            "step_id": 1, "type": "llm_call", "timestamp_ms": 1000,
            "prompt_blob": llm_args_ref, "response_blob": llm_resp_ref,
            "side_effecting": False, "causal_parents": [],
        },
        {
            "step_id": 2, "type": "tool_call", "timestamp_ms": 1100,
            "tool": "get_ticket",
            "args_blob": tk_args_ref, "result_blob": tk_result_ref,
            "side_effecting": False, "causal_parents": [1],
            "parallel_group": PG_ID,
        },
        {
            "step_id": 3, "type": "tool_call", "timestamp_ms": 1150,
            "tool": "get_user",
            "args_blob": us_args_ref, "result_blob": us_result_ref,
            "side_effecting": False, "causal_parents": [1],
            "parallel_group": PG_ID,
        },
        {
            "step_id": 4, "type": "tool_call", "timestamp_ms": 1200,
            "tool": "get_priority",
            "args_blob": pr_args_ref, "result_blob": pr_result_ref,
            "side_effecting": False, "causal_parents": [1],
            "parallel_group": PG_ID,
        },
    ]
    refs = {
        "llm_args_ref": llm_args_ref, "llm_resp_ref": llm_resp_ref,
        "tk_args_ref": tk_args_ref,   "tk_result_ref": tk_result_ref,
        "us_args_ref": us_args_ref,   "us_result_ref": us_result_ref,
        "pr_args_ref": pr_args_ref,   "pr_result_ref": pr_result_ref,
    }

    db = tmp_path / "parallel_test.sqlite3"
    ts = TraceStore(db_path=str(db))
    ts.start_run(run_id, agent="test", mode="record")
    for step in steps:
        ts.append_step(run_id, step)
    ts.finish_run(run_id, status="ok")
    return ts, refs


class TestParallelGroup:
    """Tests for parallel tool call support (parallel_group field)."""

    def test_parallel_group_index_built(self, tmp_path):
        """Replayer must build _parallel_group_index keyed by tool name."""
        ts, _ = _make_parallel_store(tmp_path)
        replayer = Replayer(ts, "parallel-run")

        assert PG_ID in replayer._parallel_group_index
        group = replayer._parallel_group_index[PG_ID]
        assert "get_ticket"   in group
        assert "get_user"     in group
        assert "get_priority" in group

    def test_parallel_siblings_served_in_any_order_via_hash(self, tmp_path):
        """Hash matching must return the correct recorded result regardless of
        which parallel sibling arrives first."""
        ts, refs = _make_parallel_store(tmp_path)
        replayer = Replayer(ts, "parallel-run")

        # Serve in reverse order: get_priority first, then get_user, then get_ticket
        resp_pr = replayer.get_response_for_hash(refs["pr_args_ref"])
        resp_us = replayer.get_response_for_hash(refs["us_args_ref"])
        resp_tk = replayer.get_response_for_hash(refs["tk_args_ref"])

        assert resp_pr["synthesized"] is False
        assert resp_us["synthesized"] is False
        assert resp_tk["synthesized"] is False
        # Served_count should reflect 3 tape steps consumed.
        assert replayer._served_count == 3

    def test_sibling_fallback_on_hash_miss(self, tmp_path):
        """When the hash drifts but tool_hint matches a sibling, serve from
        tape instead of synthesizing."""
        ts, refs = _make_parallel_store(tmp_path)
        replayer = Replayer(ts, "parallel-run", synthesize_on_miss=True)

        unknown_hash = "sha256:" + "ab" * 32
        # Provide the correct tool name as a hint
        resp = replayer.get_response_for_hash(unknown_hash, tool_hint="get_ticket")

        assert resp["synthesized"] is False, (
            "sibling fallback must serve from tape, not synthesizer"
        )
        assert replayer.synthesized_count == 0

    def test_no_sibling_fallback_without_tool_hint(self, tmp_path):
        """Without tool_hint, a hash miss must NOT try sibling fallback."""
        ts, _ = _make_parallel_store(tmp_path)
        replayer = Replayer(ts, "parallel-run", synthesize_on_miss=True)

        unknown_hash = "sha256:" + "cd" * 32
        with patch("ai_agents.mock_synthesizer.synthesize") as mock_synth:
            mock_synth.return_value = MagicMock(
                value={}, confidence=0.5, rationale="synth"
            )
            resp = replayer.get_response_for_hash(unknown_hash)

        assert resp["synthesized"] is True
        assert replayer.synthesized_count == 1

    def test_finish_ok_after_full_hash_replay(self, tmp_path):
        """After serving all steps via get_response_for_hash, finish() must
        report status='ok', not 'incomplete'."""
        ts, refs = _make_parallel_store(tmp_path)
        replayer = Replayer(ts, "parallel-run")

        # Serve the LLM call + all 3 parallel tool calls via hash matching
        replayer.get_response_for_hash(refs["llm_args_ref"])
        replayer.get_response_for_hash(refs["tk_args_ref"])
        replayer.get_response_for_hash(refs["us_args_ref"])
        replayer.get_response_for_hash(refs["pr_args_ref"])

        result = replayer.finish()
        assert result.status == "ok", (
            f"expected 'ok', got {result.status!r}. "
            "finish() must use _served_count, not _cursor."
        )
        assert result.steps_replayed == 4

    def test_sequential_cursor_serves_sibling_from_tape_in_fork(self, tmp_path):
        """In record-over mode, get_next_response must serve a parallel sibling
        (step_id > fork_step_id but same parallel_group) from tape, not
        delegate it to the synthesizer."""
        ts, refs = _make_parallel_store(tmp_path)

        # Build a fork that edits step 2 (get_ticket).  Steps 3 and 4 are
        # siblings and must be served from tape even though their step_ids > 2.
        from replay_engine.divergence import Divergence
        div = Divergence(ts)
        fork_id = div.fork(
            run_id="parallel-run",
            fork_step_id=2,
            edit={"_result_content": '{"title": "EDITED"}'},
            new_run_id="parallel-fork-001",
        )

        fork_replayer = Replayer(ts, fork_id, synthesize_on_miss=True)

        # Advance past the pre-fork LLM step (step 1)
        resp_llm = fork_replayer.get_next_response("llm_call")
        assert resp_llm["synthesized"] is False

        # Step 2 (the edited fork step) — served from tape with the edit applied
        resp_tk = fork_replayer.get_next_response("tool_call")
        assert resp_tk["synthesized"] is False

        # Step 3 (get_user) — sibling, must NOT be synthesized
        resp_us = fork_replayer.get_next_response("tool_call")
        assert resp_us["synthesized"] is False, (
            "parallel sibling get_user must be served from tape in record-over fork"
        )

        # Step 4 (get_priority) — sibling, must NOT be synthesized
        resp_pr = fork_replayer.get_next_response("tool_call")
        assert resp_pr["synthesized"] is False, (
            "parallel sibling get_priority must be served from tape in record-over fork"
        )

    def test_fork_copies_siblings_not_fan_in(self, tmp_path):
        """Divergence.fork() at a parallel step must copy its siblings into the
        forked run but NOT any step outside the parallel group."""
        ts, refs = _make_parallel_store(tmp_path)

        # Add a fan-in LLM step (step 5) after the parallel group
        fan_in_args  = store_blob('{"prompt": "summarise results"}')
        fan_in_resp  = store_blob('{"content": "ticket assigned"}')
        ts.append_step("parallel-run", {
            "step_id": 5, "type": "llm_call", "timestamp_ms": 1500,
            "prompt_blob": fan_in_args, "response_blob": fan_in_resp,
            "side_effecting": False, "causal_parents": [2, 3, 4],
        })

        from replay_engine.divergence import Divergence
        div = Divergence(ts)
        fork_id = div.fork(
            run_id="parallel-run",
            fork_step_id=3,   # fork at get_user
            edit={"_result_content": '{"name": "Bob"}'},
            new_run_id="parallel-fork-002",
        )

        fork_doc = ts.get_run(fork_id)
        fork_step_ids = {s["step_id"] for s in fork_doc["steps"]}

        # step 1 (pre-fork), step 3 (edited fork step), step 2 and 4 (siblings)
        assert 1 in fork_step_ids, "pre-fork LLM step must be copied"
        assert 3 in fork_step_ids, "fork step itself must be present (edited)"
        assert 2 in fork_step_ids, "get_ticket sibling must be copied"
        assert 4 in fork_step_ids, "get_priority sibling must be copied"
        # Fan-in step must NOT be in the fork
        assert 5 not in fork_step_ids, (
            "fan-in LLM step (step 5) must NOT be copied into the fork"
        )

    def test_compare_reports_siblings(self, tmp_path):
        """compare() must return non-empty parallel_siblings_in_fork when the
        fork step belongs to a parallel group."""
        ts, refs = _make_parallel_store(tmp_path)

        from replay_engine.divergence import Divergence
        div = Divergence(ts)
        fork_id = div.fork(
            run_id="parallel-run",
            fork_step_id=2,
            edit={"_result_content": '{"title": "EDITED"}'},
            new_run_id="parallel-fork-003",
        )

        diff = div.compare("parallel-run", fork_id)
        assert "parallel_siblings_in_fork" in diff
        # Siblings of step 2 (get_ticket) are steps 3 and 4
        assert set(diff["parallel_siblings_in_fork"]) == {3, 4}
