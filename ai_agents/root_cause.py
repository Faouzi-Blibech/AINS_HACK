"""Root-cause analyzer: the Temporal Blame Graph.

Instead of flagging the step that visibly failed, this traces backward through
causal_parent links and computes a blame score for every prior step:

  1. Start from the failed step.
  2. For each prior step, run a mini-replay with that step's output perturbed.
  3. If perturbing step N changes the final outcome  -> high blame for N.
  4. If it changes nothing                          -> blame 0 (innocent).

Verdict example: "Step 8 is where it failed. Step 2, which returned an
ambiguous priority, is why." Attributing blame across an unstructured reasoning
trajectory is irreducibly a semantic-reasoning task.

Skeleton only.
"""
from __future__ import annotations


class BlameGraph:
    """Per-step blame scores plus the identified root cause and failure point."""


def analyze(run_id: str, failed_step_id: int) -> BlameGraph:
    """Compute the blame graph for a failed run."""
    raise NotImplementedError
