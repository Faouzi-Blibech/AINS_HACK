# Data Description

## Overview

Cassette uses a small, synthetic dataset to demonstrate and evaluate deterministic replay, side-effect containment, semantic matching, root-cause analysis, and failure-memory retrieval for AI agent debugging. The data models enterprise automation scenarios such as Jira ticket triage, workflow routing, summarization, classification, schema validation, and notification handling.

No production customer data is used. All tickets, traces, tool outputs, failure labels, IDs, and evaluation examples are generated fixtures for the AINS 2026 hackathon prototype.

## Sources Used

| Source | Path | Purpose |
|---|---|---|
| Project context | `CONTEXT.md` | Defines the product, trace contract, safety invariant, demo story, evaluation plan, and final-submission data-description requirement. |
| Trace schema | `docs/trace_schema.json` | Canonical JSON schema for recorded agent runs. This is the contract shared by recorder, trace store, replay engine, AI analysis, visualizer, and eval harness. |
| Sample trace | `docs/fixtures/sample_trace.json` | Representative recorded run for the Jira triage demo. Includes LLM calls, tool calls, causal links, blob references, confidence, and side-effect flags. |
| Blob fixture | `docs/fixtures/blobs/` | Content-addressed payload storage keyed by SHA-256. Demonstrates the pattern for storing large prompts, responses, arguments, and tool results outside the trace. |
| Evaluation scenarios | `eval/test_set/scenarios/*.json` | Six synthetic fault-injection scenarios with expected root-cause labels and replay-resolution oracles. |
| Semantic equivalence labels | `eval/test_set/equivalence_pairs.json` | Human-labeled expected vs actual text pairs used to evaluate the semantic matcher. |
| Evaluation results | `eval/results.json` | Current metric outputs and caveats for determinism, side-effect containment, semantic match precision/recall, and root-cause accuracy. |
| Failure-memory seed data | `api/failure_memory.py`, `ai_agents/failure_library.py` | Seeded recurring failure patterns used for Layer 2 retrieval-augmented debugging and preventive guidance. |
| Persistent failure schema | `trace_store/failure_library.py` | SQLite table definition for diagnosed failures written after analysis. |

## Data Formats

### Trace Files

Trace data is stored as JSON. A trace represents one agent run and contains top-level metadata plus an ordered `steps` array. Each step is either an `llm_call` or a `tool_call`.

The canonical schema is `docs/trace_schema.json`. Large payloads are referenced by SHA-256 blob IDs rather than stored inline.

### Blob Store

Large or sensitive payloads are stored separately as content-addressed blobs. Trace fields such as `prompt_blob`, `response_blob`, `args_blob`, and `result_blob` contain references in the form `sha256:<hash>`.

This keeps traces lightweight, deduplicates repeated payloads, and creates a natural boundary for redaction and access control.

### Evaluation Scenarios

Each scenario is a JSON fixture containing:

- `scenario_id`: stable scenario identifier.
- `injected_fault`: natural-language description of the seeded failure.
- `expected_root_cause_step`: gold root-cause step label.
- `resolves_at`: step IDs where a perturbation is expected to resolve the failure.
- `trace`: compact synthetic trace used by the eval harness.

The six current scenarios cover ambiguous priority, stale lookup data, incomplete context, intent misclassification, invalid schema validation, and wrong metadata enrichment.

### Semantic Equivalence Labels

The semantic-matcher dataset is a JSON array of labeled pairs:

- `expected`: target outcome text.
- `actual`: observed outcome text.
- `gold_equivalent`: boolean human label for semantic equivalence.

The pairs include both paraphrase-equivalent outcomes and intentionally non-equivalent outcomes.

### Failure Memory

Failure-memory entries appear in seeded Python data and in the SQLite-backed store schema. The persistent table is `failure_library` with:

- `id`: generated row ID.
- `failure_pattern`: diagnosed recurring failure pattern.
- `blame_step`: root-cause step ID.
- `fix_that_worked`: verified fix description.
- `agent_config`: optional agent version or configuration label.
- `determinism_rate`: optional fraction from `0.0` to `1.0`.
- `created_at`: insertion timestamp.

## Key Fields

### Run-Level Trace Fields

| Field | Description |
|---|---|
| `schema_version` | Trace schema version, currently `1.0`. |
| `run_id` | Unique identifier for a recorded or replayed run. |
| `agent` | Agent under test, such as `jira_triage_agent` or `triage_agent`. |
| `created_at_ms` | Run start time as epoch milliseconds. |
| `mode` | Run mode: `record`, `play`, or `record-over`. |
| `parent_run_id` | Parent run for a record-over fork, if applicable. |
| `fork_step_id` | Step where a record-over fork diverged, if applicable. |
| `status` | Overall run status: `ok`, `error`, `timeout`, or `aborted`. |
| `duration_ms` | Total run duration. |
| `steps` | Ordered list of LLM and tool-call steps. |

### Step-Level Trace Fields

| Field | Description |
|---|---|
| `step_id` | Ordered step identifier within the run. |
| `type` | Step type: `llm_call` or `tool_call`. |
| `timestamp_ms` | Step timestamp as epoch milliseconds. |
| `latency_ms` | Step latency. |
| `status` | Step result status: `ok` or `error`. |
| `causal_parents` | Prior step IDs whose outputs caused this step. Used by the Temporal Blame Graph. |
| `side_effecting` | Whether the call writes, sends, or modifies external state. These calls are always mocked during replay. |
| `confidence` | Optional self-reported confidence score from `0.0` to `1.0`. |
| `model` | LLM model name for `llm_call` steps. |
| `params` | LLM parameters, such as temperature or max tokens. |
| `prompt_blob` | SHA-256 reference to full prompt/context payload. |
| `response_blob` | SHA-256 reference to model response payload. |
| `token_usage` | Prompt and completion token counts. |
| `tool` | Tool name for `tool_call` steps. |
| `transport` | Interception transport: `http`, `mcp`, or `sdk`. |
| `args_blob` | SHA-256 reference to tool arguments. |
| `result_blob` | SHA-256 reference to tool result payload. |

### Eval-Only Fields

Some evaluation fixtures include compact helper fields that are not part of the canonical trace schema:

- `key_outputs`: reduced step output used by scripted evaluation.
- `injected_fault`: description of the seeded failure.
- `expected_root_cause_step`: gold label for root-cause evaluation.
- `resolves_at`: oracle for which perturbation points resolve the failure.

These fields are for benchmark convenience and should not be treated as production trace fields.

## Quality Notes

- The dataset is synthetic and intentionally small. It is suitable for prototype validation, demo reproducibility, and hackathon scoring, not for broad statistical claims.
- Evaluation scenarios are seeded with known faults and gold root-cause labels, which makes them useful for regression checks but easier than noisy real production traces.
- `eval/results.json` notes that the current `ScriptedReplay` path is a deterministic stand-in for the full divergence engine. It uses pre-specified `resolves_at` oracles rather than running a complete real replay implementation.
- Side-effect containment is measured from replay outcomes, and the design invariant requires `side_effecting: true` calls to execute zero times during replay.
- Semantic-match precision and recall depend on labeled equivalence pairs. The current set is balanced for demonstration but small.
- Some eval traces are intentionally compact and omit full schema-required operational fields such as timestamps and blob references. They should be read as eval fixtures, not full recorded traces.
- The sample trace and schema demonstrate the intended production shape: payloads are separated into blobs, causal parents are explicit, and side effects are annotated at the step level.

## Sensitivity Handling

Cassette is designed for debugging enterprise agents, so the data model assumes prompts, tool arguments, tool results, and generated outputs may contain sensitive business information in real deployments. The prototype handles sensitivity through the following rules:

- No real customer or production enterprise data is included in the repository fixtures.
- Large payloads are never stored inline in traces. They are referenced through `sha256:<hash>` blob IDs.
- Blob separation allows future redaction, encryption, retention policies, and role-based access around raw prompts, responses, tool arguments, and results.
- The `side_effecting` field is treated as a safety-critical annotation. During replay, any step marked `side_effecting: true` must be mocked and must not call the real external service.
- The failure-memory library stores summaries of diagnosed patterns and fixes, not raw payloads. In production, entries should avoid secrets, personal data, access tokens, customer identifiers, and private message content.
- Logs and UI views should prefer step metadata, hashes, redacted summaries, and explainability rationales over raw blob contents unless an authorized user explicitly opens the payload.
- Environment files and API keys are not part of the dataset and should remain outside committed fixtures.

## Current Dataset Inventory

| Dataset | Count | Notes |
|---|---:|---|
| Full sample traces | 1 | `docs/fixtures/sample_trace.json`. |
| Eval fault scenarios | 6 | `eval/test_set/scenarios/scenario_01.json` through `scenario_06.json`. |
| Semantic equivalence pairs | 13 | `eval/test_set/equivalence_pairs.json`. |
| API failure-memory seeds | 3 | Static API-facing entries in `api/failure_memory.py`. |
| AI failure-memory seeds | 5 | Retrieval entries in `ai_agents/failure_library.py`. |

## Intended Use

This dataset supports the final Cassette demo flow: record a failing run, replay it with zero side effects, identify the root cause, test a repair, verify the fix, and use failure memory to warn future runs about recurring patterns.

It should be extended with more synthetic scenarios, stronger human labels, and sanitized real-world pilot feedback before making claims about production accuracy.
