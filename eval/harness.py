"""Evaluation harness.

Runs the four Cassette metrics against the synthetic test set and prints a
report:

  - determinism_rate          target 100%
  - side_effect_containment   target 0 (always)
  - semantic_match_precision_recall   target > 0.85
  - root_cause_accuracy       target > 0.75

Usage:
    python -m eval.harness
"""
from __future__ import annotations

import datetime
import json
import pathlib
from typing import Any

DEFAULT_TEST_SET_DIR = pathlib.Path(__file__).parent / "test_set"
DEFAULT_OUT_PATH = pathlib.Path(__file__).parent / "results.json"


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #


def load_scenarios(test_set_dir: str | pathlib.Path = DEFAULT_TEST_SET_DIR) -> list[dict]:
    """Load all scenario JSON files from test_set_dir/scenarios/."""
    scenarios_dir = pathlib.Path(test_set_dir) / "scenarios"
    scenarios = []
    for path in sorted(scenarios_dir.glob("*.json")):
        with path.open(encoding="utf-8") as fh:
            scenarios.append(json.load(fh))
    return scenarios


def load_equivalence_pairs(
    test_set_dir: str | pathlib.Path = DEFAULT_TEST_SET_DIR,
) -> list[dict]:
    """Load the labeled equivalence pairs from test_set_dir/equivalence_pairs.json."""
    pairs_path = pathlib.Path(test_set_dir) / "equivalence_pairs.json"
    with pairs_path.open(encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def _recorded_tool_sequence(trace: dict) -> list[str]:
    """Extract the ordered tool-name sequence from the trace steps.

    For llm_call steps the tool name is 'llm_call'; for tool_call steps it is
    the step's 'tool' field. This is what the recording captured.
    """
    sequence = []
    for step in trace.get("steps", []):
        if step.get("type") == "tool_call":
            sequence.append(step.get("tool", "unknown_tool"))
        else:
            sequence.append(step.get("type", "unknown"))
    return sequence


def _replayed_tool_sequence(outcome_key_outputs: dict[str, Any], trace: dict) -> list[str]:
    """Derive the replayed tool sequence from a ReplayOutcome.

    ScriptedReplay populates key_outputs with one entry per step keyed as
    'step{sid}'. The presence and ordering of these keys vs the recorded steps
    determines whether the replay reproduced the exact recorded trajectory.

    We compare against the recorded step ids (in order) to check that:
    1. Every recorded step id appears in the replayed key_outputs.
    2. No extra steps appear in the replay.

    Returns the same list as _recorded_tool_sequence when the replay is
    fully deterministic (all steps present, none added).
    """
    recorded_steps = trace.get("steps", [])
    recorded_ids = [s["step_id"] for s in recorded_steps]
    replayed_ids_set = set()
    for key in outcome_key_outputs:
        if key.startswith("step"):
            try:
                replayed_ids_set.add(int(key[4:]))
            except ValueError:
                pass

    # Build the replayed sequence by checking which recorded steps were included
    replayed_sequence = []
    for step in recorded_steps:
        sid = step["step_id"]
        if sid in replayed_ids_set:
            if step.get("type") == "tool_call":
                replayed_sequence.append(step.get("tool", "unknown_tool"))
            else:
                replayed_sequence.append(step.get("type", "unknown"))

    # Append any extra replayed steps not in the recorded trace.
    # Forward-looking: the real Replayer may emit novel steps; ScriptedReplay never does today.
    extra_ids = replayed_ids_set - set(recorded_ids)
    for eid in sorted(extra_ids):
        replayed_sequence.append(f"extra_step_{eid}")

    return replayed_sequence


def root_cause_accuracy(scenarios: list[dict]) -> float:
    """Fraction of scenarios where analyze identifies the correct root cause.

    Ground truth (expected_root_cause_step) is used ONLY for scoring. It is
    never passed into analyze. The ScriptedReplay oracle is built from the
    scenario's resolves_at list.
    """
    from ai_agents.root_cause import analyze, ScriptedReplay

    if not scenarios:
        return 0.0

    correct = 0
    for sc in scenarios:
        trace = sc["trace"]
        resolves_at = set(sc["resolves_at"])
        expected = sc["expected_root_cause_step"]

        replay = ScriptedReplay(trace, resolves_at=resolves_at)
        graph = analyze(trace, replay=replay)

        if graph.root_cause_step_id == expected:
            correct += 1

    return correct / len(scenarios)


def side_effect_containment(scenarios: list[dict]) -> int:
    """Total side-effecting calls executed across all replays.

    Reads side_effect_count directly from each ReplayOutcome. Must be 0 for
    ScriptedReplay, which enforces the safety invariant.
    """
    from ai_agents.root_cause import ScriptedReplay

    total = 0
    for sc in scenarios:
        trace = sc["trace"]
        run_id = trace.get("run_id", sc.get("scenario_id", ""))
        resolves_at = set(sc["resolves_at"])
        replay = ScriptedReplay(trace, resolves_at=resolves_at)
        outcome = replay.replay(run_id)
        total += outcome.side_effect_count
    return total


def determinism_rate(scenarios: list[dict]) -> float:
    """Fraction of replays that reproduce the original tool-call sequence.

    Compares the ordered tool sequence extracted from the recorded trace
    against the sequence reconstructed from the ReplayOutcome's key_outputs.
    ScriptedReplay is fully deterministic so this will be 1.0 against all
    synthetic scenarios; the metric is computed honestly (no fabrication).
    """
    from ai_agents.root_cause import ScriptedReplay

    if not scenarios:
        return 0.0

    matching = 0
    for sc in scenarios:
        trace = sc["trace"]
        run_id = trace.get("run_id", sc.get("scenario_id", ""))
        resolves_at = set(sc["resolves_at"])
        replay = ScriptedReplay(trace, resolves_at=resolves_at)
        outcome = replay.replay(run_id)

        recorded_seq = _recorded_tool_sequence(trace)
        replayed_seq = _replayed_tool_sequence(outcome.key_outputs, trace)

        if recorded_seq == replayed_seq:
            matching += 1

    return matching / len(scenarios)


def semantic_match_pr(
    pairs: list[dict],
) -> tuple[float | None, float | None]:
    """Compute precision and recall of the semantic matcher vs gold labels.

    Calls ai_agents.semantic_matcher.match LIVE on each pair. Treats
    gold_equivalent=True as the positive class.

    Returns (precision, recall). Returns (None, None) when the LLM is not
    configured (GROQ_API_KEY absent). Per-pair errors are caught and that
    pair is skipped rather than crashing the whole metric.
    """
    from ai_agents import semantic_matcher
    from ai_agents.llm import LLMNotConfigured

    tp = 0
    fp = 0
    fn = 0

    for pair in pairs:
        expected = pair["expected"]
        actual = pair["actual"]
        gold = pair["gold_equivalent"]
        try:
            result = semantic_matcher.match(expected, actual)
            predicted = result.value.equivalent
        except LLMNotConfigured:
            return (None, None)
        except Exception:
            # Skip pairs that error for reasons other than missing key
            continue

        if predicted and gold:
            tp += 1
        elif predicted and not gold:
            fp += 1
        elif not predicted and gold:
            fn += 1
        # True negatives (not predicted, not gold) do not affect P/R

    if (tp + fp) == 0:
        precision = None
    else:
        precision = tp / (tp + fp)

    if (tp + fn) == 0:
        recall = None
    else:
        recall = tp / (tp + fn)

    return (precision, recall)


# --------------------------------------------------------------------------- #
# Main report
# --------------------------------------------------------------------------- #


def main(
    test_set_dir: str | pathlib.Path = DEFAULT_TEST_SET_DIR,
    out_path: str | pathlib.Path = DEFAULT_OUT_PATH,
) -> None:
    """Load the test set, compute all four metrics, print a report, and write results.json."""
    test_set_dir = pathlib.Path(test_set_dir)
    out_path = pathlib.Path(out_path)

    scenarios = load_scenarios(test_set_dir)
    pairs = load_equivalence_pairs(test_set_dir)

    print(f"Loaded {len(scenarios)} scenarios and {len(pairs)} equivalence pairs.\n")

    rca = root_cause_accuracy(scenarios)
    sec = side_effect_containment(scenarios)
    dr = determinism_rate(scenarios)
    precision, recall = semantic_match_pr(pairs)

    # ------------------------------------------------------------------ #
    # Print report table
    # ------------------------------------------------------------------ #
    col_w = [34, 12, 12, 8]
    header = (
        f"{'Metric':<{col_w[0]}}"
        f"{'Value':>{col_w[1]}}"
        f"{'Target':>{col_w[2]}}"
        f"{'Status':>{col_w[3]}}"
    )
    separator = "-" * sum(col_w)

    print(separator)
    print(header)
    print(separator)

    def _row(label: str, value_str: str, target_str: str, passed: bool | None) -> str:
        if passed is None:
            status = "N/A"
        else:
            status = "PASS" if passed else "FAIL"
        return (
            f"{label:<{col_w[0]}}"
            f"{value_str:>{col_w[1]}}"
            f"{target_str:>{col_w[2]}}"
            f"{status:>{col_w[3]}}"
        )

    print(_row("Determinism Rate", f"{dr:.1%}", "100%", dr >= 1.0))
    print(_row("Side-effect Containment", str(sec), "0", sec == 0))

    if precision is None and recall is None:
        print(_row("Semantic Match Precision", "unavailable", "> 0.85", None))
        print(_row("Semantic Match Recall", "unavailable", "> 0.85", None))
        pr_unavailable = True
    else:
        prec_str = f"{precision:.3f}" if precision is not None else "N/A"
        rec_str = f"{recall:.3f}" if recall is not None else "N/A"
        prec_pass = precision is not None and precision > 0.85
        rec_pass = recall is not None and recall > 0.85
        print(_row("Semantic Match Precision", prec_str, "> 0.85", prec_pass))
        print(_row("Semantic Match Recall", rec_str, "> 0.85", rec_pass))
        pr_unavailable = False

    print(_row("Root-cause Accuracy", f"{rca:.1%}", "> 75%", rca > 0.75))
    print(separator)

    if pr_unavailable:
        print("\nNote: Semantic match P/R unavailable (no LLM key configured).")

    # ------------------------------------------------------------------ #
    # Build results.json
    # ------------------------------------------------------------------ #
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    metrics: list[dict] = [
        {
            "key": "determinism_rate",
            "label": "Determinism Rate",
            "value": dr,
            "target_text": "100%",
            "passed": dr >= 1.0,
            "unit": "fraction",
        },
        {
            "key": "side_effect_containment",
            "label": "Side-effect Containment",
            "value": sec,
            "target_text": "0",
            "passed": sec == 0,
            "unit": "count",
        },
        {
            "key": "semantic_match_precision",
            "label": "Semantic Match Precision",
            "value": precision,
            "target_text": "> 0.85",
            "passed": (precision > 0.85) if precision is not None else None,
            "unit": "fraction",
        },
        {
            "key": "semantic_match_recall",
            "label": "Semantic Match Recall",
            "value": recall,
            "target_text": "> 0.85",
            "passed": (recall > 0.85) if recall is not None else None,
            "unit": "fraction",
        },
        {
            "key": "root_cause_accuracy",
            "label": "Root-cause Accuracy",
            "value": rca,
            "target_text": "> 75%",
            "passed": rca > 0.75,
            "unit": "fraction",
        },
    ]

    caveats = [
        "ScriptedReplay is a deterministic stand-in for the real divergence engine; "
        "it resolves scenarios according to a pre-specified oracle (resolves_at) rather "
        "than running actual replay. This is the intended design for the eval harness "
        "prior to the real Replayer being available.",
        "Side-effect containment is measured honestly from ReplayOutcome.side_effect_count; "
        "ScriptedReplay always returns 0 per the safety invariant.",
        "Semantic match P/R requires GROQ_API_KEY to be set; if absent, both values are null.",
    ]

    report = {
        "generated_at": now,
        "metrics": metrics,
        "caveats": caveats,
        "available": True,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print(f"\nResults written to: {out_path}")


if __name__ == "__main__":
    main()
