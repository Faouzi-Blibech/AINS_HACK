"""Record ANY agent through the Cassette proxy.

Usage:
  python -m recorder.record --run-id NAME -- <command to run your agent>
  python -m recorder.record --demo            # hermetic Jira demo (starts the mock upstream)

Starts the mitmproxy recorder, injects proxy + CA env vars into the agent
subprocess, runs it, then prints the recorded trace. The recorder never imports
the agent: it records whatever HTTP the subprocess makes.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

from recorder.http_proxy import Recorder
from trace_store.store import TraceStore


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="recorder.record")
    ap.add_argument("--run-id", default=f"run-{int(time.time())}")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--demo", action="store_true",
                    help="hermetic demo: start the mock upstream and record the Jira agent")
    ap.add_argument("--mcp", action="store_true",
                    help="with --demo: record the MCP-over-HTTP agent instead of the REST one")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="-- <command> to run your agent")
    args = ap.parse_args(argv)

    cmd = args.command[1:] if args.command and args.command[0] == "--" else args.command
    server = None
    sub_env = dict(os.environ)

    if args.demo and not cmd:
        from recorder.mock_upstream import serve
        server, base = serve(0)
        if args.mcp:
            sub_env["CASSETTE_MCP_URL"] = f"{base}/mcp"
            cmd = [sys.executable, "agent/mcp_jira_agent.py"]
        else:
            sub_env["CASSETTE_TOOLS_URL"] = base
            sub_env["CASSETTE_LLM_URL"] = f"{base}/v1/chat/completions"
            sub_env.setdefault("GROQ_API_KEY", "demo-key")
            cmd = [sys.executable, "agent/jira_triage_agent.py"]

    if not cmd:
        ap.error("provide a command after -- (or use --demo)")

    work = tempfile.mkdtemp(prefix="cassette-")
    os.environ["CASSETTE_BLOB_DIR"] = os.path.join(work, "blobs")
    store = TraceStore(db_path=os.path.join(work, "trace.sqlite3"))
    rec = Recorder(args.run_id, port=args.port, store=store).start()

    ca = rec.env()["SSL_CERT_FILE"]
    sub_env.update(rec.env())
    sub_env["NO_PROXY"] = ""
    sub_env["no_proxy"] = ""
    sub_env.setdefault("REQUESTS_CA_BUNDLE", ca)
    sub_env.setdefault("NODE_EXTRA_CA_CERTS", ca)

    try:
        subprocess.run(cmd, env=sub_env)
        time.sleep(0.6)
    finally:
        rec.stop()
        if server is not None:
            server.shutdown()

    trace = store.get_run(args.run_id)
    print(json.dumps(trace, indent=2))
    se = sum(1 for s in trace["steps"] if s.get("side_effecting"))
    kinds = [s["type"] for s in trace["steps"]]
    print(f"\nrun {args.run_id}: {len(trace['steps'])} steps {kinds} | side-effecting: {se} | blobs in {work}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
