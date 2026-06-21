# agent/full_stack_agent.py
"""Demo agent that natively uses three transports: http (LLM), mcp (a tool), and
local native-function tools (sdk). It contains ZERO Cassette code — the recorder
captures http/mcp via the proxy and transparently instruments the local tools
from the driver (recorder.record_session), so the agent stays fully unmodified.
"""
from __future__ import annotations

import json
import os

import httpx

# Module-level effect counters. They stand in for real side effects so a test can
# prove a side-effecting tool is never executed during replay. This is the agent's
# OWN state, not Cassette instrumentation.
EXECUTED = {"enrich": 0, "audit": 0}


def enrich_priority(raw_priority: str) -> dict:
    """Read-only native tool (no network)."""
    EXECUTED["enrich"] += 1
    level = "critical" if "p1" in raw_priority.lower() else "medium"
    return {"normalized": level}


def write_audit_log(ticket_key: str, action: str) -> dict:
    """Side-effecting native tool (no network): in production this would persist."""
    EXECUTED["audit"] += 1
    return {"logged": True, "ticket": ticket_key, "action": action}


def _llm() -> dict:
    url = os.environ["CASSETTE_LLM_URL"]
    r = httpx.post(url, json={"model": "mock", "messages": [{"role": "user", "content": "triage"}]},
                   timeout=30)
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def _mcp_call(name: str, arguments: dict) -> dict:
    url = os.environ["CASSETTE_MCP_URL"]
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": name, "arguments": arguments}}
    r = httpx.post(url, json=msg, timeout=30)
    r.raise_for_status()
    return json.loads(r.json()["result"]["content"][0]["text"])


def main() -> int:
    draft = _llm()                                              # http (proxy-captured)
    norm = enrich_priority("P1 - outage")                       # sdk (driver-instrumented)
    assigned = _mcp_call("assign_ticket", {"ticket_key": "OPS-1", "team": "Backend"})  # mcp
    audit = write_audit_log("OPS-1", "assigned")               # sdk (driver-instrumented)
    print(f"draft={draft} norm={norm} assigned={assigned} audit={audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
