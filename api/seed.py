"""Seed the TraceStore with fixture data on first startup.

Loads the sample trace from docs/fixtures/sample_trace.json and inserts
two small extra runs so the runs list has multiple rows.  All inserts are
idempotent: the function checks list_runs() first and skips any run that
already exists.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Repo root relative to this file: api/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_PATH = _REPO_ROOT / "docs" / "fixtures" / "sample_trace.json"

# Blob references that are guaranteed to exist in docs/fixtures/blobs/
# (used by the extra stub runs so resolution does not break)
_EXISTING_BLOBS = {
    "args_blob": "sha256:6ccf67662e73ed737c2965abe2c3f845d607ed83ef9b093c4984d0c3c9b541e7",
    "result_blob": "sha256:3c34e3763cf9d4cddd9e759c33ff6de8fa9e6a27be4564f78a1565403fbe8ae8",
    "prompt_blob": "sha256:9ba79d451fa42c006dfeb1701a541a980102beb578cea5a342e094feefc6d9af",
    "response_blob": "sha256:6989e5ad668feaae451d0f94ee29278ff39a47a12768b74999289c029a6db9d5",
}

_EXTRA_RUNS: list[dict[str, Any]] = [
    {
        "run_id": "run-ok-0002",
        "agent": "stub_agent",
        "mode": "record",
        "created_at_ms": 1750240100000,
        "status": "ok",
        "steps": [
            {
                "step_id": 1,
                "type": "llm_call",
                "timestamp_ms": 1750240100000,
                "latency_ms": 200,
                "status": "ok",
                "model": "llama-3.3-70b-versatile",
                "prompt_blob": _EXISTING_BLOBS["prompt_blob"],
                "response_blob": _EXISTING_BLOBS["response_blob"],
                "side_effecting": False,
                "causal_parents": [],
            },
            {
                "step_id": 2,
                "type": "tool_call",
                "timestamp_ms": 1750240100205,
                "latency_ms": 50,
                "status": "ok",
                "tool": "get_priority",
                "transport": "http",
                "args_blob": _EXISTING_BLOBS["args_blob"],
                "result_blob": _EXISTING_BLOBS["result_blob"],
                "side_effecting": False,
                "causal_parents": [1],
            },
        ],
    },
    {
        "run_id": "run-ok-0003",
        "agent": "stub_agent",
        "mode": "record",
        "created_at_ms": 1750240200000,
        "status": "ok",
        "steps": [
            {
                "step_id": 1,
                "type": "llm_call",
                "timestamp_ms": 1750240200000,
                "latency_ms": 180,
                "status": "ok",
                "model": "llama-3.3-70b-versatile",
                "prompt_blob": _EXISTING_BLOBS["prompt_blob"],
                "response_blob": _EXISTING_BLOBS["response_blob"],
                "side_effecting": False,
                "causal_parents": [],
            },
            {
                "step_id": 2,
                "type": "tool_call",
                "timestamp_ms": 1750240200185,
                "latency_ms": 45,
                "status": "ok",
                "tool": "get_priority",
                "transport": "http",
                "args_blob": _EXISTING_BLOBS["args_blob"],
                "result_blob": _EXISTING_BLOBS["result_blob"],
                "side_effecting": False,
                "causal_parents": [1],
            },
        ],
    },
]


def _insert_run(store: Any, run: dict[str, Any]) -> None:
    """Insert a single run dict (with a 'steps' key) into the store."""
    store.start_run(
        run["run_id"],
        run.get("agent", ""),
        run.get("mode", "record"),
        created_at_ms=run.get("created_at_ms"),
    )
    for step in run.get("steps", []):
        store.append_step(run["run_id"], step)
    store.finish_run(
        run["run_id"],
        status=run.get("status", "ok"),
        duration_ms=run.get("duration_ms"),
    )


def seed_store(store: Any) -> None:
    """Seed *store* with fixture and stub runs if they are not already present.

    Idempotent: skips any run that already appears in store.list_runs().
    """
    existing_ids = {r["run_id"] for r in store.list_runs()}

    # Seed the main fixture run
    if "run-fixture-001" not in existing_ids:
        with open(_FIXTURE_PATH, encoding="utf-8") as fh:
            trace = json.load(fh)
        _insert_run(store, trace)

    # Seed the two extra stub runs
    for run in _EXTRA_RUNS:
        if run["run_id"] not in existing_ids:
            _insert_run(store, run)
