"""Record an agent subprocess into the shared persistent store (~/.cassette)."""
from __future__ import annotations

import os
import subprocess
import time

from cassette import ca, paths, shim_env
from recorder.http_proxy import Recorder
from trace_store.store import TraceStore


def record_subprocess(cmd, *, run_id: str, port: int = 8899, extra_env=None) -> dict:
    paths.ensure_home()
    os.environ["CASSETTE_BLOB_DIR"] = str(paths.blob_dir())
    store = TraceStore(db_path=str(paths.db_path()))
    try:
        rec = Recorder(run_id, port=port, store=store).start()
        try:
            ca.materialize_ca()
            sub_env = dict(os.environ)
            if extra_env:
                sub_env.update(extra_env)
            sub_env.update(ca.proxy_env(port))
            sub_env = shim_env.with_shim(sub_env)
            subprocess.run(cmd, env=sub_env)
            time.sleep(0.6)
        finally:
            rec.stop()
        return store.get_run(run_id)
    finally:
        store.close()


def record_subprocess_safe(cmd, *, run_id: str, port: int = 8899, extra_env=None) -> int:
    """Record, but NEVER break the agent: on any failure, run un-proxied."""
    import sys
    try:
        record_subprocess(cmd, run_id=run_id, port=port, extra_env=extra_env)
        return 0
    except Exception as exc:  # noqa: BLE001 - degradation is intentional
        print(f"cassette: recording unavailable ({exc}); running un-proxied", file=sys.stderr)
        sub_env = dict(os.environ)
        if extra_env:
            sub_env.update(extra_env)
        return subprocess.run(cmd, env=sub_env).returncode
