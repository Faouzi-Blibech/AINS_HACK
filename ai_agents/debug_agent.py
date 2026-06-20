"""Debug agent: natural language to JSON injection.

The engineer never edits raw JSON. They type plain English, e.g.
"at step 2, the priority should have been high, not medium", and this agent
builds the exact, structurally valid injection and fires the replay from that
step. Without the LLM the engineer is back to hand-editing trace payloads, so
this is the clearest proof AI is load-bearing.

The injection it produces is a replay_interface.Injection (the same shape the
blame graph perturbs with and the /diverge API accepts), so the debug agent and
the rest of the AI layer speak one language.

Prompt, JSON schema, and validation are all here. The live LLM call goes through
ai_agents.llm so any OpenAI-compatible provider works without touching this file.
"""
from __future__ import annotations

import json

from ai_agents import llm
from ai_agents import prompts
from ai_agents.confidence import AIResult, wrap
from ai_agents.replay_interface import Injection

_VALID_TARGETS = {"prompt", "response", "args", "result"}
# A target only makes sense for the matching step type.
_TARGETS_BY_TYPE = {
    "llm_call": {"prompt", "response"},
    "tool_call": {"args", "result"},
}


def validate_injection(trace: dict, injection: Injection) -> None:
    """Raise ValueError if the injection does not fit the trace/schema.

    Guards the model's output before it reaches the replay engine: real step,
    target valid for that step's type.
    """
    by_id = {s["step_id"]: s for s in trace.get("steps", [])}
    step = by_id.get(injection.step_id)
    if step is None:
        raise ValueError(f"injection targets unknown step_id {injection.step_id}")
    if injection.target not in _VALID_TARGETS:
        raise ValueError(f"invalid target {injection.target!r}")
    allowed = _TARGETS_BY_TYPE.get(step.get("type"), set())
    if injection.target not in allowed:
        raise ValueError(
            f"target {injection.target!r} not valid for a {step.get('type')} step "
            f"(allowed: {sorted(allowed)})"
        )


def build_injection(trace: dict, instruction: str) -> AIResult[Injection]:
    """Turn a plain-English instruction into a validated, confidence-wrapped Injection.

    Calls the configured LLM with the debug-agent system prompt and a compact
    trace summary, requests a JSON object matching DEBUG_AGENT_INJECTION_SCHEMA,
    parses it into an Injection, validates it against the trace, then returns it
    in an AIResult envelope with the model's self-reported confidence and rationale.

    Parameters
    ----------
    trace:
        The full recorded trace dict (same shape as docs/fixtures/sample_trace.json).
    instruction:
        A plain-English debugging instruction from the engineer, e.g.
        "at step 2 the priority should be high, not medium".

    Returns
    -------
    AIResult[Injection]
        The parsed, validated injection wrapped with confidence and rationale.

    Raises
    ------
    llm.LLMNotConfigured
        When GROQ_API_KEY is absent. No deterministic fallback exists for the
        debug agent; the error must surface so the caller can inform the engineer.
    ValueError
        When validate_injection rejects the model's output (bad step_id or target),
        or when the model returns non-JSON or omits a required key.
    """
    summary = prompts.summarize_trace_for_prompt(trace)
    raw = llm.llm_complete(
        system=prompts.DEBUG_AGENT_SYSTEM,
        user=prompts.debug_agent_user(instruction=instruction, trace_summary=summary),
        model=llm.reasoning_model(),
        json_schema=prompts.DEBUG_AGENT_INJECTION_SCHEMA,
    )
    try:
        data = json.loads(raw)
        inj = Injection(step_id=data["step_id"], target=data["target"], value=data["value"])
        confidence = data["confidence"]
        rationale = data["rationale"]
    except (json.JSONDecodeError, KeyError):
        raise ValueError(
            "debug agent: could not parse a valid injection from the model response"
        )
    validate_injection(trace, inj)
    return wrap(inj, confidence, rationale=rationale)
