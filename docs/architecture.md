# Architecture

Cassette has five layers, top to bottom. Remove the AI analysis layer and the system collapses to a tape recorder that can replay bytes but cannot tell you anything about why a run failed.

![Architecture](images/architecture.png)

## 1. Agent under test

A toy Jira-triage agent (reads incoming tickets, sets priority, assigns a team, notifies the reporter). It is unmodified: it does not know it is being recorded. See [`../agent/`](../agent/).

## 2. Interception layer

Sits transparently between the agent and its tools. Three interception modes cover the protocol gap that no single point covers:

| Mode | Intercepts | How |
|---|---|---|
| HTTP/TLS proxy | LLM API calls + REST tool calls | Route agent traffic through a local proxy |
| MCP proxy | MCP-protocol tool calls (Jira, Confluence) | Wrap the MCP client layer |
| SDK hooks | Native function-calling tools | Decorator / middleware on tool definitions |

See [`../recorder/`](../recorder/).

## 3. Trace store + blob store

The trace store is an append-only event log keyed by `run_id` / `step_id`, following the contract in [`trace_schema.json`](trace_schema.json). Payloads are never stored inline: each large value (prompt, context window, tool response) is content-addressed by its sha256 hash and stored once in the blob store. Deduplication keeps storage linear, so 10x volume is a scale-out, not a redesign.

See [`../trace_store/`](../trace_store/).

## 4. Replay engine

Three modes:

- **Deterministic replay (Play):** re-run the agent step-by-step. Every tool call returns its recorded response from the tape. No live endpoint is hit. Side-effecting calls are always mocked.
- **Divergence (Record-over):** edit a prompt or tool result at step N. The call's identity changes, the recorded response no longer matches, so the engine forks a new branch and the agent continues down a new trajectory.
- **State snapshot and resume:** serialize the agent's context window at any step, then resume or inspect from that exact state.

The key invariant: `side_effecting: true` calls are ALWAYS mocked during replay. No exceptions. This is the core safety guarantee.

See [`../replay_engine/`](../replay_engine/).

## 5. AI analysis layer

Five AI components turn the trace into diagnosis and repair:

1. **Semantic matcher** decides whether two outputs express the same intent; scores replay fidelity and determinism.
2. **Mock synthesizer** generates a plausible tool response when divergence mode produces a call with no recorded response.
3. **Root-cause analyzer (Temporal Blame Graph)** traces backward through `causal_parent` links and assigns a blame score per step.
4. **Counterfactual repair agent** generates N fix variants, replays them in parallel, and ranks by outcome.
5. **Debug agent** turns a plain-English instruction into a structurally valid JSON injection and fires the replay.

A confidence / self-evaluation layer attaches an uncertainty score to every output and flags low-confidence steps for human review.

See [`../ai_agents/`](../ai_agents/).

## Outputs: replay, visualization, evaluation

- **Replay engine** produces the deterministic re-run and the forked trajectories.
- **Visualizer** ([`../visualizer/`](../visualizer/)) renders the trajectory tree, step inspector, and divergence diff.
- **Eval harness** ([`../eval/`](../eval/)) reports the four metrics against a synthetic test set.
