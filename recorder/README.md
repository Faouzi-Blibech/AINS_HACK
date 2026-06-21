# recorder/: the interception layer

The transparent proxy that captures a live run without changing the agent. Proxying is the primary technical challenge of Use Case 2, and no single interception point covers how modern agents call tools, so Cassette intercepts at three layers.

| File | Mode | Intercepts |
|---|---|---|
| `http_proxy.py` | HTTP/TLS proxy | LLM API calls + REST tool calls |
| `mcp_proxy.py` | MCP transport router | MCP-protocol tool calls (Jira, Confluence) |
| `sdk_hooks.py` | SDK hooks | Native function-calling tools wired via SDK |

Each captured call becomes a step written to the trace store, with large payloads pushed to the blob store. The same code paths run in two directions: in **record** mode they forward to the live endpoint and capture the response; in **play** mode they return the recorded response and never forward.

## HTTP record path (implemented)

`http_proxy.py` is a real **mitmproxy forward proxy**. Point any agent at it via env (`HTTP_PROXY`/`HTTPS_PROXY` + `SSL_CERT_FILE` for the mitmproxy CA, all printed by `Recorder.env()`); it records every LLM + REST tool call into a schema-valid trace, payloads stored as sha256 blobs. It is **agent-agnostic** (no `agent/` imports) and driven by a declarative `policy.yaml`: classification (llm vs tool), side-effect rules, and a secret-redaction denylist. Secrets never hit disk (headers are not persisted; denylisted body fields are redacted). CA trust is per-process only (`SSL_CERT_FILE`), never the system store.

Record any agent (generic CLI): `python -m recorder.record -- <your agent command>`. Hermetic Jira demo: `python -m recorder.record --demo`.

## Replay (play mode)

Re-run a recorded agent through the proxy, served entirely from tape:

    python -m recorder.replay --demo

The proxy computes each request's identity and delegates to the replay engine
(`replay_engine.Replayer.response_for`), which serves the recorded response.
Hermetic: no upstream runs during replay, side-effecting calls are served but
never executed (`live_executed` stays 0), and a faithful replay reports
`divergences: 0`. For an arbitrary recorded run:

    python -m recorder.replay --run-id NAME --tape tape.sqlite3 --blob-dir blobs -- <agent cmd>

## MCP record + replay (implemented)

MCP over Streamable HTTP is JSON-RPC 2.0 carried as HTTP POST bodies, so it
rides the same real proxy: no second interception point. `mcp_proxy.py` is the
MCP half of a transport router. `capture.compute_identity` (shared by record and
replay) detects a JSON-RPC envelope, tags the step `transport: "mcp"`, pulls the
real tool name + arguments from `params` (not the URL path, since every
`tools/call` hits one endpoint), and builds an **id-independent identity** so a
replayed handshake, which issues fresh JSON-RPC ids, still matches the tape. The
identity also strips `policy.yaml` `volatile_fields` from the arguments at any
depth (same as the HTTP path), so a tool that takes a per-call timestamp or
nonce still replays without a false divergence.
Side-effects are classified by tool name (`policy.yaml` `mcp.read_only_tools`);
`initialize`, `tools/list`, and notifications are never side-effecting, so the
handshake replays cleanly offline.

Hermetic MCP demo (record an MCP-over-HTTP agent, then replay it from tape):

    python -m recorder.record --demo --mcp
    python -m recorder.replay --demo --mcp

Replay shuts the MCP server down first: served 6/6 from tape, 2 side-effecting
tools served but never executed (`live_executed: 0`), `divergences: 0`.

stdio-transport MCP servers (subprocess JSON-RPC over stdin/stdout) are a
documented follow-up: the JSON-RPC parsing in `mcp_proxy.py` is transport-neutral
and reusable, but stdio needs a separate stream shim rather than the HTTP proxy.

## SDK hooks — the third transport (implemented, agent stays untouched)

Native function-calling tools never touch the network, so the proxy cannot see them. The hook
is therefore installed **from outside the agent at runtime** — install-from-outside
instrumentation, the same approach as OpenTelemetry/`wrapt` — so the agent's source is never
modified. `sdk_hooks.py` provides the underlying wrapper `record_tool(side_effecting=...)`, a
**framework-neutral** wrapper for any Python callable:

- **No active recording session** → pure passthrough (one contextvar read); the tool runs
  normally with ~zero overhead.
- **Record** → run the tool, then store an `sdk` `tool_call` step (args + result redacted via
  `policy.redact_body`, large payloads to the blob store), keyed by the same transport-router
  identity used by HTTP/MCP (`capture.sdk_identity`, with `volatile_fields` stripping).
- **Replay** → serve the recorded result and **never execute the function**; a side-effecting
  tool is never run in replay even on a cache miss (fail closed → `ReplayDivergence`).

Sync and async tools are both supported. `record_tool` is also available as an **opt-in**
decorator for teams who prefer an explicit annotation, but the default path applies it
externally (see the driver below), so no agent change is required.

### Single recorder for all three transports

Because SDK interception is in-process, `session.py` holds a `RecordingSession` in a
`contextvars` variable — the single source of truth for a run (mode, store, run_id, policy,
and a thread-safe **shared step-id allocator**). The HTTP/MCP mitmproxy thread pulls step-ids
from that same allocator (`CaptureAddon`/`Recorder` accept a `step_id_source`), so all three
transports land in **one trace** with one collision-free step sequence.

`record_session.py` is the agent-agnostic in-process driver. It loads the agent by
`"module:function"` (so `recorder/` keeps zero `agent/` imports), **transparently instruments
the named SDK tools** by reassigning their module attributes to recorded wrappers before the
run and restoring them afterward (`_instrument_sdk`/`_restore_sdk` + the `sdk_tools` arg), starts
the proxy thread bound to the session's store, runs the agent in-process, and prints the unified
trace (record) or a merged replay report. The demo agent (`agent/full_stack_agent.py`) has zero
Cassette imports — a test asserts this. Hermetic 3-transport demo:

    python -m recorder.record_session --demo            # record http+mcp+sdk in one run
    python -m recorder.record_session --demo --replay   # then replay from tape

Replay shuts the upstream first and reports `live_executed: 0`, `divergences: 0`,
`served == recorded_steps` — side-effecting MCP and SDK tools are served from tape but never
executed.
