"""Toy MCP-over-HTTP agent: a Jira triage flow that talks to an MCP server.

A minimal MCP client over Streamable HTTP (JSON-RPC 2.0 as HTTP POST bodies):
handshake (initialize + notifications/initialized), discover tools (tools/list),
then call three tools (one read-only, two side-effecting). It exists to exercise
the recorder's MCP path; point it at a server with CASSETTE_MCP_URL.

Run directly behind the Cassette proxy via `python -m recorder.record --demo --mcp`.
"""
from __future__ import annotations

import itertools
import json
import os

import requests

MCP_URL = os.environ.get("CASSETTE_MCP_URL", "http://127.0.0.1:8000/mcp")
_ids = itertools.count(1)


def _rpc(method: str, params: dict | None = None, *, notify: bool = False):
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if not notify:
        msg["id"] = next(_ids)
    resp = requests.post(MCP_URL, json=msg, timeout=30)
    if notify:
        return None
    return resp.json().get("result", {})


def _call_tool(name: str, arguments: dict) -> dict:
    result = _rpc("tools/call", {"name": name, "arguments": arguments})
    return json.loads(result["content"][0]["text"])


def main() -> int:
    _rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "mcp-jira-agent", "version": "0.1"}})
    _rpc("notifications/initialized", notify=True)
    _rpc("tools/list")

    priority = _call_tool("get_priority", {"raw_priority": "P1 - outage"})
    assigned = _call_tool("assign_ticket", {"ticket_key": "OPS-42", "team": "Backend"})
    emailed = _call_tool("send_email", {"to": "oncall@example.com",
                                        "subject": "OPS-42 assigned"})
    print(f"priority={priority} assigned={assigned} emailed={emailed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
