import os, tempfile, pathlib
os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

from recorder.record_session import record_run, replay_run
from recorder.mock_upstream import serve
from trace_store.store import TraceStore
import agent.full_stack_agent as fsa

ENTRY = "agent.full_stack_agent:main"
SDK_TOOLS = {"agent.full_stack_agent:enrich_priority": False,
             "agent.full_stack_agent:write_audit_log": True}


def _env_store():
    server, base = serve(0)
    env = {"CASSETTE_LLM_URL": f"{base}/v1/chat/completions", "CASSETTE_MCP_URL": f"{base}/mcp"}
    store = TraceStore(db_path=os.path.join(tempfile.mkdtemp(), "t.sqlite3"))
    return server, env, store


def test_records_all_three_transports_transparently():
    server, env, store = _env_store()
    try:
        trace = record_run(entry=ENTRY, run_id="r", env=env, store=store,
                           port=8899, sdk_tools=SDK_TOOLS)
    finally:
        server.shutdown()
    transports = {s["transport"] for s in trace["steps"]}
    assert {"http", "mcp", "sdk"} <= transports
    ids = [s["step_id"] for s in trace["steps"]]
    assert len(ids) == len(set(ids))  # no step-id collisions across transports


def test_replay_is_hermetic_and_contains_side_effects():
    server, env, store = _env_store()
    try:
        record_run(entry=ENTRY, run_id="r2", env=env, store=store, port=8897, sdk_tools=SDK_TOOLS)
        recorded = len(store.get_run("r2")["steps"])
    finally:
        server.shutdown()  # NO live upstream during replay -> proves zero live endpoints
    fsa.EXECUTED["audit"] = 0
    rep = replay_run(entry=ENTRY, run_id="r2", env=env, store=store, port=8896, sdk_tools=SDK_TOOLS)
    assert rep["live_executed"] == 0
    assert rep["divergences"] == 0
    assert rep["served"] == recorded
    assert rep["side_effecting_served"] >= 1
    assert fsa.EXECUTED["audit"] == 0  # side-effecting native tool NEVER ran in replay


def test_demo_agent_is_cassette_free():
    """The whole point: the agent under test imports nothing from Cassette."""
    src = pathlib.Path(fsa.__file__).read_text(encoding="utf-8")
    assert "record_tool" not in src
    assert "import recorder" not in src and "from recorder" not in src
