"""Tests for the counterfactual repair agent.

TDD: tests are written first, then the implementation is filled in.

Run from the repo root:
    pytest ai_agents/tests/test_counterfactual.py -v
"""
from __future__ import annotations

import json

import pytest

from ai_agents.confidence import AIResult
from ai_agents.replay_interface import Injection, ReplayOutcome, default_failure_resolved
from ai_agents.llm import LLMNotConfigured


# ---------------------------------------------------------------------------
# Fake ReplayEngine: exactly one injected variant resolves the failure.
# ---------------------------------------------------------------------------

RESOLVING_PROMPT = "variant-that-fixes-it"
RUN_ID = "run-cf-test"
STEP_ID = 2

FAKE_VARIANTS = [
    "variant-one",
    RESOLVING_PROMPT,
    "variant-three",
]


class FakeReplayEngine:
    """Deterministic stand-in: baseline fails; injecting RESOLVING_PROMPT succeeds."""

    def __init__(self):
        self.replay_calls: list[str] = []
        self.injection_calls: list[Injection] = []

    def replay(self, run_id: str) -> ReplayOutcome:
        self.replay_calls.append(run_id)
        return ReplayOutcome(
            run_id=run_id,
            final_status="error",
            failed_step_id=STEP_ID,
            side_effect_count=0,
            key_outputs={"team": "unknown"},
        )

    def replay_with_injection(self, run_id: str, injection: Injection) -> ReplayOutcome:
        self.injection_calls.append(injection)
        resolved = injection.value == RESOLVING_PROMPT
        return ReplayOutcome(
            run_id=run_id,
            final_status="ok" if resolved else "error",
            failed_step_id=None if resolved else STEP_ID,
            side_effect_count=0,
            key_outputs={"team": "backend" if resolved else "unknown"},
            replay_run_id=f"{run_id}-fork@{injection.step_id}",
        )


@pytest.fixture()
def fake_engine():
    return FakeReplayEngine()


# ---------------------------------------------------------------------------
# Happy path: fake generate seam, one variant resolves
# ---------------------------------------------------------------------------


class TestRepairRanking:
    """Core ranking logic via the injectable generate seam (no LLM needed)."""

    def _run(self, fake_engine):
        from ai_agents.counterfactual import repair

        # Pass default_failure_resolved explicitly so no live LLM call is made
        # for the comparator (the generate seam already avoids the LLM for variants).
        return repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            generate=lambda task, original_prompt, n: FAKE_VARIANTS,
            comparator=default_failure_resolved,
        )

    def test_returns_ai_result(self, fake_engine):
        result = self._run(fake_engine)
        assert isinstance(result, AIResult)

    def test_value_is_list_of_variants(self, fake_engine):
        from ai_agents.counterfactual import Variant

        result = self._run(fake_engine)
        assert isinstance(result.value, list)
        assert all(isinstance(v, Variant) for v in result.value)

    def test_resolving_variant_ranks_first(self, fake_engine):
        result = self._run(fake_engine)
        assert result.value[0].resolved is True
        assert result.value[0].prompt == RESOLVING_PROMPT

    def test_non_resolving_variants_have_resolved_false(self, fake_engine):
        result = self._run(fake_engine)
        for v in result.value[1:]:
            assert v.resolved is False

    def test_resolved_flags_correct_count(self, fake_engine):
        result = self._run(fake_engine)
        resolved_count = sum(1 for v in result.value if v.resolved)
        assert resolved_count == 1

    def test_all_variants_present(self, fake_engine):
        result = self._run(fake_engine)
        prompts_in_result = {v.prompt for v in result.value}
        assert prompts_in_result == set(FAKE_VARIANTS)

    def test_confidence_in_unit_interval(self, fake_engine):
        result = self._run(fake_engine)
        assert 0.0 <= result.confidence <= 1.0

    def test_rationale_is_string(self, fake_engine):
        result = self._run(fake_engine)
        assert isinstance(result.rationale, str)
        assert len(result.rationale) > 0

    def test_rationale_mentions_winning_variant(self, fake_engine):
        result = self._run(fake_engine)
        # The rationale should describe a successful resolution
        assert result.value[0].prompt in result.rationale or "variant" in result.rationale.lower()

    def test_winner_has_higher_score_than_losers(self, fake_engine):
        result = self._run(fake_engine)
        winner_score = result.value[0].score
        for v in result.value[1:]:
            assert winner_score > v.score

    def test_variant_ids_are_unique(self, fake_engine):
        result = self._run(fake_engine)
        ids = [v.variant_id for v in result.value]
        assert len(ids) == len(set(ids))

    def test_steps_changed_is_int(self, fake_engine):
        result = self._run(fake_engine)
        for v in result.value:
            assert isinstance(v.steps_changed, int)
            assert v.steps_changed >= 0

    def test_cost_delta_is_float(self, fake_engine):
        result = self._run(fake_engine)
        for v in result.value:
            assert isinstance(v.cost_delta, float)

    def test_outcome_attached_to_each_variant(self, fake_engine):
        result = self._run(fake_engine)
        for v in result.value:
            assert isinstance(v.outcome, ReplayOutcome)


class TestSideEffectInvariant:
    """side_effect_count must be 0 on every ReplayOutcome in the repair result."""

    def test_all_outcomes_have_zero_side_effects(self, fake_engine):
        from ai_agents.counterfactual import repair

        result = repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            generate=lambda task, original_prompt, n: FAKE_VARIANTS,
            comparator=default_failure_resolved,
        )
        for v in result.value:
            assert v.outcome.side_effect_count == 0, (
                f"Variant {v.variant_id} has side_effect_count={v.outcome.side_effect_count}"
            )

    def test_baseline_from_engine_has_zero_side_effects(self, fake_engine):
        baseline = fake_engine.replay(RUN_ID)
        assert baseline.side_effect_count == 0


# ---------------------------------------------------------------------------
# Injection contract: engine is called with correct Injection objects
# ---------------------------------------------------------------------------


class TestInjectionContract:
    def test_engine_called_with_injection_for_each_variant(self, fake_engine):
        from ai_agents.counterfactual import repair

        repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            generate=lambda task, original_prompt, n: FAKE_VARIANTS,
            comparator=default_failure_resolved,
        )
        assert len(fake_engine.injection_calls) == len(FAKE_VARIANTS)

    def test_injection_step_id_matches(self, fake_engine):
        from ai_agents.counterfactual import repair

        repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            generate=lambda task, original_prompt, n: FAKE_VARIANTS,
            comparator=default_failure_resolved,
        )
        for inj in fake_engine.injection_calls:
            assert inj.step_id == STEP_ID

    def test_injection_values_match_variants(self, fake_engine):
        from ai_agents.counterfactual import repair

        repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            generate=lambda task, original_prompt, n: FAKE_VARIANTS,
            comparator=default_failure_resolved,
        )
        injected_values = {inj.value for inj in fake_engine.injection_calls}
        assert injected_values == set(FAKE_VARIANTS)

    def test_default_target_is_prompt(self, fake_engine):
        from ai_agents.counterfactual import repair

        repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            generate=lambda task, original_prompt, n: FAKE_VARIANTS,
            comparator=default_failure_resolved,
        )
        for inj in fake_engine.injection_calls:
            assert inj.target == "prompt"


# ---------------------------------------------------------------------------
# n parameter: generate is called with n
# ---------------------------------------------------------------------------


class TestNParameter:
    def test_generate_receives_n(self, fake_engine):
        from ai_agents.counterfactual import repair

        captured = {}

        def capture_generate(task, original_prompt, n):
            captured["n"] = n
            return ["v1", "v2", "v3"]

        repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            n=3,
            generate=capture_generate,
            comparator=default_failure_resolved,
        )
        assert captured["n"] == 3

    def test_custom_n_produces_that_many_variants(self, fake_engine):
        from ai_agents.counterfactual import repair

        result = repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            n=2,
            generate=lambda task, original_prompt, n: ["a", "b"][:n],
            comparator=default_failure_resolved,
        )
        assert len(result.value) == 2


# ---------------------------------------------------------------------------
# LLM path: monkeypatched llm_complete returns JSON variants array
# ---------------------------------------------------------------------------


def _make_variants_json(variants: list[str], confidence: float = 0.8, rationale: str = "test") -> str:
    return json.dumps({
        "variants": variants,
        "confidence": confidence,
        "rationale": rationale,
    })


class TestLLMPath:
    """Default generate path: LLM returns JSON with a variants array."""

    def test_default_generate_parses_llm_variants(self, fake_engine, monkeypatch):
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: _make_variants_json(["llm-v1", RESOLVING_PROMPT, "llm-v3"]),
        )
        from ai_agents.counterfactual import repair

        # Pass comparator explicitly so only the generate path calls llm_complete.
        result = repair(
            RUN_ID, STEP_ID, engine=fake_engine, n=3, comparator=default_failure_resolved
        )
        prompts_in_result = {v.prompt for v in result.value}
        assert "llm-v1" in prompts_in_result
        assert RESOLVING_PROMPT in prompts_in_result
        assert "llm-v3" in prompts_in_result

    def test_llm_called_with_reasoning_model(self, fake_engine, monkeypatch):
        from ai_agents import llm

        captured = {}

        def fake_llm(**kw):
            captured.update(kw)
            return _make_variants_json(["v1", "v2", "v3"])

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm)
        from ai_agents.counterfactual import repair

        # Use default_failure_resolved so only the generate path hits the fake LLM.
        repair(RUN_ID, STEP_ID, engine=fake_engine, n=3, comparator=default_failure_resolved)
        assert captured.get("model") == llm.reasoning_model()

    def test_llm_called_with_counterfactual_schema(self, fake_engine, monkeypatch):
        from ai_agents import prompts

        captured = {}

        def fake_llm(**kw):
            captured.update(kw)
            return _make_variants_json(["v1", "v2", "v3"])

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm)
        from ai_agents.counterfactual import repair

        repair(RUN_ID, STEP_ID, engine=fake_engine, n=3, comparator=default_failure_resolved)
        assert captured.get("json_schema") == prompts.COUNTERFACTUAL_VARIANTS_SCHEMA

    def test_resolving_variant_still_ranks_first_via_llm(self, fake_engine, monkeypatch):
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: _make_variants_json([RESOLVING_PROMPT, "bad1", "bad2"]),
        )
        from ai_agents.counterfactual import repair

        result = repair(
            RUN_ID, STEP_ID, engine=fake_engine, n=3, comparator=default_failure_resolved
        )
        assert result.value[0].resolved is True


# ---------------------------------------------------------------------------
# Offline fallback: LLMNotConfigured -> deterministic template variants
# ---------------------------------------------------------------------------


class TestOfflineFallback:
    def test_llm_not_configured_produces_variants(self, fake_engine, monkeypatch):
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: (_ for _ in ()).throw(LLMNotConfigured("no key")),
        )
        from ai_agents.counterfactual import repair

        # comparator=default_failure_resolved avoids a second LLM call in the comparator.
        result = repair(RUN_ID, STEP_ID, engine=fake_engine, n=3, comparator=default_failure_resolved)
        # Must still return a valid AIResult with some variants
        assert isinstance(result, AIResult)
        assert isinstance(result.value, list)
        assert len(result.value) > 0

    def test_fallback_produces_n_variants(self, fake_engine, monkeypatch):
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: (_ for _ in ()).throw(LLMNotConfigured("no key")),
        )
        from ai_agents.counterfactual import repair

        result = repair(RUN_ID, STEP_ID, engine=fake_engine, n=4, comparator=default_failure_resolved)
        assert len(result.value) == 4

    def test_fallback_variants_are_strings(self, fake_engine, monkeypatch):
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: (_ for _ in ()).throw(LLMNotConfigured("no key")),
        )
        from ai_agents.counterfactual import repair

        result = repair(RUN_ID, STEP_ID, engine=fake_engine, n=3, comparator=default_failure_resolved)
        for v in result.value:
            assert isinstance(v.prompt, str)
            assert len(v.prompt) > 0

    def test_json_parse_error_falls_back_to_deterministic(self, fake_engine, monkeypatch):
        """json.JSONDecodeError during parse also triggers the fallback."""
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: "not valid json at all !!",
        )
        from ai_agents.counterfactual import repair

        result = repair(RUN_ID, STEP_ID, engine=fake_engine, n=3, comparator=default_failure_resolved)
        assert isinstance(result, AIResult)
        assert len(result.value) == 3

    def test_missing_variants_key_falls_back(self, fake_engine, monkeypatch):
        """Missing 'variants' key in LLM JSON triggers the fallback."""
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: json.dumps({"unexpected": "shape"}),
        )
        from ai_agents.counterfactual import repair

        result = repair(RUN_ID, STEP_ID, engine=fake_engine, n=3, comparator=default_failure_resolved)
        assert isinstance(result, AIResult)
        assert len(result.value) == 3


# ---------------------------------------------------------------------------
# Custom comparator seam
# ---------------------------------------------------------------------------


class TestComparatorSeam:
    def test_custom_comparator_is_used(self, fake_engine):
        """Custom comparator overrides the default resolution check."""
        from ai_agents.counterfactual import repair

        # Comparator that resolves nothing (always False)
        result = repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            generate=lambda task, original_prompt, n: FAKE_VARIANTS,
            comparator=lambda baseline, outcome: False,
        )
        resolved_count = sum(1 for v in result.value if v.resolved)
        assert resolved_count == 0

    def test_comparator_that_resolves_all(self, fake_engine):
        """Custom comparator that resolves every variant."""
        from ai_agents.counterfactual import repair

        result = repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            generate=lambda task, original_prompt, n: FAKE_VARIANTS,
            comparator=lambda baseline, outcome: True,
        )
        resolved_count = sum(1 for v in result.value if v.resolved)
        assert resolved_count == len(FAKE_VARIANTS)


# ---------------------------------------------------------------------------
# Baseline seam: pre-computed baseline avoids extra engine.replay() call
# ---------------------------------------------------------------------------


class TestBaselineSeam:
    def test_provided_baseline_avoids_extra_replay_call(self, fake_engine):
        """When baseline is provided, engine.replay should not be called."""
        from ai_agents.counterfactual import repair
        from ai_agents.replay_interface import ReplayOutcome

        pre_baseline = ReplayOutcome(
            run_id=RUN_ID,
            final_status="error",
            failed_step_id=STEP_ID,
            side_effect_count=0,
            key_outputs={"team": "unknown"},
        )

        repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            baseline=pre_baseline,
            generate=lambda task, original_prompt, n: FAKE_VARIANTS,
            comparator=default_failure_resolved,
        )
        # engine.replay() should NOT have been called since baseline was injected
        assert len(fake_engine.replay_calls) == 0


# ---------------------------------------------------------------------------
# Prompt exports from prompts.py
# ---------------------------------------------------------------------------


class TestPromptsExports:
    def test_system_prompt_exported(self):
        from ai_agents import prompts

        assert hasattr(prompts, "COUNTERFACTUAL_VARIANTS_SYSTEM")
        assert isinstance(prompts.COUNTERFACTUAL_VARIANTS_SYSTEM, str)
        assert len(prompts.COUNTERFACTUAL_VARIANTS_SYSTEM) > 0

    def test_schema_exported(self):
        from ai_agents import prompts

        assert hasattr(prompts, "COUNTERFACTUAL_VARIANTS_SCHEMA")
        schema = prompts.COUNTERFACTUAL_VARIANTS_SCHEMA
        assert isinstance(schema, dict)
        assert schema.get("type") == "object"
        props = schema.get("properties", {})
        assert "variants" in props
        assert "confidence" in props
        assert "rationale" in props

    def test_user_builder_exported(self):
        from ai_agents import prompts

        assert hasattr(prompts, "counterfactual_variants_user")
        user_str = prompts.counterfactual_variants_user(
            task="triage ticket",
            original_prompt="classify this ticket",
            n=5,
        )
        assert isinstance(user_str, str)
        assert "5" in user_str

    def test_names_in_all(self):
        from ai_agents import prompts

        for name in (
            "COUNTERFACTUAL_VARIANTS_SYSTEM",
            "COUNTERFACTUAL_VARIANTS_SCHEMA",
            "counterfactual_variants_user",
        ):
            assert name in prompts.__all__, f"{name} missing from prompts.__all__"


# ---------------------------------------------------------------------------
# original_prompt seam: value reaches the generate function when supplied
# ---------------------------------------------------------------------------


class TestOriginalPromptSeam:
    """Verify that passing original_prompt forwards the value to the generate seam."""

    def test_original_prompt_reaches_generate(self, fake_engine):
        """When original_prompt is supplied, generate receives that exact string."""
        from ai_agents.counterfactual import repair

        captured: dict = {}

        def capturing_generate(task, original_prompt, n):
            captured["original_prompt"] = original_prompt
            return ["v1", "v2", "v3"]

        repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            original_prompt="the real step prompt text",
            generate=capturing_generate,
            comparator=default_failure_resolved,
        )
        assert captured["original_prompt"] == "the real step prompt text"

    def test_without_original_prompt_generate_receives_placeholder(self, fake_engine):
        """When original_prompt is omitted, generate receives the bracketed placeholder."""
        from ai_agents.counterfactual import repair

        captured: dict = {}

        def capturing_generate(task, original_prompt, n):
            captured["original_prompt"] = original_prompt
            return ["v1", "v2", "v3"]

        repair(
            RUN_ID,
            STEP_ID,
            engine=fake_engine,
            generate=capturing_generate,
            comparator=default_failure_resolved,
        )
        assert "original step" in captured["original_prompt"]
        assert str(STEP_ID) in captured["original_prompt"]
        assert RUN_ID in captured["original_prompt"]
