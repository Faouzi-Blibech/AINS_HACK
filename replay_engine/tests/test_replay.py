import os, tempfile, json
os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

from recorder.capture import build_step, request_identity
from recorder.policy import load_policy
from trace_store.store import TraceStore
from replay_engine.replay import Replayer

P = load_policy()


def _store(steps):
    store = TraceStore(db_path=os.path.join(tempfile.mkdtemp(), "t.sqlite3"))
    store.start_run("r", agent="", mode="record", created_at_ms=0)
    for s in steps:
        store.append_step("r", s)
    return store


def _tool(step_id, url, body, resp):
    return build_step(step_id=step_id, prev_step_id=None, method="POST", url=url,
        req_body=body, status_code=200, resp_body=resp, latency_ms=1, ts_ms=1, policy=P)


def test_response_for_hit_marks_side_effect_and_keeps_invariant():
    url, body = "http://127.0.0.1:9/assign_ticket", '{"ticket_key":"T1"}'
    store = _store([_tool(1, url, body, '{"ok":true,"assigned":"T1"}')])
    r = Replayer(store, "r")
    resp = r.response_for(request_identity("POST", url, body, P.volatile_fields()))
    assert resp["status_code"] == 200
    assert json.loads(resp["body"])["assigned"] == "T1"
    assert resp["side_effecting"] is True
    assert r.side_effecting_served == 1
    assert r.side_effect_count == 0


def test_response_for_repeated_identity_served_in_order():
    url, body = "http://127.0.0.1:9/poll", '{"q":1}'
    store = _store([_tool(1, url, body, '{"n":1}'), _tool(2, url, body, '{"n":2}')])
    r = Replayer(store, "r")
    ident = request_identity("POST", url, body, P.volatile_fields())
    assert json.loads(r.response_for(ident)["body"])["n"] == 1
    assert json.loads(r.response_for(ident)["body"])["n"] == 2


def test_response_for_miss_returns_none():
    store = _store([_tool(1, "http://127.0.0.1:9/a", '{}', '{"ok":true}')])
    r = Replayer(store, "r")
    assert r.response_for("POST /nope\nx") is None
