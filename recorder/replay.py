"""Replay a recorded run by re-running an agent through the proxy from tape.

Usage:
  python -m recorder.replay --run-id NAME --tape <db> --blob-dir <dir> -- <agent cmd>
  python -m recorder.replay --demo     # record the Jira agent, then replay it
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

from recorder.http_proxy import Recorder, Player
from trace_store.store import TraceStore


def _run_agent(env_extra: dict, cmd: list[str]) -> None:
    sub_env = dict(os.environ)
    sub_env.update(env_extra)
    sub_env["NO_PROXY"] = sub_env["no_proxy"] = ""
    ca = env_extra["SSL_CERT_FILE"]
    sub_env.setdefault("REQUESTS_CA_BUNDLE", ca)
    sub_env.setdefault("NODE_EXTRA_CA_CERTS", ca)
    subprocess.run(cmd, env=sub_env)
    time.sleep(0.6)


def _demo(mcp: bool = False) -> int:
    from recorder.mock_upstream import serve
    work = tempfile.mkdtemp(prefix="cassette-replay-")
    os.environ["CASSETTE_BLOB_DIR"] = os.path.join(work, "blobs")
    store = TraceStore(db_path=os.path.join(work, "tape.sqlite3"))
    run_id = f"replay-demo-{int(time.time())}"

    server, base = serve(0)
    if mcp:
        demo_env = {"CASSETTE_MCP_URL": f"{base}/mcp"}
        agent_cmd = [sys.executable, "agent/mcp_jira_agent.py"]
    else:
        demo_env = {"CASSETTE_TOOLS_URL": base,
                    "CASSETTE_LLM_URL": f"{base}/v1/chat/completions",
                    "GROQ_API_KEY": os.environ.get("GROQ_API_KEY", "demo-key")}
        agent_cmd = [sys.executable, "agent/jira_triage_agent.py"]

    rec = Recorder(run_id, port=8899, store=store).start()
    try:
        _run_agent({**demo_env, **rec.env()}, agent_cmd)
    finally:
        rec.stop()
    recorded = len(store.get_run(run_id)["steps"])

    server.shutdown()  # no live upstream during replay: proves zero live endpoints
    player = Player(run_id, port=8898, store=store).start()
    try:
        _run_agent({**demo_env, **player.env()}, agent_cmd)
    finally:
        player.stop()

    rep = player.report()
    print(json.dumps({"run_id": run_id, "recorded_steps": recorded, **rep}, indent=2))
    print(f"\nreplay {run_id}: served {rep['served']}/{recorded} from tape | "
          f"side-effecting served {rep['side_effecting_served']} | "
          f"live executed {rep['live_executed']} | divergences {rep['divergences']}")
    ok = (rep["live_executed"] == 0 and rep["divergences"] == 0 and rep["served"] == recorded)
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="recorder.replay")
    ap.add_argument("--demo", action="store_true",
                    help="record the Jira agent, then replay it from tape (hermetic)")
    ap.add_argument("--mcp", action="store_true",
                    help="with --demo: use the MCP-over-HTTP agent")
    ap.add_argument("--run-id")
    ap.add_argument("--tape", help="path to the recorded SQLite tape")
    ap.add_argument("--blob-dir", help="path to the recorded blob dir")
    ap.add_argument("--port", type=int, default=8898)
    ap.add_argument("command", nargs=argparse.REMAINDER, help="-- <command> to run your agent")
    args = ap.parse_args(argv)

    if args.demo:
        return _demo(mcp=args.mcp)

    if not (args.run_id and args.tape and args.blob_dir):
        ap.error("provide --run-id, --tape, and --blob-dir (or use --demo)")
    cmd = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not cmd:
        ap.error("provide a command after -- (or use --demo)")

    os.environ["CASSETTE_BLOB_DIR"] = args.blob_dir
    store = TraceStore(db_path=args.tape)
    player = Player(args.run_id, port=args.port, store=store).start()
    try:
        _run_agent(player.env(), cmd)
    finally:
        player.stop()
    rep = player.report()
    print(json.dumps(rep, indent=2))
    return 0 if rep["live_executed"] == 0 and rep["divergences"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
