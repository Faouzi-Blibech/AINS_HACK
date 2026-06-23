# cassette/cli.py
"""The `cassette` CLI: one-command local recording + remote attach helpers."""
from __future__ import annotations

import argparse
import subprocess
import time

from cassette import ca, consent, paths
from cassette.session_runner import record_subprocess


def _split_cmd(rest: list[str]) -> list[str]:
    return rest[1:] if rest and rest[0] == "--" else rest


def _cmd_run(args) -> int:
    cmd = _split_cmd(args.command)
    if not cmd:
        print("provide a command after --, e.g. cassette run -- python my_agent.py")
        return 2
    if not consent.ensure_consent(cmd):
        print("Declined: not recording this agent. Run again and answer 'y' to record.")
        return 0
    run_id = args.run_id or f"run-{int(time.time())}"
    doc = record_subprocess(cmd, run_id=run_id, port=args.port)
    n = len(doc.get("steps", []))
    print(f"recorded run {run_id}: {n} steps -> open the UI to inspect it")
    return 0


def _cmd_env(args) -> int:
    env = ca.proxy_env(args.port)
    keys = ["HTTP_PROXY", "HTTPS_PROXY", "SSL_CERT_FILE",
            "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"]
    if args.shell == "powershell":
        for k in keys:
            print(f'$env:{k} = "{env[k]}"')
    else:
        for k in keys:
            print(f'export {k}="{env[k]}"')
    return 0


def _compose(action: str) -> int:
    paths.ensure_home()
    try:
        if action == "up":
            subprocess.run(["docker", "compose", "up", "-d", "--build"])
        else:
            subprocess.run(["docker", "compose", "down"])
        return 0
    except FileNotFoundError:
        print("docker not found. Install Docker Desktop, then run 'docker compose up'.")
        return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cassette")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="record an agent (one-time consent)")
    p_run.add_argument("--port", type=int, default=8899)
    p_run.add_argument("--run-id")
    p_run.add_argument("command", nargs=argparse.REMAINDER)
    p_run.set_defaults(fn=_cmd_run)

    p_env = sub.add_parser("env", help="print the attach env block (remote)")
    p_env.add_argument("--shell", choices=["powershell", "bash"], default="powershell")
    p_env.add_argument("--port", type=int, default=8899)
    p_env.set_defaults(fn=_cmd_env)

    p_up = sub.add_parser("up", help="start the API + UI over ~/.cassette")
    p_up.set_defaults(fn=lambda a: _compose("up"))
    p_down = sub.add_parser("down", help="stop the API + UI")
    p_down.set_defaults(fn=lambda a: _compose("down"))

    import sys as _sys
    import os as _os
    from cassette import trust as _trust
    from cassette.ca import materialize_ca
    from recorder.http_proxy import Recorder
    from trace_store.store import TraceStore

    def _cmd_trust(a):
        if not paths.ca_path().exists():
            print("No Cassette CA yet. Run 'cassette serve' (or 'cassette run -- <agent>') "
                  "once to generate it, then re-run 'cassette trust'.")
            return 1
        path = _trust.trust(a.python or _sys.executable)
        print(f"trusted: appended Cassette CA to {path} (reversible with 'cassette untrust')")
        return 0

    def _cmd_untrust(a):
        ok = _trust.untrust(a.python or _sys.executable)
        print("untrusted: restored original bundle" if ok else "nothing to restore")
        return 0

    def _cmd_serve(a):
        paths.ensure_home()
        _os.environ["CASSETTE_BLOB_DIR"] = str(paths.blob_dir())
        run_id = a.run_id or f"serve-{int(time.time())}"
        store = TraceStore(db_path=str(paths.db_path()))
        try:
            rec = Recorder(run_id, port=a.port, store=store).start()
            try:
                materialize_ca()
                print(f"recording into run {run_id}. Point your agent at the proxy:")
                _cmd_env(argparse.Namespace(shell="powershell", port=a.port))
                print("Press Ctrl+C to stop.")
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            finally:
                rec.stop()
        finally:
            store.close()
        return 0

    p_trust = sub.add_parser("trust", help="append the Cassette CA to a Python's certifi bundle")
    p_trust.add_argument("--python")
    p_trust.set_defaults(fn=_cmd_trust)
    p_untrust = sub.add_parser("untrust", help="restore the original certifi bundle")
    p_untrust.add_argument("--python")
    p_untrust.set_defaults(fn=_cmd_untrust)
    p_serve = sub.add_parser("serve", help="long-lived recorder for a remote/separate agent")
    p_serve.add_argument("--port", type=int, default=8899)
    p_serve.add_argument("--run-id")
    p_serve.set_defaults(fn=_cmd_serve)

    from cassette import launchers as _launchers

    def _cmd_enable(a):
        cmd = _split_cmd(a.command)
        if not cmd:
            print("usage: cassette enable --name NAME -- <cmd>")
            return 2
        name = a.name or cmd[-1].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        path = _launchers.install(name, cmd)
        print(f"enabled: '{name}' now auto-records. Added {path}.")
        print(f"Add this dir to PATH so '{name}' resolves to it:\n  {paths.bin_dir()}")
        return 0

    def _cmd_disable(a):
        cmd = _split_cmd(a.command)
        name = a.name or (cmd[-1] if cmd else "")
        ok = _launchers.remove(name, cmd)
        print("disabled" if ok else "no launcher found")
        return 0

    p_enable = sub.add_parser("enable", help="auto-record every future session of an agent")
    p_enable.add_argument("--name")
    p_enable.add_argument("command", nargs=argparse.REMAINDER)
    p_enable.set_defaults(fn=_cmd_enable)
    p_disable = sub.add_parser("disable", help="stop auto-recording an agent")
    p_disable.add_argument("--name")
    p_disable.add_argument("command", nargs=argparse.REMAINDER)
    p_disable.set_defaults(fn=_cmd_disable)

    args = ap.parse_args(argv)
    return args.fn(args)
