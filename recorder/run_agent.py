# recorder/run_agent.py
"""Proxy-free runner: record a local scripted agent via SDK hooks only.

Generic over any agent module that exposes:
  * ``call_model(messages) -> assistant message dict``
  * ``main() -> int``
  * ``SDK_TOOLS: dict[str, bool]``   (tool attribute name -> side_effecting)

Records straight into the store the UI serves (``./.cassette-data`` by default,
which is the docker bind mount), so the run appears in the dashboard right away.

Deterministic, no API key, no network. Does NOT import recorder.record_session
or recorder.http_proxy (no mitmproxy), mirroring recorder.run_hosted.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import uuid

from recorder.policy import load_policy
from recorder.sdk_hooks import record_llm, record_tool
from recorder.session import RecordingSession
from trace_store.store import TraceStore


def _default_paths() -> tuple[str, str]:
    home = os.environ.get("CASSETTE_HOME") or os.path.join(os.getcwd(), ".cassette-data")
    db = os.environ.get("CASSETTE_DB_PATH") or os.path.join(home, "cassette.sqlite3")
    blob = os.environ.get("CASSETTE_BLOB_DIR") or os.path.join(home, "blobs")
    return db, blob


def record_run(*, module: str, run_id: str, store: TraceStore) -> dict:
    """Instrument the agent's call_model + SDK tools, run it under a recording
    session, and return the recorded trace."""
    agent = importlib.import_module(module)
    sdk_tools = getattr(agent, "SDK_TOOLS", {})

    return _run_instrumented(agent, module, run_id, store)


def _run_instrumented(agent, module, run_id, store, *,
                      parent_run_id=None, fork_step_id=None) -> dict:
    sdk_tools = getattr(agent, "SDK_TOOLS", {})
    policy = load_policy()
    # Idempotent re-record: replace any existing run with this id (no UNIQUE clash).
    store.delete_run(run_id)
    session = RecordingSession(
        mode="record", store=store, run_id=run_id, policy=policy,
        register_run=True, schema_version="1.1", agent=module,
        parent_run_id=parent_run_id, fork_step_id=fork_step_id,
    )

    # Instrument from the outside; keep originals to restore afterwards.
    originals = {"call_model": agent.call_model}
    agent.call_model = record_llm(agent.call_model)
    for name, side_effecting in sdk_tools.items():
        originals[name] = getattr(agent, name)
        setattr(agent, name, record_tool(side_effecting=side_effecting)(getattr(agent, name)))

    try:
        with session:
            agent.main()
    finally:
        agent.call_model = originals.pop("call_model")
        for name, orig in originals.items():
            setattr(agent, name, orig)

    return store.get_run(run_id)


def record_over(*, module: str, base_run_id: str, override_env: str, value: str,
                store: TraceStore, run_id: str | None = None) -> dict:
    """Record-over: re-run the agent from scratch with one decision value
    overridden (via ``override_env``), producing a NEW run that shares the
    base run's prefix and then diverges. This is the live record-over the brief
    describes: inject a value and let the agent continue on a new trajectory.

    The fork is tagged with parent_run_id = base_run_id so it is excluded from
    the primary run list and rendered as a record-over branch.
    """
    agent = importlib.import_module(module)
    base = store.get_run(base_run_id)
    # The decision step = the first step whose tool reads the overridden value.
    fork_step_id = next(
        (s["step_id"] for s in base.get("steps", [])
         if s.get("tool") == getattr(agent, "DECISION_TOOL", "assess_severity")),
        None,
    )
    new_id = run_id or f"fork-{uuid.uuid4().hex[:8]}"
    prev = os.environ.get(override_env)
    os.environ[override_env] = value
    try:
        return _run_instrumented(agent, module, new_id, store,
                                 parent_run_id=base_run_id, fork_step_id=fork_step_id)
    finally:
        if prev is None:
            os.environ.pop(override_env, None)
        else:
            os.environ[override_env] = prev


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="recorder.run_agent",
                                 description="Record a local scripted agent via SDK hooks.")
    ap.add_argument("--module", default="agent.ops_incident_agent",
                    help="Agent module exposing call_model, main, and SDK_TOOLS.")
    ap.add_argument("--run-id", default=None, help="Run id (default: ops-<uuid>).")
    db_default, blob_default = _default_paths()
    ap.add_argument("--db", default=db_default, help="Path to the SQLite trace store.")
    ap.add_argument("--blob-dir", default=blob_default, help="Blob directory.")
    ap.add_argument("--model-label", default="ops-incident-agent (scripted)",
                    help="Label written to each llm_call step's model field.")
    args = ap.parse_args(argv)

    run_id = args.run_id or f"ops-{uuid.uuid4().hex[:8]}"
    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    os.makedirs(args.blob_dir, exist_ok=True)
    os.environ["CASSETTE_BLOB_DIR"] = args.blob_dir
    # record_llm reads CASSETTE_HOSTED_MODEL for the llm_call step's model field.
    os.environ["CASSETTE_HOSTED_MODEL"] = args.model_label

    store = TraceStore(args.db)
    try:
        trace = record_run(module=args.module, run_id=run_id, store=store)
    except Exception as exc:
        import traceback
        print(f"ERROR: run_id={run_id} failed: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    print(f"recorded run_id={run_id} steps={len(trace.get('steps', []))} db={args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
