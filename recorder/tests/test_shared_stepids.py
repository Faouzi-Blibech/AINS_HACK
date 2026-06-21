import os, tempfile, json
os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

from recorder.http_proxy import CaptureAddon
from recorder.policy import load_policy
from trace_store.store import TraceStore

P = load_policy()


class _Msg:
    def __init__(self, body): self._b = body
    def get_text(self, strict=False): return self._b
    raw_content = b""


class _Req(_Msg):
    def __init__(self, body):
        super().__init__(body)
        self.method, self.url, self.host = "POST", "http://127.0.0.1/get_priority", "127.0.0.1"
        self.timestamp_start = 1.0


class _Resp(_Msg):
    def __init__(self, body):
        super().__init__(body)
        self.status_code = 200
        self.timestamp_end = 1.1


class _Flow:
    def __init__(self, rb, sb):
        self.request, self.response = _Req(rb), _Resp(sb)


def test_capture_addon_uses_injected_step_id_source():
    s = TraceStore(db_path=os.path.join(tempfile.mkdtemp(), "t.sqlite3"))
    s.start_run("r")
    seq = iter([10, 11])
    addon = CaptureAddon(s, "r", P, step_id_source=lambda: next(seq))
    addon.response(_Flow('{"raw_priority":"P1"}', '{"priority":"critical"}'))
    addon.response(_Flow('{"raw_priority":"P3"}', '{"priority":"low"}'))
    ids = [st["step_id"] for st in s.get_run("r")["steps"]]
    assert ids == [10, 11]
