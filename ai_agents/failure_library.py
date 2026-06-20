"""Layer-2 failure-memory intelligence: swap-ready library interface, seed, and relevance retrieval.

The public surface is:
- FailureEntry      dataclass holding a single known failure pattern.
- FailureLibrary    Protocol (runtime-checkable): implementors expose ``all()``.
- SeedFailureLibrary concrete implementation backed by built-in seed data.
- relevant_failures the main retrieval function: judges each library entry
                    against a described situation, ranks by relevance score,
                    and returns the top-k wrapped in an AIResult.

LLM calls are made as ``llm.llm_complete(...)`` (module attribute) so tests
can monkeypatch ``ai_agents.llm.llm_complete`` without touching imports here.

Offline-safe: when the LLM is not configured (or any parse error occurs), the
default judge falls back to deterministic case-insensitive keyword-overlap
scoring so the demo ranks without an API key.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

import ai_agents.confidence as confidence
from ai_agents import llm
from ai_agents.prompts import FAILURE_RELEVANCE_SCHEMA, FAILURE_RELEVANCE_SYSTEM, failure_relevance_user

# Type alias for the injectable judge seam.
# Returns (relevant, score, confidence, rationale).
JudgeFn = Callable[[str, str], tuple[bool, float, float, str]]


# ---------------------------------------------------------------------------
# FailureEntry dataclass
# ---------------------------------------------------------------------------


@dataclass
class FailureEntry:
    """A single known failure pattern from the library.

    Attributes
    ----------
    id:
        Unique identifier (e.g. "FM-014").
    failure_pattern:
        Short description of what went wrong.
    blame_step:
        The step index that is the root cause.
    fix_that_worked:
        Description of the fix that resolved the pattern.
    agent_config:
        Agent configuration version string at the time of the failure.
    determinism_rate:
        Fraction 0..1 of runs exhibiting this pattern deterministically.
    """

    id: str
    failure_pattern: str
    blame_step: int
    fix_that_worked: str
    agent_config: str
    determinism_rate: float


# ---------------------------------------------------------------------------
# FailureLibrary Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class FailureLibrary(Protocol):
    """Swap seam for the failure store (seed today, SQLite later).

    Any object implementing this Protocol can be passed to
    ``relevant_failures``. The seed implementation is ``SeedFailureLibrary``;
    a persistent store implementation can be swapped in without changing the
    retrieval logic.
    """

    def all(self) -> list[FailureEntry]:
        """Return all entries in the library."""
        ...


# ---------------------------------------------------------------------------
# Seed data (mirroring the 3 patterns from api/failure_memory.py without importing it)
# ---------------------------------------------------------------------------

SEED_ENTRIES: list[FailureEntry] = [
    FailureEntry(
        id="FM-014",
        failure_pattern=(
            "ambiguous priority field caused wrong routing: "
            "get_priority='medium' on payment tickets is historically wrong"
        ),
        blame_step=2,
        fix_that_worked=(
            "require explicit priority justification; enforce priority enum "
            "with no implicit 'medium' default for payment-category tickets"
        ),
        agent_config="v2.3.1",
        determinism_rate=0.82,
    ),
    FailureEntry(
        id="FM-007",
        failure_pattern=(
            "malformed tool argument: tool call sent a string where the "
            "schema requires an integer, causing downstream parse error"
        ),
        blame_step=1,
        fix_that_worked=(
            "add strict type coercion in the tool-call wrapper before "
            "forwarding arguments to the external API"
        ),
        agent_config="v2.2.0",
        determinism_rate=0.95,
    ),
    FailureEntry(
        id="FM-021",
        failure_pattern=(
            "missing context window: agent invoked summarization step "
            "without injecting the preceding conversation history, "
            "producing an out-of-context response"
        ),
        blame_step=3,
        fix_that_worked=(
            "always prepend the last N turns of conversation history "
            "before calling the summarization tool; N defaults to 5"
        ),
        agent_config="v2.4.0",
        determinism_rate=0.78,
    ),
]


class SeedFailureLibrary:
    """Concrete FailureLibrary backed by the built-in seed entries.

    This is the default store used until a persistent backend is available.
    It satisfies the FailureLibrary Protocol and is the swap seam for a
    future SQLite or vector-store implementation.
    """

    def all(self) -> list[FailureEntry]:
        """Return all seed failure entries."""
        return list(SEED_ENTRIES)


# ---------------------------------------------------------------------------
# Keyword-overlap fallback scorer (deterministic, offline-safe)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase word tokens, filtering single characters."""
    return {tok for tok in re.split(r"\W+", text.lower()) if len(tok) > 1}


def _keyword_overlap_score(situation: str, failure_pattern: str) -> float:
    """Compute normalized case-insensitive keyword overlap between two texts.

    Returns a float in [0, 1]: the fraction of situation tokens that appear
    in the failure_pattern token set. Returns 0.0 when the situation has no
    tokens.
    """
    sit_tokens = _tokenize(situation)
    pat_tokens = _tokenize(failure_pattern)
    if not sit_tokens:
        return 0.0
    overlap = sit_tokens & pat_tokens
    return len(overlap) / len(sit_tokens)


# ---------------------------------------------------------------------------
# Default LLM judge
# ---------------------------------------------------------------------------


def _default_judge(situation: str, failure_pattern: str) -> tuple[bool, float, float, str]:
    """Judge relevance via LLM with a keyword-overlap fallback.

    Returns (relevant, score, confidence, rationale).

    Raises nothing: LLMNotConfigured and all parse errors are caught and
    redirected to the deterministic fallback.
    """
    try:
        raw = llm.llm_complete(
            system=FAILURE_RELEVANCE_SYSTEM,
            user=failure_relevance_user(situation=situation, failure_pattern=failure_pattern),
            model=llm.cheap_model(),
            json_schema=FAILURE_RELEVANCE_SCHEMA,
        )
        data = json.loads(raw)
        relevant = bool(data["relevant"])
        score = float(data["score"])
        conf = float(data["confidence"])
        rationale = str(data["rationale"])
        return (relevant, score, conf, rationale)
    except (llm.LLMNotConfigured, json.JSONDecodeError, KeyError, ValueError, TypeError):
        score = _keyword_overlap_score(situation, failure_pattern)
        relevant = score > 0.0
        # Derive a rough confidence from the overlap magnitude
        conf = min(0.5, score) if relevant else 0.2
        rationale = f"Keyword overlap score {score:.2f} (offline fallback)"
        return (relevant, score, conf, rationale)


# ---------------------------------------------------------------------------
# Main retrieval function
# ---------------------------------------------------------------------------


def relevant_failures(
    library: FailureLibrary,
    situation: str,
    *,
    k: int = 3,
    judge: JudgeFn | None = None,
) -> confidence.AIResult[list[tuple[FailureEntry, float]]]:
    """Retrieve the top-k failure entries most relevant to *situation*.

    Parameters
    ----------
    library:
        Any object satisfying the FailureLibrary Protocol.
    situation:
        A short text describing the new run or ticket being analyzed.
    k:
        Maximum number of entries to return (default 3).
    judge:
        Injectable seam: ``(situation, failure_pattern) -> (relevant, score,
        confidence, rationale)``. When None, the default judge is used (LLM
        with keyword-overlap fallback).

    Returns
    -------
    AIResult[list[tuple[FailureEntry, float]]]
        Top-k (entry, score) pairs sorted by score descending, wrapped in an
        AIResult with confidence derived from the top entry and a rationale
        naming the best match.
    """
    effective_judge: JudgeFn = judge if judge is not None else _default_judge

    entries = library.all()

    if not entries:
        return confidence.wrap(
            [],
            confidence=0.1,
            rationale="No entries in library.",
        )

    # Score each entry.
    scored: list[tuple[FailureEntry, float, float, str]] = []  # (entry, score, conf, rationale)
    for entry in entries:
        try:
            relevant, score, conf, rationale = effective_judge(situation, entry.failure_pattern)
        except Exception:
            relevant, score, conf, rationale = False, 0.0, 0.1, "Judge error"
        if relevant or score > 0.0:
            scored.append((entry, score, conf, rationale))

    # Sort by score descending.
    scored.sort(key=lambda x: x[1], reverse=True)

    # Take top-k.
    top_k = scored[:k]

    if not top_k:
        return confidence.wrap(
            [],
            confidence=0.1,
            rationale="No relevant failures found.",
        )

    top_entry, top_score, top_conf, top_rationale = top_k[0]
    result_pairs = [(entry, score) for entry, score, _conf, _rat in top_k]

    rationale = f"Top match: {top_entry.id} (score {top_score:.2f}). {top_rationale}"
    return confidence.wrap(
        result_pairs,
        confidence=top_conf,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Preventive note composer
# ---------------------------------------------------------------------------


def preventive_note(
    library: FailureLibrary,
    situation: str,
    *,
    k: int = 3,
    threshold: float = 0.6,
    judge: JudgeFn | None = None,
) -> confidence.AIResult[str | None]:
    """Compose a short system-prompt warning from failures relevant to *situation*.

    Parameters
    ----------
    library:
        Any object satisfying the FailureLibrary Protocol.
    situation:
        A short text describing the new run or ticket being analyzed.
    k:
        Maximum number of entries to consider (passed to relevant_failures).
    threshold:
        Minimum score for an entry to be included in the note (default 0.6).
    judge:
        Injectable seam for the relevance scorer (same type as relevant_failures).

    Returns
    -------
    AIResult[str | None]
        When qualifying entries are found, value is a short actionable warning
        string. When nothing qualifies above threshold, value is None. The result
        is always wrapped in an AIResult carrying the confidence from the
        underlying relevant_failures call.
    """
    retrieval = relevant_failures(library, situation, k=k, judge=judge)
    retrieval_conf = retrieval.confidence

    # Filter to entries that score at or above threshold.
    qualifying = [(entry, score) for entry, score in retrieval.value if score >= threshold]

    if not qualifying:
        return confidence.wrap(
            None,
            retrieval_conf,
            rationale="No relevant prior failures above threshold.",
        )

    # Compose one compact warning from the qualifying entries.
    lines: list[str] = ["Preventive guidance from prior runs:"]
    for entry, score in qualifying:
        pattern_short = entry.failure_pattern.rstrip(".")
        fix_short = entry.fix_that_worked.rstrip(".")
        lines.append(f"  - When {pattern_short}; fix: {fix_short}.")

    note_str = " ".join(lines[0:1]) + "\n" + "\n".join(lines[1:])

    rationale = (
        f"Composed from {len(qualifying)} qualifying failure(s); "
        f"top score {qualifying[0][1]:.2f} >= threshold {threshold:.2f}."
    )
    return confidence.wrap(
        note_str,
        retrieval_conf,
        rationale=rationale,
    )


if __name__ == "__main__":  # pragma: no cover
    """Offline end-to-end demo: retrieve failures, compose a preventive note, run the agent."""
    import sys

    print("=" * 60)
    print("Layer-2 Failure-Memory Demo (offline-safe)")
    print("=" * 60)

    lib = SeedFailureLibrary()

    # Derive a situation from the ambiguous-priority demo ticket.
    situation = (
        "checkout API ticket with raw_priority='P2 / medium?' - "
        "priority field is ambiguous, risk of wrong team routing"
    )
    print(f"\nSituation: {situation}\n")

    # Step 1: retrieve relevant failures.
    rel_result = relevant_failures(lib, situation)
    print(f"[relevant_failures] confidence={rel_result.confidence:.2f}")
    print(f"  rationale: {rel_result.rationale}")
    print("  Top matches:")
    for entry, score in rel_result.value:
        print(f"    [{entry.id}] score={score:.2f} | {entry.failure_pattern[:70]}")

    # Step 2: compose preventive note.
    note_result = preventive_note(lib, situation)
    print(f"\n[preventive_note] confidence={note_result.confidence:.2f}")
    print(f"  rationale: {note_result.rationale}")
    print(f"  note value:\n    {note_result.value!r}")

    # Step 3: run the agent with the note injected (or None if nothing qualified).
    note_str: str | None = note_result.value

    try:
        from agent.jira_triage_agent import run, DEMO_TICKET  # type: ignore[import]

        print("\n" + "-" * 60)
        print(f"Running agent (DEMO_TICKET={DEMO_TICKET.key}) with preventive_note={note_str is not None}")
        print("-" * 60)
        outcome = run(DEMO_TICKET, preventive_note=note_str, verbose=True)
        note_was_injected = note_str is not None and len(note_str) > 0
        print(f"\nPreventive note injected into system prompt: {note_was_injected}")
        if note_was_injected:
            print(f"  (offline path confirms via preventive_applied={outcome.get('email', {}).get('preventive_applied', 'n/a')})")
        print(f"Outcome: {DEMO_TICKET.key} -> team={outcome['assigned_team']} priority={outcome['resolved_priority']}")
    except ImportError as exc:
        print(f"\n[demo] Could not import agent: {exc}. Skipping agent run.")

    print("\nDemo complete (ran fully offline).")
