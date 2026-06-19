"""Tests for ai_agents.semantic_matcher (LLM-backed).

All tests mock ``ai_agents.llm.llm_complete`` so no network call or API key is
needed. The mocking contract requires calling ``llm.llm_complete(...)`` (module
attribute) in the implementation, which is verified implicitly: if the wrong
import form were used (``from ai_agents.llm import llm_complete``), the
monkeypatch would not take effect and the tests would raise ``LLMNotConfigured``
instead of using the fake.

Run from the repo root:
    pytest ai_agents/tests/test_semantic_matcher.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from ai_agents.llm import LLMNotConfigured
from ai_agents.replay_interface import ReplayOutcome
from ai_agents.semantic_matcher import MatchResult, llm_failure_resolved, match


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "sample_trace.json"
)


def _json_response(**kwargs) -> str:
    """Return a JSON string as the fake llm_complete would."""
    return json.dumps(kwargs)


def _raise_not_configured(*args, **kwargs):
    raise LLMNotConfigured("GROQ_API_KEY is not set")


# ---------------------------------------------------------------------------
# Part A: match()
# ---------------------------------------------------------------------------


class TestMatch:
    def test_happy_path_returns_ai_result_with_match_result(self, monkeypatch):
        """match() parses the LLM JSON and returns a properly wrapped AIResult."""
        fake_response = _json_response(
            equivalent=True,
            score=0.9,
            confidence=0.8,
            rationale="same team",
        )
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: fake_response)

        result = match("routed to backend", "assigned to Backend Engineers")

        assert result.value.equivalent is True
        assert result.value.score == pytest.approx(0.9)
        assert result.confidence == pytest.approx(0.8)
        assert result.rationale == "same team"
        # confidence=0.8 > REVIEW_THRESHOLD=0.6 -> needs_review=False
        assert result.needs_review is False

    def test_needs_review_true_when_low_confidence(self, monkeypatch):
        """needs_review is True when LLM-reported confidence is below 0.6."""
        fake_response = _json_response(
            equivalent=False,
            score=0.2,
            confidence=0.4,
            rationale="different routing targets",
        )
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: fake_response)

        result = match("routed to backend", "sent to frontend")

        assert result.confidence == pytest.approx(0.4)
        assert result.needs_review is True

    def test_not_equivalent_propagated(self, monkeypatch):
        """match() propagates equivalent=False from the LLM correctly."""
        fake_response = _json_response(
            equivalent=False,
            score=0.1,
            confidence=0.9,
            rationale="completely different outcomes",
        )
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: fake_response)

        result = match("success", "error: timeout")

        assert result.value.equivalent is False
        assert result.value.score == pytest.approx(0.1)

    def test_propagates_llm_not_configured(self, monkeypatch):
        """match() must NOT catch LLMNotConfigured; it should propagate."""
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        with pytest.raises(LLMNotConfigured):
            match("expected", "actual")

    def test_task_parameter_is_forwarded(self, monkeypatch):
        """The task= kwarg is passed through to the LLM prompt."""
        captured = {}

        def fake_llm(**kw):
            captured.update(kw)
            return _json_response(equivalent=True, score=1.0, confidence=0.95, rationale="ok")

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm)
        match("a", "b", task="ticket routing")

        # The user prompt should contain the task string
        assert "ticket routing" in captured["user"]

    def test_result_value_is_match_result_instance(self, monkeypatch):
        """The AIResult.value must be a MatchResult dataclass instance."""
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: _json_response(equivalent=True, score=0.9, confidence=0.8, rationale="x"),
        )
        result = match("a", "b")
        assert isinstance(result.value, MatchResult)


# ---------------------------------------------------------------------------
# Part C: llm_failure_resolved()
# ---------------------------------------------------------------------------


class TestLlmFailureResolved:
    """Tests for the LLM-backed OutcomeComparator factory."""

    def _make_outcomes(
        self,
        baseline_status: str = "error",
        perturbed_status: str = "ok",
        baseline_outputs: dict | None = None,
        perturbed_outputs: dict | None = None,
    ):
        baseline = ReplayOutcome(
            run_id="run-1",
            final_status=baseline_status,
            key_outputs=baseline_outputs or {"team": "backend", "priority": "medium"},
        )
        perturbed = ReplayOutcome(
            run_id="run-1-fork",
            final_status=perturbed_status,
            key_outputs=perturbed_outputs or {"team": "frontend", "priority": "high"},
        )
        return baseline, perturbed

    def test_returns_true_when_non_equivalent_and_perturbed_ok(self, monkeypatch):
        """Comparator returns True: baseline failed, perturbed ok, outputs differ."""
        # LLM says: NOT equivalent -> failure is genuinely resolved
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: _json_response(equivalent=False, score=0.1, confidence=0.9, rationale="different"),
        )
        comparator = llm_failure_resolved()
        baseline, perturbed = self._make_outcomes()

        assert comparator(baseline, perturbed) is True

    def test_returns_false_when_equivalent_even_if_perturbed_ok(self, monkeypatch):
        """Comparator returns False when LLM says outputs are equivalent (behavior unchanged)."""
        # LLM says: equivalent -> the "fix" didn't actually change the behavior
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: _json_response(equivalent=True, score=0.9, confidence=0.9, rationale="same"),
        )
        comparator = llm_failure_resolved()
        baseline, perturbed = self._make_outcomes()

        assert comparator(baseline, perturbed) is False

    def test_returns_false_when_perturbed_still_failing(self, monkeypatch):
        """Comparator short-circuits to False when perturbed run is still failing."""
        # The LLM should NOT be called at all in this case.
        called = []
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: called.append(True) or _json_response(
                equivalent=False, score=0.1, confidence=0.9, rationale="x"
            ),
        )
        comparator = llm_failure_resolved()
        baseline, perturbed = self._make_outcomes(
            baseline_status="error", perturbed_status="error"
        )

        result = comparator(baseline, perturbed)

        assert result is False
        assert len(called) == 0  # LLM was not invoked

    def test_returns_false_when_baseline_was_ok(self, monkeypatch):
        """Comparator returns False when baseline was already ok (no failure to resolve)."""
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: _json_response(equivalent=False, score=0.1, confidence=0.9, rationale="x"),
        )
        comparator = llm_failure_resolved()
        baseline, perturbed = self._make_outcomes(
            baseline_status="ok", perturbed_status="ok"
        )

        assert comparator(baseline, perturbed) is False

    def test_falls_back_to_default_on_llm_not_configured(self, monkeypatch):
        """On LLMNotConfigured, the comparator falls back to default_failure_resolved."""
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        comparator = llm_failure_resolved()
        baseline, perturbed = self._make_outcomes(
            baseline_status="error", perturbed_status="ok"
        )

        # default_failure_resolved(baseline, perturbed) -> True (baseline failed, perturbed ok)
        from ai_agents.replay_interface import default_failure_resolved

        fallback_result = default_failure_resolved(baseline, perturbed)
        assert comparator(baseline, perturbed) == fallback_result

    def test_fallback_when_both_failing_matches_default(self, monkeypatch):
        """Fallback behavior is consistent with default_failure_resolved."""
        # For both-failing case the status check happens before the LLM call,
        # so LLMNotConfigured is irrelevant; still False.
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        comparator = llm_failure_resolved()
        baseline, perturbed = self._make_outcomes(
            baseline_status="error", perturbed_status="error"
        )

        from ai_agents.replay_interface import default_failure_resolved

        assert comparator(baseline, perturbed) == default_failure_resolved(baseline, perturbed)

    def test_task_parameter_passed_to_match(self, monkeypatch):
        """The task= parameter is forwarded to the LLM judge."""
        captured = {}

        def fake_llm(**kw):
            captured.update(kw)
            return _json_response(equivalent=False, score=0.1, confidence=0.9, rationale="ok")

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm)

        comparator = llm_failure_resolved(task="ticket routing")
        baseline, perturbed = self._make_outcomes()
        comparator(baseline, perturbed)

        assert "ticket routing" in captured.get("user", "")

    def test_falls_back_to_default_on_malformed_json(self, monkeypatch):
        """On malformed LLM reply (non-JSON), comparator degrades to default_failure_resolved."""
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: "not json")

        comparator = llm_failure_resolved()
        baseline, perturbed = self._make_outcomes(
            baseline_status="error", perturbed_status="ok"
        )

        from ai_agents.replay_interface import default_failure_resolved

        assert comparator(baseline, perturbed) == default_failure_resolved(baseline, perturbed)
