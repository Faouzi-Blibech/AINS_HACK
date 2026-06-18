"""The C <-> B contract for perturbation and divergence.

The AI analysis layer never replays anything itself. Whenever it needs to
ask "what would have happened if step N had produced a different output?" it
goes through this interface, which the replay_engine module implements with
real deterministic replay (side-effecting calls always mocked, counter stays 0).

Three AI components consume this contract:
  - root_cause   : perturb each ancestor of the failed step, see if the failure resolves.
  - counterfactual: replay N reworded prompt variants from the fork point.
  - debug_agent  : fire a single user-authored injection and diff the result.

This defines the contract. `ScriptedReplay` in root_cause.py is a deterministic
stand-in so the blame graph runs end to end against the sample fixture before
the real Replayer exists; swap it for replay_engine.Replayer with no change to
the algorithm.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

# Where an injection edits a step. Matches the blob fields in the trace schema:
#   prompt -> prompt_blob   response -> response_blob   (llm_call)
#   args   -> args_blob      result  -> result_blob     (tool_call)
InjectionTarget = str  # "prompt" | "response" | "args" | "result"


@dataclass
class Injection:
    """A single edit applied to one step before/at replay.

    Identical in shape to the `injection` field of the /diverge API request
    (api_contract_sketch.DivergeRequest) and to debug_agent's output, so the
    blame graph, the debug agent, and the divergence endpoint all speak one
    language. Editing a step changes the call's identity, so B forks a new
    branch from `step_id` and continues from there.
    """

    step_id: int
    target: InjectionTarget
    value: Any
    note: str | None = None


@dataclass
class ReplayOutcome:
    """The result B returns for a replay (with or without an injection).

    `key_outputs` carries the semantically interesting outputs (e.g. the team a
    ticket was assigned to) so the semantic matcher can judge behavioral
    equivalence without re-reading every blob.
    """

    run_id: str
    final_status: str  # "ok" | "error"
    failed_step_id: int | None = None
    side_effect_count: int = 0  # invariant: MUST stay 0 on replay
    key_outputs: dict[str, Any] = field(default_factory=dict)
    replay_run_id: str | None = None  # set when the injection forked a branch


@runtime_checkable
class ReplayEngine(Protocol):
    """What the replay_engine.Replayer must expose for the AI layer.

    Both methods must guarantee side_effect_count == 0: replay never touches a
    live endpoint, and side_effecting calls are always mocked.
    """

    def replay(self, run_id: str) -> ReplayOutcome:
        """Deterministically replay the recorded run as-is (the baseline)."""
        ...

    def replay_with_injection(self, run_id: str, injection: Injection) -> ReplayOutcome:
        """Fork at injection.step_id with the edit applied; replay onward."""
        ...


# Judges whether a perturbed replay resolved the original failure. Backed by the
# semantic matcher in production (so "assigned to Backend Engineers" and "routed
# to backend" count as the same outcome); a cheap status check is the default.
OutcomeComparator = Callable[[ReplayOutcome, ReplayOutcome], bool]


def default_failure_resolved(baseline: ReplayOutcome, perturbed: ReplayOutcome) -> bool:
    """Stand-in for the semantic matcher: the baseline failed and the perturbed run did not."""
    return baseline.final_status != "ok" and perturbed.final_status == "ok"
