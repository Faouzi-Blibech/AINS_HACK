# agent/: the agent under test

A toy Jira-triage agent used as the subject of recording and replay. It reads an incoming ticket, sets a priority, assigns a team, and emails the reporter. It is deliberately unmodified by Cassette: it talks to its LLM endpoint and tools normally, and Cassette intercepts that traffic transparently.

- `jira_triage_agent.py`: the agent loop. Side-effecting tools (`send_email`, `assign_ticket`) are flagged so the recorder marks them `side_effecting: true`.
