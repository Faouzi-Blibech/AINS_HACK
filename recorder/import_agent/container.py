"""Build and execute the `docker run` invocation for an imported agent.

Secret env values are passed by NAME (`-e KEY`) so docker reads them from this
process's environment — values never appear on the command line or in logs.
"""
from __future__ import annotations

import os
import subprocess

_CONTAINER_HOME = "/root/.cassette"
_DB = f"{_CONTAINER_HOME}/cassette.sqlite3"
_BLOBS = f"{_CONTAINER_HOME}/blobs"


def build_run_argv(*, image, workspace, store_home, run_id, entry=None,
                   command=None, manifest=None, env=None, port=8899) -> list[str]:
    argv = [
        "docker", "run", "--rm",
        "-v", f"{workspace}:/workspace",
        "-v", f"{store_home}:{_CONTAINER_HOME}",
    ]
    for key in (env or {}):
        argv += ["-e", key]  # by name; docker inherits the value from os.environ
    argv += [image,
             "--run-id", run_id, "--db", _DB, "--blob-dir", _BLOBS, "--port", str(port)]
    if entry:
        argv += ["--entry", entry]
    if manifest:
        argv += ["--manifest", manifest]
    if command:
        argv += ["--", *command]
    return argv


def run_container(argv, *, timeout, runner=subprocess.run) -> subprocess.CompletedProcess:
    return runner(argv, capture_output=True, text=True, timeout=timeout, env=dict(os.environ))
