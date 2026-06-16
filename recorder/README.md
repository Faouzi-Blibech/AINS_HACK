# recorder/: the interception layer

The transparent proxy that captures a live run without changing the agent. Proxying is the primary technical challenge of Use Case 2, and no single interception point covers how modern agents call tools, so Cassette intercepts at three layers.

| File | Mode | Intercepts |
|---|---|---|
| `http_proxy.py` | HTTP/TLS proxy | LLM API calls + REST tool calls |
| `mcp_proxy.py` | MCP proxy | MCP-protocol tool calls (Jira, Confluence) |
| `sdk_hooks.py` | SDK hooks | Native function-calling tools wired via SDK |

Each captured call becomes a step written to the trace store, with large payloads pushed to the blob store. The same code paths run in two directions: in **record** mode they forward to the live endpoint and capture the response; in **play** mode they return the recorded response and never forward.
