# trace_store/: event log + content-addressed blob store

Persists a run as an append-only event log following [`../docs/trace_schema.json`](../docs/trace_schema.json).

- `store.py`: append-only step log keyed by `run_id` / `step_id` (SQLite for the prototype).
- `blob_store.py`: content-addressed key/value store. Key = sha256 of the content, value = the raw payload. If 100 runs share the same system prompt, it is stored once. Deduplication keeps storage linear.

The trace store holds small, structured step records; every large payload (prompt, context window, tool response) lives in the blob store and is referenced by its `sha256:...` hash.
