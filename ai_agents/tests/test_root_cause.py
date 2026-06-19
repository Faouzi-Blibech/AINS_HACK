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


# ---------------------------------------------------------------------------
# Minimal synthetic trace for multi-resolver tests.
# ---------------------------------------------------------------------------

SYNTHETIC_TRACE_TWO_RESOLVERS = {
    "run_id": "run-synthetic-two",
    "steps": [
        {"step_id": 1, "type": "tool_call", "causal_parents": [], "status": "ok"},
        {"step_id": 2, "type": "tool_call", "causal_parents": [1], "status": "ok"},
        {"step_id": 3, "type": "tool_call", "causal_parents": [2], "status": "error"},
    ],
}


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
        # OLD binary test -- replaced by graded test below; keep for regression.
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        by_id = {s.step_id: s.blame_score for s in graph.steps}
        assert by_id[2] == 1.0

    def test_high_confidence_when_single_resolver(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        assert graph.confidence == pytest.approx(0.9)

    def test_root_cause_is_upstream_most_resolver(self, trace):
        # If both 1 and 2 resolve it, the upstream-most (1) is the root cause.
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={1, 2}))
        assert graph.root_cause_step_id == 1
        assert graph.confidence == pytest.approx(0.5)  # ambiguous: several resolve

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


# ---------------------------------------------------------------------------
# New tests: graded blame scoring + confidence wiring (Task 3)
# ---------------------------------------------------------------------------


class TestGradedBlameSampeFixture:
    """Graded blame scores for the sample fixture with resolves_at={2}.

    Topology (causal_parents):
      1 -> (no parents)
      2 -> [1]
      3 -> [1, 2]
      4 -> [3]  (failed step)

    Transitive descendants:
      desc(1) = {2, 3, 4}  -> injecting at 1 changes 4 keys (1+3) / 4 total = 1.0
      desc(2) = {3, 4}     -> resolves_at={2} -> blame_score = 1.0
      desc(3) = {4}        -> injecting at 3 changes 2 keys (3+4) / 4 total = 0.5

    Expected scores (formula: 0.2 + 0.4 * divergence):
      step 1: divergence=1.0 -> 0.2 + 0.4*1.0 = 0.6  (contributor)
      step 2: resolves       -> 1.0                    (root)
      step 3: divergence=0.5 -> 0.2 + 0.4*0.5 = 0.4  (contributor)
    """

    def test_root_step_score_is_1(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        by_id = {s.step_id: s.blame_score for s in graph.steps}
        assert by_id[2] == pytest.approx(1.0)

    def test_contributor_step1_score(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        by_id = {s.step_id: s.blame_score for s in graph.steps}
        # divergence = 4/4 = 1.0 -> 0.2 + 0.4*1.0 = 0.6
        assert by_id[1] == pytest.approx(0.6)

    def test_contributor_step3_score(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        by_id = {s.step_id: s.blame_score for s in graph.steps}
        # divergence = 2/4 = 0.5 -> 0.2 + 0.4*0.5 = 0.4
        assert by_id[3] == pytest.approx(0.4)

    def test_contributor_scores_in_valid_range(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        by_id = {s.step_id: s.blame_score for s in graph.steps}
        # Contributors must be in (0, 0.6] (between innocent and root)
        assert 0 < by_id[1] <= 0.6
        assert 0 < by_id[3] <= 0.6

    def test_contributor_rationale_text(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        by_id = {s.step_id: s for s in graph.steps}
        assert "contributor" in by_id[1].rationale
        assert "contributor" in by_id[3].rationale

    def test_root_rationale_text(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        by_id = {s.step_id: s for s in graph.steps}
        assert "root cause" in by_id[2].rationale


class TestInnocentTier:
    """A step whose perturbation changes no key_outputs gets blame_score == 0.0."""

    def test_innocent_step_score_is_zero(self):
        # Build a trace with two ancestors: step 1 has no downstream effect
        # because ScriptedReplay only populates key_outputs when there are
        # descendants. Force innocent by using a trace where the innocent
        # ancestor's key_outputs are identical in baseline and injection
        # (i.e., divergence == 0.0).
        #
        # We achieve this with a custom subclass that returns empty key_outputs
        # for both baseline and injection -- which triggers the
        # "if either side has no key_outputs, divergence is 0.0" branch.
        trace = {
            "run_id": "run-innocent",
            "steps": [
                {"step_id": 1, "type": "tool_call", "causal_parents": [], "status": "ok"},
                {"step_id": 2, "type": "tool_call", "causal_parents": [1], "status": "ok"},
                {"step_id": 3, "type": "tool_call", "causal_parents": [2], "status": "error"},
            ],
        }

        class EmptyOutputReplay(ScriptedReplay):
            """ScriptedReplay that never populates key_outputs (simulates no change)."""

            def replay(self, run_id):
                outcome = super().replay(run_id)
                # Leave key_outputs empty to trigger divergence=0.0
                return outcome

            def replay_with_injection(self, run_id, injection):
                outcome = super().replay_with_injection(run_id, injection)
                # Wipe key_outputs so divergence is 0.0 for ALL injections
                from ai_agents.replay_interface import ReplayOutcome
                return ReplayOutcome(
                    run_id=outcome.run_id,
                    final_status=outcome.final_status,
                    failed_step_id=outcome.failed_step_id,
                    side_effect_count=0,
                    key_outputs={},  # empty -> divergence == 0.0
                    replay_run_id=outcome.replay_run_id,
                )

        replay = EmptyOutputReplay(trace, resolves_at=set())
        graph = analyze(trace, replay=replay)
        by_id = {s.step_id: s for s in graph.steps}
        # With no key_outputs on either side, divergence=0.0 -> blame_score=0.0
        for sid in (1, 2):
            assert by_id[sid].blame_score == pytest.approx(0.0), (
                f"Step {sid} should be innocent but got {by_id[sid].blame_score}"
            )
            assert "innocent" in by_id[sid].rationale

    def test_innocent_step_via_no_descendants(self):
        # A step with no descendants in the trace should have divergence = 1/N
        # from its own changed output. But if we place the "innocent" step as
        # a sibling ancestor with empty desc, the formula gives divergence = 1/N > 0.
        # True zero divergence comes only from empty key_outputs. Confirm the
        # branch logic: empty key_outputs -> 0.0 score with innocent rationale.
        trace = {
            "run_id": "run-innocent2",
            "steps": [
                {"step_id": 10, "type": "tool_call", "causal_parents": [], "status": "ok"},
                {"step_id": 11, "type": "tool_call", "causal_parents": [10], "status": "error"},
            ],
        }
        # ScriptedReplay WITH key_outputs but resolves_at empty:
        # desc(10) = {11} -> 2 changed out of 2 total = 1.0 divergence -> contributor
        # So for a step to be innocent, key_outputs must be empty.
        replay = ScriptedReplay(trace, resolves_at=set())
        graph = analyze(trace, replay=replay)
        by_id = {s.step_id: s for s in graph.steps}
        # step 10 changes step10 + step11 = 2 keys out of 2 -> divergence=1.0 -> contributor
        assert by_id[10].blame_score == pytest.approx(0.6)
        assert "contributor" in by_id[10].rationale


class TestConfidenceWiring:
    """Confidence module integration tests."""

    def test_single_resolver_confidence_09(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        assert graph.confidence == pytest.approx(0.9)

    def test_two_resolvers_confidence_05(self):
        graph = analyze(
            SYNTHETIC_TRACE_TWO_RESOLVERS,
            replay=ScriptedReplay(SYNTHETIC_TRACE_TWO_RESOLVERS, resolves_at={1, 2}),
        )
        assert graph.confidence == pytest.approx(0.5)

    def test_no_resolver_confidence_03(self):
        graph = analyze(
            SYNTHETIC_TRACE_TWO_RESOLVERS,
            replay=ScriptedReplay(SYNTHETIC_TRACE_TWO_RESOLVERS, resolves_at=set()),
        )
        assert graph.confidence == pytest.approx(0.3)

    def test_as_ai_result_needs_review_false_for_high_confidence(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        ai_result = graph.as_ai_result()
        # confidence=0.9 > REVIEW_THRESHOLD=0.6 -> needs_review=False
        assert ai_result.needs_review is False

    def test_as_ai_result_needs_review_true_for_low_confidence(self):
        graph = analyze(
            SYNTHETIC_TRACE_TWO_RESOLVERS,
            replay=ScriptedReplay(SYNTHETIC_TRACE_TWO_RESOLVERS, resolves_at=set()),
        )
        ai_result = graph.as_ai_result()
        # confidence=0.3 < REVIEW_THRESHOLD=0.6 -> needs_review=True
        assert ai_result.needs_review is True

    def test_as_ai_result_value_is_verdict(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        ai_result = graph.as_ai_result()
        assert ai_result.value == graph.verdict

    def test_as_ai_result_confidence_matches_graph(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        ai_result = graph.as_ai_result()
        assert ai_result.confidence == pytest.approx(graph.confidence)


class TestContentResolver:
    """Wire-in tests: content_resolver extends rationales; None keeps them exact."""

    def test_with_resolver_step2_rationale_starts_with_tier_string(self, trace):
        import pathlib
        from ai_agents.trace_content import make_resolver

        blob_dir = str(
            pathlib.Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "blobs"
        )
        resolver = make_resolver(blob_dir)
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}), content_resolver=resolver)
        by_id = {s.step_id: s for s in graph.steps}
        step2_rationale = by_id[2].rationale
        # Must start with the unchanged tier string
        assert step2_rationale.startswith("root cause: correcting this step's output resolves the failure")
        # And must also contain the resolved content
        assert "medium" in step2_rationale

    def test_without_resolver_step2_rationale_is_exact_tier_string(self, trace):
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        by_id = {s.step_id: s for s in graph.steps}
        # Without a resolver the rationale is exactly the tier string (regression guard)
        assert by_id[2].rationale == "root cause: correcting this step's output resolves the failure"


class TestSideEffectInvariant:
    """side_effect_count must stay 0 for every outcome."""

    def test_baseline_side_effect_count_zero(self, trace):
        replay = ScriptedReplay(trace, resolves_at={2})
        baseline = replay.replay(trace["run_id"])
        assert baseline.side_effect_count == 0

    def test_injection_side_effect_count_zero(self, trace):
        from ai_agents.replay_interface import Injection
        replay = ScriptedReplay(trace, resolves_at={2})
        injection = Injection(step_id=2, target="result", value="<neutralized>")
        outcome = replay.replay_with_injection(trace["run_id"], injection)
        assert outcome.side_effect_count == 0

    def test_all_outcomes_in_analyze_have_zero_side_effects(self, trace):
        # Patch replay to intercept all calls and record side_effect_counts.
        from ai_agents.replay_interface import Injection, ReplayOutcome

        class TrackingReplay(ScriptedReplay):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.recorded_side_effects: list[int] = []

            def replay(self, run_id):
                outcome = super().replay(run_id)
                self.recorded_side_effects.append(outcome.side_effect_count)
                return outcome

            def replay_with_injection(self, run_id, injection):
                outcome = super().replay_with_injection(run_id, injection)
                self.recorded_side_effects.append(outcome.side_effect_count)
                return outcome

        replay = TrackingReplay(trace, resolves_at={2})
        analyze(trace, replay=replay)
        assert all(c == 0 for c in replay.recorded_side_effects)
        assert len(replay.recorded_side_effects) > 1  # baseline + at least one injection


# ---------------------------------------------------------------------------
# Task 5: verdict_via_llm (additive assertions)
# ---------------------------------------------------------------------------


import json as _json

from ai_agents.llm import LLMNotConfigured
from ai_agents.root_cause import verdict_via_llm


def _make_verdict_json(**kwargs) -> str:
    base = dict(
        failed_step_id=4,
        root_cause_step_id=2,
        verdict="Step 4 is where it failed. Step 2 is why.",
        rationale="The priority tool returned ambiguous output.",
        confidence=0.85,
    )
    base.update(kwargs)
    return _json.dumps(base)


class TestVerdictViaLlm:
    """LLM-phrased verdict: happy path, fallback on LLMNotConfigured."""

    def test_happy_path_returns_llm_verdict(self, trace, monkeypatch):
        """verdict_via_llm returns the LLM-phrased verdict wrapped in AIResult."""
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: _make_verdict_json(verdict="LLM says: Step 4 is where it failed. Step 2 is why."),
        )
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        result = verdict_via_llm(graph, trace)

        assert result.value == "LLM says: Step 4 is where it failed. Step 2 is why."
        assert result.confidence == pytest.approx(0.85)
        assert result.rationale == "The priority tool returned ambiguous output."

    def test_happy_path_confidence_matches_json(self, trace, monkeypatch):
        """AIResult.confidence comes from the LLM-reported confidence field."""
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: _make_verdict_json(confidence=0.72),
        )
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        result = verdict_via_llm(graph, trace)

        assert result.confidence == pytest.approx(0.72)

    def test_fallback_on_llm_not_configured(self, trace, monkeypatch):
        """When LLMNotConfigured is raised, verdict_via_llm falls back to graph.as_ai_result()."""
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: (_ for _ in ()).throw(LLMNotConfigured("no key")),
        )
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        result = verdict_via_llm(graph, trace)
        deterministic = graph.as_ai_result()

        assert result.value == deterministic.value
        assert "Step 4" in result.value and "Step 2" in result.value
        assert result.confidence == pytest.approx(deterministic.confidence)

    def test_fallback_verdict_contains_expected_step_ids(self, trace, monkeypatch):
        """The deterministic fallback verdict contains the known step references."""
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: (_ for _ in ()).throw(LLMNotConfigured("no key")),
        )
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        result = verdict_via_llm(graph, trace)

        assert "Step 4" in result.value
        assert "Step 2" in result.value

    def test_with_content_resolver(self, trace, monkeypatch):
        """content_resolver is called to produce step summaries for the LLM prompt."""
        captured_user = []

        def fake_llm(**kw):
            captured_user.append(kw.get("user", ""))
            return _make_verdict_json()

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm)

        resolver_calls = []

        def my_resolver(step):
            resolver_calls.append(step["step_id"])
            return f"step-{step['step_id']}-summary"

        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        verdict_via_llm(graph, trace, content_resolver=my_resolver)

        # Resolver must have been called for each blamed step
        assert len(resolver_calls) > 0
        # Summaries must appear in the user prompt
        for sid in resolver_calls:
            assert f"step-{sid}-summary" in captured_user[0]

    def test_llm_called_with_reasoning_model(self, trace, monkeypatch):
        """verdict_via_llm uses the reasoning model, not the cheap model."""
        captured = {}

        def fake_llm(**kw):
            captured.update(kw)
            return _make_verdict_json()

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm)
        from ai_agents.llm import reasoning_model

        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        verdict_via_llm(graph, trace)

        assert captured.get("model") == reasoning_model()
        # JSON output is requested via the verdict schema (which also makes the
        # adapter inject the JSON instruction Groq's json_object mode requires).
        from ai_agents import prompts

        assert captured.get("json_schema") == prompts.ROOT_CAUSE_VERDICT_SCHEMA

    def test_fallback_on_non_json_reply(self, trace, monkeypatch):
        """verdict_via_llm falls back to graph.as_ai_result() when LLM returns non-JSON."""
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: "oops")
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        result = verdict_via_llm(graph, trace)
        assert result.value == graph.verdict

    def test_fallback_on_json_missing_key(self, trace, monkeypatch):
        """verdict_via_llm falls back when LLM returns JSON missing a required key."""
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: '{"verdict": "x"}',  # missing confidence and rationale
        )
        graph = analyze(trace, replay=ScriptedReplay(trace, resolves_at={2}))
        result = verdict_via_llm(graph, trace)
        assert result.value == graph.verdict
