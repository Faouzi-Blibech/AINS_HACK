"""Offline tests for the sophisticated local agent (agent/ops_incident_agent.py)
recorded via the SDK-hooks runner (recorder/run_agent.py). Deterministic; no key.
"""
import os
import pathlib
import tempfile

os.environ["CASSETTE_BLOB_DIR"] = tempfile.mkdtemp()

from recorder.run_agent import record_over, record_run
from trace_store.store import TraceStore


def _store():
    return TraceStore(db_path=os.path.join(tempfile.mkdtemp(), "t.sqlite3"))


def _record(monkeypatch, run_id="ops-test"):
    blob_dir = tempfile.mkdtemp()
    monkeypatch.setenv("CASSETTE_BLOB_DIR", blob_dir)
    monkeypatch.setenv("CASSETTE_HOSTED_MODEL", "ops-incident-agent (scripted)")
    return record_run(module="agent.ops_incident_agent", run_id=run_id, store=_store())


def test_agent_is_cassette_free():
    import agent.ops_incident_agent as a
    src = pathlib.Path(a.__file__).read_text(encoding="utf-8")
    assert "import recorder" not in src and "from recorder" not in src


def test_records_a_rich_multi_step_trace(monkeypatch):
    trace = _record(monkeypatch)
    steps = trace["steps"]
    assert len(steps) >= 20, f"expected a rich trace; got {len(steps)} steps"
    kinds = {s["type"] for s in steps}
    assert "llm_call" in kinds and "tool_call" in kinds
    assert trace["schema_version"] == "1.1"


def test_step_ids_unique_and_sequential(monkeypatch):
    steps = _record(monkeypatch, run_id="ops-seq")["steps"]
    ids = [s["step_id"] for s in steps]
    assert ids == sorted(ids) and len(ids) == len(set(ids))


def test_parallel_batches_are_grouped(monkeypatch):
    """The two multi-tool model turns produce parallel_group-tagged tool steps."""
    steps = _record(monkeypatch, run_id="ops-par")["steps"]
    groups: dict[str, list[int]] = {}
    for s in steps:
        pg = s.get("parallel_group")
        if pg:
            groups.setdefault(pg, []).append(s["step_id"])
    # Two parallel batches (one of 3 tools, one of 2 tools).
    assert len(groups) == 2, f"expected 2 parallel groups; got {groups}"
    sizes = sorted(len(v) for v in groups.values())
    assert sizes == [2, 3], f"expected batches of 2 and 3; got {sizes}"
    # Siblings in a batch share one dispatching llm_call as causal parent.
    for sibling_ids in groups.values():
        parents = {
            tuple(s["causal_parents"])
            for s in steps if s["step_id"] in sibling_ids
        }
        assert len(parents) == 1, f"siblings disagree on causal parent: {parents}"


def test_side_effecting_tools_flagged(monkeypatch):
    steps = _record(monkeypatch, run_id="ops-se")["steps"]
    by_tool = {s.get("tool"): s for s in steps if s["type"] == "tool_call"}
    for ro in ("fetch_incident", "check_service_health", "search_runbook"):
        assert by_tool[ro]["side_effecting"] is False, ro
    for se in ("set_severity", "assign_incident", "page_oncall", "resolve_incident"):
        assert by_tool[se]["side_effecting"] is True, se


def test_steps_have_confidence(monkeypatch):
    """Heuristic confidence is populated (no more n/a) on recorded steps."""
    steps = _record(monkeypatch, run_id="ops-conf")["steps"]
    assert all(isinstance(s.get("confidence"), (int, float)) for s in steps)


def test_low_severity_takes_minimal_path(monkeypatch):
    """Overriding the severity decision makes the agent take a different path."""
    monkeypatch.setenv("CASSETTE_OPS_SEVERITY", "SEV-4")
    trace = _record(monkeypatch, run_id="ops-low")
    tools = [s.get("tool") for s in trace["steps"] if s["type"] == "tool_call"]
    assert "resolve_incident" in tools
    assert "page_oncall" not in tools and "create_followup_ticket" not in tools


def test_record_over_diverges(monkeypatch):
    """Record-over re-runs the agent with a new value -> a divergent forked run."""
    monkeypatch.setenv("CASSETTE_BLOB_DIR", tempfile.mkdtemp())
    store = _store()
    base = record_run(module="agent.ops_incident_agent", run_id="ob", store=store)
    fork = record_over(module="agent.ops_incident_agent", base_run_id="ob",
                       override_env="CASSETTE_OPS_SEVERITY", value="SEV-4", store=store)
    assert fork["parent_run_id"] == "ob"
    assert fork["mode"] == "record-over"
    assert len(fork["steps"]) < len(base["steps"])  # low path is shorter


def test_failing_run_is_recorded_and_record_over_fixes_it(monkeypatch):
    """A wrong (low) severity decision produces a recorded FAILURE; re-running
    with the correct severity via record-over fixes it."""
    monkeypatch.setenv("CASSETTE_BLOB_DIR", tempfile.mkdtemp())
    monkeypatch.setenv("CASSETTE_OPS_SEVERITY", "SEV-4")  # wrong/low -> verify fails
    store = _store()
    fail = record_run(module="agent.ops_incident_agent", run_id="of", store=store)
    assert fail["status"] == "error"
    assert any(s.get("status") == "error" for s in fail["steps"])
    monkeypatch.delenv("CASSETTE_OPS_SEVERITY", raising=False)
    fork = record_over(module="agent.ops_incident_agent", base_run_id="of",
                       override_env="CASSETTE_OPS_SEVERITY", value="SEV-2", store=store)
    assert fork["status"] == "ok"  # the corrected re-run passes
