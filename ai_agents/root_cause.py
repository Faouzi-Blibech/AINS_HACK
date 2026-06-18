"""Root-cause analyzer: the Temporal Blame Graph.

Instead of flagging the step that visibly failed, this traces backward through
causal_parents links and assigns a blame score to every prior step by
perturbation:

  1. Find the failed step and its transitive causal ancestors.
  2. For each ancestor N, ask the replay engine to re-run the trace with N's
     output replaced (Injection), everything downstream re-derived, side
     effects mocked.
  3. If perturbing N resolves the failure  -> high blame for N.
     If it changes nothing                 -> blame ~0 (innocent).
  4. The root cause is the upstream-most step whose correction would have
     prevented the failure. Verdict: "Step <failed> is where it failed.
     Step <root> is why."

Attributing blame across an unstructured reasoning trajectory is irreducibly a
reasoning task: the perturbation loop is the mechanism, the semantic matcher
decides "did the failure resolve?", and an LLM phrases the final verdict
(see prompts.ROOT_CAUSE_VERDICT_*).

The algorithm (ancestor walk, perturbation loop, root-cause selection, verdict,
confidence) is real and runs end to end against docs/fixtures/sample_trace.json
using `ScriptedReplay`, a deterministic stand-in for the replay_engine.Replayer
plus the semantic matcher. Pass a real ReplayEngine and a matcher-backed
comparator and nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ai_agents.replay_interface import (
    Injection,
    OutcomeComparator,
    ReplayEngine,
    ReplayOutcome,
    default_failure_resolved,
)


# --------------------------------------------------------------------------- #
# Result types (map 1:1 to api_contract_sketch.BlameGraphResponse)
# --------------------------------------------------------------------------- #


@dataclass
class BlameStepScore:
    step_id: int
    blame_score: float  # 0..1
    rationale: str = ""


@dataclass
class BlameGraph:
    run_id: str
    failed_step_id: int | None
    root_cause_step_id: int | None
    verdict: str
    confidence: float
    steps: list[BlameStepScore] = field(default_factory=list)

    def to_api_dict(self) -> dict:
        """Shape consumed by the /runs/{id}/blame endpoint and the UI."""
        return {
            "run_id": self.run_id,
            "failed_step_id": self.failed_step_id,
            "root_cause_step_id": self.root_cause_step_id,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "steps": [
                {"step_id": s.step_id, "blame_score": s.blame_score, "rationale": s.rationale}
                for s in self.steps
            ],
        }


# --------------------------------------------------------------------------- #
# Causal-graph helpers
# --------------------------------------------------------------------------- #


def _steps_by_id(trace: dict) -> dict[int, dict]:
    return {s["step_id"]: s for s in trace.get("steps", [])}


def infer_failed_step(trace: dict) -> int | None:
    """The visibly-failed step: the last step whose status is an error."""
    failed = [s["step_id"] for s in trace.get("steps", []) if s.get("status") == "error"]
    return max(failed) if failed else None


def causal_ancestors(trace: dict, step_id: int) -> list[int]:
    """All steps that transitively fed into `step_id`, via causal_parents."""
    by_id = _steps_by_id(trace)
    seen: set[int] = set()
    stack = list(by_id.get(step_id, {}).get("causal_parents", []))
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in by_id:
            continue
        seen.add(cur)
        stack.extend(by_id[cur].get("causal_parents", []))
    return sorted(seen)


def _injection_target(step: dict) -> str:
    """Which output of a step a corrective injection edits."""
    return "response" if step.get("type") == "llm_call" else "result"


# --------------------------------------------------------------------------- #
# The blame graph
# --------------------------------------------------------------------------- #


def analyze(
    trace: dict,
    failed_step_id: int | None = None,
    *,
    replay: ReplayEngine,
    failure_resolved: OutcomeComparator | None = None,
) -> BlameGraph:
    """Compute the Temporal Blame Graph for a (failed) run.

    Parameters
    ----------
    trace
        A trace document (docs/trace_schema.json shape).
    failed_step_id
        The visibly-failed step. Inferred from status==error if omitted.
    replay
        The deterministic replay engine (or ScriptedReplay).
    failure_resolved
        Judges whether a perturbed replay resolved the failure. Backed by the
        semantic matcher in production; defaults to a status comparison.
    """
    run_id = trace.get("run_id", "")
    resolved = failure_resolved or default_failure_resolved
    by_id = _steps_by_id(trace)

    if failed_step_id is None:
        failed_step_id = infer_failed_step(trace)
    if failed_step_id is None:
        return BlameGraph(run_id, None, None, "Run did not fail; nothing to attribute.", 0.0, [])

    baseline = replay.replay(run_id)
    candidates = causal_ancestors(trace, failed_step_id)

    scores: list[BlameStepScore] = []
    resolving: list[int] = []
    for sid in candidates:
        step = by_id[sid]
        injection = Injection(
            step_id=sid,
            target=_injection_target(step),
            value="<neutralized>",  # symbolic; real value comes from the matcher/debug agent
            note="blame-graph perturbation",
        )
        outcome: ReplayOutcome = replay.replay_with_injection(run_id, injection)
        did_resolve = resolved(baseline, outcome)
        # Scoring is currently binary (resolves / does not). The richer version
        # grades blame by how much the downstream trajectory diverges.
        score = 1.0 if did_resolve else 0.0
        rationale = (
            "correcting this step's output resolves the failure"
            if did_resolve
            else "perturbing this step does not change the outcome"
        )
        scores.append(BlameStepScore(sid, score, rationale))
        if did_resolve:
            resolving.append(sid)

    # Root cause = the upstream-most step whose correction prevents the failure.
    root = min(resolving) if resolving else None

    if root is None:
        verdict = f"Step {failed_step_id} failed; no single upstream step explains it."
        confidence = 0.3
    else:
        verdict = f"Step {failed_step_id} is where it failed. Step {root} is why."
        # Confident when exactly one step resolves it; less so when several do.
        confidence = 0.9 if len(resolving) == 1 else 0.6

    scores.sort(key=lambda s: s.step_id)
    return BlameGraph(run_id, failed_step_id, root, verdict, confidence, scores)


# --------------------------------------------------------------------------- #
# Deterministic stand-in for the replay engine + matcher
# --------------------------------------------------------------------------- #


class ScriptedReplay:
    """A deterministic ReplayEngine stand-in.

    Models the sample fixture without any LLM or live replay: the baseline
    reproduces the recorded failure, and injecting at a step in `resolves_at`
    flips the run to success. This lets the blame-graph algorithm run and be
    tested end to end before the real Replayer and matcher exist. It always
    reports side_effect_count == 0, honoring the core safety invariant.

    Replace with replay_engine.Replayer (same ReplayEngine protocol).
    """

    def __init__(self, trace: dict, resolves_at: set[int] | frozenset[int] = frozenset()):
        self._trace = trace
        self._run_id = trace.get("run_id", "")
        self._resolves_at = set(resolves_at)
        self._failed = infer_failed_step(trace)

    def replay(self, run_id: str) -> ReplayOutcome:
        return ReplayOutcome(
            run_id=run_id,
            final_status="error" if self._failed is not None else "ok",
            failed_step_id=self._failed,
            side_effect_count=0,
        )

    def replay_with_injection(self, run_id: str, injection: Injection) -> ReplayOutcome:
        fixed = injection.step_id in self._resolves_at
        return ReplayOutcome(
            run_id=run_id,
            final_status="ok" if fixed else "error",
            failed_step_id=None if fixed else self._failed,
            side_effect_count=0,
            replay_run_id=f"{run_id}-fork@{injection.step_id}",
        )


if __name__ == "__main__":  # runnable demo against the sample fixture
    import json
    import pathlib

    fixture = (
        pathlib.Path(__file__).resolve().parents[1] / "docs" / "fixtures" / "sample_trace.json"
    )
    trace = json.loads(fixture.read_text(encoding="utf-8"))

    # Demo oracle: in the fixture, step 2 (get_priority, ambiguous priority) is
    # the seeded root cause; correcting it resolves the downstream failure.
    replay = ScriptedReplay(trace, resolves_at={2})
    graph = analyze(trace, replay=replay)

    print(json.dumps(graph.to_api_dict(), indent=2))
