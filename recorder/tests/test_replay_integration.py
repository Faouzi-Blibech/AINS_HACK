import os, tempfile, time, httpx
os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

from recorder.http_proxy import Recorder, Player
from recorder.mock_upstream import serve
from trace_store.store import TraceStore


def _agent(env, base):
    with httpx.Client(proxy=env["HTTP_PROXY"], timeout=10) as c:
        r1 = c.post(f"{base}/v1/chat/completions",
                    json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
        r2 = c.post(f"{base}/assign_ticket", json={"ticket_key": "T1", "team": "Backend"})
    return r1, r2


def test_record_then_replay_hits_zero_live_endpoints():
    db = os.path.join(tempfile.mkdtemp(), "tape.sqlite3")
    store = TraceStore(db_path=db)

    # Record against the real mock upstream.
    upstream, base = serve(0)
    rec = Recorder("run-x", port=8911, store=store).start()
    try:
        _agent(rec.env(), base)
        time.sleep(0.5)
    finally:
        rec.stop()

    recorded_steps = len(store.get_run("run-x")["steps"])
    assert recorded_steps >= 2

    # Tear the upstream DOWN, then replay the SAME agent at the SAME base.
    # With no upstream alive, any forwarded request would fail: success here
    # proves every call was served from tape (zero live endpoints).
    upstream.shutdown()
    player = Player("run-x", port=8912, store=store).start()
    try:
        r1, r2 = _agent(player.env(), base)
        time.sleep(0.5)
    finally:
        player.stop()

    assert r1.status_code == 200 and r2.status_code == 200  # served from tape, not errors
    rep = player.report()
    assert rep["served"] == recorded_steps
    assert rep["side_effecting_served"] >= 1
    assert rep["divergences"] == 0
    assert rep["live_executed"] == 0
