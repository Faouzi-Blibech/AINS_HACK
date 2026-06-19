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

import json
from dataclasses import dataclass, field
from typing import Callable

import ai_agents.confidence as confidence
from ai_agents import llm
from ai_agents import prompts
from ai_agents import trace_content
from ai_agents.llm import LLMNotConfigured
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

    def as_ai_result(self) -> confidence.AIResult:
        """Wrap the verdict with confidence using the standard AIResult envelope.

        Downstream code gets {value, confidence, rationale, needs_review} and
        the needs_review flag is driven by confidence.REVIEW_THRESHOLD.
        """
        rationale = (
            f"Blame graph confidence {self.confidence:.2f}: "
            + (
                "single clear resolver identified."
                if self.confidence >= confidence.REVIEW_THRESHOLD
                else "multiple resolvers or none found; flagged for review."
            )
        )
        return confidence.wrap(self.verdict, self.confidence, rationale=rationale)


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


def _causal_descendants(trace: dict, step_id: int) -> set[int]:
    """All steps that are transitively downstream of `step_id`.

    Mirrors causal_ancestors but walks downward: a step D is a descendant of N
    if N appears in D's transitive causal_parents chain.
    """
    by_id = _steps_by_id(trace)
    # Build a children map (inverse of causal_parents)
    children: dict[int, list[int]] = {sid: [] for sid in by_id}
    for sid, step in by_id.items():
        for parent in step.get("causal_parents", []):
            if parent in children:
                children[parent].append(sid)

    descendants: set[int] = set()
    stack = list(children.get(step_id, []))
    while stack:
        cur = stack.pop()
        if cur in descendants:
            continue
        descendants.add(cur)
        stack.extend(children.get(cur, []))
    return descendants


def _injection_target(step: dict) -> str:
    """Which output of a step a corrective injection edits."""
    return "response" if step.get("type") == "llm_call" else "result"


def _divergence(baseline_outputs: dict, perturbed_outputs: dict) -> float:
    """Fraction of keys whose value differs between baseline and perturbed outputs.

    Returns 0.0 if either side has no key_outputs (no signal to measure).

    Note: assumes both outcomes report the same key set (true for ScriptedReplay).
    When replay_engine.Replayer lands, keys added or dropped by the replay will
    also count as differing.
    """
    if not baseline_outputs or not perturbed_outputs:
        return 0.0
    all_keys = set(baseline_outputs) | set(perturbed_outputs)
    if not all_keys:
        return 0.0
    differing = sum(
        1 for k in all_keys if baseline_outputs.get(k) != perturbed_outputs.get(k)
    )
    return differing / len(all_keys)


# --------------------------------------------------------------------------- #
# The blame graph
# --------------------------------------------------------------------------- #


def analyze(
    trace: dict,
    failed_step_id: int | None = None,
    *,
    replay: ReplayEngine,
    failure_resolved: OutcomeComparator | None = None,
    content_resolver: Callable[[dict], str] | None = None,
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
    content_resolver
        Optional callable ``step -> str`` (e.g. from
        ``ai_agents.trace_content.make_resolver``). When provided, each
        step's rationale is extended with the resolver's output:
        ``"<tier_rationale> | <content_resolver(step)>"``. When None
        (the default), rationales are exactly the tier strings and all
        existing behaviour is preserved byte-for-byte.
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
        div = _divergence(baseline.key_outputs, outcome.key_outputs)

        if did_resolve:
            blame_score = 1.0
            rationale = "root cause: correcting this step's output resolves the failure"
        elif div > 0:
            blame_score = round(0.2 + 0.4 * div, 3)
            rationale = (
                "contributor: perturbing this step changes the downstream trajectory "
                "but does not resolve the failure"
            )
        else:
            blame_score = 0.0
            rationale = "innocent: perturbing this step does not change the outcome"

        if content_resolver is not None:
            rationale = f"{rationale} | {content_resolver(step)}"

        scores.append(BlameStepScore(sid, blame_score, rationale))
        if did_resolve:
            resolving.append(sid)

    # Root cause = the upstream-most step whose correction prevents the failure.
    root = min(resolving) if resolving else None

    if root is None:
        verdict = f"Step {failed_step_id} failed; no single upstream step explains it."
        conf = 0.3
    else:
        verdict = f"Step {failed_step_id} is where it failed. Step {root} is why."
        # Confident when exactly one step resolves it; ambiguous when several do.
        conf = 0.9 if len(resolving) == 1 else 0.5

    scores.sort(key=lambda s: s.step_id)
    return BlameGraph(run_id, failed_step_id, root, verdict, conf, scores)


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

    key_outputs are populated to enable the divergence signal:
    - Baseline: one entry per step with a stable signature.
    - Injection at step N: N and all transitive descendants change to a
      different signature; all other steps keep the baseline signature.

    Replace with replay_engine.Replayer (same ReplayEngine protocol).
    """

    def __init__(self, trace: dict, resolves_at: set[int] | frozenset[int] = frozenset()):
        self._trace = trace
        self._run_id = trace.get("run_id", "")
        self._resolves_at = set(resolves_at)
        self._failed = infer_failed_step(trace)
        # Cache all step ids for key_outputs population
        self._all_step_ids: list[int] = [
            s["step_id"] for s in trace.get("steps", [])
        ]

    def _baseline_key_outputs(self) -> dict[str, str]:
        return {f"step{sid}": "<baseline>" for sid in self._all_step_ids}

    def _descendants_of(self, step_id: int) -> set[int]:
        return _causal_descendants(self._trace, step_id)

    def replay(self, run_id: str) -> ReplayOutcome:
        return ReplayOutcome(
            run_id=run_id,
            final_status="error" if self._failed is not None else "ok",
            failed_step_id=self._failed,
            side_effect_count=0,
            key_outputs=self._baseline_key_outputs(),
        )

    def replay_with_injection(self, run_id: str, injection: Injection) -> ReplayOutcome:
        n = injection.step_id
        fixed = n in self._resolves_at
        # Build perturbed key_outputs: N and its descendants use a different signature
        descendants = self._descendants_of(n)
        changed_steps = {n} | descendants
        perturbed_outputs = {
            f"step{sid}": (
                f"perturbed@{n}" if sid in changed_steps else "<baseline>"
            )
            for sid in self._all_step_ids
        }
        return ReplayOutcome(
            run_id=run_id,
            final_status="ok" if fixed else "error",
            failed_step_id=None if fixed else self._failed,
            side_effect_count=0,
            key_outputs=perturbed_outputs,
            replay_run_id=f"{run_id}-fork@{n}",
        )


# --------------------------------------------------------------------------- #
# LLM-phrased verdict (additive; does not change analyze's default behavior)
# --------------------------------------------------------------------------- #


def verdict_via_llm(
    graph: BlameGraph,
    trace: dict,
    *,
    content_resolver: Callable[[dict], str] | None = None,
) -> confidence.AIResult:
    """Phrase a root-cause verdict by calling the LLM.

    The deterministic blame graph (from ``analyze``) supplies the structure;
    the LLM turns it into a human verdict with rationale and calibrated
    confidence.

    Parameters
    ----------
    graph:
        The ``BlameGraph`` produced by ``analyze``.
    trace:
        The trace document (same dict passed to ``analyze``).
    content_resolver:
        Optional ``step -> str`` callable (e.g. from
        ``ai_agents.trace_content.make_resolver``). When provided, each
        step summary is the resolver's output; otherwise
        ``trace_content.describe_step`` is used (structural, no blobs).

    Returns
    -------
    AIResult[str]
        The LLM-phrased verdict wrapped in the confidence envelope.

    Raises
    ------
    (never) -- on ``LLMNotConfigured`` falls back to
    ``graph.as_ai_result()`` (the deterministic verdict).
    """
    by_id: dict[int, dict] = {s["step_id"]: s for s in trace.get("steps", [])}
    blame_scores: dict[int, float] = {s.step_id: s.blame_score for s in graph.steps}

    if content_resolver is not None:
        step_summaries: dict[int, str] = {
            sid: content_resolver(by_id[sid])
            for sid in blame_scores
            if sid in by_id
        }
    else:
        step_summaries = {
            sid: trace_content.describe_step(by_id[sid])
            for sid in blame_scores
            if sid in by_id
        }

    try:
        raw = llm.llm_complete(
            system=prompts.ROOT_CAUSE_VERDICT_SYSTEM,
            user=prompts.root_cause_verdict_user(
                failed_step_id=graph.failed_step_id,
                blame_scores=blame_scores,
                step_summaries=step_summaries,
            ),
            model=llm.reasoning_model(),
            json_schema=prompts.ROOT_CAUSE_VERDICT_SCHEMA,
        )
        data = json.loads(raw)
        return confidence.wrap(
            data["verdict"],
            data["confidence"],
            rationale=data["rationale"],
        )
    except (LLMNotConfigured, KeyError, ValueError):
        return graph.as_ai_result()


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
