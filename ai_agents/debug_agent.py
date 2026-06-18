"""Debug agent: natural language to JSON injection.

The engineer never edits raw JSON. They type plain English, e.g.
"at step 2, the priority should have been high, not medium", and this agent
builds the exact, structurally valid injection and fires the replay from that
step. Without the LLM the engineer is back to hand-editing trace payloads, so
this is the clearest proof AI is load-bearing.

The injection it produces is a replay_interface.Injection (the same shape the
blame graph perturbs with and the /diverge API accepts), so the debug agent and
the rest of the AI layer speak one language.

Prompt and validation are drafted (see prompts.DEBUG_AGENT_*). The live LLM call
is provider-agnostic and wired once the model is chosen and the divergence
replay is ready. `validate_injection` is runnable now.
"""
from __future__ import annotations

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
    """Turn a plain-English instruction into a validated injection.

    Live implementation (provider-agnostic): send prompts.DEBUG_AGENT_SYSTEM +
    debug_agent_user to the configured LLM, requesting JSON that matches
    DEBUG_AGENT_INJECTION_SCHEMA (use the provider's JSON-schema / structured-
    output mode if available, otherwise instruct the model to return JSON), parse
    into an Injection, run validate_injection, and wrap with the model's
    self-reported confidence. `llm_complete` is a thin adapter over whichever
    provider is chosen (Groq, NVIDIA NIM, an OpenAI-compatible endpoint, ...):

        from ai_agents import prompts
        raw = llm_complete(
            model=prompts.REASONING_MODEL,
            system=prompts.DEBUG_AGENT_SYSTEM,
            user=prompts.debug_agent_user(
                instruction=instruction,
                trace_summary=prompts.summarize_trace_for_prompt(trace)),
            json_schema=prompts.DEBUG_AGENT_INJECTION_SCHEMA,
        )
        data = json.loads(raw)
        inj = Injection(step_id=data["step_id"], target=data["target"], value=data["value"])
        validate_injection(trace, inj)
        return wrap(inj, data["confidence"], data["rationale"])
    """
    raise NotImplementedError("wire the LLM call (prompt + schema drafted in prompts.py)")
