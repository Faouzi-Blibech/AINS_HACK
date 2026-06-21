"""Fake upstream services (LLM + Jira/email REST): a test/demo fixture, not part of any agent."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _resolve_priority(raw: str) -> str:
    raw = raw.lower()
    if "p1" in raw or "critical" in raw:
        return "critical"
    if "p3" in raw or "low" in raw:
        return "low"
    return "medium"


_MCP_TOOLS = [
    {"name": "get_priority", "description": "resolve a raw priority label"},
    {"name": "assign_ticket", "description": "assign a ticket to a team"},
    {"name": "send_email", "description": "send a notification email"},
]


def _mcp_dispatch(msg: dict):
    """Minimal MCP server: JSON-RPC 2.0 over HTTP. Returns a response dict, or
    None for a notification (the caller answers 202 with no body)."""
    method = msg.get("method")
    mid = msg.get("id")
    if "id" not in msg:  # notification (e.g. notifications/initialized)
        return None
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "mock-mcp", "version": "0.1"}}
    elif method == "tools/list":
        result = {"tools": _MCP_TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        name, args = p.get("name"), p.get("arguments", {})
        if name == "get_priority":
            payload = {"priority": _resolve_priority(args.get("raw_priority", ""))}
        elif name == "assign_ticket":
            payload = {"ok": True, "ticket": args.get("ticket_key"), "assigned_to": args.get("team")}
        elif name == "send_email":
            payload = {"ok": True, "to": args.get("to"), "delivered": True}
        else:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": f"unknown tool: {name}"}}
        result = {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}
    else:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send_json(self, data: bytes, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        path = self.path
        if path.endswith("/mcp"):
            resp = _mcp_dispatch(body)
            if resp is None:  # notification: acknowledge, no body
                self._send_json(b"", status=202)
            else:
                self._send_json(json.dumps(resp).encode())
            return
        if path.endswith("/chat/completions"):
            resp = {"id": "mock", "model": body.get("model", "mock"),
                    "choices": [{"message": {"role": "assistant",
                        "content": json.dumps({"intent": "triage",
                            "email_subject": "Re: ticket", "email_body": "queued"})}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        elif path.endswith("/get_priority"):
            resp = {"priority": _resolve_priority(body.get("raw_priority", ""))}
        elif path.endswith("/assign_ticket"):
            resp = {"ok": True, "ticket": body.get("ticket_key"), "assigned_to": body.get("team")}
        elif path.endswith("/send_email"):
            resp = {"ok": True, "to": body.get("to"), "delivered": True}
        else:
            self.send_error(404); return
        self._send_json(json.dumps(resp).encode())


def serve(port: int = 0):
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
