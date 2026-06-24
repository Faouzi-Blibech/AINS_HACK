"""Self-contained Jira-triage agent for the Cassette import demo.

This is an ordinary agent: it makes an LLM call and a few tool calls over HTTP.
There is no Cassette code here, so when you import it, Cassette records that
traffic transparently (same as any HTTP/REST agent).

The deliberate bug: the ambiguous priority field ("P2 / medium?") resolves to
"medium", which routes an urgent outage to the General Triage Queue. The
assignment service refuses to put a live-outage ticket in a non-engineering
queue and returns HTTP 500, so the run fails at assign_ticket. The upstream
cause is the priority step.

Run: python main.py
Needs an LLM key in GROQ_API_KEY or OPENAI_API_KEY (Groq, OpenAI-compatible).
The ticket text comes from the import "Task" field (CASSETTE_AGENT_STDIN);
left blank, a default urgent-outage ticket is used so the failure still fires.
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import httpx

ROUTING = {
    "critical": "Backend Engineers", "high": "Backend Engineers",
    "medium": "General Triage Queue", "low": "General Triage Queue",
}
ENGINEERING = {"Backend Engineers"}

DEFAULT_TICKET = (
    "OPS-4521: Checkout API returning 500s for all EU customers since the 14:00 "
    "deploy. Revenue impact is live. Logs point at the payments service. "
    "Reporter: maria.k@acme.io. Priority field (raw): P2 / medium?"
)


def resolve_priority(raw: str) -> str:
    raw = raw.lower()
    if "p1" in raw or "critical" in raw:
        return "critical"
    if "p3" in raw or "low" in raw:
        return "low"
    return "medium"  # ambiguous "P2 / medium?" sinks to medium -- the bug


def is_urgent(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in ("urgent", "outage", "500", "revenue", "all eu", "down", "sev1", "p1"))


class ToolHandler(BaseHTTPRequestHandler):
    ticket_text = DEFAULT_TICKET  # set per run before serving

    def log_message(self, *a):  # keep stdout clean
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.endswith("/get_priority"):
            raw = parse_qs(u.query).get("raw", ["P2 / medium?"])[0]
            self._send(200, {"priority": resolve_priority(raw)})
        else:
            self._send(404, {"error": "unknown tool"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        u = urlparse(self.path)
        if u.path.endswith("/assign_ticket"):
            team = data.get("team", "")
            # The assignment service refuses to file a live outage under a
            # non-engineering queue. The wrong priority is what lands us here.
            if is_urgent(ToolHandler.ticket_text) and team not in ENGINEERING:
                self._send(500, {"ok": False,
                                 "error": f"refusing to assign urgent ticket to {team!r}"})
            else:
                self._send(200, {"ok": True, "assigned_to": team})
        elif u.path.endswith("/send_email"):
            self._send(200, {"ok": True, "delivered": True})
        else:
            self._send(404, {"error": "unknown tool"})


def start_tool_server(ticket_text: str) -> str:
    ToolHandler.ticket_text = ticket_text
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ToolHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def llm_triage(ticket_text: str, key: str) -> dict:
    url = os.environ.get("CASSETTE_LLM_URL",
                         "https://api.groq.com/openai/v1/chat/completions")
    model = os.environ.get("AGENT_MODEL", "llama-3.3-70b-versatile")
    try:
        r = httpx.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model, "temperature": 0, "max_tokens": 300,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content":
                     "You triage Jira tickets. Return STRICT JSON with keys "
                     "intent, email_subject, email_body. Be concise."},
                    {"role": "user", "content": ticket_text + "\nReturn only the JSON."},
                ],
            },
            timeout=30,
        )
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as exc:  # never crash the run on an LLM hiccup
        print(f"[agent] llm call failed ({exc}); using a fallback draft", file=sys.stderr)
        return {"intent": "Route by reported priority and notify reporter.",
                "email_subject": "Re: OPS-4521 - logged",
                "email_body": "Hi, we logged your ticket and placed it in the queue."}


def main() -> None:
    ticket_text = (os.environ.get("CASSETTE_AGENT_STDIN") or "").strip() or DEFAULT_TICKET
    key = os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    tools = start_tool_server(ticket_text)
    print(f"Triage run for: {ticket_text[:80]}...")

    draft = llm_triage(ticket_text, key)
    print(f"[agent] step 1 llm_call: intent = {draft.get('intent')!r}")

    pr = httpx.get(f"{tools}/get_priority", params={"raw": "P2 / medium?"}, timeout=10)
    priority = pr.json()["priority"]
    print(f"[agent] step 2 get_priority: resolved = {priority}")

    team = ROUTING.get(priority, "General Triage Queue")
    ar = httpx.post(f"{tools}/assign_ticket",
                    json={"ticket_key": "OPS-4521", "team": team}, timeout=10)
    print(f"[agent] step 3 assign_ticket -> {team}: HTTP {ar.status_code}")

    if ar.status_code < 400:
        httpx.post(f"{tools}/send_email",
                   json={"to": "maria.k@acme.io",
                         "subject": draft.get("email_subject", ""),
                         "body": draft.get("email_body", "")}, timeout=10)
        print("[agent] step 4 send_email: notified reporter")
    else:
        print("[agent] assignment rejected; the urgent ticket was misrouted "
              "(priority resolved to medium). Aborting before notifying reporter.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
