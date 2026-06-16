"""Semantic matcher.

Compares two agent outputs that may express the same intent in different words
("routed to backend" vs "assigned to Backend Engineers"). Exact-string matching
fails on non-deterministic agents, so equivalence is judged by an LLM. Also used
to score replay fidelity and the determinism-rate metric.

Skeleton only.
"""
from __future__ import annotations


class MatchResult:
    """equivalent: bool, score: float (0..1), confidence: float, rationale: str."""


def match(expected: str, actual: str) -> MatchResult:
    """Judge whether actual is semantically equivalent to expected."""
    raise NotImplementedError
