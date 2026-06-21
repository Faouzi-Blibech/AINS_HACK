import os, tempfile, json, threading
os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

import pytest
from recorder.session import RecordingSession, current_session, ReplayDivergence
from recorder.policy import load_policy
from trace_store.store import TraceStore
from replay_engine.replay import Replayer

P = load_policy()


def _store():
    d = tempfile.mkdtemp()
    return TraceStore(db_path=os.path.join(d, "t.sqlite3"))


def test_contextvar_set_and_cleared():
    s = _store()
    assert current_session() is None
    with RecordingSession(mode="record", store=s, run_id="r1", policy=P).start() as sess:
        assert current_session() is sess
    assert current_session() is None


def test_step_id_allocator_threadsafe_unique():
    sess = RecordingSession(mode="record", store=_store(), run_id="r", policy=P)
    out, lock = [], threading.Lock()

    def worker():
        for _ in range(100):
            v = sess.next_step_id()
            with lock:
                out.append(v)

    ts = [threading.Thread(target=worker) for _ in range(5)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(out) == list(range(1, 501))  # unique, no gaps


def test_record_then_replay_sdk_roundtrip_without_executing():
    s = _store()
    with RecordingSession(mode="record", store=s, run_id="run", policy=P).start() as rec:
        rec.record_sdk(tool="get_priority", args={"raw": "P1"}, result={"priority": "critical"},
                       side_effecting=False, latency_ms=1, ts_ms=1)
    # replay against the same tape
    rep = RecordingSession(mode="replay", store=s, run_id="run", policy=P,
                           replayer=Replayer(s, "run"))
    with rep.start():
        got = rep.replay_sdk(tool="get_priority", args={"raw": "P1"}, side_effecting=False)
    assert got == {"priority": "critical"}
    assert rep.replay_report()["served"] == 1
    assert rep.replay_report()["live_executed"] == 0


def test_replay_miss_on_side_effecting_fails_closed():
    s = _store()
    with RecordingSession(mode="record", store=s, run_id="run", policy=P).start():
        pass  # empty tape
    rep = RecordingSession(mode="replay", store=s, run_id="run", policy=P,
                           replayer=Replayer(s, "run"))
    with rep.start():
        with pytest.raises(ReplayDivergence):
            rep.replay_sdk(tool="assign_ticket", args={"k": 1}, side_effecting=True)
    assert rep.replay_report()["divergences"] == 1
