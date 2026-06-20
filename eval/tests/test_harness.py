"""Tests for eval/harness.py.

All tests monkeypatch ai_agents.llm.llm_complete so no live endpoint is hit.
"""
from __future__ import annotations

import json
import pathlib

import pytest

# ------------------------------------------------------------------ #
# Inline scenario fixtures
# ------------------------------------------------------------------ #

# A simple 3-step trace: step 1 (llm), step 2 (tool, causal parent: 1),
# step 3 (tool, causal parent: 2, status=error).
# Root cause is step 1: injecting at step 1 resolves the failure.
TRACE_SIMPLE = {
    "run_id": "run-test-simple",
    "status": "error",
    "steps": [
        {
            "step_id": 1,
            "type": "llm_call",
            "side_effecting": False,
            "causal_parents": [],
            "status": "ok",
            "key_outputs": {"intent": "wrong"},
        },
        {
            "step_id": 2,
            "type": "tool_call",
            "tool": "get_queue",
            "side_effecting": False,
            "causal_parents": [1],
            "status": "ok",
            "key_outputs": {"queue": "wrong_queue"},
        },
        {
            "step_id": 3,
            "type": "tool_call",
            "tool": "assign_ticket",
            "side_effecting": True,
            "causal_parents": [2],
            "status": "error",
            "key_outputs": {},
        },
    ],
}

# Scenario where analyze correctly identifies step 1 as root cause.
SCENARIO_CORRECT = {
    "scenario_id": "sc-correct",
    "trace": TRACE_SIMPLE,
    "resolves_at": [1],
    "expected_root_cause_step": 1,
    "injected_fault": "Step 1 LLM produced wrong intent",
}

# A trace where the injected fault is at step 1 but we record step 2 as
# expected root cause -- so analyze will find step 1 (the actual resolver)
# but we expect step 2 => intentionally WRONG attribution label.
TRACE_WRONG_EXPECTED = {
    "run_id": "run-test-wrong",
    "status": "error",
    "steps": [
        {
            "step_id": 1,
            "type": "llm_call",
            "side_effecting": False,
            "causal_parents": [],
            "status": "ok",
            "key_outputs": {"intent": "misclassified"},
        },
        {
            "step_id": 2,
            "type": "tool_call",
            "tool": "lookup_dept",
            "side_effecting": False,
            "causal_parents": [1],
            "status": "ok",
            "key_outputs": {"dept": "wrong"},
        },
        {
            "step_id": 3,
            "type": "tool_call",
            "tool": "create_case",
            "side_effecting": True,
            "causal_parents": [1, 2],
            "status": "error",
            "key_outputs": {},
        },
    ],
}

# resolves_at=[1] means analyze will pick step 1 as root cause,
# but expected_root_cause_step=2 means the scoring marks it WRONG.
SCENARIO_WRONG = {
    "scenario_id": "sc-wrong",
    "trace": TRACE_WRONG_EXPECTED,
    "resolves_at": [1],
    "expected_root_cause_step": 2,
    "injected_fault": "Step 1 misclassification (but we label step 2 as expected to force a miss)",
}


# ------------------------------------------------------------------ #
# Tests: root_cause_accuracy
# ------------------------------------------------------------------ #


class TestRootCauseAccuracy:
    def test_mixed_correct_and_wrong_is_half(self):
        """One correct, one wrong => accuracy = 0.5.

        This proves the metric is not hardcoded to pass.
        """
        from eval.harness import root_cause_accuracy

        result = root_cause_accuracy([SCENARIO_CORRECT, SCENARIO_WRONG])
        assert result == pytest.approx(0.5)

    def test_all_correct(self):
        from eval.harness import root_cause_accuracy

        result = root_cause_accuracy([SCENARIO_CORRECT, SCENARIO_CORRECT])
        assert result == pytest.approx(1.0)

    def test_all_wrong(self):
        from eval.harness import root_cause_accuracy

        result = root_cause_accuracy([SCENARIO_WRONG, SCENARIO_WRONG])
        assert result == pytest.approx(0.0)

    def test_empty_scenarios(self):
        from eval.harness import root_cause_accuracy

        assert root_cause_accuracy([]) == pytest.approx(0.0)

    def test_multi_resolver_picks_upstream_most(self):
        """When resolves_at has multiple steps, analyze should pick min(resolvers)."""
        from eval.harness import root_cause_accuracy

        # Steps 1 -> 2 -> 3(error). resolves_at=[1,2] => analyze returns min=1.
        trace_multi = {
            "run_id": "run-multi",
            "status": "error",
            "steps": [
                {
                    "step_id": 1,
                    "type": "llm_call",
                    "side_effecting": False,
                    "causal_parents": [],
                    "status": "ok",
                    "key_outputs": {"v": "a"},
                },
                {
                    "step_id": 2,
                    "type": "tool_call",
                    "tool": "process",
                    "side_effecting": False,
                    "causal_parents": [1],
                    "status": "ok",
                    "key_outputs": {"v": "b"},
                },
                {
                    "step_id": 3,
                    "type": "tool_call",
                    "tool": "finish",
                    "side_effecting": True,
                    "causal_parents": [2],
                    "status": "error",
                    "key_outputs": {},
                },
            ],
        }
        sc = {
            "scenario_id": "sc-multi",
            "trace": trace_multi,
            "resolves_at": [1, 2],
            "expected_root_cause_step": 1,  # upstream-most
            "injected_fault": "both 1 and 2 resolve, expect 1",
        }
        assert root_cause_accuracy([sc]) == pytest.approx(1.0)

    def test_ground_truth_not_passed_to_analyze(self):
        """Verify expected_root_cause_step is not used inside the metric function.

        The metric computes its answer purely from analyze() output.
        We force a discrepancy: expected=2 but oracle resolves at 1.
        The metric must return 0.0 (the label is wrong, not the code).
        """
        from eval.harness import root_cause_accuracy

        assert root_cause_accuracy([SCENARIO_WRONG]) == pytest.approx(0.0)


# ------------------------------------------------------------------ #
# Tests: side_effect_containment
# ------------------------------------------------------------------ #


class TestSideEffectContainment:
    def test_always_zero_on_scripted_replay(self):
        from eval.harness import side_effect_containment

        result = side_effect_containment([SCENARIO_CORRECT, SCENARIO_WRONG])
        assert result == 0

    def test_empty_scenarios(self):
        from eval.harness import side_effect_containment

        assert side_effect_containment([]) == 0


# ------------------------------------------------------------------ #
# Tests: determinism_rate
# ------------------------------------------------------------------ #


class TestDeterminismRate:
    def test_scripted_replay_is_fully_deterministic(self):
        """ScriptedReplay reproduces all recorded steps => rate = 1.0."""
        from eval.harness import determinism_rate

        result = determinism_rate([SCENARIO_CORRECT, SCENARIO_WRONG])
        assert result == pytest.approx(1.0)

    def test_empty_scenarios(self):
        from eval.harness import determinism_rate

        assert determinism_rate([]) == pytest.approx(0.0)

    def test_mismatched_sequence_is_not_one(self):
        """A mock replay returning a subset of steps gives rate < 1.0.

        This proves the metric actually measures something (not hardcoded 1.0).
        """
        from eval.harness import _recorded_tool_sequence, _replayed_tool_sequence

        trace = TRACE_SIMPLE
        recorded = _recorded_tool_sequence(trace)
        # Simulate a replay that dropped step 2 (only step1 and step3 in output)
        partial_key_outputs = {"step1": "<baseline>", "step3": "<baseline>"}
        replayed = _replayed_tool_sequence(partial_key_outputs, trace)
        assert recorded != replayed

    def test_matching_sequence_is_equal(self):
        from eval.harness import _recorded_tool_sequence, _replayed_tool_sequence

        trace = TRACE_SIMPLE
        recorded = _recorded_tool_sequence(trace)
        full_key_outputs = {
            "step1": "<baseline>",
            "step2": "<baseline>",
            "step3": "<baseline>",
        }
        replayed = _replayed_tool_sequence(full_key_outputs, trace)
        assert recorded == replayed

    def test_determinism_rate_below_one_when_step_omitted(self, monkeypatch):
        """determinism_rate returns < 1.0 when a replay omits a recorded step.

        We monkeypatch ScriptedReplay.replay to return an outcome whose
        key_outputs omit step 2 from a 3-step trace, causing the replayed
        sequence to differ from the recorded one.
        """
        from eval.harness import determinism_rate
        from ai_agents.root_cause import ScriptedReplay, ReplayOutcome

        def _partial_replay(self, run_id):
            # Return only step1 and step3; step2 is absent => sequence mismatch.
            return ReplayOutcome(
                run_id=run_id,
                final_status="ok",
                key_outputs={"step1": "<out>", "step3": "<out>"},
                side_effect_count=0,
            )

        monkeypatch.setattr(ScriptedReplay, "replay", _partial_replay)

        result = determinism_rate([SCENARIO_CORRECT])
        assert result < 1.0


# ------------------------------------------------------------------ #
# Tests: semantic_match_pr
# ------------------------------------------------------------------ #

# The JSON that llm_complete returns when we want equivalent=True
_LLM_TRUE = json.dumps(
    {"equivalent": True, "score": 0.95, "confidence": 0.9, "rationale": "same meaning"}
)
# The JSON that llm_complete returns when we want equivalent=False
_LLM_FALSE = json.dumps(
    {"equivalent": False, "score": 0.1, "confidence": 0.9, "rationale": "different"}
)


def _make_pairs():
    """6 pairs: 3 true positives (gold=T, predicted=T), 1 false positive (gold=F, predicted=T),
    1 false negative (gold=T, predicted=F), 1 true negative (gold=F, predicted=F).

    TP=3, FP=1, FN=1
    Precision = 3/(3+1) = 0.75
    Recall    = 3/(3+1) = 0.75
    """
    return [
        {"expected": "a", "actual": "a2", "gold_equivalent": True},   # TP
        {"expected": "b", "actual": "b2", "gold_equivalent": True},   # TP
        {"expected": "c", "actual": "c2", "gold_equivalent": True},   # TP
        {"expected": "d", "actual": "d2", "gold_equivalent": False},  # FP (predicted T)
        {"expected": "e", "actual": "e2", "gold_equivalent": True},   # FN (predicted F)
        {"expected": "f", "actual": "f2", "gold_equivalent": False},  # TN (predicted F)
    ]


def _make_llm_complete_mock(pairs_results: list[bool]):
    """Return a mock for llm_complete that yields True/False in sequence."""
    calls = iter(pairs_results)

    def _mock(**kwargs):
        val = next(calls)
        return _LLM_TRUE if val else _LLM_FALSE

    return _mock


class TestSemanticMatchPR:
    def test_precision_and_recall(self, monkeypatch):
        """With known LLM responses, P and R are computed correctly."""
        import ai_agents.llm as llm_mod
        from eval.harness import semantic_match_pr

        # Sequence: T, T, T, T(gold=F => FP), F(gold=T => FN), F(gold=F => TN)
        mock = _make_llm_complete_mock([True, True, True, True, False, False])
        monkeypatch.setattr(llm_mod, "llm_complete", mock)

        pairs = _make_pairs()
        precision, recall = semantic_match_pr(pairs)
        assert precision == pytest.approx(0.75)
        assert recall == pytest.approx(0.75)

    def test_llm_not_configured_returns_none_none(self, monkeypatch):
        """When LLMNotConfigured is raised, returns (None, None) without crashing."""
        import ai_agents.llm as llm_mod
        from eval.harness import semantic_match_pr

        def _raise(**kwargs):
            raise llm_mod.LLMNotConfigured("no key")

        monkeypatch.setattr(llm_mod, "llm_complete", _raise)

        pairs = [{"expected": "x", "actual": "y", "gold_equivalent": True}]
        result = semantic_match_pr(pairs)
        assert result == (None, None)

    def test_all_correct_predictions(self, monkeypatch):
        """When all predictions match gold, P=1.0 and R=1.0."""
        import ai_agents.llm as llm_mod
        from eval.harness import semantic_match_pr

        pairs = [
            {"expected": "a", "actual": "a2", "gold_equivalent": True},
            {"expected": "b", "actual": "b2", "gold_equivalent": True},
            {"expected": "c", "actual": "c2", "gold_equivalent": False},
        ]
        # Predict: T, T, F => TP=2, FP=0, FN=0 => P=1.0, R=1.0
        mock = _make_llm_complete_mock([True, True, False])
        monkeypatch.setattr(llm_mod, "llm_complete", mock)

        precision, recall = semantic_match_pr(pairs)
        assert precision == pytest.approx(1.0)
        assert recall == pytest.approx(1.0)

    def test_empty_pairs(self, monkeypatch):
        """Empty pair list returns (None, None) due to zero denominator."""
        import ai_agents.llm as llm_mod
        from eval.harness import semantic_match_pr

        monkeypatch.setattr(llm_mod, "llm_complete", lambda **kw: _LLM_TRUE)
        result = semantic_match_pr([])
        assert result == (None, None)


# ------------------------------------------------------------------ #
# Tests: results.json shape
# ------------------------------------------------------------------ #


class TestResultsJsonShape:
    def test_main_writes_results_json(self, monkeypatch, tmp_path):
        """main() writes a results.json with the documented keys."""
        import ai_agents.llm as llm_mod
        from eval.harness import main

        # Monkeypatch LLM to return a deterministic match response
        monkeypatch.setattr(llm_mod, "llm_complete", lambda **kw: _LLM_TRUE)

        out_file = tmp_path / "results.json"
        test_set_dir = pathlib.Path(__file__).parent.parent / "test_set"

        main(test_set_dir=test_set_dir, out_path=out_file)

        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))

        assert "generated_at" in data
        assert "metrics" in data
        assert "caveats" in data
        assert data.get("available") is True
        assert isinstance(data["metrics"], list)
        assert len(data["metrics"]) > 0

        required_metric_keys = {"key", "label", "value", "target_text", "passed", "unit"}
        for m in data["metrics"]:
            assert required_metric_keys.issubset(set(m.keys())), (
                f"Metric missing keys: {required_metric_keys - set(m.keys())}"
            )

        metric_keys = {m["key"] for m in data["metrics"]}
        assert "determinism_rate" in metric_keys
        assert "side_effect_containment" in metric_keys
        assert "root_cause_accuracy" in metric_keys
        assert "semantic_match_precision" in metric_keys
        assert "semantic_match_recall" in metric_keys

    def test_main_with_no_llm_key_still_writes_results(self, monkeypatch, tmp_path):
        """When LLM is not configured, main() still writes results with null P/R."""
        import ai_agents.llm as llm_mod
        from eval.harness import main

        def _raise(**kwargs):
            raise llm_mod.LLMNotConfigured("no key")

        monkeypatch.setattr(llm_mod, "llm_complete", _raise)

        out_file = tmp_path / "results.json"
        test_set_dir = pathlib.Path(__file__).parent.parent / "test_set"

        main(test_set_dir=test_set_dir, out_path=out_file)

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data.get("available") is True

        pr_metrics = [
            m for m in data["metrics"]
            if m["key"] in ("semantic_match_precision", "semantic_match_recall")
        ]
        for m in pr_metrics:
            assert m["value"] is None
            assert m["passed"] is None
