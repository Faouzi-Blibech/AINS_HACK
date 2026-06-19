"""mitmproxy-based forward proxy that records any agent's HTTP traffic.

Record mode only (play mode is designed in the spec, built later with Derbal).
"""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

from mitmproxy import options
from mitmproxy.tools.dump import DumpMaster

from recorder.capture import build_step
from recorder.policy import load_policy
from trace_store.store import TraceStore

CA_PATH = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"


def _body_text(message) -> str:
    txt = message.get_text(strict=False)
    if txt is not None:
        return txt
    import base64
    return base64.b64encode(message.raw_content or b"").decode()


class CaptureAddon:
    def __init__(self, store: TraceStore, run_id: str, policy) -> None:
        self.store, self.run_id, self.policy = store, run_id, policy
        self.step_id = 0

    def response(self, flow) -> None:
        if not self.policy.should_record(flow.request.host):
            return
        self.step_id += 1
        step = build_step(
            step_id=self.step_id,
            prev_step_id=self.step_id - 1 if self.step_id > 1 else None,
            method=flow.request.method,
            url=flow.request.url,
            req_body=_body_text(flow.request),
            status_code=flow.response.status_code,
            resp_body=_body_text(flow.response),
            latency_ms=int((flow.response.timestamp_end - flow.request.timestamp_start) * 1000),
            ts_ms=int(flow.request.timestamp_start * 1000),
            policy=self.policy,
        )
        self.store.append_step(self.run_id, step)


class Recorder:
    def __init__(self, run_id: str, *, port: int = 8899, store: TraceStore | None = None, policy=None) -> None:
        self.run_id, self.port = run_id, port
        self.store = store or TraceStore()
        self.policy = policy or load_policy()
        self._loop = asyncio.new_event_loop()
        self._master = None
        self._t0 = time.time()

    def start(self) -> "Recorder":
        self.store.start_run(self.run_id, agent="", mode="record",
                             created_at_ms=int(self._t0 * 1000))

        def run():
            asyncio.set_event_loop(self._loop)
            opts = options.Options(listen_host="127.0.0.1", listen_port=self.port, ssl_insecure=True)
            self._master = DumpMaster(opts, loop=self._loop, with_termlog=False, with_dumper=False)
            self._master.addons.add(CaptureAddon(self.store, self.run_id, self.policy))
            self._loop.run_until_complete(self._master.run())

        threading.Thread(target=run, daemon=True).start()
        for _ in range(50):
            if self._master is not None and CA_PATH.exists():
                break
            time.sleep(0.1)
        return self

    def env(self) -> dict:
        url = f"http://127.0.0.1:{self.port}"
        return {"HTTP_PROXY": url, "HTTPS_PROXY": url, "SSL_CERT_FILE": str(CA_PATH)}

    def stop(self, status: str = "ok") -> None:
        self.store.finish_run(self.run_id, status=status,
                              duration_ms=int((time.time() - self._t0) * 1000))
        if self._master is not None:
            self._loop.call_soon_threadsafe(self._master.shutdown)
