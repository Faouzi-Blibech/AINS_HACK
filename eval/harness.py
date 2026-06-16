"""Evaluation harness.

Runs the four Cassette metrics against the synthetic test set and prints a
report:

  - determinism_rate          target 100%
  - side_effect_containment   target 0 (always)
  - semantic_match_precision_recall   target > 0.85
  - root_cause_accuracy       target > 0.75

Skeleton only.
"""
from __future__ import annotations


def determinism_rate(results) -> float:
    raise NotImplementedError


def side_effect_containment(results) -> int:
    raise NotImplementedError


def semantic_match_pr(results) -> tuple[float, float]:
    raise NotImplementedError


def root_cause_accuracy(results) -> float:
    raise NotImplementedError


def main() -> None:
    """Load test_set/, run every scenario, compute and print all four metrics."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
