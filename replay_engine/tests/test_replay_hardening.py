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
