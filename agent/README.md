# agent/: the agent under test

A toy Jira-triage agent used as the subject of recording and replay. It reads an incoming ticket, sets a priority, assigns a team, and emails the reporter. It is deliberately unmodified by Cassette: it talks to its LLM endpoint and tools normally, and Cassette intercepts that traffic transparently.

- `jira_triage_agent.py`: the agent loop. Side-effecting tools (`send_email`, `assign_ticket`) are flagged so the recorder marks them `side_effecting: true`.

Run it: `python agent/jira_triage_agent.py`. It runs offline (deterministic stub LLM) by default; set `GROQ_API_KEY` to route the single LLM call to Groq (free, OpenAI-compatible, over plain HTTP so the recorder can intercept it). The bug is intentional: an ambiguous priority field resolves to `medium` at step 2 (`get_priority`), routing the ticket to the wrong team.

## Transport plan

The agent calls its tools normally; the recorder decides which interception mode captures each call. For the Day-4 demo-safe slice every tool is recorded over **HTTP** (the only path that must work end to end), which is what `docs/fixtures/sample_trace.json` reflects.

| Tool | side_effecting | Demo-safe (Day 4) | Breadth (Day 5) |
|---|---|---|---|
| `get_priority` | no | http | http |
| `assign_ticket` | yes | http | mcp |
| `send_email` | yes | http | sdk |

The mcp/sdk variants are added on Day 5 to showcase all three modes; the agent code never changes, only the recorder.
