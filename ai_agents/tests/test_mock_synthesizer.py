"""Tests for ai_agents.mock_synthesizer (LLM-backed with offline fallback).

All tests monkeypatch ``ai_agents.llm.llm_complete`` so no network call or API
key is needed. The mocking contract requires calling ``llm.llm_complete(...)``
(module attribute) in the implementation; if the implementation used
``from ai_agents.llm import llm_complete`` instead, the monkeypatch would not
take effect and tests would raise ``LLMNotConfigured``.

Run from the repo root:
    pytest ai_agents/tests/test_mock_synthesizer.py -v
"""
from __future__ import annotations

import json

import pytest

from ai_agents.llm import LLMNotConfigured
from ai_agents.mock_synthesizer import _skeleton_from_schema, synthesize


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "count": {"type": "integer"},
        "ratio": {"type": "number"},
        "ok": {"type": "boolean"},
        "items": {"type": "array"},
        "meta": {"type": "object"},
    },
    "required": ["status", "count"],
}

SAMPLE_TOOL = "get_ticket_info"
SAMPLE_ARGUMENTS = {"ticket_id": "TKT-123"}
SAMPLE_CONTEXT = {"run_id": "run-1", "step_id": 2}


def _fake_llm_returns(obj: dict):
    """Return a fake llm_complete that serialises obj as the response."""
    def _fake(**kwargs):
        return json.dumps(obj)
    return _fake


def _raise_not_configured(**kwargs):
    raise LLMNotConfigured("GROQ_API_KEY is not set")


# ---------------------------------------------------------------------------
# _skeleton_from_schema unit tests
# ---------------------------------------------------------------------------


class TestSkeletonFromSchema:
    def test_empty_schema_returns_empty_dict(self):
        assert _skeleton_from_schema({}) == {}

    def test_none_schema_returns_empty_dict(self):
        assert _skeleton_from_schema(None) == {}

    def test_string_property_defaults_to_empty_string(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        result = _skeleton_from_schema(schema)
        assert result == {"name": ""}

    def test_integer_property_defaults_to_zero(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        result = _skeleton_from_schema(schema)
        assert result == {"count": 0}

    def test_number_property_defaults_to_zero(self):
        schema = {"type": "object", "properties": {"ratio": {"type": "number"}}}
        result = _skeleton_from_schema(schema)
        assert result == {"ratio": 0}

    def test_boolean_property_defaults_to_false(self):
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        result = _skeleton_from_schema(schema)
        assert result == {"ok": False}

    def test_array_property_defaults_to_empty_list(self):
        schema = {"type": "object", "properties": {"items": {"type": "array"}}}
        result = _skeleton_from_schema(schema)
        assert result == {"items": []}

    def test_object_property_defaults_to_empty_dict(self):
        schema = {"type": "object", "properties": {"meta": {"type": "object"}}}
        result = _skeleton_from_schema(schema)
        assert result == {"meta": {}}

    def test_object_with_nested_properties_recurses_one_level(self):
        schema = {
            "type": "object",
            "properties": {
                "nested": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "score": {"type": "number"},
                    },
                }
            },
        }
        result = _skeleton_from_schema(schema)
        assert result == {"nested": {"label": "", "score": 0}}

    def test_all_types_in_one_schema(self):
        result = _skeleton_from_schema(SAMPLE_SCHEMA)
        assert result["status"] == ""
        assert result["count"] == 0
        assert result["ratio"] == 0
        assert result["ok"] is False
        assert result["items"] == []
        assert result["meta"] == {}

    def test_unknown_type_defaults_to_none(self):
        schema = {"type": "object", "properties": {"x": {"type": "null"}}}
        result = _skeleton_from_schema(schema)
        assert "x" in result
        assert result["x"] is None

    def test_property_without_type_defaults_to_none(self):
        schema = {"type": "object", "properties": {"x": {}}}
        result = _skeleton_from_schema(schema)
        assert "x" in result


# ---------------------------------------------------------------------------
# synthesize: happy path (LLM returns a valid JSON object)
# ---------------------------------------------------------------------------


class TestSynthesizeLLMPath:
    def test_returns_ai_result_with_dict_value(self, monkeypatch):
        expected = {"status": "open", "count": 5}
        monkeypatch.setattr("ai_agents.llm.llm_complete", _fake_llm_returns(expected))

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert result.value == expected

    def test_confidence_is_high_on_clean_llm_response(self, monkeypatch):
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            _fake_llm_returns({"status": "ok", "count": 1}),
        )

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert result.confidence >= 0.6
        assert result.needs_review is False

    def test_needs_review_false_on_clean_llm_response(self, monkeypatch):
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            _fake_llm_returns({"status": "done", "count": 0}),
        )

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert result.needs_review is False

    def test_rationale_is_non_empty_string(self, monkeypatch):
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            _fake_llm_returns({"status": "x", "count": 0}),
        )

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert isinstance(result.rationale, str)
        assert len(result.rationale) > 0

    def test_llm_called_with_cheap_model(self, monkeypatch):
        captured = {}

        def fake_llm(**kw):
            captured.update(kw)
            return json.dumps({"status": "", "count": 0})

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm)

        from ai_agents.llm import cheap_model

        synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert captured.get("model") == cheap_model()

    def test_llm_called_with_json_schema(self, monkeypatch):
        captured = {}

        def fake_llm(**kw):
            captured.update(kw)
            return json.dumps({"status": "", "count": 0})

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm)

        synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert captured.get("json_schema") == SAMPLE_SCHEMA

    def test_user_prompt_contains_tool_name(self, monkeypatch):
        captured = {}

        def fake_llm(**kw):
            captured.update(kw)
            return json.dumps({"status": "", "count": 0})

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm)

        synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert SAMPLE_TOOL in captured.get("user", "")


# ---------------------------------------------------------------------------
# synthesize: fallback path (LLMNotConfigured)
# ---------------------------------------------------------------------------


class TestSynthesizeFallbackOnNotConfigured:
    def test_does_not_raise_on_llm_not_configured(self, monkeypatch):
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert result is not None

    def test_fallback_value_has_correct_keys(self, monkeypatch):
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert "status" in result.value
        assert "count" in result.value

    def test_fallback_string_field_is_empty_string(self, monkeypatch):
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert result.value["status"] == ""

    def test_fallback_integer_field_is_zero(self, monkeypatch):
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert result.value["count"] == 0

    def test_fallback_confidence_is_low(self, monkeypatch):
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert result.confidence < 0.6

    def test_fallback_needs_review_is_true(self, monkeypatch):
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert result.needs_review is True

    def test_fallback_rationale_mentions_placeholder(self, monkeypatch):
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert len(result.rationale) > 0


# ---------------------------------------------------------------------------
# synthesize: fallback path (invalid JSON from LLM)
# ---------------------------------------------------------------------------


class TestSynthesizeFallbackOnInvalidJSON:
    def test_does_not_raise_on_invalid_json(self, monkeypatch):
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: "not valid json {{")

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert result is not None

    def test_fallback_used_on_invalid_json(self, monkeypatch):
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: "not valid json {{")

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert result.needs_review is True
        assert "status" in result.value

    def test_fallback_used_when_llm_returns_non_dict(self, monkeypatch):
        """LLM returns valid JSON but not an object (e.g. a list)."""
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: json.dumps([1, 2, 3]))

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert result.needs_review is True

    def test_fallback_used_on_missing_key_error(self, monkeypatch):
        """LLM returns JSON but accessing a required key raises KeyError."""

        def _bad_llm(**kwargs):
            return json.dumps({})

        monkeypatch.setattr("ai_agents.llm.llm_complete", _bad_llm)

        # Even an empty object should not raise; synthesize is never-raise
        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, SAMPLE_SCHEMA, SAMPLE_CONTEXT)

        assert result is not None


# ---------------------------------------------------------------------------
# synthesize: empty / None schema edge cases
# ---------------------------------------------------------------------------


class TestSynthesizeEdgeCases:
    def test_empty_schema_does_not_raise_on_fallback(self, monkeypatch):
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, {}, SAMPLE_CONTEXT)

        assert result is not None
        assert isinstance(result.value, dict)

    def test_none_schema_does_not_raise(self, monkeypatch):
        monkeypatch.setattr("ai_agents.llm.llm_complete", _raise_not_configured)

        result = synthesize(SAMPLE_TOOL, SAMPLE_ARGUMENTS, None, SAMPLE_CONTEXT)

        assert result is not None
        assert isinstance(result.value, dict)
