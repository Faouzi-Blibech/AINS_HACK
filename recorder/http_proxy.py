"""mitmproxy-based forward proxy: record path (CaptureAddon/Recorder) and
replay path (ReplayAddon/Player). Replay delegates to replay_engine.Replayer and
never forwards, so a replayed run hits zero live endpoints.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

from mitmproxy import http, options
from mitmproxy.tools.dump import DumpMaster

from recorder.capture import build_step, request_identity
from recorder.policy import load_policy
from trace_store.store import TraceStore
from replay_engine.replay import Replayer

CA_PATH = Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem"


def _body_text(message) -> str:
    txt = message.get_text(strict=False)
    if txt is not None:
        return txt
    import base64
    return base64.b64encode(message.raw_content or b"").decode()


class _ProxyBase:
    """Shared mitmproxy lifecycle: a DumpMaster on a background thread."""

    def __init__(self, *, port: int) -> None:
        self.port = port
        self._loop = asyncio.new_event_loop()
        self._master = None

    def _make_addon(self):
        raise NotImplementedError

    def start(self) -> "_ProxyBase":
        def run():
            asyncio.set_event_loop(self._loop)
            opts = options.Options(listen_host="127.0.0.1", listen_port=self.port, ssl_insecure=True)
            self._master = DumpMaster(opts, loop=self._loop, with_termlog=False, with_dumper=False)
            self._master.addons.add(self._make_addon())
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

    def _shutdown(self) -> None:
        if self._master is not None:
            self._loop.call_soon_threadsafe(self._master.shutdown)


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


class ReplayAddon:
    """Play mode: delegate to the engine by request_identity, never forward."""

    def __init__(self, replayer, policy) -> None:
        self.replayer = replayer
        self.policy = policy
        self._volatile = policy.volatile_fields()
        self.served = self.divergences = 0

    def request(self, flow) -> None:
        if not self.policy.should_record(flow.request.host):
            flow.response = http.Response.make(
                502, b'{"error":"blocked: non-recordable host during replay"}',
                {"Content-Type": "application/json"})
            return
        ident = request_identity(flow.request.method, flow.request.url,
                                 _body_text(flow.request), self._volatile)
        resp = self.replayer.response_for(ident)
        if resp is None:
            self.divergences += 1
            flow.response = http.Response.make(
                504, json.dumps({"error": "divergence: no recorded step",
                                 "identity": ident}).encode(),
                {"Content-Type": "application/json"})
            return
        body = resp["body"]
        flow.response = http.Response.make(
            int(resp["status_code"]),
            body.encode() if isinstance(body, str) else body,
            {"Content-Type": "application/json"})
        self.served += 1

    def report(self) -> dict:
        return {"served": self.served, "divergences": self.divergences,
                "side_effecting_served": getattr(self.replayer, "side_effecting_served", 0),
                "live_executed": getattr(self.replayer, "side_effect_count", 0)}


class Recorder(_ProxyBase):
    def __init__(self, run_id: str, *, port: int = 8899, store: TraceStore | None = None, policy=None) -> None:
        super().__init__(port=port)
        self.run_id = run_id
        self.store = store or TraceStore()
        self.policy = policy or load_policy()
        self._t0 = time.time()

    def _make_addon(self):
        return CaptureAddon(self.store, self.run_id, self.policy)

    def start(self) -> "Recorder":
        self.store.start_run(self.run_id, agent="", mode="record",
                             created_at_ms=int(self._t0 * 1000))
        super().start()
        return self

    def stop(self, status: str = "ok") -> None:
        self.store.finish_run(self.run_id, status=status,
                              duration_ms=int((time.time() - self._t0) * 1000))
        self._shutdown()


class Player(_ProxyBase):
    def __init__(self, run_id: str, *, port: int = 8898, store: TraceStore | None = None, policy=None) -> None:
        super().__init__(port=port)
        self.run_id = run_id
        self.store = store or TraceStore()
        self.policy = policy or load_policy()
        self._addon: ReplayAddon | None = None

    def _make_addon(self):
        self._addon = ReplayAddon(Replayer(self.store, self.run_id), self.policy)
        return self._addon

    def report(self) -> dict:
        return self._addon.report() if self._addon else {}

    def stop(self) -> None:
        self._shutdown()
