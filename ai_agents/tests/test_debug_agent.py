"""Tests for ai_agents.debug_agent (offline; no network, no API key required).

All tests mock ``ai_agents.llm.llm_complete`` via monkeypatch so the mocking
contract is verified implicitly: if debug_agent used
``from ai_agents.llm import llm_complete`` the patch would not take effect and
the tests would raise ``LLMNotConfigured`` instead of using the fake.

Run from the repo root:
    pytest ai_agents/tests/test_debug_agent.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

import ai_agents.llm
import ai_agents.prompts
from ai_agents.confidence import AIResult
from ai_agents.debug_agent import build_injection, validate_injection
from ai_agents.llm import LLMNotConfigured
from ai_agents.replay_interface import Injection

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "sample_trace.json"
)


@pytest.fixture()
def trace() -> dict:
    """Return the 4-step sample trace fixture."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fake_llm_response(**kwargs) -> str:
    """Return a JSON string as the fake llm_complete would."""
    return json.dumps(kwargs)


def _raise_not_configured(*args, **kwargs):
    raise LLMNotConfigured("GROQ_API_KEY is not set")


# ---------------------------------------------------------------------------
# 1. Valid injection: happy path
# ---------------------------------------------------------------------------


class TestBuildInjectionValid:
    def test_returns_ai_result_with_correct_injection(self, monkeypatch, trace):
        """build_injection parses the LLM response and returns a properly wrapped AIResult."""
        fake_response = _fake_llm_response(
            step_id=2,
            target="result",
            value='{"priority": "high"}',
            rationale="step 2 returned an ambiguous priority",
            confidence=0.82,
        )
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: fake_response)

        result = build_injection(trace, "at step 2 the priority should be high, not medium")

        assert isinstance(result, AIResult)
        assert isinstance(result.value, Injection)
        assert result.value.step_id == 2
        assert result.value.target == "result"
        assert result.confidence == pytest.approx(0.82)
        assert result.needs_review is False

    def test_rationale_is_forwarded(self, monkeypatch, trace):
        """The rationale from the LLM response is stored in the AIResult."""
        fake_response = _fake_llm_response(
            step_id=2,
            target="result",
            value='{"priority": "high"}',
            rationale="step 2 returned an ambiguous priority",
            confidence=0.82,
        )
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: fake_response)

        result = build_injection(trace, "at step 2 the priority should be high, not medium")

        assert result.rationale == "step 2 returned an ambiguous priority"

    def test_value_field_is_forwarded_verbatim(self, monkeypatch, trace):
        """The value string from the model is stored verbatim in the Injection."""
        raw_value = '{"priority": "high"}'
        fake_response = _fake_llm_response(
            step_id=2,
            target="result",
            value=raw_value,
            rationale="priority fix",
            confidence=0.9,
        )
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: fake_response)

        result = build_injection(trace, "at step 2 the priority should be high, not medium")

        assert result.value.value == raw_value


# ---------------------------------------------------------------------------
# 2. Validation guard: unknown step
# ---------------------------------------------------------------------------


class TestValidationGuardUnknownStep:
    def test_raises_value_error_for_unknown_step_id(self, monkeypatch, trace):
        """build_injection must propagate ValueError when the step_id is not in the trace."""
        fake_response = _fake_llm_response(
            step_id=99,
            target="result",
            value='{"priority": "high"}',
            rationale="unknown step",
            confidence=0.5,
        )
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: fake_response)

        with pytest.raises(ValueError, match="unknown step_id"):
            build_injection(trace, "fix step 99")


# ---------------------------------------------------------------------------
# 3. Validation guard: wrong target for step type
# ---------------------------------------------------------------------------


class TestValidationGuardWrongTarget:
    def test_raises_value_error_when_target_invalid_for_step_type(self, monkeypatch, trace):
        """Step 2 is a tool_call; 'prompt' is only valid for llm_call steps."""
        fake_response = _fake_llm_response(
            step_id=2,
            target="prompt",
            value="rephrase the prompt",
            rationale="trying to change prompt on a tool_call",
            confidence=0.6,
        )
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: fake_response)

        with pytest.raises(ValueError):
            build_injection(trace, "change the prompt at step 2")


# ---------------------------------------------------------------------------
# 4. Malformed JSON from the LLM
# ---------------------------------------------------------------------------


class TestMalformedLLMResponse:
    def test_raises_value_error_on_non_json_response(self, monkeypatch, trace):
        """A non-JSON reply from the model must raise ValueError (parse error path)."""
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: "not json")

        with pytest.raises(ValueError, match="debug agent: could not parse"):
            build_injection(trace, "at step 2 the priority should be high, not medium")

    def test_raises_value_error_on_missing_key(self, monkeypatch, trace):
        """A JSON reply missing required keys must raise ValueError (missing-key path)."""
        incomplete = json.dumps({"step_id": 2, "target": "result"})  # missing value/rationale/confidence
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: incomplete)

        with pytest.raises(ValueError, match="debug agent: could not parse"):
            build_injection(trace, "at step 2 the priority should be high, not medium")


# ---------------------------------------------------------------------------
# 5. LLMNotConfigured propagates unchanged
# ---------------------------------------------------------------------------


class TestLLMNotConfiguredPropagates:
    def test_llm_not_configured_propagates(self, monkeypatch, trace):
        """LLMNotConfigured from llm_complete must not be caught by build_injection."""
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        with pytest.raises(LLMNotConfigured):
            build_injection(trace, "at step 2 the priority should be high, not medium")


# ---------------------------------------------------------------------------
# 6. validate_injection unit tests
# ---------------------------------------------------------------------------


class TestValidateInjection:
    def test_valid_injection_does_not_raise(self, trace):
        """A valid Injection for a tool_call step with target='result' must not raise."""
        inj = Injection(step_id=2, target="result", value='{"priority": "high"}')
        validate_injection(trace, inj)  # must not raise

    def test_invalid_target_for_tool_call_raises(self, trace):
        """'prompt' is not a valid target for a tool_call step; must raise ValueError."""
        inj = Injection(step_id=2, target="prompt", value="text")
        with pytest.raises(ValueError):
            validate_injection(trace, inj)

    def test_valid_injection_for_llm_call_step(self, trace):
        """Step 1 is an llm_call; target='prompt' is valid for it."""
        inj = Injection(step_id=1, target="prompt", value="revised prompt text")
        validate_injection(trace, inj)  # must not raise

    def test_invalid_target_args_for_llm_call_raises(self, trace):
        """'args' is a tool_call target; must be invalid for the llm_call at step 1."""
        inj = Injection(step_id=1, target="args", value="{}")
        with pytest.raises(ValueError):
            validate_injection(trace, inj)

    def test_unknown_step_id_raises(self, trace):
        """A step_id not present in the trace must raise ValueError."""
        inj = Injection(step_id=99, target="result", value="{}")
        with pytest.raises(ValueError, match="unknown step_id"):
            validate_injection(trace, inj)


# ---------------------------------------------------------------------------
# 7. Error boundary: missing confidence/rationale raises ValueError (Fix 1)
# ---------------------------------------------------------------------------


class TestMissingConfidenceOrRationale:
    def test_raises_value_error_when_confidence_and_rationale_missing(self, monkeypatch, trace):
        """A reply with valid step_id/target/value but missing confidence and rationale
        must raise ValueError (not a raw KeyError) because both fields are read inside
        the same try/except as the other required keys."""
        incomplete = json.dumps(
            {"step_id": 2, "target": "result", "value": '{"priority": "high"}'}
        )
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: incomplete)

        with pytest.raises(ValueError, match="debug agent: could not parse"):
            build_injection(trace, "at step 2 the priority should be high, not medium")


# ---------------------------------------------------------------------------
# 8. Prompt construction: kwargs forwarded to llm_complete (Fix 6)
# ---------------------------------------------------------------------------


class TestPromptConstruction:
    def test_llm_complete_receives_correct_kwargs(self, monkeypatch, trace):
        """build_injection must call llm_complete with model=reasoning_model(),
        json_schema=DEBUG_AGENT_INJECTION_SCHEMA, and a user string that contains
        the engineer instruction text."""
        captured: dict = {}

        def fake_llm_complete(**kwargs):
            captured.update(kwargs)
            return json.dumps(
                {
                    "step_id": 2,
                    "target": "result",
                    "value": '{"priority": "high"}',
                    "rationale": "priority fix",
                    "confidence": 0.9,
                }
            )

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm_complete)

        instruction = "at step 2 the priority should be high, not medium"
        build_injection(trace, instruction)

        assert captured.get("model") == ai_agents.llm.reasoning_model()
        assert captured.get("json_schema") == ai_agents.prompts.DEBUG_AGENT_INJECTION_SCHEMA
        assert instruction in captured.get("user", "")
