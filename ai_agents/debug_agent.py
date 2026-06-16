"""Debug agent: natural language to JSON injection.

The engineer never edits raw JSON. They type plain English, e.g.
"at step 4, the ticket should have been assigned to platform not backend",
and this agent builds the exact, structurally valid injection and fires the
replay from that step. Without the LLM the engineer is back to hand-editing
trace payloads, which is the clearest proof AI is load-bearing.

Skeleton only.
"""
from __future__ import annotations


class Injection:
    """The structured edit: step_id, target (prompt/tool result), new value."""


def build_injection(run_id: str, instruction: str) -> Injection:
    """Turn a plain-English instruction into a validated injection."""
    raise NotImplementedError
