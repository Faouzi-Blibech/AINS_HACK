"""Draft LLM prompts for the AI analysis layer.

Three prompts live here; they are the load-bearing "AI is the mechanism" surface:

  1. EQUIVALENCE_JUDGE  - the semantic matcher's core question, also used inside
     the blame loop to decide whether a perturbed replay resolved the failure.
  2. ROOT_CAUSE_VERDICT - turns raw per-step blame scores into the human verdict
     ("Step 8 is where it failed. Step 2 is why.") + rationale + confidence.
  3. DEBUG_AGENT_INJECTION - turns plain English into a structurally valid
     injection (the clearest proof the LLM is load-bearing).

These prompts are provider-agnostic in mechanism: the provider is Groq
(OpenAI-compatible API, open-source models), but nothing here depends on
Groq-specific surface area. Any OpenAI-compatible endpoint with JSON/structured-
output mode is sufficient to run these prompts. Two tiers are referenced: a
stronger model for reasoning (root-cause verdict, debug agent) and a
cheaper/faster one for the high-volume equivalence judge. Where a provider supports structured output (JSON-schema / JSON mode),
pass the matching `*_SCHEMA` so the result is schema-valid by construction;
otherwise instruct the model to return JSON and validate against the schema.
These are drafts to tune against the sample fixture.

Each builder returns (system, user) strings; the caller wraps the response in
confidence.AIResult.
"""
from __future__ import annotations

import json
import os
from typing import Any

from ai_agents.llm import cheap_model, reasoning_model

# Model ids come from the single source of truth in ai_agents.llm; they read
# from environment variables and fall back to the Groq defaults.
REASONING_MODEL = reasoning_model()
CHEAP_MODEL = cheap_model()


# --------------------------------------------------------------------------- #
# 1. Semantic equivalence judge (matcher + blame-loop oracle)
# --------------------------------------------------------------------------- #

EQUIVALENCE_JUDGE_SYSTEM = """\
You judge whether two AI-agent outputs mean the same thing in effect, not \
whether they are textually identical. Agents are non-deterministic, so exact \
string matching is wrong: "routed to backend", "assigned to the Backend \
Engineers queue", and "team=backend" are the same outcome. Different routing \
targets, different tool arguments, or a success vs an error are NOT the same \
outcome.

Judge only the behavior that matters for the task. Ignore wording, ordering, \
formatting, and incidental metadata (timestamps, ids). Report a calibrated \
confidence and a one-sentence rationale. When genuinely unsure, say so with a \
low confidence rather than guessing."""

# Structured-output schema for the judge (pass to the provider's JSON-schema mode).
EQUIVALENCE_JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "equivalent": {"type": "boolean"},
        "score": {"type": "number"},  # 0..1 behavioral-equivalence score
        "confidence": {"type": "number"},  # 0..1 self-assessed certainty
        "rationale": {"type": "string"},
    },
    "required": ["equivalent", "score", "confidence", "rationale"],
    "additionalProperties": False,
}


def equivalence_user(expected: str, actual: str, *, task: str | None = None) -> str:
    """User turn for the equivalence judge."""
    ctx = f"Task the agent was performing: {task}\n\n" if task else ""
    return (
        f"{ctx}EXPECTED outcome:\n{expected}\n\n"
        f"ACTUAL outcome:\n{actual}\n\n"
        "Do these express the same outcome for the task above?"
    )


# --------------------------------------------------------------------------- #
# 2. Root-cause verdict (Temporal Blame Graph -> human sentence)
# --------------------------------------------------------------------------- #

ROOT_CAUSE_VERDICT_SYSTEM = """\
You explain WHY an AI agent run failed, for an engineer who has the trace open. \
You are given: the step that visibly failed, and a per-step blame score \
computed by perturbation (each prior step's output was changed and the run \
re-played; a high score means changing that step's output resolved the \
failure). The visibly-failed step is rarely the cause. Identify the upstream \
root cause: the earliest step whose corrected output would have prevented the \
failure, traced through the causal links.

Be specific and concrete: name the step number, what it did, and the precise \
thing about its output that caused the downstream failure. One tight paragraph. \
End with a single-sentence verdict of the form \
"Step <failed> is where it failed. Step <root> is why." Report a calibrated \
confidence; if the blame scores are diffuse or tied, lower it and say the \
attribution is uncertain."""

ROOT_CAUSE_VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "failed_step_id": {"type": "integer"},
        "root_cause_step_id": {"type": "integer"},
        "verdict": {"type": "string"},
        "rationale": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": [
        "failed_step_id",
        "root_cause_step_id",
        "verdict",
        "rationale",
        "confidence",
    ],
    "additionalProperties": False,
}


def root_cause_verdict_user(
    *,
    failed_step_id: int,
    blame_scores: dict[int, float],
    step_summaries: dict[int, str],
) -> str:
    """User turn: hand the model the failed step, blame scores, and step summaries."""
    lines = [f"Visibly failed step: {failed_step_id}", "", "Per-step blame (step_id: score, summary):"]
    for sid in sorted(step_summaries):
        score = blame_scores.get(sid, 0.0)
        lines.append(f"  step {sid}: blame={score:.2f} | {step_summaries[sid]}")
    lines += ["", "Give the root-cause verdict for this run."]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 3. Debug agent: natural language -> validated injection
# --------------------------------------------------------------------------- #

DEBUG_AGENT_SYSTEM = """\
You convert a plain-English debugging instruction from an engineer into a single \
precise edit (an "injection") to one step of a recorded agent trace. The \
engineer should never hand-edit JSON; that is your job.

Rules:
- Pick exactly the one step the instruction refers to. Use the trace summary to \
resolve references like "the priority step" or "step 2" to a real step_id.
- `target` must match the step type: for an llm_call edit "prompt" or \
"response"; for a tool_call edit "args" or "result". Never set a target the \
step type does not have.
- `value` is the corrected content for that target, expressed the same way the \
recorded value is (a JSON object for args/result, text for prompt/response).
- Do not invent edits the instruction did not ask for. If the instruction is \
ambiguous or names no resolvable step, set confidence low and explain why in \
the rationale instead of guessing.
Report a calibrated confidence and a one-sentence rationale."""

# The injection the model must emit (mirrors replay_interface.Injection and the
# /diverge API). strict structured output guarantees a schema-valid edit.
DEBUG_AGENT_INJECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "step_id": {"type": "integer"},
        "target": {"type": "string", "enum": ["prompt", "response", "args", "result"]},
        "value": {"type": "string"},  # JSON-encoded for args/result; raw text otherwise
        "rationale": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["step_id", "target", "value", "rationale", "confidence"],
    "additionalProperties": False,
}


def debug_agent_user(*, instruction: str, trace_summary: str) -> str:
    """User turn: the engineer's instruction plus a compact trace summary."""
    return (
        "Recorded trace (one line per step):\n"
        f"{trace_summary}\n\n"
        f'Engineer instruction: "{instruction}"\n\n'
        "Produce the single injection that applies this instruction."
    )


def summarize_trace_for_prompt(trace: dict) -> str:
    """Render a trace dict as a compact one-line-per-step summary for prompts.

    Blob refs are shown as-is (the model reasons over structure, not payloads);
    a later pass can resolve key blobs inline when needed.
    """
    lines = []
    for step in trace.get("steps", []):
        sid = step.get("step_id")
        stype = step.get("type")
        label = step.get("tool") or step.get("model") or stype
        parents = step.get("causal_parents", [])
        flags = []
        if step.get("side_effecting"):
            flags.append("side-effecting")
        if step.get("status") and step["status"] != "ok":
            flags.append(step["status"])
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"  step {sid} ({stype}: {label}) parents={parents}{flag_str}")
    return "\n".join(lines)


__all__ = [
    "REASONING_MODEL",
    "CHEAP_MODEL",
    "EQUIVALENCE_JUDGE_SYSTEM",
    "EQUIVALENCE_JUDGE_SCHEMA",
    "equivalence_user",
    "ROOT_CAUSE_VERDICT_SYSTEM",
    "ROOT_CAUSE_VERDICT_SCHEMA",
    "root_cause_verdict_user",
    "DEBUG_AGENT_SYSTEM",
    "DEBUG_AGENT_INJECTION_SCHEMA",
    "debug_agent_user",
    "summarize_trace_for_prompt",
]


if __name__ == "__main__":  # quick visual check of the rendered prompts
    demo = {
        "steps": [
            {"step_id": 1, "type": "llm_call", "model": "<model>", "causal_parents": []},
            {"step_id": 2, "type": "tool_call", "tool": "get_priority", "causal_parents": [1]},
            {"step_id": 3, "type": "tool_call", "tool": "assign_ticket", "causal_parents": [1, 2], "side_effecting": True},
        ]
    }
    print(summarize_trace_for_prompt(demo))
    print("---")
    print(debug_agent_user(instruction="at step 2 priority should be high", trace_summary=summarize_trace_for_prompt(demo)))
    print("---")
    print(json.dumps(DEBUG_AGENT_INJECTION_SCHEMA, indent=2))
