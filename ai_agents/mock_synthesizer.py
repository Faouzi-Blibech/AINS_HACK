"""Mock synthesizer.

In divergence mode, new tool calls can appear after the fork point that have no
recorded response. This component generates a plausible response from the tool's
schema and surrounding context, so replay can continue without hitting a live
endpoint.

Skeleton only.
"""
from __future__ import annotations


def synthesize(tool: str, arguments: dict, schema: dict, context: dict) -> dict:
    """Generate a plausible response for an unrecorded tool call."""
    raise NotImplementedError
