"""Tests for the opt-in preventive_note wiring in agent/jira_triage_agent.py.

Run: python -m pytest agent/tests/test_preventive.py -q

These tests verify that:
- run(..., preventive_note="HEADS UP") passes through to the offline path and
  sets draft["preventive_applied"] = True in the returned outcome.
- run(...) with no note leaves the outcome unchanged (no preventive_applied key).
- The agent runs without GROQ_API_KEY (offline-safe).
"""
from __future__ import annotations

import os

import pytest

from agent.jira_triage_agent import DEMO_TICKET, run, _llm_triage_offline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_offline(monkeypatch, **kwargs):
    """Run the agent with GROQ_API_KEY suppressed and _load_dotenv no-oped."""
    import agent.jira_triage_agent as agent_mod

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # No-op the dotenv loader so it cannot restore the key from a .env file.
    monkeypatch.setattr(agent_mod, "_load_dotenv", lambda: None)
    return run(DEMO_TICKET, verbose=False, **kwargs)


# ---------------------------------------------------------------------------
# Baseline: no note -> existing behavior unchanged
# ---------------------------------------------------------------------------


def test_run_no_note_returns_dict(monkeypatch):
    """run() with no preventive_note must return a dict."""
    outcome = _run_offline(monkeypatch)
    assert isinstance(outcome, dict)


def test_run_no_note_no_preventive_applied(monkeypatch):
    """run() with no preventive_note must NOT set preventive_applied on the draft."""
    outcome = _run_offline(monkeypatch)
    email_section = outcome.get("email", {})
    assert "preventive_applied" not in outcome
    assert "preventive_applied" not in email_section


def test_run_no_note_has_expected_keys(monkeypatch):
    """Baseline outcome must contain the usual keys."""
    outcome = _run_offline(monkeypatch)
    for key in ("ticket", "resolved_priority", "assigned_team", "email"):
        assert key in outcome, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Opt-in: with note -> preventive_applied set
# ---------------------------------------------------------------------------


def test_run_with_note_sets_preventive_applied(monkeypatch):
    """run() with a truthy preventive_note must set preventive_applied=True in the email."""
    outcome = _run_offline(monkeypatch, preventive_note="HEADS UP")
    # _llm_triage_offline sets draft["preventive_applied"] = True when note is truthy.
    # outcome["email"] is built as {"to": ..., **draft} so the key propagates there.
    email_section = outcome.get("email", {})
    assert email_section.get("preventive_applied") is True, (
        "Expected preventive_applied=True in outcome['email'] when note is provided"
    )


def test_run_with_note_still_has_expected_keys(monkeypatch):
    """run() with a note must still return all the usual keys."""
    outcome = _run_offline(monkeypatch, preventive_note="HEADS UP")
    for key in ("ticket", "resolved_priority", "assigned_team", "email"):
        assert key in outcome, f"Missing key after wiring note: {key}"


def test_run_with_none_note_unchanged(monkeypatch):
    """run() with preventive_note=None (explicit) behaves like the baseline."""
    outcome = _run_offline(monkeypatch, preventive_note=None)
    email_section = outcome.get("email", {})
    assert "preventive_applied" not in email_section


def test_run_offline_with_note_does_not_raise(monkeypatch):
    """Agent must not raise even when a note is injected and no GROQ key is set."""
    outcome = _run_offline(monkeypatch, preventive_note="Preventive: check priority.")
    assert outcome is not None


def test_run_offline_no_note_does_not_raise(monkeypatch):
    """Agent must not raise when offline and no note is provided."""
    outcome = _run_offline(monkeypatch)
    assert outcome is not None


# ---------------------------------------------------------------------------
# Unit test: _llm_triage_offline directly
# ---------------------------------------------------------------------------


def test_llm_triage_offline_sets_preventive_applied():
    """_llm_triage_offline must set preventive_applied=True when note is truthy."""
    draft = _llm_triage_offline(DEMO_TICKET, preventive_note="HEADS UP")
    assert draft.get("preventive_applied") is True


def test_llm_triage_offline_no_note_no_key():
    """_llm_triage_offline must NOT set preventive_applied when note is None."""
    draft = _llm_triage_offline(DEMO_TICKET, preventive_note=None)
    assert "preventive_applied" not in draft


def test_llm_triage_offline_preserves_existing_keys():
    """_llm_triage_offline must still return the usual keys regardless of note."""
    for note in (None, "HEADS UP"):
        draft = _llm_triage_offline(DEMO_TICKET, preventive_note=note)
        for key in ("intent", "email_subject", "email_body"):
            assert key in draft, f"Missing key {key!r} when preventive_note={note!r}"
