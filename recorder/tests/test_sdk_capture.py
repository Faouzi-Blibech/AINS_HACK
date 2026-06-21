import os, tempfile, json
os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

from recorder.capture import sdk_identity, build_sdk_step
from recorder.policy import load_policy
from trace_store.blob_store import fetch_blob

P = load_policy()


def test_sdk_identity_is_tool_and_arg_sensitive():
    base = sdk_identity("get_priority", {"raw": "P1"}, P.volatile_fields())
    assert base.startswith("sdk get_priority\n")
    assert base != sdk_identity("assign_ticket", {"raw": "P1"}, P.volatile_fields())
    assert base != sdk_identity("get_priority", {"raw": "P3"}, P.volatile_fields())


def test_sdk_identity_strips_volatile_args_nested():
    a = sdk_identity("t", {"meta": {"timestamp": 1}, "k": 1}, P.volatile_fields())
    b = sdk_identity("t", {"meta": {"timestamp": 9}, "k": 1}, P.volatile_fields())
    assert a == b


def test_build_sdk_step_shape_and_redaction():
    step = build_sdk_step(
        step_id=3, prev_step_id=2, tool="assign_ticket",
        args={"ticket_key": "T1", "api_key": "secret"},
        result={"ok": True}, side_effecting=True,
        latency_ms=4, ts_ms=123, policy=P,
    )
    assert step["transport"] == "sdk" and step["type"] == "tool_call"
    assert step["tool"] == "assign_ticket" and step["side_effecting"] is True
    assert step["step_id"] == 3 and step["causal_parents"] == [2]
    assert step["request_identity"] == sdk_identity(
        "assign_ticket", {"ticket_key": "T1", "api_key": "secret"}, P.volatile_fields())
    # secret redacted in the stored args blob
    assert "secret" not in fetch_blob(step["args_blob"])
    assert json.loads(fetch_blob(step["result_blob"])) == {"ok": True}
