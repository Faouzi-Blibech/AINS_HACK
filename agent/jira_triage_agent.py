"""Toy Jira-triage agent: the subject under test.

Reads a ticket, sets a priority, assigns a team, and notifies the reporter. The
agent is unmodified by Cassette: it calls its LLM and tools normally; the
recorder intercepts that traffic (see ../recorder/).

The bug is deliberate: the ambiguous priority field resolves to "medium" at
step 2 (get_priority), which routes the ticket to the wrong team. Root cause is
step 2, matching docs/fixtures/sample_trace.json and CONTEXT.md.

Runs offline by default (deterministic stub LLM, no key needed). Set
GROQ_API_KEY to make the single LLM call hit Groq (free, OpenAI-compatible);
plain HTTP so the Day-2 recorder can intercept it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx


# Tools flagged here are ALWAYS mocked during replay (the core safety invariant).
SIDE_EFFECTING_TOOLS = {"assign_ticket", "send_email"}

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
AGENT_MODEL = os.environ.get("CASSETTE_AGENT_MODEL", "llama-3.3-70b-versatile")

_ROUTING = {
    "critical": "Backend Engineers",
    "high": "Backend Engineers",
    "medium": "General Triage Queue",
    "low": "General Triage Queue",
}


@dataclass
class Ticket:
    key: str
    summary: str
    description: str
    reporter: str
    raw_priority: str = "P2 / medium?"  # ambiguous on purpose


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from the repo-root .env into the environment."""
    path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip("'\""))


def _llm_triage(ticket: Ticket) -> dict:
    """The single LLM call: draft the triage decision + reporter email."""
    _load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY")
    if api_key:
        try:
            return _llm_triage_live(ticket, api_key)
        except Exception as exc:  # degrade to offline, never crash the demo
            print(f"  [llm] live call failed ({exc}); using offline draft")
    return _llm_triage_offline(ticket)


def _llm_triage_live(ticket: Ticket, api_key: str) -> dict:
    system = (
        "You triage Jira tickets. Return STRICT JSON with keys: intent, "
        "email_subject, email_body. Be concise."
    )
    user = (
        f"Ticket {ticket.key}\nSummary: {ticket.summary}\n"
        f"Description: {ticket.description}\nReporter: {ticket.reporter}\n"
        f"Priority field (raw): {ticket.raw_priority}\nReturn only the JSON."
    )
    resp = httpx.post(
        os.environ.get("CASSETTE_LLM_URL", GROQ_URL),
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": AGENT_MODEL,
            "max_tokens": 400,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])


def _llm_triage_offline(ticket: Ticket) -> dict:
    return {
        "intent": "Routine ticket; route by reported priority and notify reporter.",
        "email_subject": f"Re: {ticket.key} - logged",
        "email_body": (
            f"Hi {ticket.reporter}, we logged {ticket.key}. This looks routine and "
            "has been placed in the general queue. Please do not escalate."
        ),
    }


def _resolve_priority(raw: str) -> str:
    raw = raw.lower()
    if "p1" in raw or "critical" in raw:
        return "critical"
    if "p3" in raw or "low" in raw:
        return "low"
    return "medium"  # "P2 / medium?" on a real outage -> should have been high


def _tools_url():
    return os.environ.get("CASSETTE_TOOLS_URL")


def get_priority(ticket: Ticket) -> str:
    """Read-only tool: resolve priority. The ambiguous field sinks the run here."""
    url = _tools_url()
    if url:
        r = httpx.post(f"{url}/get_priority", json={"raw_priority": ticket.raw_priority}, timeout=10)
        r.raise_for_status()
        return r.json()["priority"]
    return _resolve_priority(ticket.raw_priority)


def assign_ticket(ticket_key: str, team: str) -> dict:
    """Side-effecting tool: writes the assignment to Jira."""
    url = _tools_url()
    if url:
        r = httpx.post(f"{url}/assign_ticket", json={"ticket_key": ticket_key, "team": team}, timeout=10)
        r.raise_for_status()
        return r.json()
    return {"ok": True, "ticket": ticket_key, "assigned_to": team}


def send_email(to: str, subject: str, body: str) -> dict:
    """Side-effecting tool: sends the reporter notification."""
    url = _tools_url()
    if url:
        r = httpx.post(f"{url}/send_email", json={"to": to, "subject": subject, "body": body}, timeout=10)
        r.raise_for_status()
        return r.json()
    return {"ok": True, "to": to, "subject": subject, "delivered": True}


def _route(priority: str) -> str:
    return _ROUTING.get(priority, "General Triage Queue")


def run(ticket: Ticket, *, verbose: bool = True) -> dict:
    """Run the triage loop: llm_call -> get_priority -> assign_ticket -> send_email."""
    def log(step, kind, label, detail):
        if verbose:
            tag = " [side-effecting]" if label in SIDE_EFFECTING_TOOLS else ""
            print(f"  step {step}  {kind:<9} {label}{tag}: {detail}")

    if verbose:
        print(f"Triage run for {ticket.key}: {ticket.summary!r}")

    draft = _llm_triage(ticket)
    log(1, "llm_call", AGENT_MODEL, draft["intent"])

    priority = get_priority(ticket)
    log(2, "tool_call", "get_priority", f"resolved priority = {priority}")

    team = _route(priority)
    assign_result = assign_ticket(ticket.key, team)
    log(3, "tool_call", "assign_ticket", f"assigned to {team}")

    email_result = send_email(ticket.reporter, draft["email_subject"], draft["email_body"])
    log(4, "tool_call", "send_email", f"to {ticket.reporter}: {draft['email_subject']!r}")

    outcome = {
        "ticket": ticket.key,
        "resolved_priority": priority,
        "assigned_team": team,
        "email": {"to": ticket.reporter, **draft},
        "assign_result": assign_result,
        "email_result": email_result,
    }
    if verbose:
        print(f"Outcome: {ticket.key} -> {team} (priority {priority}).")
    return outcome


# Canonical demo ticket: an urgent outage with an ambiguous priority field.
DEMO_TICKET = Ticket(
    key="OPS-4521",
    summary="Checkout API returning 500s for all EU customers",
    description=(
        "Since the 14:00 deploy every EU checkout call fails with HTTP 500. "
        "Revenue impact is live. Logs point at the payments service."
    ),
    reporter="maria.k@acme.io",
    raw_priority="P2 / medium?",
)


if __name__ == "__main__":
    run(DEMO_TICKET)
