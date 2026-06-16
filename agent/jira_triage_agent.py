"""Toy Jira-triage agent: the subject under test.

Reads an incoming ticket, sets a priority, assigns a team, and notifies the
reporter. The agent is unmodified by Cassette: it calls its LLM and tools
normally. Cassette intercepts that traffic transparently (see ../recorder/).

Skeleton only. Implementation follows for the final submission.
"""
from __future__ import annotations

from dataclasses import dataclass


# Tools whose side_effecting flag is True are ALWAYS mocked during replay.
SIDE_EFFECTING_TOOLS = {"assign_ticket", "send_email"}


@dataclass
class Ticket:
    key: str
    summary: str
    description: str
    reporter: str


def get_priority(ticket: Ticket) -> str:
    """Read-only tool: classify ticket priority. Recorded, not mocked."""
    raise NotImplementedError


def assign_ticket(ticket_key: str, team: str) -> dict:
    """Side-effecting tool: writes the assignment to Jira."""
    raise NotImplementedError


def send_email(to: str, subject: str, body: str) -> dict:
    """Side-effecting tool: sends the reporter notification."""
    raise NotImplementedError


def run(ticket: Ticket) -> dict:
    """Run the triage loop end to end and return the final outcome."""
    raise NotImplementedError
