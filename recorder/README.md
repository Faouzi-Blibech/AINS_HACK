# recorder/: the interception layer

The transparent proxy that captures a live run without changing the agent. Proxying is the primary technical challenge of Use Case 2, and no single interception point covers how modern agents call tools, so Cassette intercepts at three layers.

| File | Mode | Intercepts |
|---|---|---|
| `http_proxy.py` | HTTP/TLS proxy | LLM API calls + REST tool calls |
| `mcp_proxy.py` | MCP proxy | MCP-protocol tool calls (Jira, Confluence) |
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
