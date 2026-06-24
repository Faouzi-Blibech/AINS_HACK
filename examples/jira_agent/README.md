# Example: Jira-triage agent (import + record a failure)

A small, self-contained agent for demoing Cassette's import + failure detection.
It contains **no Cassette code**: it just makes an LLM call and a few tool calls
over HTTP, which Cassette records transparently when you import it.

## The deliberate bug

The ticket's priority field is ambiguous ("P2 / medium?"). The agent resolves it
to `medium`, which routes a live outage to the General Triage Queue. The
assignment service refuses to file an urgent ticket there and returns HTTP 500,
so the run fails at `assign_ticket`. The upstream cause is the priority step.

Steps recorded: `llm_call` (Groq) -> `get_priority` (read-only) ->
`assign_ticket` (side-effecting, **fails 500**).

## How to run it through the UI

1. Connect agent -> Import -> **Upload folder**, pick this `examples/jira_agent`
   folder. Run command: `python main.py`.
2. **Agent API key:** your Groq key (sent as `OPENAI_API_KEY`; the agent also
   accepts `GROQ_API_KEY` via Extra environment variables).
3. **Task / message to send:** optional. Paste a ticket, e.g.
   *"OPS urgent: checkout 500s for all EU customers, priority P2/medium?"*.
   Leave blank to use the bundled urgent-outage ticket (the failure still fires).
4. Import & record. The run opens with a failed `assign_ticket` step and the
   failure banner.

Only urgent/outage tickets misrouted to a non-engineering queue fail; a routine
ticket assigns cleanly (no false failure).
