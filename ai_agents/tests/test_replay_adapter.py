"""Tests for StoreReplayEngine (ai_agents/replay_adapter.py).

Offline only -- no LLM, no network.

Run from the repo root:
    python -m pytest ai_agents/tests/test_replay_adapter.py -q
"""
from __future__ import annotations

import json
import pathlib

import pytest

from ai_agents.replay_interface import Injection, ReplayEngine

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "sample_trace.json"
)
BLOBS_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "blobs"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_store(store, trace: dict) -> None:
    """Populate *store* with the full trace document."""
    store.start_run(
        trace["run_id"],
        agent=trace.get("agent", ""),
        mode=trace.get("mode", "record"),
        created_at_ms=trace.get("created_at_ms"),
    )
    for step in trace["steps"]:
        store.append_step(trace["run_id"], step)
    store.finish_run(
        trace["run_id"],
        status=trace.get("status", "ok"),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def trace() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def store(tmp_path, monkeypatch, trace):
    """A fresh TraceStore seeded with the sample fixture."""
    monkeypatch.setenv("CASSETTE_BLOB_DIR", BLOBS_DIR)

    from trace_store.store import TraceStore

    db_path = tmp_path / "cassette_test.sqlite3"
    ts = TraceStore(db_path=str(db_path))
    _seed_store(ts, trace)
    yield ts
    ts.close()


@pytest.fixture()
def engine(store):
    from ai_agents.replay_adapter import StoreReplayEngine
    return StoreReplayEngine(store)


# ---------------------------------------------------------------------------
# Test 1: replay() returns correct final_status and failed_step_id
# ---------------------------------------------------------------------------

class TestBaselineReplay:

    def test_final_status_is_error(self, engine, trace):
        outcome = engine.replay(trace["run_id"])
        assert outcome.final_status == "error"

    def test_failed_step_id_is_4(self, engine, trace):
        outcome = engine.replay(trace["run_id"])
        assert outcome.failed_step_id == 4

    def test_run_id_preserved(self, engine, trace):
        outcome = engine.replay(trace["run_id"])
        assert outcome.run_id == trace["run_id"]

    def test_key_outputs_contains_step4(self, engine, trace):
        outcome = engine.replay(trace["run_id"])
        assert "step4" in outcome.key_outputs

    def test_key_outputs_has_entry_per_step(self, engine, trace):
        outcome = engine.replay(trace["run_id"])
        # Fixture has 4 steps -> key_outputs must have 4 keys
        assert len(outcome.key_outputs) == len(trace["steps"])


# ---------------------------------------------------------------------------
# Test 2: side_effect_count must stay 0 (the safety invariant)
# ---------------------------------------------------------------------------

class TestSideEffectInvariant:

    def test_side_effect_count_is_zero(self, engine, trace):
        outcome = engine.replay(trace["run_id"])
        assert outcome.side_effect_count == 0

    def test_side_effecting_steps_did_not_increment_counter(self, engine, trace):
        """Steps 3 and 4 are side_effecting=True; counter must still be 0."""
        outcome = engine.replay(trace["run_id"])
        # Explicit assertion that mirrors the brief requirement
        assert outcome.side_effect_count == 0, (
            "side_effect_count must be 0: side-effecting calls are always mocked on replay"
        )


# ---------------------------------------------------------------------------
# Test 3: replay_with_injection raises DivergenceNotReady
# ---------------------------------------------------------------------------

class TestInjectionPath:

    def test_raises_divergence_not_ready(self, engine, trace):
        from ai_agents.replay_adapter import DivergenceNotReady

        injection = Injection(step_id=2, target="result", value='{"priority": "high"}')
        with pytest.raises(DivergenceNotReady):
            engine.replay_with_injection(trace["run_id"], injection)

    def test_divergence_not_ready_is_not_implemented_error(self, engine, trace):
        from ai_agents.replay_adapter import DivergenceNotReady

        assert issubclass(DivergenceNotReady, NotImplementedError)

    def test_divergence_not_ready_message_is_helpful(self, engine, trace):
        from ai_agents.replay_adapter import DivergenceNotReady

        injection = Injection(step_id=2, target="result", value='{"priority": "high"}')
        with pytest.raises(DivergenceNotReady, match="fork"):
            engine.replay_with_injection(trace["run_id"], injection)


# ---------------------------------------------------------------------------
# Test 4: protocol compliance
# ---------------------------------------------------------------------------

class TestProtocolCompliance:

    def test_is_replay_engine_protocol(self, store):
        from ai_agents.replay_adapter import StoreReplayEngine

        engine = StoreReplayEngine(store)
        assert isinstance(engine, ReplayEngine)
