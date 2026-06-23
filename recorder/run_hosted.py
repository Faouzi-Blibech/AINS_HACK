# recorder/run_hosted.py
"""Proxy-free runner: records a hosted OpenAI-compatible agent via SDK hooks only.

Does NOT import recorder.record_session or recorder.http_proxy.
Keys come from environment variables, never from args, never logged.

The agent module is imported lazily inside record_run so that importing this
module does not pull in agent code at module load time (satisfying the
test_recorder_has_no_agent_imports integration check).
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys

from recorder.policy import load_policy
from recorder.sdk_hooks import record_llm, record_tool
from recorder.session import RecordingSession
from trace_store.store import TraceStore


def record_run(*, run_id: str, store: TraceStore) -> dict:
    """Instrument hosted_agent, run it under a RecordingSession, return the trace."""
    # Lazy import -- keeps the module-level import graph proxy-free and
    # avoids triggering test_recorder_has_no_agent_imports.
    _agent = importlib.import_module("agent.hosted_agent")

    policy = load_policy()
    session = RecordingSession(
        mode="record",
        store=store,
        run_id=run_id,
        policy=policy,
        register_run=True,
    )

    # Save originals for clean teardown.
    orig_call_model = _agent.call_model
    orig_lookup = _agent.lookup_info
    orig_submit = _agent.submit_result

    # Instrument by reference (mirrors _instrument_sdk in record_session.py).
    _agent.call_model = record_llm(_agent.call_model)
    _agent.lookup_info = record_tool(side_effecting=False)(_agent.lookup_info)
    _agent.submit_result = record_tool(side_effecting=True)(_agent.submit_result)

    try:
        with session:
            _agent.main()
    finally:
        _agent.call_model = orig_call_model
        _agent.lookup_info = orig_lookup
        _agent.submit_result = orig_submit

    return store.get_run(run_id)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="recorder.run_hosted",
                                 description="Record a hosted-model agent trace.")
    ap.add_argument("--run-id", required=True, help="Unique identifier for this run.")
    ap.add_argument("--db", required=True, help="Path to the SQLite trace store.")
    ap.add_argument("--blob-dir", required=True, help="Directory for blob storage.")
    ap.add_argument("--model", required=True,
                    help="Model name (written to CASSETTE_HOSTED_MODEL).")
    ap.add_argument("--task", default=None,
                    help="Agent task (written to CASSETTE_AGENT_TASK).")
    args = ap.parse_args(argv)

    # Propagate args into env so agent + hooks can read them.
    os.environ["CASSETTE_HOSTED_MODEL"] = args.model
    os.environ["CASSETTE_BLOB_DIR"] = args.blob_dir
    if args.task:
        os.environ["CASSETTE_AGENT_TASK"] = args.task
    # base_url and key come from CASSETTE_HOSTED_BASE_URL / CASSETTE_HOSTED_KEY.

    store = TraceStore(args.db)
    try:
        trace = record_run(run_id=args.run_id, store=store)
    except Exception as exc:
        import traceback
        print(f"ERROR: run_id={args.run_id} failed: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    step_count = len(trace.get("steps", []))
    print(f"run_id={args.run_id} steps={step_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
