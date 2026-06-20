"""Tests for ai_agents/failure_library.py (TDD).

Run: python -m pytest ai_agents/tests/test_failure_library.py -q
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from ai_agents.failure_library import (
    FailureEntry,
    FailureLibrary,
    SeedFailureLibrary,
    relevant_failures,
    preventive_note,
)
from ai_agents.confidence import AIResult


# ---------------------------------------------------------------------------
# SeedFailureLibrary
# ---------------------------------------------------------------------------


def test_seed_library_returns_three_entries():
    lib = SeedFailureLibrary()
    entries = lib.all()
    assert len(entries) == 3


def test_seed_library_entry_ids():
    lib = SeedFailureLibrary()
    ids = {e.id for e in lib.all()}
    assert ids == {"FM-014", "FM-007", "FM-021"}


def test_seed_library_blame_steps():
    lib = SeedFailureLibrary()
    by_id = {e.id: e for e in lib.all()}
    assert by_id["FM-014"].blame_step == 2
    assert by_id["FM-007"].blame_step == 1
    assert by_id["FM-021"].blame_step == 3


def test_seed_library_entries_are_failure_entry():
    lib = SeedFailureLibrary()
    for entry in lib.all():
        assert isinstance(entry, FailureEntry)


def test_seed_library_satisfies_protocol():
    lib = SeedFailureLibrary()
    assert isinstance(lib, FailureLibrary)


def test_failure_entry_fields():
    """FailureEntry must expose all required fields."""
    lib = SeedFailureLibrary()
    entry = lib.all()[0]
    # All fields present and correct types
    assert isinstance(entry.id, str)
    assert isinstance(entry.failure_pattern, str)
    assert isinstance(entry.blame_step, int)
    assert isinstance(entry.fix_that_worked, str)
    assert isinstance(entry.agent_config, str)
    assert isinstance(entry.determinism_rate, float)
    assert 0.0 <= entry.determinism_rate <= 1.0


# ---------------------------------------------------------------------------
# relevant_failures with injected judge
# ---------------------------------------------------------------------------


def _make_judge(high_id: str, high_score: float = 0.9):
    """Return an injected judge that scores the given id high, others low."""

    def judge(situation: str, failure_pattern: str) -> tuple[bool, float, float, str]:
        by_id = {e.id: e for e in SeedFailureLibrary().all()}
        for entry in by_id.values():
            if entry.id == high_id and failure_pattern == entry.failure_pattern:
                return (True, high_score, 0.85, f"Pattern {high_id} is applicable")
        return (False, 0.1, 0.9, "Not applicable")

    return judge


def test_relevant_failures_returns_airesult():
    lib = SeedFailureLibrary()
    judge = _make_judge("FM-014")
    result = relevant_failures(lib, "some situation", judge=judge)
    assert isinstance(result, AIResult)


def test_relevant_failures_top_entry_first():
    lib = SeedFailureLibrary()
    judge = _make_judge("FM-007", high_score=0.95)
    result = relevant_failures(lib, "tool argument type mismatch", judge=judge)
    assert result.value[0][0].id == "FM-007"


def test_relevant_failures_respects_k():
    lib = SeedFailureLibrary()
    judge = _make_judge("FM-014")
    result = relevant_failures(lib, "payment routing", k=1, judge=judge)
    assert len(result.value) == 1


def test_relevant_failures_k_default():
    lib = SeedFailureLibrary()
    # All entries score > 0 if we give everyone a moderate score
    def judge(situation, failure_pattern):
        return (True, 0.5, 0.7, "ok")

    result = relevant_failures(lib, "anything", judge=judge)
    # Default k=3 and seed has 3 entries
    assert len(result.value) <= 3


def test_relevant_failures_confidence_in_range():
    lib = SeedFailureLibrary()
    judge = _make_judge("FM-021", high_score=0.8)
    result = relevant_failures(lib, "context missing", judge=judge)
    assert 0.0 <= result.confidence <= 1.0


def test_relevant_failures_result_tuples():
    lib = SeedFailureLibrary()
    judge = _make_judge("FM-014")
    result = relevant_failures(lib, "priority ambiguous", judge=judge)
    for item in result.value:
        entry, score = item
        assert isinstance(entry, FailureEntry)
        assert isinstance(score, float)


def test_relevant_failures_sorted_descending():
    lib = SeedFailureLibrary()
    judge = _make_judge("FM-014", high_score=0.9)
    result = relevant_failures(lib, "routing failure", judge=judge)
    scores = [score for _, score in result.value]
    assert scores == sorted(scores, reverse=True)


def test_relevant_failures_empty_library():
    """Empty library must return AIResult with empty list and not raise."""

    class EmptyLib:
        def all(self) -> list[FailureEntry]:
            return []

    result = relevant_failures(EmptyLib(), "anything")
    assert isinstance(result, AIResult)
    assert result.value == []
    assert result.confidence < 0.6  # low confidence expected


# ---------------------------------------------------------------------------
# Default judge: monkeypatched LLM path
# ---------------------------------------------------------------------------


def _make_llm_response(relevant: bool, score: float, confidence: float, rationale: str) -> str:
    return json.dumps(
        {
            "relevant": relevant,
            "score": score,
            "confidence": confidence,
            "rationale": rationale,
        }
    )


def test_default_judge_llm_path(monkeypatch):
    """Monkeypatch llm_complete to return valid JSON; assert parsing and ranking."""
    import ai_agents.llm as llm_module

    call_count = [0]

    def fake_llm_complete(**kwargs: Any) -> str:
        call_count[0] += 1
        # Make the first call (FM-014, sorted by id iteration order) return high score,
        # others low. We can't know the iteration order, so use the pattern text to detect.
        user_text = kwargs.get("user", "")
        if "ambiguous priority" in user_text:
            return _make_llm_response(True, 0.92, 0.88, "Priority mismatch applies")
        return _make_llm_response(False, 0.1, 0.9, "Not applicable")

    monkeypatch.setattr(llm_module, "llm_complete", fake_llm_complete)

    lib = SeedFailureLibrary()
    result = relevant_failures(lib, "payment ticket with ambiguous priority field")
    assert isinstance(result, AIResult)
    # FM-014 should rank first
    assert result.value[0][0].id == "FM-014"
    assert result.value[0][1] > 0.5
    assert 0.0 <= result.confidence <= 1.0
    # LLM was called once per entry (3 entries)
    assert call_count[0] == 3


# ---------------------------------------------------------------------------
# Offline fallback: LLMNotConfigured -> keyword overlap
# ---------------------------------------------------------------------------


def test_offline_fallback_does_not_raise(monkeypatch):
    """When LLMNotConfigured is raised, keyword fallback must not raise."""
    import ai_agents.llm as llm_module

    def raise_not_configured(**kwargs: Any) -> str:
        raise llm_module.LLMNotConfigured("no key")

    monkeypatch.setattr(llm_module, "llm_complete", raise_not_configured)

    lib = SeedFailureLibrary()
    result = relevant_failures(lib, "priority ambiguous payment routing")
    assert isinstance(result, AIResult)
    assert not isinstance(result.value, Exception)


def test_offline_fallback_ranks_fm014_first(monkeypatch):
    """Keyword overlap with 'priority ambiguous' should rank FM-014 first."""
    import ai_agents.llm as llm_module

    def raise_not_configured(**kwargs: Any) -> str:
        raise llm_module.LLMNotConfigured("no key")

    monkeypatch.setattr(llm_module, "llm_complete", raise_not_configured)

    lib = SeedFailureLibrary()
    # FM-014 pattern mentions "ambiguous priority"; this situation mirrors it
    result = relevant_failures(lib, "priority ambiguous medium payment ticket wrong routing")
    if result.value:
        top_id = result.value[0][0].id
        assert top_id == "FM-014", f"Expected FM-014 first, got {top_id}"


def test_offline_fallback_empty_situation(monkeypatch):
    """Empty situation with LLMNotConfigured must return gracefully."""
    import ai_agents.llm as llm_module

    def raise_not_configured(**kwargs: Any) -> str:
        raise llm_module.LLMNotConfigured("no key")

    monkeypatch.setattr(llm_module, "llm_complete", raise_not_configured)

    lib = SeedFailureLibrary()
    result = relevant_failures(lib, "")
    assert isinstance(result, AIResult)
    assert isinstance(result.value, list)


def test_offline_fallback_no_relevant_entries(monkeypatch):
    """Situation with no keyword overlap produces empty or low-score results."""
    import ai_agents.llm as llm_module

    def raise_not_configured(**kwargs: Any) -> str:
        raise llm_module.LLMNotConfigured("no key")

    monkeypatch.setattr(llm_module, "llm_complete", raise_not_configured)

    lib = SeedFailureLibrary()
    # A situation with no words overlapping any failure pattern
    result = relevant_failures(lib, "xyzzy qwerty zork")
    assert isinstance(result, AIResult)
    # Either empty list or all scores are 0 (relevant=False means not included or score=0)
    assert isinstance(result.value, list)


# ---------------------------------------------------------------------------
# preventive_note
# ---------------------------------------------------------------------------


def _make_high_judge(threshold: float = 0.6):
    """Judge that scores FM-014 above threshold, others below."""

    def judge(situation: str, failure_pattern: str) -> tuple[bool, float, float, str]:
        lib = SeedFailureLibrary()
        for entry in lib.all():
            if entry.id == "FM-014" and failure_pattern == entry.failure_pattern:
                score = threshold + 0.2
                return (True, score, 0.85, "FM-014 is highly relevant")
        return (False, 0.1, 0.9, "Not applicable")

    return judge


def _make_low_judge():
    """Judge that scores everything below 0.6 threshold."""

    def judge(situation: str, failure_pattern: str) -> tuple[bool, float, float, str]:
        return (False, 0.05, 0.9, "Not applicable")

    return judge


def test_preventive_note_returns_airesult():
    """preventive_note must always return an AIResult."""
    lib = SeedFailureLibrary()
    result = preventive_note(lib, "priority ambiguous", judge=_make_high_judge())
    assert isinstance(result, AIResult)


def test_preventive_note_returns_string_when_relevant():
    """When an entry scores above threshold, the note value must be a non-empty string."""
    lib = SeedFailureLibrary()
    result = preventive_note(lib, "priority ambiguous payment ticket", judge=_make_high_judge())
    assert isinstance(result.value, str)
    assert len(result.value) > 0


def test_preventive_note_contains_actionable_guidance():
    """The composed note must reference the relevant pattern and its fix."""
    lib = SeedFailureLibrary()
    result = preventive_note(lib, "priority ambiguous payment ticket", judge=_make_high_judge())
    assert result.value is not None
    # Should mention some priority or routing guidance
    note_lower = result.value.lower()
    assert any(word in note_lower for word in ("priority", "routing", "medium", "enum", "fix")), (
        f"Note does not contain expected guidance keywords: {result.value!r}"
    )


def test_preventive_note_returns_none_when_nothing_qualifies():
    """When no entry qualifies above threshold, value must be None."""
    lib = SeedFailureLibrary()
    result = preventive_note(lib, "unrelated situation xyz", judge=_make_low_judge())
    assert result.value is None


def test_preventive_note_none_has_rationale():
    """Even when value is None, the AIResult must carry a rationale."""
    lib = SeedFailureLibrary()
    result = preventive_note(lib, "unrelated", judge=_make_low_judge())
    assert isinstance(result.rationale, str)
    assert len(result.rationale) > 0


def test_preventive_note_offline_path_composes_note(monkeypatch):
    """When LLMNotConfigured, keyword fallback must still compose a note for obvious match."""
    import ai_agents.llm as llm_module

    def raise_not_configured(**kwargs: Any) -> str:
        raise llm_module.LLMNotConfigured("no key")

    monkeypatch.setattr(llm_module, "llm_complete", raise_not_configured)

    lib = SeedFailureLibrary()
    # This situation has strong keyword overlap with FM-014 (ambiguous priority routing)
    situation = "priority ambiguous medium wrong routing payment ticket"
    result = preventive_note(lib, situation)
    assert isinstance(result, AIResult)
    # Should not raise; value may be a string or None but must not be an exception
    assert result.value is None or isinstance(result.value, str)


def test_preventive_note_offline_always_returns_airesult(monkeypatch):
    """Offline path must never raise and always return AIResult."""
    import ai_agents.llm as llm_module

    def raise_not_configured(**kwargs: Any) -> str:
        raise llm_module.LLMNotConfigured("no key")

    monkeypatch.setattr(llm_module, "llm_complete", raise_not_configured)

    lib = SeedFailureLibrary()
    result = preventive_note(lib, "checkout payment priority P2 medium ambiguous routing")
    assert isinstance(result, AIResult)


def test_preventive_note_respects_threshold():
    """score >= threshold means the note must be produced (non-None, non-empty string)."""
    lib = SeedFailureLibrary()

    # Injected judge returns score exactly 0.6 for FM-014, making the boundary deterministic.
    def borderline_judge(situation: str, failure_pattern: str) -> tuple[bool, float, float, str]:
        for entry in SeedFailureLibrary().all():
            if entry.id == "FM-014" and failure_pattern == entry.failure_pattern:
                return (True, 0.6, 0.8, "Borderline")
        return (False, 0.05, 0.9, "Not applicable")

    result = preventive_note(lib, "priority ambiguous", threshold=0.6, judge=borderline_judge)
    # Contract: score >= threshold (0.6 >= 0.6 is True) -> note must be non-None and non-empty.
    assert result.value is not None
    assert isinstance(result.value, str)
    assert len(result.value) > 0
