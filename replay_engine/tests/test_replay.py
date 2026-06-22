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


def _error_tool(step_id, url, body, resp, status_code=500):
    """Build a step that was recorded as an error (status_code >= 400)."""
    return build_step(step_id=step_id, prev_step_id=None, method="POST", url=url,
        req_body=body, status_code=status_code, resp_body=resp, latency_ms=1, ts_ms=1, policy=P)


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


def test_response_for_miss_returns_none_when_synthesis_disabled():
    """synthesize_on_miss=False keeps the original None divergence signal."""
    store = _store([_tool(1, "http://127.0.0.1:9/a", '{}', '{"ok":true}')])
    r = Replayer(store, "r", synthesize_on_miss=False)
    assert r.response_for("POST /nope\nx") is None


def test_response_for_miss_returns_synthesized_response():
    """synthesize_on_miss=True (default) returns a synthesized envelope on a miss."""
    store = _store([_tool(1, "http://127.0.0.1:9/a", '{}', '{"ok":true}')])
    r = Replayer(store, "r")  # synthesize_on_miss=True by default
    resp = r.response_for("POST /nope\nx")
    assert resp is not None
    assert resp["synthesized"] is True
    assert r.synthesized_count == 1


def test_get_response_for_hash_miss_synthesizes():
    """A hash miss with synthesize_on_miss=True returns a synthesized envelope."""
    store = _store([_tool(1, "http://127.0.0.1:9/a", '{}', '{"ok":true}')])
    r = Replayer(store, "r")
    resp = r.get_response_for_hash("sha256:" + "a" * 64)
    assert resp["synthesized"] is True
    assert r.synthesized_count == 1


def test_get_response_for_hash_miss_raises_when_synthesis_disabled():
    """A hash miss with synthesize_on_miss=False raises ReplayError."""
    import pytest
    from replay_engine.replay import ReplayError
    store = _store([_tool(1, "http://127.0.0.1:9/a", '{}', '{"ok":true}')])
    r = Replayer(store, "r", synthesize_on_miss=False)
    with pytest.raises(ReplayError, match="No recorded step found"):
        r.get_response_for_hash("sha256:" + "a" * 64)


# ---------------------------------------------------------------------------
# Error-step tests
# ---------------------------------------------------------------------------

def test_error_step_faithful_mode_replays_error_payload():
    """Default faithful mode returns the error payload with is_error_step=True.

    response_for does NOT own error_step_count (EC-6 fix); the counter stays 0
    on this path. Only _build_response (hash / sequential paths) increments it.
    """
    url, body = "http://127.0.0.1:9/get_priority", '{}'
    store = _store([_error_tool(1, url, body, '{"error":"internal"}', status_code=500)])
    r = Replayer(store, "r")  # error_step_mode="faithful" by default
    ident = request_identity("POST", url, body, P.volatile_fields())
    resp = r.response_for(ident)
    assert resp["is_error_step"] is True
    assert resp["status_code"] == 500
    assert r.error_step_count == 0  # response_for does not own the counter (EC-6)


def test_error_step_suppress_mode_returns_empty_success():
    """suppress mode replaces the error with {} and status_code=200.

    response_for does NOT own error_step_count (EC-6 fix); the counter stays 0
    on this path. The caller still sees is_error_step=True in the envelope.
    """
    url, body = "http://127.0.0.1:9/get_priority", '{}'
    store = _store([_error_tool(1, url, body, '{"error":"internal"}', status_code=500)])
    r = Replayer(store, "r", error_step_mode="suppress")
    ident = request_identity("POST", url, body, P.volatile_fields())
    resp = r.response_for(ident)
    assert resp["is_error_step"] is True   # caller still knows it was an error
    assert resp["status_code"] == 200      # suppressed so agent can continue
    assert resp["body"] == "{}"            # response_for envelope uses 'body', not 'payload'
    assert r.error_step_count == 0  # response_for does not own the counter (EC-6)


def test_finish_reports_error_step_count():
    """finish() includes error_step_count in ReplayResult (sequential path)."""
    url, body = "http://127.0.0.1:9/get_priority", '{}'
    store = _store([
        _tool(1, "http://127.0.0.1:9/ok", '{}', '{"ok":true}'),
        _error_tool(2, url, body, '{"error":"oops"}', status_code=404),
    ])
    r = Replayer(store, "r")
    r.get_next_response("tool_call")
    r.get_next_response("tool_call")
    result = r.finish()
    assert result.error_step_count == 1
    assert result.steps_replayed == 2


# ---------------------------------------------------------------------------
# EC-6 regression: error_step_count owned exclusively by _build_response
# ---------------------------------------------------------------------------

def test_error_step_count_not_incremented_via_response_for():
    """response_for on an error step must NOT increment error_step_count.

    Before EC-6 fix both response_for and _build_response incremented the
    counter, so mixing the two APIs on one Replayer caused double-counting.
    After the fix only _build_response owns it; response_for leaves it at 0.
    """
    url, body = "http://127.0.0.1:9/send_email", '{"to":"a@b.com"}'
    store = _store([_error_tool(1, url, body, '{"error":"mailbox unavailable"}', status_code=503)])
    r = Replayer(store, "r")
    ident = request_identity("POST", url, body, P.volatile_fields())

    resp = r.response_for(ident)
    assert resp["is_error_step"] is True  # envelope still signals the error
    assert r.error_step_count == 0, (
        "response_for must not touch error_step_count; "
        "only _build_response (hash / sequential paths) owns the counter"
    )


def test_error_step_count_incremented_once_via_hash_path():
    """get_response_for_hash on an error step increments error_step_count exactly once."""
    url, body = "http://127.0.0.1:9/get_priority", '{}'
    error_step = _error_tool(1, url, body, '{"error":"oops"}', status_code=500)
    store = _store([error_step])
    r = Replayer(store, "r")

    # Retrieve the real args_blob ref the store assigned
    args_ref = store.get_run("r")["steps"][0]["args_blob"]

    resp = r.get_response_for_hash(args_ref)
    assert resp["is_error_step"] is True
    assert r.error_step_count == 1, "hash path must count the error step exactly once"


# ---------------------------------------------------------------------------
# Tape-exhaustion / record-over fork tests
# ---------------------------------------------------------------------------

def _fork_store(steps, fork_step_id=1):
    """Create a store with a record-over forked run (simulates divergence.fork())."""
    store = TraceStore(db_path=os.path.join(tempfile.mkdtemp(), "t.sqlite3"))
    store.start_run(
        "fork",
        agent="",
        mode="record-over",
        created_at_ms=0,
        fork_step_id=fork_step_id,
        parent_run_id="original",
    )
    for s in steps:
        store.append_step("fork", s)
    return store


def test_tape_exhausted_non_fork_raises_replay_error():
    """Normal play run — cursor exhausted raises ReplayError (genuine mismatch)."""
    import pytest
    from replay_engine.replay import ReplayError, TapeExhaustedForFork
    store = _store([_tool(1, "http://127.0.0.1:9/a", '{}', '{"ok":true}')])
    r = Replayer(store, "r")
    r.get_next_response("tool_call")  # consumes the one step
    with pytest.raises(ReplayError) as exc_info:
        r.get_next_response("tool_call")
    assert not isinstance(exc_info.value, TapeExhaustedForFork)


def test_tape_exhausted_record_over_synthesizes_when_enabled():
    """Record-over fork + synthesize_on_miss=True → synthesized response returned."""
    store = _fork_store([_tool(1, "http://127.0.0.1:9/a", '{}', '{"ok":true}')], fork_step_id=1)
    r = Replayer(store, "fork")  # synthesize_on_miss=True by default
    r.get_next_response("tool_call")  # consume the one tape step
    resp = r.get_next_response("tool_call")  # past tape end → synthesize
    assert resp["synthesized"] is True
    assert r.synthesized_count == 1


def test_tape_exhausted_record_over_raises_fork_signal_when_disabled():
    """Record-over fork + synthesize_on_miss=False → TapeExhaustedForFork raised."""
    import pytest
    from replay_engine.replay import TapeExhaustedForFork
    store = _fork_store([_tool(1, "http://127.0.0.1:9/a", '{}', '{"ok":true}')], fork_step_id=1)
    r = Replayer(store, "fork", synthesize_on_miss=False)
    r.get_next_response("tool_call")
    with pytest.raises(TapeExhaustedForFork) as exc_info:
        r.get_next_response("tool_call")
    assert exc_info.value.fork_step_id == 1


def test_finish_status_fork_live_for_record_over():
    """finish() reports status='fork-live' when a record-over run went past its tape."""
    store = _fork_store([_tool(1, "http://127.0.0.1:9/a", '{}', '{"ok":true}')], fork_step_id=1)
    r = Replayer(store, "fork")
    r.get_next_response("tool_call")  # consume tape
    r.get_next_response("tool_call")  # past tape → synthesized
    result = r.finish()
    assert result.status == "fork-live"
    assert result.synthesized_count == 1

