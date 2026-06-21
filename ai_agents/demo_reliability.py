"""Demo-reliability harness.

A multi-run statistical harness that exercises the demo-critical AI decisions
against the canonical demo trace and reports per-check reliability rates. This
is the tuning instrument: run it live (with GROQ_API_KEY set) to measure how
reliably each check produces the correct output, then edit prompts and re-run
until the numbers are satisfactory.

When GROQ_API_KEY is absent, all checks are reported as skipped and the process
exits with status 0. Per-call errors that are not LLMNotConfigured count as
either errored (transient HTTP errors after retries) or incorrect (bad LLM
output); they never crash the harness.

Checks exercised
----------------
1. debug_agent.build_injection   - correct when step_id==2 and value contains "high"
2. root_cause.verdict_via_llm    - correct when root_cause_step_id==2 and verdict text
                                   contains "2"
3. counterfactual.repair         - correct when 4 variants returned, at least one
                                   resolved, winner at index 0 exists, no error
4. semantic_matcher.match        - correct when two sub-assertions both hold
                                   (equivalent True for same-intent pair,
                                   equivalent False for different-team pair)

Usage
-----
    python -m ai_agents.demo_reliability

This reads docs/fixtures/sample_trace.json and docs/fixtures/blobs (paths are
anchored to the repo root, resolved relative to this file).
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any, Callable, TypeVar

import httpx

from ai_agents import debug_agent
from ai_agents import counterfactual
from ai_agents import semantic_matcher
from ai_agents.llm import LLMNotConfigured
from ai_agents.root_cause import analyze, verdict_via_llm, ScriptedReplay
from ai_agents.trace_content import make_resolver, resolve_step_content

# ---------------------------------------------------------------------------
# Repo-root anchored paths (mirrors the pattern in recorded_trace.py)
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FIXTURE_PATH = _REPO_ROOT / "docs" / "fixtures" / "sample_trace.json"
_BLOB_DIR = str(_REPO_ROOT / "docs" / "fixtures" / "blobs")

# Step 2 is the get_priority tool_call identified as the root cause.
_ROOT_CAUSE_STEP = 2
_RUN_ID = "run-fixture-001"
_INSTRUCTION = "at step 2, priority should have been high, not medium"

# HTTP status codes that indicate a transient server-side problem.
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503}

# Retry delays in seconds for the backoff helper (2s, 4s, 8s).
_RETRY_DELAYS = (2, 4, 8)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Internal retry helper
# ---------------------------------------------------------------------------


def _with_retry(fn: Callable[[], T]) -> T:
    """Call ``fn()`` and retry up to 3 times on transient HTTP errors.

    Raises the final exception if all retries are exhausted. Any
    ``httpx.HTTPStatusError`` whose ``response.status_code`` is in
    ``_TRANSIENT_STATUS_CODES`` triggers a retry with an increasing sleep
    (2 s, 4 s, 8 s). All other exceptions propagate immediately.
    """
    last_exc: Exception | None = None
    for attempt, delay in enumerate((_RETRY_DELAYS[0],) + _RETRY_DELAYS):
        if attempt > 0:
            # Only the first element is the pre-retry delay; skip it on the
            # first pass so we call fn() immediately.
            pass
        try:
            return fn()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _TRANSIENT_STATUS_CODES:
                last_exc = exc
                if attempt < len(_RETRY_DELAYS):
                    time.sleep(_RETRY_DELAYS[attempt])
                continue
            raise
    assert last_exc is not None
    raise last_exc


def _call_with_retry(fn: Callable[[], T]) -> T:
    """Attempt fn() up to 1 + len(_RETRY_DELAYS) times on transient HTTP errors.

    On the first call, no sleep occurs. On each subsequent retry the sleep
    doubles: 2 s, 4 s, 8 s. If still failing after all retries, re-raises the
    last exception.
    """
    last_exc: Exception | None = None
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            return fn()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _TRANSIENT_STATUS_CODES:
                last_exc = exc
                if attempt < len(_RETRY_DELAYS):
                    time.sleep(_RETRY_DELAYS[attempt])
            else:
                raise
    assert last_exc is not None
    raise last_exc


def _is_transient_http_error(exc: BaseException) -> bool:
    """Return True when exc is an httpx.HTTPStatusError with a transient code."""
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in _TRANSIENT_STATUS_CODES
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def load_demo_trace() -> dict:
    """Read and return the canonical demo trace JSON."""
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _resolve_step2_content(trace: dict) -> str:
    """Return the recorded result content of step 2 as a plain string."""
    by_id = {s["step_id"]: s for s in trace.get("steps", [])}
    step2 = by_id.get(_ROOT_CAUSE_STEP, {})
    content = resolve_step_content(step2, blob_dir=_BLOB_DIR)
    if content:
        result = content.get("result") or content.get("args") or ""
        if isinstance(result, dict):
            return json.dumps(result)
        return str(result)
    return f"[step {_ROOT_CAUSE_STEP} content unavailable]"


def _skipped_record(check: str) -> dict:
    """Return a result record indicating the check was skipped (no LLM key)."""
    return {
        "check": check,
        "correct": 0,
        "total": 0,
        "errored": 0,
        "rate": None,
        "notes": "skipped (no LLM key)",
    }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_debug_agent(trace: dict, runs: int = 5) -> dict:
    """Run debug_agent.build_injection `runs` times and report reliability.

    Correct when:
      - inj.step_id == 2
      - "high" appears (case-insensitive) in the injection value string

    On LLMNotConfigured: return a skipped record.
    Transient HTTP errors after retries: counted as errored (excluded from rate).
    Other per-call errors: count as incorrect with a note.
    """
    correct = 0
    errored = 0
    notes_parts: list[str] = []

    for i in range(runs):
        try:
            result = _call_with_retry(
                lambda: debug_agent.build_injection(trace, _INSTRUCTION)
            )
            inj = result.value
            value_str = str(inj.value) if inj.value is not None else ""
            # Try to parse as JSON to look inside the value field
            try:
                value_data = json.loads(value_str)
                if isinstance(value_data, dict):
                    value_str = json.dumps(value_data)
            except (json.JSONDecodeError, ValueError):
                pass
            step_ok = (inj.step_id == _ROOT_CAUSE_STEP)
            value_ok = ("high" in value_str.lower())
            if step_ok and value_ok:
                correct += 1
            else:
                notes_parts.append(
                    f"run {i + 1}: step_id={inj.step_id} value={value_str[:60]!r}"
                )
        except LLMNotConfigured:
            return _skipped_record("debug_agent")
        except Exception as exc:
            if _is_transient_http_error(exc):
                errored += 1
                notes_parts.append(f"run {i + 1} rate-limited/errored (excluded)")
            else:
                notes_parts.append(f"run {i + 1} error: {type(exc).__name__}: {exc!s:.80}")

    effective = runs - errored
    rate = (correct / effective) if effective > 0 else None
    if errored:
        notes_parts.append(f"{errored} run(s) rate-limited/errored, excluded")

    return {
        "check": "debug_agent",
        "correct": correct,
        "total": runs,
        "errored": errored,
        "rate": rate,
        "notes": "; ".join(notes_parts) if notes_parts else "all correct",
    }


def check_blame_verdict(trace: dict, resolver: Any, runs: int = 5) -> dict:
    """Run root_cause.analyze + verdict_via_llm `runs` times and report reliability.

    Correct when:
      - graph.root_cause_step_id == 2   (deterministic from ScriptedReplay)
      - the LLM verdict text contains "2"

    On LLMNotConfigured: return a skipped record.
    Transient HTTP errors after retries: counted as errored (excluded from rate).
    Other per-call errors: count as incorrect with a note.
    """
    correct = 0
    errored = 0
    notes_parts: list[str] = []

    for i in range(runs):
        try:
            replay = ScriptedReplay(trace, resolves_at={_ROOT_CAUSE_STEP})
            graph = analyze(trace, replay=replay, content_resolver=resolver)

            def _verdict():
                return verdict_via_llm(graph, trace, content_resolver=resolver)

            ai_result = _call_with_retry(_verdict)

            step_ok = (graph.root_cause_step_id == _ROOT_CAUSE_STEP)
            verdict_text = str(ai_result.value)
            verdict_ok = (str(_ROOT_CAUSE_STEP) in verdict_text)

            if step_ok and verdict_ok:
                correct += 1
            else:
                notes_parts.append(
                    f"run {i + 1}: root={graph.root_cause_step_id} verdict={verdict_text[:80]!r}"
                )
        except LLMNotConfigured:
            return _skipped_record("blame_verdict")
        except Exception as exc:
            if _is_transient_http_error(exc):
                errored += 1
                notes_parts.append(f"run {i + 1} rate-limited/errored (excluded)")
            else:
                notes_parts.append(f"run {i + 1} error: {type(exc).__name__}: {exc!s:.80}")

    effective = runs - errored
    rate = (correct / effective) if effective > 0 else None
    if errored:
        notes_parts.append(f"{errored} run(s) rate-limited/errored, excluded")

    return {
        "check": "blame_verdict",
        "correct": correct,
        "total": runs,
        "errored": errored,
        "rate": rate,
        "notes": "; ".join(notes_parts) if notes_parts else "all correct",
    }


def check_counterfactual(trace: dict, runs: int = 5) -> dict:
    """Run counterfactual.repair `runs` times and report reliability.

    Correct when:
      - the AIResult contains exactly 4 variants (n=4)
      - at least one variant has resolved=True
      - variants[0] (the winner) exists
      - no exception was raised

    On LLMNotConfigured: return a skipped record.
    Transient HTTP errors after retries: counted as errored (excluded from rate).
    Other per-call errors: count as incorrect with a note.
    """
    correct = 0
    errored = 0
    notes_parts: list[str] = []
    original_prompt = _resolve_step2_content(trace)

    for i in range(runs):
        try:
            engine = ScriptedReplay(trace, resolves_at={_ROOT_CAUSE_STEP})

            def _repair():
                return counterfactual.repair(
                    _RUN_ID,
                    _ROOT_CAUSE_STEP,
                    engine=engine,
                    target="result",
                    n=4,
                    original_prompt=original_prompt,
                )

            ai_result = _call_with_retry(_repair)
            variants = ai_result.value
            count_ok = (len(variants) == 4)
            has_resolved = any(v.resolved for v in variants)
            winner_ok = (len(variants) > 0)

            if count_ok and has_resolved and winner_ok:
                correct += 1
            else:
                notes_parts.append(
                    f"run {i + 1}: variants={len(variants)} resolved={has_resolved}"
                )
        except LLMNotConfigured:
            return _skipped_record("counterfactual")
        except Exception as exc:
            if _is_transient_http_error(exc):
                errored += 1
                notes_parts.append(f"run {i + 1} rate-limited/errored (excluded)")
            else:
                notes_parts.append(f"run {i + 1} error: {type(exc).__name__}: {exc!s:.80}")

    effective = runs - errored
    rate = (correct / effective) if effective > 0 else None
    if errored:
        notes_parts.append(f"{errored} run(s) rate-limited/errored, excluded")

    return {
        "check": "counterfactual",
        "correct": correct,
        "total": runs,
        "errored": errored,
        "rate": rate,
        "notes": "; ".join(notes_parts) if notes_parts else "all correct",
    }


def check_matcher(runs: int = 5) -> dict:
    """Run semantic_matcher.match `runs` times with two sub-assertions per run.

    Sub-assertion 1: match("assigned to the Backend Engineers queue",
                           "routed to backend") -> equivalent True
    Sub-assertion 2: match("assigned to backend",
                           "assigned to the data team") -> equivalent False

    Both must hold for a run to count as correct.

    On LLMNotConfigured: return a skipped record.
    Transient HTTP errors after retries: counted as errored (excluded from rate).
    Other per-call errors: count as incorrect with a note.
    """
    correct = 0
    errored = 0
    notes_parts: list[str] = []

    for i in range(runs):
        try:
            r1 = _call_with_retry(
                lambda: semantic_matcher.match(
                    "assigned to the Backend Engineers queue",
                    "routed to backend",
                )
            )
            r2 = _call_with_retry(
                lambda: semantic_matcher.match(
                    "assigned to backend",
                    "assigned to the data team",
                )
            )
            sub1_ok = r1.value.equivalent is True
            sub2_ok = r2.value.equivalent is False
            if sub1_ok and sub2_ok:
                correct += 1
            else:
                notes_parts.append(
                    f"run {i + 1}: sub1_equiv={r1.value.equivalent} sub2_equiv={r2.value.equivalent}"
                )
        except LLMNotConfigured:
            return _skipped_record("semantic_matcher")
        except Exception as exc:
            if _is_transient_http_error(exc):
                errored += 1
                notes_parts.append(f"run {i + 1} rate-limited/errored (excluded)")
            else:
                notes_parts.append(f"run {i + 1} error: {type(exc).__name__}: {exc!s:.80}")

    effective = runs - errored
    rate = (correct / effective) if effective > 0 else None
    if errored:
        notes_parts.append(f"{errored} run(s) rate-limited/errored, excluded")

    return {
        "check": "semantic_matcher",
        "correct": correct,
        "total": runs,
        "errored": errored,
        "rate": rate,
        "notes": "; ".join(notes_parts) if notes_parts else "all correct",
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_reliability(runs: int = 5) -> list[dict]:
    """Run all four demo-critical checks and return per-check result records.

    Each record has: check, correct, total, errored, rate (float or None), notes.

    If the very first live LLM call raises LLMNotConfigured, all checks are
    reported as skipped and the list is returned without further calls.
    """
    trace = load_demo_trace()
    resolver = make_resolver(_BLOB_DIR)

    results: list[dict] = []

    # debug_agent is the first check; if it raises LLMNotConfigured we skip all.
    debug_result = check_debug_agent(trace, runs=runs)
    results.append(debug_result)

    if debug_result["total"] == 0 and debug_result["rate"] is None:
        # LLM not available; skip remaining checks without further calls.
        results.append(_skipped_record("blame_verdict"))
        results.append(_skipped_record("counterfactual"))
        results.append(_skipped_record("semantic_matcher"))
        return results

    results.append(check_blame_verdict(trace, resolver, runs=runs))
    results.append(check_counterfactual(trace, runs=runs))
    results.append(check_matcher(runs=runs))

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Print a reliability table and an overall headline to stdout."""
    results = run_reliability()

    print(f"{'Check':<22} {'correct/N':>10}  {'errored':>8}  {'rate':>7}")
    print("-" * 55)

    sum_correct = 0
    sum_effective = 0

    for r in results:
        check = r["check"]
        correct = r["correct"]
        total = r["total"]
        errored = r.get("errored", 0)
        rate = r["rate"]

        errored_str = str(errored) if total > 0 else "-"

        if total == 0 and rate is None:
            rate_str = "skipped"
            frac_str = "0/0"
        else:
            effective = total - errored
            if rate is None:
                rate_str = "n/a"
            else:
                rate_str = f"{rate * 100:.1f}%"
            frac_str = f"{correct}/{total}"
            sum_correct += correct
            sum_effective += effective

        print(f"{check:<22} {frac_str:>10}  {errored_str:>8}  {rate_str:>7}")

    print("-" * 55)
    print(f"demo-critical reliability: {sum_correct}/{sum_effective}")


if __name__ == "__main__":
    main()
