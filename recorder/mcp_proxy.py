"""MCP (Model Context Protocol) awareness for the recorder.

MCP over Streamable HTTP is JSON-RPC 2.0 carried as HTTP POST bodies, so it
already flows through the HTTP forward proxy in ``http_proxy.py``. This module
is the MCP half of the transport router: it detects a JSON-RPC envelope,
extracts the real MCP tool name + arguments from a ``tools/call``, and builds an
id-independent identity so a replayed handshake (which issues fresh JSON-RPC
ids) still matches the recorded step.

Pure functions only: no network, no agent imports.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

TOOL_CALL_METHOD = "tools/call"


@dataclass
class McpCall:
    method: str             # JSON-RPC method, e.g. "tools/call", "initialize"
    tool: str | None        # tool name for tools/call, else None
    arguments: dict | None  # tool arguments for tools/call, else None
    is_notification: bool   # JSON-RPC notification (no id, no response expected)


def _loads(body: str):
    try:
        obj = json.loads(body)
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _is_envelope(obj) -> bool:
    return bool(obj and obj.get("jsonrpc") == "2.0" and "method" in obj)


def is_mcp(req_body: str) -> bool:
    """True if the request body is a JSON-RPC 2.0 envelope (MCP transport)."""
    return _is_envelope(_loads(req_body))


def parse_request(req_body: str) -> McpCall | None:
    """Parse a JSON-RPC request body into an McpCall, or None if not MCP."""
    obj = _loads(req_body)
    if not _is_envelope(obj):
        return None
    method = obj["method"]
    params = obj.get("params") or {}
    tool = arguments = None
    if method == TOOL_CALL_METHOD and isinstance(params, dict):
        tool = params.get("name")
        arguments = params.get("arguments") or {}
    return McpCall(method=method, tool=tool, arguments=arguments,
                   is_notification="id" not in obj)


def unwrap_sse(resp_body: str) -> str:
    """Return the JSON payload of an MCP response.

    Real MCP servers may answer a POST with a ``text/event-stream`` instead of
    plain JSON. Return the data of the last ``data:`` event, or the body
    unchanged when it is already plain JSON.
    """
    if "data:" not in resp_body:
        return resp_body
    data = [ln[len("data:"):].strip()
            for ln in resp_body.splitlines() if ln.startswith("data:")]
    return data[-1] if data else resp_body


def _strip_volatile(obj, volatile: set[str]):
    """Recursively drop volatile keys from an arguments tree (identity only)."""
    if isinstance(obj, dict):
        return {k: _strip_volatile(v, volatile)
                for k, v in obj.items() if k not in volatile}
    if isinstance(obj, list):
        return [_strip_volatile(v, volatile) for v in obj]
    return obj


def mcp_identity(call: McpCall, volatile: list[str] | None = None) -> str:
    """Id-independent identity: keyed on JSON-RPC method + (tool, arguments).

    The volatile JSON-RPC ``id`` (and any transport session id) are excluded so
    a replayed run, which issues fresh ids, still matches the recorded step.
    Policy ``volatile_fields`` (timestamps, nonces, idempotency keys, ...) are
    stripped from the arguments at any depth, mirroring the HTTP identity, so a
    tool that takes a per-call nonce still replays without a false divergence.
    """
    arguments = call.arguments
    if arguments is not None and volatile:
        arguments = _strip_volatile(arguments, set(volatile))
    payload = {"method": call.method, "tool": call.tool, "arguments": arguments}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(blob).hexdigest()
    return f"mcp {call.method} {call.tool or ''}\n{digest}"
