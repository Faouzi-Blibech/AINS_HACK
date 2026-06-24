import os, tempfile, json
os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

from recorder.capture import build_step, request_identity
from recorder.policy import load_policy
from trace_store.blob_store import fetch_blob

P = load_policy()

def _llm_step():
    return build_step(step_id=1, prev_step_id=None, method="POST",
        url="http://127.0.0.1:9/v1/chat/completions",
        req_body='{"model":"m","messages":[{"role":"user","content":"hi"}]}',
        status_code=200,
        resp_body='{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":5,"completion_tokens":2}}',
        latency_ms=12, ts_ms=1000, policy=P)

def test_llm_step_shape():
    s = _llm_step()
    assert s["type"] == "llm_call" and s["transport"] == "http"
    assert s["model"] == "m" and s["side_effecting"] is False
    # confidence is now a heuristic record-time proxy (0..1), not None.
    assert isinstance(s["confidence"], (int, float)) and s["causal_parents"] == []
    assert s["token_usage"] == {"prompt": 5, "completion": 2}
    assert fetch_blob(s["prompt_blob"]).startswith("{")

def test_tool_step_side_effecting_and_parents():
    s = build_step(step_id=2, prev_step_id=1, method="POST",
        url="http://127.0.0.1:9/assign_ticket",
        req_body='{"team":"x"}', status_code=200, resp_body='{"ok":true}',
        latency_ms=3, ts_ms=1001, policy=P)
    assert s["type"] == "tool_call" and s["tool"] == "assign_ticket"
    assert s["side_effecting"] is True and s["causal_parents"] == [1]

def test_secret_redacted_in_blob():
    s = build_step(step_id=1, prev_step_id=None, method="POST",
        url="http://127.0.0.1:9/tool", req_body='{"api_key":"sk-XYZ"}',
        status_code=200, resp_body="{}", latency_ms=1, ts_ms=1, policy=P)
    assert "sk-XYZ" not in fetch_blob(s["args_blob"])

def test_request_identity_stable_ignores_volatile():
    a = request_identity("POST", "http://h/x", '{"a":1,"timestamp":1}', ["timestamp"])
    b = request_identity("POST", "http://h/x", '{"timestamp":999,"a":1}', ["timestamp"])
    assert a == b

def test_step_carries_status_code_and_request_identity():
    s = build_step(step_id=1, prev_step_id=None, method="POST",
        url="http://127.0.0.1:9/assign_ticket",
        req_body='{"ticket_key":"T1","team":"Backend"}',
        status_code=201, resp_body='{"ok":true}', latency_ms=4, ts_ms=1, policy=P)
    assert s["status_code"] == 201
    assert s["request_identity"] == request_identity(
        "POST", "http://127.0.0.1:9/assign_ticket",
        '{"ticket_key":"T1","team":"Backend"}', P.volatile_fields())
