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


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        path = self.path
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
        data = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(port: int = 0):
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
