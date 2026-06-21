# agent/: the agent under test

A toy Jira-triage agent used as the subject of recording and replay. It reads an incoming ticket, sets a priority, assigns a team, and emails the reporter. It is deliberately unmodified by Cassette: it talks to its LLM endpoint and tools normally, and Cassette intercepts that traffic transparently.

Two agents live here, both **unmodified by Cassette** (zero Cassette imports):

- `jira_triage_agent.py`: the canonical subject-under-test. One LLM call + 3 tools
  (`get_priority` read-only; `assign_ticket`, `send_email` side-effecting). It talks HTTP only;
  the recorder intercepts that traffic transparently. Run it: `python agent/jira_triage_agent.py`.
  Offline (deterministic stub LLM) by default; set `GROQ_API_KEY` to route the single LLM call
  to Groq (free, OpenAI-compatible, plain HTTP so the recorder can intercept). The bug is
  intentional: an ambiguous priority field resolves to `medium` at step 2 (`get_priority`),
  routing the ticket to the wrong team.
- `full_stack_agent.py`: a demo agent that natively uses **all three transports** in one run —
  an HTTP LLM call, an MCP tool call, and two local native-function tools (`enrich_priority`,
  `write_audit_log`). It exists to show http + mcp + sdk captured into one trace. It also
  contains zero Cassette code (a test enforces this).

## How each transport is captured (the agent is never modified)

The recorder is transport-**agnostic**: it captures whatever protocol the agent natively
speaks; it does not rewrite one transport into another. The agent's source is never touched.

| Transport | How it's captured | Agent change |
|---|---|---|
| **HTTP** (LLM + REST tools) | agent's traffic routed through the proxy via env | none |
| **MCP** (JSON-RPC over HTTP) | same proxy detects the JSON-RPC envelope | none (agent must natively speak MCP) |
| **SDK** (native Python tools) | the **driver** wraps the tool callables at runtime, by reference, before the run — install-from-outside instrumentation (like OpenTelemetry) | none |

**SDK capture without touching the agent.** Native calls have no network seam, so the recorder
installs the hook from *outside*: `recorder.record_session` reassigns the named tool callables
to recorded wrappers before running the agent and restores them afterward. The agent's source
is unchanged. `@record_tool` (from `recorder.sdk_hooks`) is the underlying wrapper and remains
available as an **opt-in** for teams who prefer an explicit annotation, but the default/demo
path applies it externally. SDK capture only happens under the in-process driver
(`recorder.record_session`), because the wrapper and the recording session share a process; the
subprocess proxy (`recorder.record`) only sees network traffic.

Demos:
- HTTP-only (jira agent, subprocess proxy): `python -m recorder.record --demo`
- All three transports (full_stack_agent, in-process): `python -m recorder.record_session --demo`
  and `python -m recorder.record_session --demo --replay` (record then hermetic replay).
