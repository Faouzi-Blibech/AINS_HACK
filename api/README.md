# Cassette API

FastAPI backend that serves recorded agent runs from a SQLite-backed TraceStore.

## Running

```bash
uvicorn api.app:app --port 8000
```

The server self-seeds from `docs/fixtures/sample_trace.json` on first startup.
Blob files are resolved from `docs/fixtures/blobs/` by default (set
`CASSETTE_BLOB_DIR` to override).  The SQLite database is written to
`api/cassette.sqlite3` by default (set `CASSETTE_DB_PATH` to override); this
file is git-ignored.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/runs` | List all runs (summary metadata) |
| GET | `/runs/{run_id}` | Full trace for a run |
| GET | `/runs/{run_id}/steps/{step_id}` | Step with blobs resolved inline |

Interactive docs: `http://localhost:8000/docs`
