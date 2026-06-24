"""Static failure-memory store (Layer 2).

Seeded with known recurring failure patterns. The real persistent store
with semantic search comes in a later iteration; this module exposes the
same interface so the /library endpoint and any future backend are
interchangeable.

Each entry matches the FailureLibraryEntry schema defined in
api_contract_sketch.py:
    failure_pattern   str
    blame_step        int
    fix_that_worked   str
    agent_config      str
    determinism_rate  float (0..1)

The optional "id" key (e.g. "FM-014") is kept for internal reference;
it is intentionally omitted from the response model so the frontend
derives display labels as needed.
"""
from __future__ import annotations

FAILURE_MEMORY: list[dict] = [
    {
        "id": "FM-014",
        "failure_pattern": (
            "ambiguous priority field caused wrong routing: "
            "get_priority='medium' on payment tickets is historically wrong"
        ),
        "blame_step": 2,
        "fix_that_worked": (
            "require explicit priority justification; enforce priority enum "
            "with no implicit 'medium' default for payment-category tickets"
        ),
        "agent_config": "v2.3.1",
        "determinism_rate": 0.82,
    },
    {
        "id": "FM-007",
        "failure_pattern": (
            "malformed tool argument: tool call sent a string where the "
            "schema requires an integer, causing downstream parse error"
        ),
        "blame_step": 1,
        "fix_that_worked": (
            "add strict type coercion in the tool-call wrapper before "
            "forwarding arguments to the external API"
        ),
        "agent_config": "v2.2.0",
        "determinism_rate": 0.95,
    },
    {
        "id": "FM-021",
        "failure_pattern": (
            "missing context window: agent invoked summarization step "
            "without injecting the preceding conversation history, "
            "producing an out-of-context response"
        ),
        "blame_step": 3,
        "fix_that_worked": (
            "always prepend the last N turns of conversation history "
            "before calling the summarization tool; N defaults to 5"
        ),
        "agent_config": "v2.4.0",
        "determinism_rate": 0.78,
    },
    {
        "id": "FM-031",
        "failure_pattern": (
            "tool-call timeout misclassified as successful empty result: the "
            "tool returned no data after timing out, but the agent treated the "
            "empty response as valid and proceeded on missing data, producing a "
            "silently incorrect downstream decision"
        ),
        "blame_step": 4,
        "fix_that_worked": (
            "treat any timeout response from the tool layer as an explicit error; "
            "raise a ToolTimeoutError instead of coercing to empty success, and "
            "halt the pipeline until the caller handles the error"
        ),
        "agent_config": "v2.5.0",
        "determinism_rate": 0.88,
    },
    {
        "id": "FM-045",
        "failure_pattern": (
            "stale over-broad context caused over-escalation: an unfiltered prior "
            "high-severity incident was included in the retrieved context for a "
            "routine ticket, causing the agent to escalate it to the on-call team "
            "unnecessarily"
        ),
        "blame_step": 2,
        "fix_that_worked": (
            "scope the retrieved context to the current ticket category and "
            "recency before the triage call; filter out incidents whose severity "
            "or category does not match the ticket being processed"
        ),
        "agent_config": "v2.5.1",
        "determinism_rate": 0.74,
    },
]
