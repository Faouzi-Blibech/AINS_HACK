"""Groq LLM adapter: the single point of contact between the AI layer and the LLM.

Every AI analysis component (semantic matcher, root-cause verdict, debug agent)
calls `llm_complete` to talk to the language model. The concrete provider is
Groq, accessed through its OpenAI-compatible chat/completions endpoint. Keeping
this in one module means swapping providers later only requires changing this
file.

The module is importable even when `GROQ_API_KEY` is absent and even when
`python-dotenv` is not installed; callers that need the LLM catch
`LLMNotConfigured` and fall back to deterministic behavior.
"""
from __future__ import annotations

import json
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import httpx

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMNotConfigured(RuntimeError):
    """Raised when GROQ_API_KEY is absent or empty."""


def reasoning_model() -> str:
    """Return the model id to use for reasoning-heavy tasks.

    Reads ``CASSETTE_REASONING_MODEL`` from the environment; defaults to
    ``llama-3.3-70b-versatile``.
    """
    return os.environ.get("CASSETTE_REASONING_MODEL", "llama-3.3-70b-versatile")


def cheap_model() -> str:
    """Return the model id to use for high-volume, low-cost tasks.

    Reads ``CASSETTE_CHEAP_MODEL`` from the environment; defaults to
    ``llama-3.1-8b-instant``.
    """
    return os.environ.get("CASSETTE_CHEAP_MODEL", "llama-3.1-8b-instant")


def llm_complete(
    *,
    system: str,
    user: str,
    model: str,
    json_mode: bool = False,
    json_schema: dict | None = None,
    temperature: float = 0.0,
    timeout: float = 30.0,
    _client: httpx.Client | None = None,
) -> str:
    """Call the Groq chat/completions endpoint and return the assistant's reply.

    Parameters
    ----------
    system:
        The system prompt.
    user:
        The user turn.
    model:
        The Groq model id (e.g. ``reasoning_model()`` or ``cheap_model()``).
    json_mode:
        When ``True``, asks the model for a single JSON object
        (``response_format={"type": "json_object"}``). The returned string is the
        raw JSON text; parse it with ``json.loads``.
    json_schema:
        Optional JSON schema (e.g. ``prompts.EQUIVALENCE_JUDGE_SCHEMA``). When
        given, JSON mode is enabled and the schema is included in the prompt so
        the reply is shaped to match it. Note that the schema is not strictly
        enforced server-side; callers should still parse defensively.
    temperature:
        Sampling temperature (0.0 for deterministic greedy decoding).
    timeout:
        HTTP timeout in seconds.
    _client:
        Optional injected ``httpx.Client``; used by tests to avoid real network
        calls. Not part of the documented public surface.

    Returns
    -------
    str
        The assistant message content. A JSON string when ``json_mode=True``.

    Raises
    ------
    LLMNotConfigured
        If ``GROQ_API_KEY`` is absent or empty.
    httpx.HTTPStatusError
        If the Groq API returns a non-2xx HTTP status.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMNotConfigured("GROQ_API_KEY is not set")

    want_json = json_mode or json_schema is not None
    if want_json:
        # Groq's json_object response_format requires the messages to mention
        # JSON, so inject an explicit instruction (and the schema when given).
        # This keeps the requirement in one place instead of in every prompt.
        instruction = "\n\nRespond with a single valid JSON object and nothing else."
        if json_schema is not None:
            instruction += " It must conform to this JSON schema: " + json.dumps(json_schema)
        system = system + instruction

    body: dict = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if want_json:
        body["response_format"] = {"type": "json_object"}

    headers = {"Authorization": f"Bearer {api_key}"}

    if _client is not None:
        resp = _client.post(_GROQ_URL, headers=headers, json=body, timeout=timeout)
    else:
        resp = httpx.post(_GROQ_URL, headers=headers, json=body, timeout=timeout)

    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
