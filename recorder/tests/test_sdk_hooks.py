import os, tempfile, asyncio
os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

import pytest
from recorder.sdk_hooks import record_tool
from recorder.session import RecordingSession, ReplayDivergence
from recorder.policy import load_policy
from trace_store.store import TraceStore
from replay_engine.replay import Replayer

P = load_policy()
EXECUTED = {"n": 0}


@record_tool(side_effecting=True)
def assign(ticket_key, team):
    EXECUTED["n"] += 1
    return {"ok": True, "ticket": ticket_key, "team": team}


@record_tool(side_effecting=False)
async def aread(x):
    return {"v": x * 2}


def _store():
    return TraceStore(db_path=os.path.join(tempfile.mkdtemp(), "t.sqlite3"))


def test_passthrough_without_session():
    EXECUTED["n"] = 0
    assert assign("T1", "Backend") == {"ok": True, "ticket": "T1", "team": "Backend"}
    assert EXECUTED["n"] == 1  # real function ran


def test_record_then_replay_does_not_execute():
    EXECUTED["n"] = 0
    s = _store()
    with RecordingSession(mode="record", store=s, run_id="r", policy=P).start():
        assign("T1", "Backend")
    assert EXECUTED["n"] == 1  # ran once during record
    rep = RecordingSession(mode="replay", store=s, run_id="r", policy=P,
                           replayer=Replayer(s, "r"))
    with rep.start():
        out = assign("T1", "Backend")
    assert out == {"ok": True, "ticket": "T1", "team": "Backend"}
    assert EXECUTED["n"] == 1  # NOT executed again in replay (containment)
    assert rep.replay_report()["side_effecting_served"] == 1


def test_async_tool_records_and_replays():
    s = _store()
    with RecordingSession(mode="record", store=s, run_id="r", policy=P).start():
        assert asyncio.run(aread(3)) == {"v": 6}
    rep = RecordingSession(mode="replay", store=s, run_id="r", policy=P,
                           replayer=Replayer(s, "r"))
    with rep.start():
        assert asyncio.run(aread(3)) == {"v": 6}


def test_replay_miss_side_effecting_fails_closed():
    s = _store()
    with RecordingSession(mode="record", store=s, run_id="r", policy=P).start():
        pass
    rep = RecordingSession(mode="replay", store=s, run_id="r", policy=P,
                           replayer=Replayer(s, "r"))
    EXECUTED["n"] = 0
    with rep.start():
        with pytest.raises(ReplayDivergence):
            assign("Z", "Z")
    assert EXECUTED["n"] == 0  # never executed on a miss
