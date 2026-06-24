# agent/ops_incident_agent.py
"""A sophisticated, multi-step incident-response agent for local platform testing.

Theme: an on-call SRE agent that triages a production incident, then BRANCHES on
the severity it assesses:
  * high (SEV-1/SEV-2) -> full escalation: page on-call, status update, follow-up
    ticket, resolve.
  * low (e.g. SEV-4)   -> minimal handling: brief status, resolve. No paging.

This branch is what makes the **record-over / divergence** demo real: re-running
the agent with a different severity at the decision step produces a genuinely
different downstream trajectory (not just a truncated faithful replay).

Design notes:
  * ZERO Cassette imports. The runner (recorder/run_agent.py) instruments
    `call_model` and the tools from outside.
  * Deterministic: the "model" is scripted and branches on the observed
    severity, so the same inputs always yield the same trace -- no key, no
    network. The decision value is read from the `assess_severity` tool result,
    which honours the override env `CASSETTE_OPS_SEVERITY` (default "SEV-2").
  * One model turn dispatches multiple tools at once (parallel batches) so the
    recorder tags them with a shared parallel_group (schema v1.1).
"""
from __future__ import annotations

import json
import os

EXECUTED = {
    "fetch_incident": 0, "check_service_health": 0, "correlate_alerts": 0,
    "lookup_recent_deploys": 0, "assess_severity": 0, "search_runbook": 0,
    "get_oncall_engineer": 0, "set_severity": 0, "assign_incident": 0,
    "page_oncall": 0, "post_status_update": 0, "create_followup_ticket": 0,
    "resolve_incident": 0, "verify_resolution": 0,
}

# Tool name -> is it side-effecting? Read by the runner to instrument correctly.
SDK_TOOLS = {
    "fetch_incident": False,
    "check_service_health": False,
    "correlate_alerts": False,
    "lookup_recent_deploys": False,
    "assess_severity": False,
    "search_runbook": False,
    "get_oncall_engineer": False,
    "verify_resolution": False,
    "set_severity": True,
    "assign_incident": True,
    "page_oncall": True,
    "post_status_update": True,
    "create_followup_ticket": True,
    "resolve_incident": True,
}

# The decision tool reads this so record-over can override it to fork the path.
SEVERITY_ENV = "CASSETTE_OPS_SEVERITY"
_DEFAULT_SEVERITY = "SEV-2"
_HIGH = {"SEV-1", "SEV-2"}

_INCIDENT = "INC-4827"
_SERVICE = "payments-api"


# --- read-only tools -------------------------------------------------------

def fetch_incident(incident_id: str) -> dict:
    EXECUTED["fetch_incident"] += 1
    return {"id": incident_id, "title": "Elevated 5xx on payments-api",
            "service": _SERVICE, "raw_severity": "P1 - customer impact",
            "reporter": "monitoring-bot", "opened_ms": 1750250000000,
            "description": "Checkout error rate jumped to 14% after 14:30 UTC."}


def check_service_health(service: str) -> dict:
    EXECUTED["check_service_health"] += 1
    return {"service": service, "status": "degraded", "error_rate": 0.14,
            "p95_latency_ms": 1820, "healthy_replicas": 2, "desired_replicas": 6}


def correlate_alerts(service: str) -> dict:
    EXECUTED["correlate_alerts"] += 1
    return {"service": service, "count": 3,
            "alerts": ["HighErrorRate", "PodCrashLoop", "LatencyP95Breach"]}


def lookup_recent_deploys(service: str) -> dict:
    EXECUTED["lookup_recent_deploys"] += 1
    return {"service": service, "last_deploy": "v2.7.3",
            "deployed_ms": 1750249800000, "by": "release-bot",
            "change": "connection-pool refactor"}


def assess_severity(service: str) -> dict:
    """The DECISION step. Returns the severity the rest of the run branches on.
    Honours the CASSETTE_OPS_SEVERITY override so record-over can fork the path."""
    EXECUTED["assess_severity"] += 1
    return {"service": service, "severity": os.environ.get(SEVERITY_ENV, _DEFAULT_SEVERITY)}


def search_runbook(query: str) -> dict:
    EXECUTED["search_runbook"] += 1
    return {"runbook": "payments-api/oncall.md", "match": query,
            "steps": ["roll back last deploy", "scale replicas", "verify error rate < 1%"]}


def get_oncall_engineer(team: str) -> dict:
    EXECUTED["get_oncall_engineer"] += 1
    return {"team": team, "engineer": "Sara K.", "contact": "@sara", "tz": "UTC+1"}


def verify_resolution(incident_id: str) -> dict:
    """Final check. Fails (returns an error) when the incident was assessed too
    LOW for a genuine P1 -- the rollback was skipped, so the error rate stays
    elevated. This makes a wrong upstream decision surface as a recorded failure
    that record-over (re-running with the correct severity) can fix."""
    EXECUTED["verify_resolution"] += 1
    sev = os.environ.get(SEVERITY_ENV, _DEFAULT_SEVERITY)
    if sev in _HIGH:
        return {"ok": True, "incident_id": incident_id, "error_rate": 0.003, "resolved": True}
    return {"ok": False, "incident_id": incident_id, "error_rate": 0.14,
            "error": "verification failed: error rate still elevated; low severity skipped the rollback"}


# --- side-effecting tools (mocked on replay) -------------------------------

def set_severity(incident_id: str, severity: str) -> dict:
    EXECUTED["set_severity"] += 1
    return {"ok": True, "incident_id": incident_id, "severity": severity}


def assign_incident(incident_id: str, team: str) -> dict:
    EXECUTED["assign_incident"] += 1
    return {"ok": True, "incident_id": incident_id, "assigned_to": team}


def page_oncall(engineer: str, message: str) -> dict:
    EXECUTED["page_oncall"] += 1
    return {"ok": True, "paged": engineer, "message": message}


def post_status_update(incident_id: str, message: str) -> dict:
    EXECUTED["post_status_update"] += 1
    return {"ok": True, "incident_id": incident_id, "posted": True}


def create_followup_ticket(title: str, description: str) -> dict:
    EXECUTED["create_followup_ticket"] += 1
    return {"ok": True, "ticket_key": "OPS-991", "title": title}


def resolve_incident(incident_id: str, resolution: str) -> dict:
    EXECUTED["resolve_incident"] += 1
    return {"ok": True, "incident_id": incident_id, "resolved": True}


# --- scripted, branching "model" ------------------------------------------

def _tc(call_id: str, name: str, **arguments) -> dict:
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


def _assistant(tool_calls: list) -> dict:
    return {"role": "assistant", "content": None, "tool_calls": tool_calls}


def _severity_from(messages: list[dict]) -> str:
    """Read the severity the agent observed from the assess_severity tool result."""
    for m in reversed(messages):
        if m.get("role") == "tool":
            try:
                data = json.loads(m.get("content") or "{}")
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and "severity" in data:
                return data["severity"]
    return _DEFAULT_SEVERITY


def call_model(messages: list[dict]) -> dict:
    """Deterministic model that branches on the assessed severity."""
    turn = sum(1 for m in messages if m.get("role") == "assistant")

    # Fixed prefix (same on every path) ------------------------------------
    if turn == 0:
        return _assistant([_tc("t1", "fetch_incident", incident_id=_INCIDENT)])
    if turn == 1:  # parallel diagnostics (3 tools at once -> parallel_group)
        return _assistant([_tc("t2", "check_service_health", service=_SERVICE),
                           _tc("t3", "correlate_alerts", service=_SERVICE),
                           _tc("t4", "lookup_recent_deploys", service=_SERVICE)])
    if turn == 2:  # the decision step
        return _assistant([_tc("t5", "assess_severity", service=_SERVICE)])

    # Branch on the observed severity --------------------------------------
    sev = _severity_from(messages)
    if sev in _HIGH:
        plan = [
            # parallel context gathering (2 tools -> a second parallel_group)
            [_tc("h0a", "search_runbook", query="payments-api elevated 5xx after deploy"),
             _tc("h0b", "get_oncall_engineer", team="Payments")],
            [_tc("h1", "set_severity", incident_id=_INCIDENT, severity=sev)],
            [_tc("h2", "assign_incident", incident_id=_INCIDENT, team="Payments")],
            [_tc("h3", "page_oncall", engineer="Sara K.",
                 message=f"{sev} on {_SERVICE}: error rate 14%, suspected bad deploy v2.7.3")],
            [_tc("h4", "post_status_update", incident_id=_INCIDENT,
                 message="Investigating elevated errors; rolling back v2.7.3 and scaling replicas.")],
            [_tc("h5", "create_followup_ticket",
                 title=f"Post-incident review: {_SERVICE} v2.7.3 regression",
                 description=f"Root cause + action items for {_INCIDENT}.")],
            [_tc("h6", "resolve_incident", incident_id=_INCIDENT,
                 resolution="Rolled back v2.7.3, scaled to 6 replicas, error rate back to 0.3%.")],
            [_tc("h7", "verify_resolution", incident_id=_INCIDENT)],
        ]
        final = (f"Incident {_INCIDENT} handled as {sev}: paged on-call, assigned to Payments, "
                 f"posted a status update, opened a post-incident review (OPS-991), and resolved.")
    else:
        plan = [
            [_tc("l1", "set_severity", incident_id=_INCIDENT, severity=sev)],
            [_tc("l2", "post_status_update", incident_id=_INCIDENT,
                 message=f"{sev}: low-impact blip on {_SERVICE}, monitoring; no paging needed.")],
            [_tc("l3", "resolve_incident", incident_id=_INCIDENT,
                 resolution="Transient blip auto-recovered; no rollback required.")],
            [_tc("l4", "verify_resolution", incident_id=_INCIDENT)],
        ]
        final = (f"Incident {_INCIDENT} handled as {sev}: low severity, logged a brief status and "
                 f"auto-resolved without paging or a follow-up.")

    branch_turn = turn - 3
    if branch_turn < len(plan):
        return _assistant(plan[branch_turn])
    return {"role": "assistant", "content": final}


def _dispatch_tool(name: str, arguments: dict) -> dict:
    """Resolve the tool by its current module binding so the runner's external
    instrumentation (which reassigns the module attributes) is always honoured."""
    import agent.ops_incident_agent as _self
    fn = getattr(_self, name, None)
    if fn is None or not callable(fn):
        return {"error": f"unknown tool {name!r}"}
    return fn(**arguments)


def main() -> int:
    messages: list[dict] = [
        {"role": "system", "content": (
            "You are an on-call SRE incident-response agent. Triage the incident, "
            "assess its severity, and handle it appropriately using the tools."
        )},
        {"role": "user", "content": f"Handle incident {_INCIDENT} on {_SERVICE}."},
    ]

    assistant_msg: dict = {}
    for _ in range(16):
        assistant_msg = call_model(messages)
        messages.append(assistant_msg)
        tool_calls = assistant_msg.get("tool_calls") or []
        if not tool_calls:
            break
        for tc in tool_calls:
            name = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"])
            result = _dispatch_tool(name, args)
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": json.dumps(result)})

    print(f"ops_incident_agent done: {assistant_msg.get('content')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
