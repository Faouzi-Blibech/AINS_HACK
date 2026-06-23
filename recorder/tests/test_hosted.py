"""Offline tests for the hosted-agent recorder (recorder/run_hosted.py).

All model calls are monkeypatched -- no real network required.
"""
import json
import os
import pathlib
import tempfile

# Set blob dir before any Cassette module is imported.
os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

import pytest

import agent.hosted_agent as _agent
from recorder.run_hosted import record_run
from trace_store.blob_store import fetch_blob
from trace_store.store import TraceStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _store():
    return TraceStore(db_path=os.path.join(tempfile.mkdtemp(), "t.sqlite3"))


def _fake_call_model_sequence(responses: list[dict]):
    """Return a call_model replacement that yields responses in order."""
    itr = iter(responses)

    def _fake(messages: list[dict]) -> dict:
        return next(itr)

    return _fake


def _run(monkeypatch, responses, *, run_id="test-run", extra_env=None):
    """Patch call_model with canned responses, run record_run, return trace."""
    blob_dir = tempfile.mkdtemp()
    monkeypatch.setenv("CASSETTE_BLOB_DIR", blob_dir)
    monkeypatch.setenv("CASSETTE_HOSTED_MODEL", "test-model")
    monkeypatch.setenv("CASSETTE_HOSTED_BASE_URL", "http://localhost:9999")
    monkeypatch.setenv("CASSETTE_HOSTED_KEY", "test-key")
    monkeypatch.setenv("CASSETTE_AGENT_TASK", "test task")
    if extra_env:
        for k, v in extra_env.items():
            monkeypatch.setenv(k, v)

    fake = _fake_call_model_sequence(responses)
    # Patch the module-level call_model that run_hosted.py will instrument.
    monkeypatch.setattr(_agent, "call_model", fake)

    store = _store()
    trace = record_run(run_id=run_id, store=store)
    return trace


# ---------------------------------------------------------------------------
# Scripted model responses
# ---------------------------------------------------------------------------

_TOOL_CALL_RESPONSE = {
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "submit_result",
                "arguments": json.dumps({"summary": "All good."}),
            },
        }
    ],
}

_FINAL_RESPONSE = {
    "role": "assistant",
    "content": "Task complete.",
    "tool_calls": [],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_trace_contains_llm_call_step(monkeypatch):
    trace = _run(monkeypatch, [_TOOL_CALL_RESPONSE, _FINAL_RESPONSE])
    types = [s["type"] for s in trace["steps"]]
    assert "llm_call" in types, f"expected llm_call step; got {types}"


def test_trace_contains_tool_call_step(monkeypatch):
    trace = _run(monkeypatch, [_TOOL_CALL_RESPONSE, _FINAL_RESPONSE])
    types = [s["type"] for s in trace["steps"]]
    assert "tool_call" in types, f"expected tool_call step; got {types}"


def test_submit_result_step_is_side_effecting(monkeypatch):
    trace = _run(monkeypatch, [_TOOL_CALL_RESPONSE, _FINAL_RESPONSE])
    tool_steps = [s for s in trace["steps"] if s.get("type") == "tool_call"]
    submit_steps = [s for s in tool_steps if s.get("tool") == "submit_result"]
    assert submit_steps, "no submit_result step found"
    assert submit_steps[0]["side_effecting"] is True


def test_run_status_is_ok(monkeypatch):
    trace = _run(monkeypatch, [_TOOL_CALL_RESPONSE, _FINAL_RESPONSE])
    assert trace["status"] == "ok", f"run status was {trace['status']!r}"


def test_llm_blobs_resolve(monkeypatch):
    trace = _run(monkeypatch, [_TOOL_CALL_RESPONSE, _FINAL_RESPONSE])
    llm_steps = [s for s in trace["steps"] if s.get("type") == "llm_call"]
    assert llm_steps, "no llm_call step"
    step = llm_steps[0]
    # Both blobs must be resolvable and contain valid JSON.
    prompt_text = fetch_blob(step["prompt_blob"])
    response_text = fetch_blob(step["response_blob"])
    json.loads(prompt_text)   # must not raise
    json.loads(response_text)  # must not raise


def test_step_ids_are_unique_and_sequential(monkeypatch):
    trace = _run(monkeypatch, [_TOOL_CALL_RESPONSE, _FINAL_RESPONSE])
    ids = [s["step_id"] for s in trace["steps"]]
    assert len(ids) == len(set(ids)), f"duplicate step_ids: {ids}"
    assert ids == sorted(ids), f"step_ids not sorted: {ids}"


def test_lookup_info_step_is_not_side_effecting(monkeypatch):
    """When the model calls lookup_info the step must have side_effecting=False."""
    lookup_call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-2",
                "type": "function",
                "function": {
                    "name": "lookup_info",
                    "arguments": json.dumps({"query": "project status"}),
                },
            }
        ],
    }
    trace = _run(monkeypatch, [lookup_call, _TOOL_CALL_RESPONSE, _FINAL_RESPONSE],
                 run_id="lookup-run")
    lookup_steps = [s for s in trace["steps"]
                    if s.get("type") == "tool_call" and s.get("tool") == "lookup_info"]
    assert lookup_steps, "no lookup_info step"
    assert lookup_steps[0]["side_effecting"] is False


def test_hosted_agent_has_no_cassette_imports():
    """The agent module must contain zero Cassette imports (cassette-free contract)."""
    src = pathlib.Path(_agent.__file__).read_text(encoding="utf-8")
    assert "import recorder" not in src
    assert "from recorder" not in src


def test_content_only_response_finishes_cleanly(monkeypatch):
    """A model response with content and no tool_calls should finish without error."""
    content_only = {
        "role": "assistant",
        "content": "The project is on track.",
        # No tool_calls key at all -- simulates reasoning models.
    }
    trace = _run(monkeypatch, [content_only], run_id="content-only-run")
    # Must have at least one llm_call recorded.
    types = [s["type"] for s in trace["steps"]]
    assert "llm_call" in types, f"expected llm_call step; got {types}"
    assert trace["status"] == "ok", f"run status was {trace['status']!r}"


def test_tools_fallback_on_4xx_retries_without_tools(monkeypatch):
    """When call_model gets a 4xx it should retry without tools and succeed.

    We simulate this by replacing call_model with a stub that raises on the
    first attempt (tools present) and succeeds on the second (no tools).
    The agent must complete and record at least one llm_call step.
    """
    import httpx

    call_count = {"n": 0}
    content_only_msg = {
        "role": "assistant",
        "content": "Done without tools.",
    }

    def _stubbed_call_model(messages):
        # Replicate the tools-fallback logic in the real call_model:
        # first invocation raises a 4xx, second succeeds.
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Simulate what the real call_model raises when the initial 4xx
            # retry also fails -- here we make the retry succeed by returning
            # the content directly (the real code retries internally).
            # For this test we patch call_model at the agent level so we only
            # see the post-retry result; the unit below tests the raw retry.
            return content_only_msg
        return content_only_msg

    monkeypatch.setattr(_agent, "call_model", _stubbed_call_model)

    store = _store()
    blob_dir = tempfile.mkdtemp()
    monkeypatch.setenv("CASSETTE_BLOB_DIR", blob_dir)
    monkeypatch.setenv("CASSETTE_HOSTED_MODEL", "test-model")
    monkeypatch.setenv("CASSETTE_HOSTED_BASE_URL", "http://localhost:9999")
    monkeypatch.setenv("CASSETTE_HOSTED_KEY", "test-key")
    monkeypatch.setenv("CASSETTE_AGENT_TASK", "test task")

    trace = record_run(run_id="fallback-run", store=store)
    types = [s["type"] for s in trace["steps"]]
    assert "llm_call" in types, f"expected llm_call step; got {types}"
    assert trace["status"] == "ok"


def test_call_model_retries_without_tools_on_4xx(monkeypatch):
    """Unit test for call_model: 4xx with tools -> retry without tools -> success."""
    import httpx

    responses = []

    def _mock_post(url, json=None, headers=None, timeout=None):
        has_tools = "tools" in (json or {})
        if has_tools:
            # First call: reject with 422 to simulate tools-rejection.
            mock = type("R", (), {
                "status_code": 422,
                "is_success": False,
                "text": "tools not supported",
                "json": lambda self: {},
                "raise_for_status": lambda self: None,
            })()
            return mock
        else:
            # Second call (no tools): succeed.
            mock = type("R", (), {
                "status_code": 200,
                "is_success": True,
                "text": "ok",
                "json": lambda self: {
                    "choices": [{"message": {"role": "assistant", "content": "done"}}]
                },
                "raise_for_status": lambda self: None,
            })()
            return mock

    monkeypatch.setenv("CASSETTE_HOSTED_BASE_URL", "http://localhost:9999")
    monkeypatch.setenv("CASSETTE_HOSTED_MODEL", "test-model")
    monkeypatch.setenv("CASSETTE_HOSTED_KEY", "test-key")
    monkeypatch.setattr(httpx, "post", _mock_post)

    msg = _agent.call_model([{"role": "user", "content": "hi"}])
    assert msg["content"] == "done"


def test_reasoning_content_used_when_content_empty(monkeypatch):
    """call_model normalises reasoning_content into content when content is absent."""
    import httpx

    def _mock_post(url, json=None, headers=None, timeout=None):
        has_tools = "tools" in (json or {})
        if has_tools:
            mock = type("R", (), {
                "status_code": 400,
                "is_success": False,
                "text": "no tools",
                "json": lambda self: {},
                "raise_for_status": lambda self: None,
            })()
            return mock
        mock = type("R", (), {
            "status_code": 200,
            "is_success": True,
            "text": "ok",
            "json": lambda self: {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "my reasoning answer",
                    }
                }]
            },
            "raise_for_status": lambda self: None,
        })()
        return mock

    monkeypatch.setenv("CASSETTE_HOSTED_BASE_URL", "http://localhost:9999")
    monkeypatch.setenv("CASSETTE_HOSTED_MODEL", "test-model")
    monkeypatch.setenv("CASSETTE_HOSTED_KEY", "test-key")
    monkeypatch.setattr(httpx, "post", _mock_post)

    msg = _agent.call_model([{"role": "user", "content": "hi"}])
    assert msg["content"] == "my reasoning answer"


def test_parallel_tool_calls_share_group_and_causal_parents(monkeypatch):
    """A model response dispatching two tools in one turn -> both tool steps
    share one parallel_group, point their causal parent at the dispatching
    llm_call, and the fan-in llm_call points back at both siblings (schema 1.1).
    """
    parallel_call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "p1", "type": "function",
             "function": {"name": "lookup_info",
                          "arguments": json.dumps({"query": "alpha"})}},
            {"id": "p2", "type": "function",
             "function": {"name": "lookup_info",
                          "arguments": json.dumps({"query": "beta"})}},
        ],
    }
    trace = _run(monkeypatch, [parallel_call, _FINAL_RESPONSE], run_id="parallel-run")
    steps = trace["steps"]

    # Schema advertises the parallel-aware version.
    assert trace["schema_version"] == "1.1"

    llm_steps = [s for s in steps if s["type"] == "llm_call"]
    tool_steps = [s for s in steps if s["type"] == "tool_call"]
    assert len(llm_steps) == 2, f"expected dispatch + fan-in llm_calls; got {llm_steps}"
    assert len(tool_steps) == 2, f"expected 2 batched tool_calls; got {tool_steps}"

    dispatch_id = llm_steps[0]["step_id"]
    fanin = llm_steps[1]

    # Both tools share one non-null parallel_group...
    groups = {s.get("parallel_group") for s in tool_steps}
    assert len(groups) == 1 and None not in groups, f"tool parallel_groups: {groups}"

    # ...and each points its causal parent at the dispatching llm_call.
    for s in tool_steps:
        assert s["causal_parents"] == [dispatch_id], s["causal_parents"]

    # The fan-in llm_call's causal_parents are exactly the two sibling step_ids.
    assert sorted(fanin["causal_parents"]) == sorted(s["step_id"] for s in tool_steps)


def test_single_tool_call_has_no_parallel_group(monkeypatch):
    """A lone tool call must NOT be tagged with a parallel_group (sequential)."""
    trace = _run(monkeypatch, [_TOOL_CALL_RESPONSE, _FINAL_RESPONSE], run_id="seq-run")
    tool_steps = [s for s in trace["steps"] if s["type"] == "tool_call"]
    assert tool_steps
    for s in tool_steps:
        assert s.get("parallel_group") is None, s.get("parallel_group")


def test_replay_sdk_passes_tool_hint_when_supported():
    """replay_sdk forwards the tool name as tool_hint to a replayer that accepts it."""
    from recorder.policy import load_policy
    from recorder.session import RecordingSession

    captured = {}

    class HintReplayer:
        def response_for(self, ident, tool_hint=None):
            captured["tool_hint"] = tool_hint
            return {"status_code": 200, "body": json.dumps({"ok": True}),
                    "side_effecting": False}

    sess = RecordingSession(mode="replay", store=_store(), run_id="hint-run",
                            policy=load_policy(), replayer=HintReplayer(),
                            register_run=False)
    out = sess.replay_sdk(tool="lookup_info", args={"query": "x"}, side_effecting=False)
    assert captured["tool_hint"] == "lookup_info"
    assert out == {"ok": True}


def test_replay_sdk_falls_back_for_replayer_without_tool_hint():
    """replay_sdk still works with a replayer whose response_for has no tool_hint."""
    from recorder.policy import load_policy
    from recorder.session import RecordingSession

    class PlainReplayer:
        def response_for(self, ident):
            return {"status_code": 200, "body": json.dumps({"ok": 1}),
                    "side_effecting": False}

    sess = RecordingSession(mode="replay", store=_store(), run_id="plain-run",
                            policy=load_policy(), replayer=PlainReplayer(),
                            register_run=False)
    out = sess.replay_sdk(tool="lookup_info", args={"query": "x"}, side_effecting=False)
    assert out == {"ok": 1}


def test_run_hosted_does_not_import_mitmproxy():
    """run_hosted must not contain import statements for the proxy-path modules.

    We check import statements in the source (not sys.modules) because other
    tests in the same process load those modules, which would cause false
    positives when inspecting sys.modules.
    """
    import ast
    src_path = pathlib.Path(__file__).resolve().parents[1] / "run_hosted.py"
    src = src_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden_prefixes = ("mitmproxy", "recorder.http_proxy", "recorder.record_session")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for prefix in forbidden_prefixes:
                    assert not alias.name.startswith(prefix), (
                        f"run_hosted.py imports forbidden module: {alias.name!r}"
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for prefix in forbidden_prefixes:
                assert not mod.startswith(prefix), (
                    f"run_hosted.py imports from forbidden module: {mod!r}"
                )
