"""In-container driver: record an imported agent into a mounted store.

Generalizes recorder/record_session.py:record_run. Two modes:
  * entry  ("module:function") -> in-process driver: HTTP + MCP + SDK.
  * command (argv list)        -> subprocess under the proxy env: HTTP + MCP only.

No cassette/ imports. The agent's source is never modified.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

from pathlib import Path

from recorder.http_proxy import CA_PATH, Recorder
from recorder.policy import load_policy
from recorder.record_session import (
    _apply_env, _instrument_sdk, _restore_env, _restore_sdk, _snapshot_env, load_entry,
)
from recorder.session import RecordingSession
from trace_store.store import TraceStore


def _agent_subprocess_env(workspace, sdk_tools) -> dict:
    """Env for the agent subprocess so HTTPS (httpx/requests) trusts the proxy.

    The agent_shim (auto-imported via PYTHONPATH as sitecustomize) only activates
    its CA trust when CASSETTE_CA points at the proxy CA, and its SDK wrap when
    CASSETTE_TOOL_MANIFEST is set. rec.env() (already in os.environ here) sets the
    proxy + SSL_CERT_FILE; this adds the CA + shim so an HTTPS agent captures
    cleanly without any per-agent setup.
    """
    child = dict(os.environ)
    if CA_PATH.exists():
        child["CASSETTE_CA"] = str(CA_PATH)
    shim_dir = str(Path(__file__).resolve().parents[1] / "agent_shim")
    repo_root = str(Path(__file__).resolve().parents[2])
    parts = [shim_dir, repo_root]
    if workspace:
        parts.append(str(workspace))
    if child.get("PYTHONPATH"):
        parts.append(child["PYTHONPATH"])
    child["PYTHONPATH"] = os.pathsep.join(parts)
    if sdk_tools:
        child["CASSETTE_TOOL_MANIFEST"] = json.dumps(sdk_tools)
    return child


def record_imported(*, run_id, store, entry=None, command=None,
                    sdk_tools=None, env=None, port=8899, workspace=None,
                    stdin_text=None) -> dict:
    if not entry and not command:
        raise ValueError("record_imported requires either entry or command")
    # Imported agents are unknown, so record every host they call, not just the
    # known LLM endpoints in the default allowlist.
    policy = load_policy(record_all=True)
    saved = _snapshot_env()
    session = RecordingSession(mode="record", store=store, run_id=run_id,
                               policy=policy, register_run=False, schema_version="1.1")
    rec = Recorder(run_id, port=port, store=store, policy=policy,
                   step_id_source=session.next_step_id).start()
    originals = _instrument_sdk(sdk_tools)
    try:
        _apply_env({**(env or {}), **rec.env()})
        if entry:
            with session:
                load_entry(entry)()
        else:
            # Feed the task to the agent's stdin so interactive (prompt-loop)
            # agents run and make recordable calls; then stdin closes (EOF).
            feed = (stdin_text + "\n") if stdin_text else None
            proc = subprocess.run(
                command,
                env=_agent_subprocess_env(workspace, sdk_tools),
                cwd=str(workspace) if workspace else None,
                input=feed,
                text=True,
                capture_output=True,
            )
            # Surface the agent's own output so a crash (missing key, import
            # error, etc.) is visible instead of producing a silent empty trace.
            if proc.stdout:
                print(proc.stdout, file=sys.stderr)
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
            if proc.returncode != 0:
                print(f"[import] agent exited with code {proc.returncode}", file=sys.stderr)
        time.sleep(0.4)
    finally:
        _restore_sdk(originals)
        rec.stop()
        _restore_env(saved)
    return store.get_run(run_id)


def _install_deps(workspace, runner=subprocess.run) -> None:
    """Install the imported agent's own deps if it declares any. Best-effort."""
    from pathlib import Path
    ws = Path(workspace)
    req = ws / "requirements.txt"
    pyproject = ws / "pyproject.toml"
    if req.exists():
        runner([sys.executable, "-m", "pip", "install", "-r", str(req)], check=False)
    elif pyproject.exists():
        runner([sys.executable, "-m", "pip", "install", str(ws)], check=False)


def _parse_manifest(raw: str | None) -> dict | None:
    """raw is JSON: {"module:function": true/false, ...} or None."""
    if not raw:
        return None
    return {k: bool(v) for k, v in json.loads(raw).items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="recorder.import_agent.driver")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--blob-dir", required=True)
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--entry", default=None, help='"module:function" for in-process capture')
    ap.add_argument("--manifest", default=None, help="JSON tool manifest for SDK capture")
    ap.add_argument("--workspace", default=None, help="agent workspace dir (default: cwd)")
    ap.add_argument("--no-install", action="store_true",
                    help="skip installing the imported agent's own dependencies")
    ap.add_argument("command", nargs=argparse.REMAINDER,
                    help="-- <argv> to run the agent as a subprocess")
    args = ap.parse_args(argv)

    workspace = args.workspace or os.getcwd()

    os.environ["CASSETTE_BLOB_DIR"] = args.blob_dir
    cmd = args.command[1:] if args.command and args.command[0] == "--" else args.command
    sys.path.insert(0, workspace)
    if not args.no_install:
        _install_deps(workspace)
    store = TraceStore(args.db)
    try:
        trace = record_imported(
            run_id=args.run_id, store=store, entry=args.entry,
            command=cmd or None, sdk_tools=_parse_manifest(args.manifest), port=args.port,
            workspace=workspace, stdin_text=os.environ.get("CASSETTE_AGENT_STDIN"),
        )
    except Exception as exc:
        import traceback
        print(f"ERROR: run_id={args.run_id} failed: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        store.close()
    steps = len(trace.get("steps", []))
    print(f"run_id={args.run_id} steps={steps}")
    if steps == 0:
        # No captured calls means the agent did not run usefully (crashed, made
        # no HTTP/LLM/tool calls, or needs a task/keys). Make it a clear failure
        # instead of a silent empty trace; the agent output was printed above.
        print(
            f"ERROR: run_id={args.run_id} recorded 0 steps. The agent made no "
            "captured calls. If it is interactive, pass a task; if it needs API "
            "keys or extra env, provide them; see the agent output above.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
