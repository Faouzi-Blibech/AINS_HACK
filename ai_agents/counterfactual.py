"""Counterfactual repair agent.

Once the root cause is identified, this agent generates N reworded variants of
the failing step's prompt, replays each variant from that step onward (side
effects always mocked by the engine, side_effect_count stays 0), and ranks them
by outcome: did the run complete successfully? how many steps changed? cost delta?

Output example: "Variant 2 resolved the failure: an explicit priority-enum
constraint prevented the downstream routing error."

Turns the debugger from a passive observer into an active problem-solver.

All perturbation happens exclusively through the ReplayEngine Protocol defined
in ai_agents.replay_interface. The engine guarantees side_effect_count == 0 on
every ReplayOutcome; this module never touches that field directly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import ai_agents.confidence as confidence
from ai_agents import llm
from ai_agents import prompts
from ai_agents import semantic_matcher
from ai_agents.confidence import AIResult
from ai_agents.llm import LLMNotConfigured
from ai_agents.replay_interface import (
    Injection,
    InjectionTarget,
    OutcomeComparator,
    ReplayEngine,
    ReplayOutcome,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class Variant:
    """A single rephrased prompt variant with its replay outcome and ranking data.

    Attributes
    ----------
    variant_id:
        Unique identifier string for this variant (e.g. "v0", "v1", ...).
    prompt:
        The reworded prompt text that was injected at the failing step.
    outcome:
        The ReplayOutcome returned by the engine after replaying with this
        variant. outcome.side_effect_count is always 0 (engine invariant).
    steps_changed:
        Number of key_outputs that differ from the baseline run. Computed as
        a count of keys whose value differs between baseline.key_outputs and
        outcome.key_outputs.
    cost_delta:
        Estimated cost difference vs the baseline replay. Set to 0.0 when the
        engine does not provide cost information (current default; leave this
        seam here for when the real Replayer exposes token counts).
    resolved:
        True when the comparator decided this variant resolved the failure.
    score:
        Ranking score in [0, 1]. Resolved variants score near 1.0 with small
        penalties for steps_changed and cost_delta. Non-resolved variants score
        near 0.0.
    """

    variant_id: str
    prompt: str
    outcome: ReplayOutcome
    steps_changed: int
    cost_delta: float
    resolved: bool
    score: float


# ---------------------------------------------------------------------------
# Deterministic offline fallback
# ---------------------------------------------------------------------------

_FALLBACK_TEMPLATES = [
    "Be explicit and concrete. {original}",
    "Think step by step before answering. {original}",
    "Validate all inputs and constraints before proceeding. {original}",
    "If any field is ambiguous, treat it as the most restrictive valid option. {original}",
    "Enumerate your assumptions before taking action. {original}",
    "Confirm prerequisites are satisfied before executing. {original}",
    "Return a structured response with each field filled. {original}",
    "When uncertain, ask for clarification rather than guessing. {original}",
]


def _fallback_variants(original_prompt: str, n: int) -> list[str]:
    """Generate n deterministic template-based variants from the original prompt.

    Used when the LLM is not configured or returns unparseable output, so the
    demo still produces ranked output offline.
    """
    variants: list[str] = []
    for i in range(n):
        template = _FALLBACK_TEMPLATES[i % len(_FALLBACK_TEMPLATES)]
        variants.append(template.format(original=original_prompt))
    return variants


# ---------------------------------------------------------------------------
# Default LLM-backed generate function
# ---------------------------------------------------------------------------


def _llm_generate(task: str | None, original_prompt: str, n: int) -> list[str]:
    """Call the LLM to produce n reworded variants of original_prompt.

    On LLMNotConfigured, json.JSONDecodeError, KeyError, or ValueError, raises
    the exception so the caller can fall back to _fallback_variants.
    """
    raw = llm.llm_complete(
        system=prompts.COUNTERFACTUAL_VARIANTS_SYSTEM,
        user=prompts.counterfactual_variants_user(
            task=task,
            original_prompt=original_prompt,
            n=n,
        ),
        model=llm.reasoning_model(),
        json_schema=prompts.COUNTERFACTUAL_VARIANTS_SCHEMA,
    )
    data = json.loads(raw)
    return [str(v) for v in data["variants"]]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

_STEPS_CHANGED_PENALTY = 0.02  # small penalty per changed step
_COST_DELTA_PENALTY = 0.01     # small penalty per unit of cost_delta


def _count_steps_changed(baseline: ReplayOutcome, outcome: ReplayOutcome) -> int:
    """Count key_outputs whose value differs between baseline and the variant outcome."""
    all_keys = set(baseline.key_outputs) | set(outcome.key_outputs)
    return sum(
        1 for k in all_keys
        if baseline.key_outputs.get(k) != outcome.key_outputs.get(k)
    )


def _score(resolved: bool, steps_changed: int, cost_delta: float) -> float:
    """Assign a ranking score to a variant.

    Resolved variants start at 1.0 and receive small penalties.
    Non-resolved variants start at 0.1 to ensure they always rank below resolved ones.
    """
    if resolved:
        raw = 1.0 - steps_changed * _STEPS_CHANGED_PENALTY - cost_delta * _COST_DELTA_PENALTY
        return max(0.5, min(1.0, raw))
    else:
        raw = 0.1 - steps_changed * _STEPS_CHANGED_PENALTY - cost_delta * _COST_DELTA_PENALTY
        return max(0.0, min(0.49, raw))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def repair(
    run_id: str,
    step_id: int,
    *,
    engine: ReplayEngine,
    baseline: ReplayOutcome | None = None,
    task: str | None = None,
    target: InjectionTarget = "prompt",
    n: int = 5,
    comparator: OutcomeComparator | None = None,
    generate: Callable[[str | None, str, int], list[str]] | None = None,
    original_prompt: str | None = None,
) -> AIResult[list[Variant]]:
    """Generate, replay, and rank N fix variants for the failing step.

    Parameters
    ----------
    run_id:
        The run identifier passed to engine.replay / engine.replay_with_injection.
    step_id:
        The step whose prompt is being repaired (Injection.step_id).
    engine:
        A ReplayEngine implementation (real or fake). All replay calls go here;
        side_effect_count == 0 is enforced by the engine, never by this function.
    baseline:
        Optional pre-computed baseline ReplayOutcome. When None, engine.replay(run_id)
        is called once to obtain the baseline. Provide this when the caller already
        has the baseline to avoid a redundant replay call.
    task:
        Optional task description for context (passed to the LLM prompt and the
        semantic-matcher comparator).
    target:
        Which field of the step to inject the variant into (default "prompt").
    n:
        Number of variants to generate and evaluate.
    comparator:
        OutcomeComparator deciding whether a variant resolved the failure.
        Defaults to semantic_matcher.llm_failure_resolved(task=task), which
        falls back to default_failure_resolved when the LLM is not configured.
    generate:
        Injectable seam returning a list[str] of variant prompt texts. Signature:
        ``(task, original_prompt, n) -> list[str]``. When None, the default LLM
        path is used (with offline fallback to template variants on
        LLMNotConfigured, json.JSONDecodeError, KeyError, or ValueError).
    original_prompt:
        The actual text of the failing step's prompt. When provided, this value
        is passed to the generate function (and used in the offline fallback)
        instead of the default placeholder string. Supplying this makes the
        prompt-rewrite seam honest: the LLM rewrites the real prompt rather than
        a bracketed stand-in.

    Returns
    -------
    AIResult[list[Variant]]
        Ranked list of Variant objects wrapped in the confidence envelope.
        The winning variant (index 0) is the one that resolved the failure
        (if any) with the best score. Confidence is derived from the margin
        between the top score and the runner-up score.
    """
    # Resolve defaults
    resolved_comparator: OutcomeComparator = comparator or semantic_matcher.llm_failure_resolved(task=task)

    # Obtain baseline (avoids extra replay call when caller already has it)
    actual_baseline: ReplayOutcome = baseline if baseline is not None else engine.replay(run_id)

    # The original prompt to reword is the injection target value from the baseline.
    # When the caller provides the real prompt text via original_prompt, use it;
    # otherwise fall back to a placeholder so the LLM can still produce useful
    # variants from the task description alone.
    original_prompt_text: str = (
        original_prompt
        if original_prompt is not None
        else f"[original step {step_id} prompt for run {run_id}]"
    )

    # Generate variant texts
    if generate is not None:
        variant_texts = generate(task, original_prompt_text, n)
    else:
        try:
            variant_texts = _llm_generate(task, original_prompt_text, n)
        except (LLMNotConfigured, json.JSONDecodeError, KeyError, ValueError):
            # Offline fallback: deterministic template variants so the demo runs
            # without GROQ_API_KEY.
            variant_texts = _fallback_variants(original_prompt_text, n)

    # Evaluate each variant via the engine
    variants: list[Variant] = []
    for i, text in enumerate(variant_texts):
        inj = Injection(step_id=step_id, target=target, value=text)
        outcome = engine.replay_with_injection(run_id, inj)
        # The engine guarantees side_effect_count == 0; we surface it in the
        # Variant but never fabricate or modify it.
        did_resolve = resolved_comparator(actual_baseline, outcome)
        steps_changed = _count_steps_changed(actual_baseline, outcome)
        # cost_delta seam: set to 0.0 until the real Replayer exposes token counts.
        cost_delta = 0.0
        s = _score(did_resolve, steps_changed, cost_delta)
        variants.append(
            Variant(
                variant_id=f"v{i}",
                prompt=text,
                outcome=outcome,
                steps_changed=steps_changed,
                cost_delta=cost_delta,
                resolved=did_resolve,
                score=s,
            )
        )

    # Rank descending by (resolved, score)
    variants.sort(key=lambda v: (v.resolved, v.score), reverse=True)

    # Confidence from margin between top and runner-up
    top_score = variants[0].score if variants else 0.0
    runner_up_score = variants[1].score if len(variants) > 1 else 0.0
    winner = variants[0] if variants else None

    if winner is not None and winner.resolved:
        rationale = (
            f"Variant {winner.variant_id} resolved the failure: "
            f"prompt '{winner.prompt[:60]}' succeeded with "
            f"{winner.steps_changed} step(s) changed from baseline."
        )
    elif variants:
        rationale = (
            "No variant resolved the failure. "
            f"Best candidate is {winner.variant_id} "
            f"(score {top_score:.2f}); consider trying different repair strategies."
        )
    else:
        rationale = "No variants were generated or evaluated."

    return confidence.from_margin(
        variants,
        top_score,
        runner_up_score,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Optional scripted demo (offline)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    """Scripted offline demo: one variant resolves, prints the ranked verdict."""
    from ai_agents.replay_interface import ReplayOutcome

    DEMO_RUN_ID = "demo-run-001"
    DEMO_STEP_ID = 2

    class _DemoEngine:
        """Minimal fake engine for the offline demo."""

        def replay(self, run_id: str) -> ReplayOutcome:
            return ReplayOutcome(
                run_id=run_id,
                final_status="error",
                failed_step_id=DEMO_STEP_ID,
                side_effect_count=0,
                key_outputs={"team": "unknown"},
            )

        def replay_with_injection(self, run_id: str, injection: Injection) -> ReplayOutcome:
            # Only the third variant (index 2, "v2") resolves the failure.
            resolves = injection.value.startswith("Validate all")
            return ReplayOutcome(
                run_id=run_id,
                final_status="ok" if resolves else "error",
                failed_step_id=None if resolves else DEMO_STEP_ID,
                side_effect_count=0,
                key_outputs={"team": "backend" if resolves else "unknown"},
            )

    engine = _DemoEngine()
    result = repair(
        DEMO_RUN_ID,
        DEMO_STEP_ID,
        engine=engine,
        task="triage support ticket and route to correct team",
        n=5,
    )

    print(f"Confidence: {result.confidence:.2f}")
    print(f"Rationale: {result.rationale}")
    print(f"Needs review: {result.needs_review}")
    print()
    for v in result.value:
        status = "RESOLVED" if v.resolved else "failed"
        print(f"[{v.variant_id}] score={v.score:.3f} {status} | {v.prompt[:80]}")
