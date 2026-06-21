import os, tempfile, json
from collections import deque
os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

from recorder import mcp_proxy
from recorder.capture import build_step, compute_identity
from recorder.http_proxy import ReplayAddon
from recorder.policy import load_policy
from trace_store.blob_store import fetch_blob

P = load_policy()
MCP_URL = "http://127.0.0.1:9/mcp"


def _envelope(method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if mid is not None:
        msg["id"] = mid
    return json.dumps(msg)


def _tools_call(name, args, mid=1):
    return _envelope("tools/call", {"name": name, "arguments": args}, mid)


# --- router detection ---

def test_is_mcp_detects_jsonrpc_envelope():
    assert mcp_proxy.is_mcp(_envelope("tools/list"))
    assert not mcp_proxy.is_mcp('{"model":"m","messages":[]}')
    assert not mcp_proxy.is_mcp("not json")


def test_parse_request_extracts_tool_and_args():
    call = mcp_proxy.parse_request(_tools_call("assign_ticket", {"team": "Backend"}))
    assert call.method == "tools/call"
    assert call.tool == "assign_ticket" and call.arguments == {"team": "Backend"}
    assert call.is_notification is False


def test_parse_request_marks_notification():
    call = mcp_proxy.parse_request(_envelope("notifications/initialized", mid=None))
    assert call.is_notification is True and call.tool is None


# --- identity is id-independent but tool/arg-sensitive ---

def test_identity_ignores_volatile_jsonrpc_id():
    a = compute_identity("POST", MCP_URL, _tools_call("get_priority", {"raw": "P1"}, mid=1), P)
    b = compute_identity("POST", MCP_URL, _tools_call("get_priority", {"raw": "P1"}, mid=999), P)
    assert a == b


def test_identity_strips_volatile_args():
    # same tool+args except a per-call nonce that policy marks volatile
    a = compute_identity("POST", MCP_URL,
        _tools_call("assign_ticket", {"ticket_key": "T1", "timestamp": 111}), P)
    b = compute_identity("POST", MCP_URL,
        _tools_call("assign_ticket", {"ticket_key": "T1", "timestamp": 999}), P)
    assert a == b


def test_identity_strips_volatile_args_nested():
    a = compute_identity("POST", MCP_URL,
        _tools_call("assign_ticket", {"meta": {"request_id": "r1"}, "k": 1}), P)
    b = compute_identity("POST", MCP_URL,
        _tools_call("assign_ticket", {"meta": {"request_id": "r2"}, "k": 1}), P)
    assert a == b


def test_identity_differs_by_tool_and_args():
    base = compute_identity("POST", MCP_URL, _tools_call("get_priority", {"raw": "P1"}), P)
    other_tool = compute_identity("POST", MCP_URL, _tools_call("assign_ticket", {"raw": "P1"}), P)
    other_args = compute_identity("POST", MCP_URL, _tools_call("get_priority", {"raw": "P3"}), P)
    assert base != other_tool and base != other_args


# --- build_step shape + side-effect classification ---

def _step(body, resp='{"jsonrpc":"2.0","id":1,"result":{}}'):
    return build_step(step_id=1, prev_step_id=None, method="POST", url=MCP_URL,
                      req_body=body, status_code=200, resp_body=resp,
                      latency_ms=5, ts_ms=1, policy=P)


def test_mcp_tool_call_step_shape():
    s = _step(_tools_call("assign_ticket", {"ticket_key": "T1"}))
    assert s["transport"] == "mcp" and s["type"] == "tool_call"
    assert s["tool"] == "assign_ticket" and s["side_effecting"] is True
    assert s["request_identity"] == compute_identity(
        "POST", MCP_URL, _tools_call("assign_ticket", {"ticket_key": "T1"}), P)


def test_mcp_read_only_tool_not_side_effecting():
    s = _step(_tools_call("get_priority", {"raw_priority": "P1"}))
    assert s["side_effecting"] is False


def test_mcp_handshake_messages_not_side_effecting():
    assert _step(_envelope("initialize"))["side_effecting"] is False
    assert _step(_envelope("tools/list"))["side_effecting"] is False
    init = _step(_envelope("initialize"))
    assert init["tool"] == "initialize"


# --- SSE unwrap ---

def test_unwrap_sse_returns_last_data_event():
    sse = "event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"ok\":true}}\n\n"
    assert json.loads(mcp_proxy.unwrap_sse(sse))["result"] == {"ok": True}
    assert mcp_proxy.unwrap_sse('{"plain":1}') == '{"plain":1}'


# --- replay round-trip through the shared addon ---

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


def test_replay_addon_serves_mcp_tool_from_tape():
    body = _tools_call("assign_ticket", {"ticket_key": "T1"}, mid=7)
    ident = compute_identity("POST", MCP_URL, body, P)
    result = '{"jsonrpc":"2.0","id":7,"result":{"content":[{"type":"text","text":"{}"}]}}'
    stub = _StubReplayer({ident: [{"status_code": 200, "body": result, "side_effecting": True}]})
    addon = ReplayAddon(stub, P)
    # replay issues a FRESH json-rpc id; identity must still match the tape
    live = _Flow("POST", MCP_URL, _tools_call("assign_ticket", {"ticket_key": "T1"}, mid=42))
    addon.request(live)
    assert live.response.status_code == 200
    rep = addon.report()
    assert rep["served"] == 1 and rep["side_effecting_served"] == 1
    assert rep["divergences"] == 0 and rep["live_executed"] == 0
