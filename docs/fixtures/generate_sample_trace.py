"""Regenerate docs/fixtures/sample_trace.json with real, fetchable blobs.

The fixture is the Day-1 contract everyone builds against. This script stores
each step's real payload in the blob store (docs/fixtures/blobs/) and writes the
trace with the matching sha256 refs, so downstream can actually resolve a blob,
not just read a placeholder hash.

Structure (status, causal_parents, step order) is kept identical to what the
merged ai_agents tests pin: step 4 (send_email) is the visible error; root cause
is step 2 (ambiguous priority). Transports are all "http" to match the Day-4
demo-safe slice.

Run from the repo root:  python docs/fixtures/generate_sample_trace.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = Path(__file__).resolve().parent
BLOB_DIR = FIXTURE_DIR / "blobs"
FIXTURE_PATH = FIXTURE_DIR / "sample_trace.json"

# Blobs live next to the fixture and are committed with it.
os.environ["CASSETTE_BLOB_DIR"] = str(BLOB_DIR)
sys.path.insert(0, str(REPO_ROOT))

from trace_store.blob_store import store_blob  # noqa: E402

REPORTER = "maria.k@acme.io"
TICKET_KEY = "OPS-4521"
BAD_EMAIL = (
    f"Hi {REPORTER}, we logged {TICKET_KEY}. This looks routine and has been "
    "placed in the general queue. Please do not escalate."
)


def _blob(obj) -> str:
    return store_blob(obj if isinstance(obj, str) else json.dumps(obj, indent=2))


def build_trace() -> dict:
    prompt = (
        f"Triage Jira ticket {TICKET_KEY}.\n"
        "Summary: Checkout API returning 500s for all EU customers.\n"
        "Priority field (raw): P2 / medium?\n"
        "Return JSON: intent, email_subject, email_body."
    )
    response = {
        "intent": "Routine ticket; route by reported priority and notify reporter.",
        "email_subject": f"Re: {TICKET_KEY} - logged",
        "email_body": BAD_EMAIL,
    }
    return {
        "schema_version": "1.0",
        "run_id": "run-fixture-001",
        "agent": "jira_triage_agent",
        "created_at_ms": 1750240000000,
        "mode": "record",
        "parent_run_id": None,
        "fork_step_id": None,
        "status": "error",
        "duration_ms": 1540,
        "steps": [
            {
                "step_id": 1,
                "type": "llm_call",
                "model": "llama-3.3-70b-versatile",
                "prompt_blob": _blob(prompt),
                "response_blob": _blob(response),
                "timestamp_ms": 1750240000000,
                "latency_ms": 820,
                "token_usage": {"prompt": 1150, "completion": 312},
                "confidence": 0.88,
                "side_effecting": False,
                "causal_parents": [],
                "status": "ok",
            },
            {
                "step_id": 2,
                "type": "tool_call",
                "tool": "get_priority",
                "transport": "http",
                "args_blob": _blob({"ticket_key": TICKET_KEY}),
                "result_blob": _blob({"priority": "medium", "raw": "P2 / medium?"}),
                "timestamp_ms": 1750240000825,
                "latency_ms": 180,
                "side_effecting": False,
                "causal_parents": [1],
                "status": "ok",
                "confidence": None,
            },
            {
                "step_id": 3,
                "type": "tool_call",
                "tool": "assign_ticket",
                "transport": "http",
                "args_blob": _blob({"ticket_key": TICKET_KEY, "team": "General Triage Queue"}),
                "result_blob": _blob({"ok": True, "ticket": TICKET_KEY, "assigned_to": "General Triage Queue"}),
                "timestamp_ms": 1750240001010,
                "latency_ms": 295,
                "side_effecting": True,
                "causal_parents": [1, 2],
                "status": "ok",
                "confidence": None,
            },
            {
                "step_id": 4,
                "type": "tool_call",
                "tool": "send_email",
                "transport": "http",
                "args_blob": _blob({"to": REPORTER, "subject": f"Re: {TICKET_KEY} - logged", "body": BAD_EMAIL}),
                "result_blob": _blob({"ok": False, "error": "email rejected: reporter mailbox unavailable"}),
                "timestamp_ms": 1750240001310,
                "latency_ms": 230,
                "side_effecting": True,
                "causal_parents": [3],
                "status": "error",
                "confidence": None,
            },
        ],
    }


def validate(trace: dict) -> None:
    """Validate against docs/trace_schema.json (jsonschema if present, else minimal)."""
    schema = json.loads((REPO_ROOT / "docs" / "trace_schema.json").read_text(encoding="utf-8"))
    try:
        import jsonschema  # type: ignore
        jsonschema.validate(trace, schema)
        print("validated with jsonschema: OK")
        return
    except ImportError:
        pass
    for key in schema["required"]:
        assert key in trace, f"missing required field: {key}"
    for step in trace["steps"]:
        for key in schema["definitions"]["step"]["required"]:
            assert key in step, f"step {step.get('step_id')} missing: {key}"
        assert step["type"] in ("llm_call", "tool_call")
    print("validated (minimal structural check): OK")


def main() -> None:
    trace = build_trace()
    validate(trace)
    FIXTURE_PATH.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE_PATH.relative_to(REPO_ROOT)}")
    print(f"blobs in {BLOB_DIR.relative_to(REPO_ROOT)} ({len(list(BLOB_DIR.iterdir()))} files)")


if __name__ == "__main__":
    main()
