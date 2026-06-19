"""Semantic matcher.

Compares two agent outputs that may express the same intent in different words
("routed to backend" vs "assigned to Backend Engineers"). Exact-string matching
fails on non-deterministic agents, so equivalence is judged by an LLM. Also used
to score replay fidelity and the determinism-rate metric.

Mocking contract: the LLM is called as ``llm.llm_complete(...)`` (module
attribute), so tests can monkeypatch ``ai_agents.llm.llm_complete`` without
touching the import in this module.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import ai_agents.confidence as confidence
from ai_agents import llm
from ai_agents import prompts
from ai_agents.replay_interface import (
    OutcomeComparator,
    ReplayOutcome,
    default_failure_resolved,
)


@dataclass
class MatchResult:
    """Behavioral equivalence result from the LLM judge.

    Attributes
    ----------
    equivalent:
        True when the LLM judges the two outputs as expressing the same outcome.
    score:
        A 0..1 behavioral-equivalence score (1.0 = identical in effect).
    """

    equivalent: bool
    score: float  # 0..1 behavioral-equivalence score


def match(
    expected: str,
    actual: str,
    *,
    task: str | None = None,
) -> confidence.AIResult[MatchResult]:
    """Judge whether *actual* is semantically equivalent to *expected*.

    Calls the LLM equivalence judge (cheap model, JSON mode) and returns the
    result wrapped in an AIResult envelope.

    Parameters
    ----------
    expected:
        The baseline / reference output string.
    actual:
        The candidate output string to compare.
    task:
        Optional task description for the LLM judge (improves relevance).

    Returns
    -------
    AIResult[MatchResult]
        The equivalence judgment with confidence and rationale.

    Raises
    ------
    LLMNotConfigured
        When GROQ_API_KEY is absent. ``match`` does NOT fall back; callers that
        need offline behavior must catch this themselves (see
        ``llm_failure_resolved``).
    """
    raw = llm.llm_complete(
        system=prompts.EQUIVALENCE_JUDGE_SYSTEM,
        user=prompts.equivalence_user(expected, actual, task=task),
        model=llm.cheap_model(),
        json_schema=prompts.EQUIVALENCE_JUDGE_SCHEMA,
    )
    data = json.loads(raw)
    result = MatchResult(
        equivalent=bool(data["equivalent"]),
        score=float(data["score"]),
    )
    return confidence.wrap(
        result,
        data["confidence"],
        rationale=data["rationale"],
    )


def llm_failure_resolved(*, task: str | None = None) -> OutcomeComparator:
    """Return an LLM-backed OutcomeComparator for ``analyze(..., failure_resolved=...)``.

    The returned comparator returns True (failure resolved) when:
      (a) the baseline run failed (final_status != "ok"), AND
      (b) the perturbed run succeeded (final_status == "ok"), AND
      (c) the LLM judge decides the perturbed key_outputs are NOT equivalent to
          the baseline key_outputs (behavior genuinely changed away from the
          failing pattern).

    When the LLM is not configured (``LLMNotConfigured``), falls back to
    ``default_failure_resolved`` (status comparison only).

    Parameters
    ----------
    task:
        Optional task description passed to the equivalence judge.

    Returns
    -------
    OutcomeComparator
        A ``(baseline, perturbed) -> bool`` callable.
    """

    def _comparator(baseline: ReplayOutcome, perturbed: ReplayOutcome) -> bool:
        # Condition (a) + (b): status check first (cheap, no LLM call needed
        # when the perturbed run is still failing).
        if baseline.final_status == "ok" or perturbed.final_status != "ok":
            return False

        # Condition (c): LLM check -- outputs must NOT be equivalent (if they
        # were equivalent the behavior didn't change, so the failure isn't
        # really resolved in a meaningful way).
        expected_str = json.dumps(baseline.key_outputs, sort_keys=True)
        actual_str = json.dumps(perturbed.key_outputs, sort_keys=True)
        try:
            result = match(expected_str, actual_str, task=task)
            # Failure is resolved when the behaviors are NOT equivalent.
            return not result.value.equivalent
        except (llm.LLMNotConfigured, KeyError, ValueError):
            return default_failure_resolved(baseline, perturbed)

    return _comparator
