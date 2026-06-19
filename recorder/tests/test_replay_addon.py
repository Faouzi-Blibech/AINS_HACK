import os, tempfile
from collections import deque
os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

from recorder.http_proxy import ReplayAddon
from recorder.capture import request_identity
from recorder.policy import load_policy

P = load_policy()


class _StubReplayer:
    def __init__(self, responses):
        self._r = {k: deque(v) for k, v in responses.items()}
        self.side_effecting_served = 0
        self.side_effect_count = 0
    def response_for(self, ident):
        q = self._r.get(ident)
        if not q:
            return None
        resp = q.popleft()
        if resp.get("side_effecting"):
            self.side_effecting_served += 1
        return resp


class _Req:
    def __init__(self, method, url, body, host="127.0.0.1"):
        self.method, self.url, self.host, self._body = method, url, host, body
    def get_text(self, strict=False):
        return self._body


class _Flow:
    def __init__(self, method, url, body, host="127.0.0.1"):
        self.request = _Req(method, url, body, host)
        self.response = None


def test_addon_hit_synthesizes_engine_response():
    url, body = "http://127.0.0.1:9/assign_ticket", '{"k":1}'
    ident = request_identity("POST", url, body, P.volatile_fields())
    stub = _StubReplayer({ident: [{"status_code": 201, "body": '{"ok":true}', "side_effecting": True}]})
    addon = ReplayAddon(stub, P)
    flow = _Flow("POST", url, body)
    addon.request(flow)
    assert flow.response.status_code == 201
    assert b'"ok":true' in flow.response.content
    rep = addon.report()
    assert rep["served"] == 1 and rep["side_effecting_served"] == 1
    assert rep["divergences"] == 0 and rep["live_executed"] == 0


def test_addon_miss_returns_504_divergence():
    addon = ReplayAddon(_StubReplayer({}), P)
    flow = _Flow("POST", "http://127.0.0.1:9/UNRECORDED", '{}')
    addon.request(flow)
    assert flow.response.status_code == 504
    assert addon.report()["divergences"] == 1


def test_addon_blocks_non_recordable_host():
    addon = ReplayAddon(_StubReplayer({}), P)
    flow = _Flow("POST", "http://evil.example.com/x", '{}', host="evil.example.com")
    addon.request(flow)
    assert flow.response.status_code == 502
