"""Confidence / self-evaluation wrapper.

Every AI output in Cassette carries an uncertainty score and a short rationale;
low-confidence outputs are flagged for human review. Explainability is 15% of
the score, so this is not optional decoration: it is how the system says "I am
not sure" instead of asserting blindly.

Design
------
Every AI component (matcher, blame graph, debug agent, counterfactual) returns
its payload wrapped in `AIResult`, never a bare value. The wrapper standardizes
three things across all five components:
  - confidence : float in [0, 1]
  - rationale  : one short human-readable sentence (the "why")
  - needs_review: True when confidence < REVIEW_THRESHOLD

Where confidence comes from (per component):
  - LLM self-report : ask the model to emit a confidence field in structured output.
  - margin          : gap between the top candidate and the runner-up (matcher, counterfactual).
  - agreement       : run the judgment twice; agreement raises confidence.
The wrapper does not care which; it just standardizes the envelope.

This module is pure Python and runnable today; the LLM-backed components plug
their scores into it as they come online.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

# Below this, surface the result for human review rather than acting on it.
REVIEW_THRESHOLD = 0.6


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


@dataclass
class AIResult(Generic[T]):
    """An AI output plus its self-assessed confidence and rationale."""

    value: T
    confidence: float
    rationale: str
    needs_review: bool

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "needs_review": self.needs_review,
        }


def wrap(
    value: T,
    confidence: float,
    rationale: str = "",
    *,
    threshold: float = REVIEW_THRESHOLD,
) -> AIResult[T]:
    """Wrap a raw AI output with a clamped confidence and a review flag."""
    c = _clamp01(confidence)
    return AIResult(value=value, confidence=c, rationale=rationale, needs_review=c < threshold)


def from_margin(
    value: T,
    top_score: float,
    runner_up_score: float,
    rationale: str = "",
    *,
    threshold: float = REVIEW_THRESHOLD,
) -> AIResult[T]:
    """Derive confidence from how decisively the top candidate beat the runner-up.

    Used by ranking-style components (semantic matcher, counterfactual): a clear
    winner is high-confidence; a near-tie is flagged for review.
    """
    margin = _clamp01(top_score - runner_up_score)
    return wrap(value, margin, rationale, threshold=threshold)


def combine(*results: AIResult) -> float:
    """Aggregate confidence across a pipeline of AI steps (weakest-link).

    A verdict is only as trustworthy as its least-confident input, so the
    pipeline confidence is the minimum of its parts.
    """
    if not results:
        return 0.0
    return min(r.confidence for r in results)
