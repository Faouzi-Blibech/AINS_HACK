# Cassette: Agent Execution Tracer and Deterministic Replay Engine

> A flight recorder for AI agents: **record** any live run, **replay** it deterministically with zero live API calls, and let an AI debugging layer tell you **why it failed** and **which fix works**, without ever touching production.

**AINS Hackathon 2026 - AI for Enterprise Automation - Use Case 2**

Working prototype: import and record any agent, deterministic replay, a Temporal Blame Graph, an AI debug agent and counterfactual repair, a self-learning failure memory with semantic recall, and a live evaluation dashboard, all behind a full React UI.

---


## Quickstart

```bash
# 1. clone, then from the repo root:
docker compose up --build
# 2. open the UI
http://localhost:5173
```

The bundled demo replays recorded runs with **no API key**. To run the live AI layer (blame verdict, debug agent, semantic failure recall) and to record new agents, add a key:

```bash
# .env in the repo root (compose reads it automatically)
GROQ_API_KEY=your_key_here
```

Groq is recommended (free tier, reliable tool calling). Without a key, the AI layer falls back to deterministic heuristics so the demo still runs.

**30-second smoke test of import (no key):** open **Connect agent**, set source to `examples/http_agent`, command `python main.py`, click **Import and record**. A bundled example agent makes one HTTPS call, so you immediately see a recorded trace.

---

## 1. The problem

When traditional software fails, you read the stack trace, reproduce the bug, and patch it. When an **AI agent** fails in production (it routes a ticket to the wrong team, calls a tool with a malformed argument, or quietly drafts an email it was never meant to send) almost none of that holds:

- **You cannot reproduce it.** The agent's behavior emerges from a sampled LLM, a live environment, and external tools, all of which shift between runs. Run it again an hour later and it reasons along a different path. The failure has dissolved.
- **You cannot safely re-run it.** The tools an agent calls are rarely read-only. They send messages, overwrite records, spend money. Debugging a faulty agent by re-running it risks firing the very side effect you were trying to understand.
- **You cannot recover what it knew.** The exact context the agent held at the decisive step vanishes the instant the run ends, and with it any hope of reconstructing what happened weeks later for an audit.

The engineer is left holding a flat log with no safe path forward. **What is missing is a recording layer that faithfully captures a live run in full (every model call, every tool exchange, every state change) paired with a replay mode that re-executes that run against the captured responses, deterministically, without ever reaching a live endpoint.** And because a trace no human can interpret is just a bigger log, that recorder needs an **intelligence layer** on top that reads the trajectory, pinpoints the fault, and proposes a fix.

---

## 2. The solution: Cassette

Cassette is a **transparent recorder** that sits between an unmodified agent and the outside world. No changes to the agent's logic: you point its traffic at Cassette, and it records everything. It runs in three modes, following a tape metaphor that explains the whole system in one breath:

| Mode | What it does |
|---|---|
| **Record** | Capture a live run to "tape": every LLM call (full prompt, context window, model, params, response) and every tool call (name, args, exact response payload, latency, status), linked into a parent to child trajectory tree. Large payloads are content-addressed (hashed) and stored once. |
| **Play** | Replay the run deterministically, served entirely from the tape. When the agent makes a call, Cassette matches it to the recording and returns the recorded response. No LLM is sampled and **no tool fires**. Side-effecting calls are **always** mocked: the core safety guarantee. |
| **Record-over** | Edit a prompt, a system message, or a tool result mid-replay. That edit changes the call's identity, so the recorded response no longer matches, and Cassette **forks a new branch** from that step. The agent continues down a new trajectory, which the UI diffs against the original. The recorder becomes a what-if debugger. |

### Transparent interception: the primary technical challenge

No single interception point covers how modern agents call tools. Cassette intercepts at **three layers**, addressing a real protocol gap:

| Transport | Intercepts | How |
|---|---|---|
| **HTTP/TLS proxy** | LLM API calls + REST tool calls | Route agent traffic through a local proxy |
| **MCP proxy** | MCP-protocol tool calls (Jira, Confluence, and similar) | JSON-RPC envelope detection on the same proxy (no second interception point) |
| **SDK hooks** | Native function-calling tools wired via SDK | `record_tool` wrap installed from outside the agent at runtime |

All three transports are implemented and the agent is never modified. HTTP and MCP are captured by an agent-agnostic mitmproxy forward proxy (per-process CA trust, never the system store; secret redaction on capture). SDK (native function) tools have no network seam, so the hook is installed from outside the agent at runtime (the same approach as OpenTelemetry), wrapping the tool callables before the run and restoring them after. A single run records all three transports into one schema-versioned trace.

---

## 3. Import and record any agent

Cassette records your own agent with no code change. You give it one input and it does the rest: it clones or stages the agent, runs it with the recording proxy and CA trust wired in automatically, and captures the run.

Open **Connect agent** in the UI. Three ways to provide the agent:

- **Git URL** (for example `https://github.com/you/agent.git`), optional branch.
- **Local path** to a folder.
- **Upload** an agent folder from your machine.

Optional fields:

- **Run command** (for example `python main.py`).
- **Task / message**: sent to the agent's stdin so interactive (chat / prompt-loop) agents actually run and produce a trace.
- **Agent API key** and **extra environment variables** (one `KEY=VALUE` per line, for agents that need more than one key). Keys are passed to the agent for that run only and are never stored.

Via the API:

```bash
curl -X POST http://localhost:8000/agents/import \
  -H 'Content-Type: application/json' \
  -d '{"source": "https://github.com/you/agent.git", "command": "python main.py"}'
```

What gets captured: **HTTP and MCP** calls for an agent in any language, transparently; **native in-process Python tools** when declared in a tool manifest. The agent's source is never modified.

Where the agent runs: if a Docker daemon is reachable (host dev mode), Cassette runs the imported agent in an isolated container. Under `docker compose up` (where the API container has no Docker daemon) it falls back to recording the agent inside the API container, so import works from a fresh clone with no extra setup. If an agent fails (missing key, crash, or no calls), the error is surfaced rather than producing a silent empty trace.

For developers, the recorder also runs from the command line:

```bash
python -m recorder.record --demo                  # hermetic HTTP-only demo
python -m recorder.record --demo --mcp            # MCP-over-HTTP demo
python -m recorder.record_session --demo          # all 3 transports in one run
python -m recorder.record_session --demo --replay # then replay from tape (zero live calls)
```

---

## 4. Core AI mechanism: AI is the mechanism, not a feature

Replay on its own is conventional infrastructure (hashing, proxying, key-matching), and on its own it is just a tape recorder. Cassette's product is **automated failure diagnosis and repair for non-deterministic agents.** Replay is the safe substrate that makes that possible; the actual job, "tell me why my agent failed, and which fix actually works", is performed by AI. Remove the AI layer and the verdict, the blame attribution, the recall, and the repair all collapse into a raw JSON dump.

| Component | What it does | Why it requires AI |
|---|---|---|
| **Semantic matcher** | Decides whether a replayed run behaved "the same" ("routed to backend" vs "assigned to Backend Engineers"). Scores replay fidelity and determinism. | Exact-string comparison fails on non-deterministic agents; equivalence is a semantic judgment. |
| **Root-cause analyzer (Temporal Blame Graph)** | Walks backward through causal links and assigns a blame score to every prior step (perturb a step's output, did the outcome change?). Verdict: "Step 8 is where it failed. Step 2 is why." Red marks the root cause, orange contributors, grey innocent. | Attributing blame across an unstructured reasoning trajectory is a reasoning task. |
| **Debug agent (natural language to fix)** | The engineer types "at step 2 the priority should have been high, not medium"; the agent builds the exact, valid change, forks the run, re-runs it, and reports whether the failure is actually resolved. | Without the LLM the engineer is back to hand-editing raw trace payloads. |
| **Counterfactual repair** | Generates several reworded variants of the failing step, replays them (downstream mocked), and ranks them by outcome. | Generating meaningful fix variants requires an LLM. |
| **Failure memory (semantic recall)** | Describes a failure in plain language, then ranks the library of past failures by meaning (not keyword), returning a match score, a rationale, and the fix that worked. Learns new patterns when a fix resolves a failure. | Matching failures by meaning across agents is beyond retrieval; see section 6. |
| **Confidence / self-evaluation** | Every AI output carries an uncertainty score; low-confidence results are flagged for human review. | Surfaces where the system is unsure instead of asserting blindly. |

### On non-determinism (the central technical concern)

Tool responses are fixed by the recorded tape, so the environment is deterministic on replay. The LLM itself may still vary, and rather than pretend otherwise, Cassette quantifies it: the semantic matcher scores behavioral equivalence, a determinism-rate metric reports how often replays reproduce the original tool-call sequence, and an AI-reliability study re-runs each AI check multiple times to measure consistency.

---

## 5. The debugging loop (detect, locate, fix, verify)

Open a failed run from the **Runs** dashboard to see the full execution trace:

- The **trajectory graph** shows every step on a causal graph; click any step to see the exact prompt, context, and tool payloads it had at that moment.
- The **Temporal Blame Graph** colors the nodes (red root cause, orange contributor, grey innocent) and states the verdict: "Step X is where it failed. Step Y is why."
- The **debug agent** turns a plain-English fix into a forked re-run and reports a pass/fail verdict (was error, now ok).
- The **side-effect counter stays at 0** throughout: nothing real fires during replay or record-over.

The Runs dashboard lists every recorded run with outcome, mode, and step count, and lets you delete runs you no longer need (forks are removed with their parent).

![Architecture](docs/images/architecture.png)
![Data flow](docs/images/data_flow.png)
![Temporal blame graph](docs/images/temporal_blame_graph.png)
![Safe replay](docs/images/safe_replay.png)

---

## 6. Failure memory: learn once, recall by meaning

Every failure Cassette diagnoses and fixes is stored as a pattern (what went wrong, the blame step, the fix that worked). The **Failure memory** page is a live recall tool: describe a situation in plain language and the AI ranks the whole library by meaning, returning each match with a relevance score and a rationale, plus the fix that worked last time. This is semantic retrieval, not keyword or step-number matching, so it generalizes across agents. When a record-over actually turns a failing run into a passing one, the new pattern is learned and becomes recallable on future runs.

---

## 7. Explainability layer

Every output is traceable, carries uncertainty, and shows the evidence behind it:

- **Decision trace:** the trajectory graph plus `causal_parents` links show exactly which steps fed each decision; the blame graph shows the backward perturbation path from the failure to its root cause.
- **Evidence:** the step inspector resolves the exact prompt, context, arguments, and results (content-addressed blobs) for any step.
- **Confidence:** the blame verdict, debug-agent fix, counterfactual ranking, and failure recall each carry a confidence score; low-confidence results are flagged for review.
- **Rationale:** the failure-memory recall and root-cause verdict include a one-line natural-language reason.
- **Safety:** the side-effects banner confirms zero live side effects on replay.

---

## 8. Evaluation

The **Evaluation** page is a live dashboard computed from the recorded runs and the test set:

- A scorecard: runs evaluated, deterministic replay rate, side-effecting calls intercepted vs executed live (0), and AI reliability.
- Replay-and-safety metrics from the run store, and AI-quality metrics from the synthetic test set.
- An AI-reliability breakdown: each AI check (debug agent, blame verdict, counterfactual, semantic matcher) run multiple times to show it is consistent, not lucky.

| Metric | Definition | Target |
|---|---|---|
| Determinism rate | % of replays that reproduce the original tool-call sequence | 100% |
| Side-effect containment | side-effecting tool calls executed during replay | 0 (always) |
| Semantic-match precision / recall | matcher vs human-labeled equivalences | > 0.85 |
| Root-cause accuracy | injected failures where the blame graph names the correct root cause | > 75% |
| AI reliability | correct answers across repeated runs of each AI check | high |

Full protocol, results, and caveats: [`docs/evaluation_report.md`](docs/evaluation_report.md). Reproduce locally:

```bash
python -m eval.harness                 # writes eval/results.json
python -m ai_agents.demo_reliability   # writes eval/reliability.json (needs a key)
```

---

## 9. Mapping to Use Case 2

| Capability expected | How Cassette delivers it |
|---|---|
| **Trajectory recording** | The proxy logs every LLM call, prompt, context variable, and tool response as a linked span tree. |
| **Deterministic replay** | Play mode re-executes step by step, returning recorded responses. Zero live endpoints hit. |
| **State snapshotting** | The agent context at each step is captured and inspectable. |
| **Divergence support** | Record-over forks the trajectory when a developer edits a prompt or tool result mid-replay. |

### Target users

- **AI / agent engineers** (primary): debugging non-deterministic failures, today armed with only flat logs.
- **Platform and MLOps teams**: observability, reproducibility, and regression-safety across a fleet of agents.
- **QA and red-teamers**: replaying and mutating adversarial runs safely, with no live side effects.
- **Compliance and risk officers**: a frozen, auditable record of exactly what an agent saw and did.

---

## 10. Architecture and technical direction

| Layer | Choice | Why |
|---|---|---|
| Language | Python | Native language of the agent ecosystem. |
| Interception | HTTP proxy + MCP proxy + SDK hooks | Keeps the agent unmodified across frameworks, raw SDKs, and MCP-based agents. |
| Trace store | SQLite + JSON spans, content-addressed blob store | Queryable; blob dedup keeps storage linear, so 10x volume is a scale-out, not a redesign. |
| AI layer | Groq (OpenAI-compatible API) | Powers the matcher, blame graph, counterfactual, debug agent, and failure recall. |
| Interface | React web app | Trajectory graph, step inspector, divergence diff, failure memory, evaluation. |

Component-by-component breakdown: [`docs/architecture.md`](docs/architecture.md). Trace contract: [`docs/trace_schema.json`](docs/trace_schema.json).

---

## 11. Repository structure

```
AINS_HACK/
├── README.md                  this file
├── requirements.txt           full deps (recorder, proxy, MCP, tests)
├── requirements-api.txt       API image deps
├── docker-compose.yml         api + ui
├── docs/
│   ├── images/                architecture and flow diagrams
│   ├── architecture.md        component-by-component breakdown
│   ├── trace_schema.json      the trace contract (shared by all modules)
│   ├── data_description.md     sources, formats, key fields, quality, sensitivity
│   ├── evaluation_report.md    metrics, test protocol, results, caveats
│   └── demo_scenario.md        end-to-end demo script
├── agent/                     example agents under test
├── examples/http_agent/       minimal zero-key example for the import demo
├── recorder/                  interception layer (HTTP / MCP / SDK) + import driver
├── trace_store/               append-only event log + content-addressed blob store + failure library
├── replay_engine/             deterministic replay, divergence, snapshot
├── ai_agents/                 semantic matcher, root-cause, counterfactual, debug agent, failure recall
├── visualizer/                React UI
└── eval/                      evaluation harness + synthetic test set
```

---

## 12. Setup details

**Run the app (recommended):**

```bash
docker compose up --build
# open http://localhost:5173
```

The API serves on `http://localhost:8000`. Recordings live in a bind-mounted store; set `CASSETTE_HOME` before `docker compose up` to relocate it.

**Live AI + recording:** add `GROQ_API_KEY` to `.env` in the repo root (see `.env.example`). Compose passes it into the API container automatically.

**Run the test suite:**

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q --import-mode=importlib
```

---

## 13. Limitations and next steps

- The single-root blame verdict is sharpest when a run carries a resolution signal; on an arbitrary failure it still scores the causal chain but may report that no single upstream step explains it.
- Record-over re-runs agents that are re-runnable; faithful-replay forks cover the rest.
- Under `docker compose`, an imported agent shares the API container's Python environment; agents with conflicting dependencies are best run in host dev mode (isolated container).
- Next: broader auto-detection of agent entry points, drift detection across runs over time, and validation with a real enterprise engineer.

---

*AINS Hackathon 2026 - AI for Enterprise Automation - Use Case 2.*
