import os, tempfile, json, httpx, pathlib
os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

from recorder.http_proxy import Recorder
from recorder.capture import request_identity
from recorder.policy import load_policy
from recorder.mock_upstream import serve
from trace_store.store import TraceStore
from trace_store.blob_store import fetch_blob


def _generic_agent(env, base):
    # A generic agent: plain httpx, NOT the Jira agent. Proves agent-agnosticism.
    with httpx.Client(proxy=env["HTTP_PROXY"], timeout=10) as c:
        c.post(f"{base}/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
        c.post(f"{base}/assign_ticket", json={"ticket_key": "T1", "team": "Backend Engineers"})


def test_records_llm_and_tool_from_any_agent():
    server, base = serve(0)
    store = TraceStore(db_path=os.path.join(tempfile.mkdtemp(), "rec.sqlite3"))
    rec = Recorder("run-itest", port=8901, store=store).start()
    try:
        _generic_agent(rec.env(), base)
        import time; time.sleep(0.5)
    finally:
        rec.stop()
        server.shutdown()

    trace = store.get_run("run-itest")
    kinds = [s["type"] for s in trace["steps"]]
    assert "llm_call" in kinds and "tool_call" in kinds
    for s in trace["steps"]:
        assert s["transport"] == "http"
        for key in ("prompt_blob", "response_blob", "args_blob", "result_blob"):
            if key in s:
                assert fetch_blob(s[key]) is not None
    tool = next(s for s in trace["steps"] if s["type"] == "tool_call")
    assert tool["tool"] == "assign_ticket" and tool["side_effecting"] is True


def test_recorder_has_no_agent_imports():
    root = pathlib.Path(__file__).resolve().parents[1]
    for py in root.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "import agent" not in text and "from agent" not in text, py.name
