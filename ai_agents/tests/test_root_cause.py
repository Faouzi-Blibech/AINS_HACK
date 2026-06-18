"""Tests for the Temporal Blame Graph's deterministic logic.

These cover the parts that need no LLM: the causal-ancestor walk, the
perturbation loop wiring (via ScriptedReplay), root-cause selection, and the
verdict. The LLM-phrased verdict and the semantic-matcher comparator are tested
separately once they come online.

Run from the repo root:
    pytest ai_agents/tests/test_root_cause.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from ai_agents.root_cause import (
    ScriptedReplay,
    analyze,
    causal_ancestors,
    infer_failed_step,
)

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "sample_trace.json"
)


@pytest.fixture()
def trace() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class TestCausalGraph:
    def test_infer_failed_step_is_last_error(self, trace):
        # Fixture: step 4 (send_email) has status "error".
        assert infer_failed_step(trace) == 4

    def test_ancestors_walk_causal_parents(self, trace):
        # 4 <- 3 <- {1,2}; 2 <- 1; 1 <- (root)
        assert causal_ancestors(trace, 4) == [1, 2, 3]

    def test_ancestors_of_first_step_is_empty(self, trace):
        assert causal_ancestors(trace, 1) == []


class TestBlameGraph:
    def test_identifies_seeded_root_cause(self, trace):
        # Demo oracle: correcting step 2 (ambiguous priority) resolves it.
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        assert graph.failed_step_id == 4
        assert graph.root_cause_step_id == 2
        assert "Step 4" in graph.verdict and "Step 2" in graph.verdict

    def test_blame_scores_only_root_is_high(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        by_id = {s.step_id: s.blame_score for s in graph.steps}
        assert by_id[2] == 1.0
        assert by_id[1] == 0.0 and by_id[3] == 0.0

    def test_high_confidence_when_single_resolver(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        assert graph.confidence == pytest.approx(0.9)

    def test_root_cause_is_upstream_most_resolver(self, trace):
        # If both 1 and 2 resolve it, the upstream-most (1) is the root cause.
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={1, 2}))
        assert graph.root_cause_step_id == 1
        assert graph.confidence == pytest.approx(0.6)  # ambiguous: several resolve

    def test_no_resolver_yields_low_confidence(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at=set()))
        assert graph.root_cause_step_id is None
        assert graph.confidence < 0.6

    def test_only_ancestors_are_scored(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        # Step 4 is the failure itself, not one of its ancestors.
        assert {s.step_id for s in graph.steps} == {1, 2, 3}

    def test_api_dict_shape(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        d = graph.to_api_dict()
        assert set(d) == {
            "run_id",
            "failed_step_id",
            "root_cause_step_id",
            "verdict",
            "confidence",
            "steps",
        }
        assert all({"step_id", "blame_score", "rationale"} == set(s) for s in d["steps"])


class TestSafetyInvariant:
    def test_replay_reports_zero_side_effects(self, trace):
        replay = ScriptedReplay(trace, resolves_at={2})
        assert replay.replay(trace["run_id"]).side_effect_count == 0
