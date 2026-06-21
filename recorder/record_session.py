# recorder/record_session.py
"""Agent-agnostic in-process driver: record/replay an agent that uses all 3 transports.

The proxy thread captures http/mcp; the RecordingSession captures sdk; both write
ONE trace with one step-id sequence. The agent is loaded by "module:function" so
this module never hard-imports a specific agent.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import tempfile
import time

from recorder.http_proxy import Recorder, Player
from recorder.policy import load_policy
from recorder.sdk_hooks import record_tool
from recorder.session import RecordingSession
from replay_engine.replay import Replayer
from trace_store.store import TraceStore

_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
             "NODE_EXTRA_CA_CERTS", "NO_PROXY", "no_proxy",
             "CASSETTE_LLM_URL", "CASSETTE_MCP_URL", "CASSETTE_TOOLS_URL",
             "GROQ_API_KEY", "CASSETTE_EMAIL_SDK")


def load_entry(spec: str):
    mod_name, _, fn_name = spec.partition(":")
    mod = importlib.import_module(mod_name)
    return getattr(mod, fn_name)


def _snapshot_env() -> dict:
    return {k: os.environ.get(k) for k in _ENV_KEYS}


def _restore_env(saved: dict) -> None:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _apply_env(env: dict) -> None:
    for k, v in env.items():
        os.environ[k] = v
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = ""


def _instrument_sdk(specs: dict | None) -> list:
    """Transparently wrap native tools by reference. `specs` maps "module:attr" ->
    side_effecting(bool). Returns [(module, attr, original)] to restore afterwards.
    The agent's source is never modified; this installs the hook from outside."""
    originals = []
    for spec, side_effecting in (specs or {}).items():
        mod_name, _, attr = spec.partition(":")
        mod = importlib.import_module(mod_name)
        orig = getattr(mod, attr)
        setattr(mod, attr, record_tool(side_effecting=side_effecting)(orig))
        originals.append((mod, attr, orig))
    return originals


def _restore_sdk(originals: list) -> None:
    for mod, attr, orig in originals:
        setattr(mod, attr, orig)


def record_run(*, entry, run_id, env, store, port=8899, sdk_tools=None) -> dict:
    policy = load_policy()
    saved = _snapshot_env()
    # the proxy's Recorder owns start_run/finish_run; the session only owns the
    # contextvar + the shared step-id allocator (register_run=False avoids a
    # double start_run on the same run_id).
    session = RecordingSession(mode="record", store=store, run_id=run_id, policy=policy,
                               register_run=False)
    rec = Recorder(run_id, port=port, store=store, policy=policy,
                   step_id_source=session.next_step_id).start()
    originals = _instrument_sdk(sdk_tools)
    try:
        _apply_env({**env, **rec.env()})
        with session:
            load_entry(entry)()
        time.sleep(0.4)
    finally:
        _restore_sdk(originals)
        rec.stop()
        _restore_env(saved)
    return store.get_run(run_id)


def replay_run(*, entry, run_id, env, store, port=8898, sdk_tools=None) -> dict:
    policy = load_policy()
    saved = _snapshot_env()
    recorded = len(store.get_run(run_id)["steps"])
    session = RecordingSession(mode="replay", store=store, run_id=run_id, policy=policy,
                               replayer=Replayer(store, run_id))
    player = Player(run_id, port=port, store=store, policy=policy).start()
    originals = _instrument_sdk(sdk_tools)
    try:
        _apply_env({**env, **player.env()})
        with session:
            load_entry(entry)()
        time.sleep(0.4)
    finally:
        _restore_sdk(originals)
        player.stop()
        _restore_env(saved)
    proxy = player.report()
    sdk = session.replay_report()
    return {
        "recorded_steps": recorded,
        "served": proxy["served"] + sdk["served"],
        "divergences": proxy["divergences"] + sdk["divergences"],
        "side_effecting_served": proxy["side_effecting_served"] + sdk["side_effecting_served"],
        "live_executed": proxy["live_executed"] + sdk["live_executed"],
    }


def demo(mode: str = "record") -> int:
    from recorder.mock_upstream import serve
    work = tempfile.mkdtemp(prefix="cassette-fullstack-")
    os.environ["CASSETTE_BLOB_DIR"] = os.path.join(work, "blobs")
    store = TraceStore(db_path=os.path.join(work, "tape.sqlite3"))
    run_id = f"fullstack-{int(time.time())}"
    server, base = serve(0)
    env = {"CASSETTE_LLM_URL": f"{base}/v1/chat/completions", "CASSETTE_MCP_URL": f"{base}/mcp"}
    entry = "agent.full_stack_agent:main"
    sdk_tools = {"agent.full_stack_agent:enrich_priority": False,
                 "agent.full_stack_agent:write_audit_log": True}
    try:
        trace = record_run(entry=entry, run_id=run_id, env=env, store=store, sdk_tools=sdk_tools)
        kinds = [(s["transport"], s["type"]) for s in trace["steps"]]
        print(f"recorded {len(trace['steps'])} steps: {kinds}")
        if mode == "record":
            print(json.dumps(trace, indent=2))
            return 0
        server.shutdown()  # prove zero live endpoints during replay
        server = None
        rep = replay_run(entry=entry, run_id=run_id, env=env, store=store, sdk_tools=sdk_tools)
        print(json.dumps(rep, indent=2))
        ok = (rep["live_executed"] == 0 and rep["divergences"] == 0
              and rep["served"] == rep["recorded_steps"])
        return 0 if ok else 1
    finally:
        if server is not None:
            server.shutdown()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="recorder.record_session")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--replay", action="store_true", help="with --demo: record then replay")
    args = ap.parse_args(argv)
    if args.demo:
        return demo(mode="replay" if args.replay else "record")
    ap.error("only --demo is supported in this driver")


if __name__ == "__main__":
    raise SystemExit(main())
