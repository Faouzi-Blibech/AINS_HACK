"""Offline tests for the Groq LLM adapter (ai_agents/llm.py).

All tests mock httpx so no real network call is made and no GROQ_API_KEY is
required in the test environment. Each test exercises one behavioral contract
of the adapter.

Run from the repo root:
    pytest ai_agents/tests/test_llm.py -v
"""
from __future__ import annotations

import json

import httpx
import pytest

from ai_agents.llm import LLMNotConfigured, cheap_model, llm_complete, reasoning_model


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_FAKE_KEY = "gsk_test_1234"


def _mock_response(content: str, status_code: int = 200) -> httpx.Response:
    """Build a minimal Groq-shaped httpx.Response for the mock transport."""
    body = json.dumps({"choices": [{"message": {"content": content}}]})
    return httpx.Response(status_code, content=body.encode(), headers={"content-type": "application/json"})


class _CapturingTransport(httpx.BaseTransport):
    """Captures the last request and returns a preset response."""

    def __init__(self, response: httpx.Response) -> None:
        self.last_request: httpx.Request | None = None
        self._response = response

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.last_request = request
        # httpx requires the stream to be read from an existing response
        # when reusing; return a fresh response with the same body.
        return httpx.Response(
            self._response.status_code,
            content=self._response.content,
            headers=dict(self._response.headers),
        )


def _make_client(transport: _CapturingTransport) -> httpx.Client:
    return httpx.Client(transport=transport)


# --------------------------------------------------------------------------- #
# 1. Happy path
# --------------------------------------------------------------------------- #


class TestHappyPath:
    def test_returns_assistant_content(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", _FAKE_KEY)
        transport = _CapturingTransport(_mock_response("hello"))
        result = llm_complete(
            system="You are helpful.",
            user="Say hello.",
            model="llama-3.1-8b-instant",
            _client=_make_client(transport),
        )
        assert result == "hello"

    def test_returns_json_string_in_json_mode(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", _FAKE_KEY)
        payload = json.dumps({"answer": 42})
        transport = _CapturingTransport(_mock_response(payload))
        result = llm_complete(
            system="You are helpful.",
            user="Return JSON.",
            model="llama-3.1-8b-instant",
            json_mode=True,
            _client=_make_client(transport),
        )
        assert json.loads(result) == {"answer": 42}


# --------------------------------------------------------------------------- #
# 2. Request shape
# --------------------------------------------------------------------------- #


class TestRequestShape:
    def _call(self, monkeypatch, *, json_mode: bool = False) -> _CapturingTransport:
        monkeypatch.setenv("GROQ_API_KEY", _FAKE_KEY)
        transport = _CapturingTransport(_mock_response("ok"))
        llm_complete(
            system="sys",
            user="usr",
            model="my-model",
            json_mode=json_mode,
            temperature=0.5,
            _client=_make_client(transport),
        )
        return transport

    def test_url_is_groq_endpoint(self, monkeypatch):
        transport = self._call(monkeypatch)
        assert str(transport.last_request.url) == _GROQ_URL

    def test_authorization_header(self, monkeypatch):
        transport = self._call(monkeypatch)
        assert transport.last_request.headers["authorization"] == f"Bearer {_FAKE_KEY}"

    def test_body_model_and_messages(self, monkeypatch):
        transport = self._call(monkeypatch)
        body = json.loads(transport.last_request.content)
        assert body["model"] == "my-model"
        assert body["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "usr"},
        ]

    def test_body_temperature(self, monkeypatch):
        transport = self._call(monkeypatch)
        body = json.loads(transport.last_request.content)
        assert body["temperature"] == pytest.approx(0.5)

    def test_no_response_format_without_json_mode(self, monkeypatch):
        transport = self._call(monkeypatch, json_mode=False)
        body = json.loads(transport.last_request.content)
        assert "response_format" not in body

    def test_response_format_added_in_json_mode(self, monkeypatch):
        transport = self._call(monkeypatch, json_mode=True)
        body = json.loads(transport.last_request.content)
        assert body["response_format"] == {"type": "json_object"}


# --------------------------------------------------------------------------- #
# 3. LLMNotConfigured raised when key is absent
# --------------------------------------------------------------------------- #


class TestMissingApiKey:
    def test_raises_when_key_not_set(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        with pytest.raises(LLMNotConfigured, match="GROQ_API_KEY is not set"):
            llm_complete(
                system="s",
                user="u",
                model="m",
            )

    def test_raises_when_key_is_empty_string(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "")
        with pytest.raises(LLMNotConfigured, match="GROQ_API_KEY is not set"):
            llm_complete(
                system="s",
                user="u",
                model="m",
            )


# --------------------------------------------------------------------------- #
# 4. Model-id helpers
# --------------------------------------------------------------------------- #


class TestModelHelpers:
    def test_reasoning_model_default(self, monkeypatch):
        monkeypatch.delenv("CASSETTE_REASONING_MODEL", raising=False)
        assert reasoning_model() == "llama-3.3-70b-versatile"

    def test_reasoning_model_env_override(self, monkeypatch):
        monkeypatch.setenv("CASSETTE_REASONING_MODEL", "my-reasoning-model")
        assert reasoning_model() == "my-reasoning-model"

    def test_cheap_model_default(self, monkeypatch):
        monkeypatch.delenv("CASSETTE_CHEAP_MODEL", raising=False)
        assert cheap_model() == "llama-3.1-8b-instant"

    def test_cheap_model_env_override(self, monkeypatch):
        monkeypatch.setenv("CASSETTE_CHEAP_MODEL", "my-cheap-model")
        assert cheap_model() == "my-cheap-model"


# --------------------------------------------------------------------------- #
# 5. JSON instruction injection (Groq json_object mode needs "json" in the prompt)
# --------------------------------------------------------------------------- #


class TestJsonInstructionInjection:
    def _send(self, monkeypatch, **kwargs) -> _CapturingTransport:
        monkeypatch.setenv("GROQ_API_KEY", _FAKE_KEY)
        transport = _CapturingTransport(_mock_response("{}"))
        llm_complete(
            system="judge equivalence",
            user="compare A and B",
            model="m",
            _client=_make_client(transport),
            **kwargs,
        )
        return transport

    def test_json_mode_injects_json_word_into_system(self, monkeypatch):
        transport = self._send(monkeypatch, json_mode=True)
        body = json.loads(transport.last_request.content)
        system_msg = body["messages"][0]["content"]
        # Groq rejects json_object mode unless the prompt mentions JSON.
        assert "json" in system_msg.lower()
        assert body["response_format"] == {"type": "json_object"}

    def test_json_schema_enables_json_and_embeds_schema(self, monkeypatch):
        schema = {
            "type": "object",
            "properties": {"equivalent": {"type": "boolean"}},
            "required": ["equivalent"],
        }
        # json_schema alone (json_mode left False) must still enable JSON mode.
        transport = self._send(monkeypatch, json_schema=schema)
        body = json.loads(transport.last_request.content)
        system_msg = body["messages"][0]["content"]
        assert "json" in system_msg.lower()
        assert "equivalent" in system_msg  # the schema is embedded in the prompt
        assert body["response_format"] == {"type": "json_object"}

    def test_no_json_instruction_when_plain(self, monkeypatch):
        transport = self._send(monkeypatch)
        body = json.loads(transport.last_request.content)
        assert body["messages"][0]["content"] == "judge equivalence"
        assert "response_format" not in body
