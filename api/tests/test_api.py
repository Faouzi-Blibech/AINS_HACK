"""Tests for the Cassette FastAPI backend.

Uses FastAPI TestClient; the app self-seeds on import so no external
process or database setup is needed.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /runs
# ---------------------------------------------------------------------------


def test_list_runs_returns_200_and_includes_fixture() -> None:
    """GET /runs returns HTTP 200 and the fixture run appears in the list."""
    resp = client.get("/runs")
    assert resp.status_code == 200
    body = resp.json()
    run_ids = [r["run_id"] for r in body["runs"]]
    assert "run-fixture-001" in run_ids
    assert body["total"] >= 3


# ---------------------------------------------------------------------------
# GET /runs/{run_id}
# ---------------------------------------------------------------------------


def test_get_fixture_run_returns_full_trace() -> None:
    """GET /runs/run-fixture-001 returns the full 4-step trace with status error."""
    resp = client.get("/runs/run-fixture-001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "run-fixture-001"
    assert body["status"] == "error"
    assert len(body["steps"]) == 4


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/steps/{step_id}
# ---------------------------------------------------------------------------


def test_get_step_2_resolves_tool_result() -> None:
    """GET /runs/run-fixture-001/steps/2 resolves result blob to the expected dict."""
    resp = client.get("/runs/run-fixture-001/steps/2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool"] == "get_priority"
    assert body["result"] == {"priority": "medium", "raw": "P2 / medium?"}


def test_get_step_1_resolves_llm_prompt() -> None:
    """GET /runs/run-fixture-001/steps/1 resolves prompt blob containing the ticket text."""
    resp = client.get("/runs/run-fixture-001/steps/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["prompt"] is not None
    assert "Triage Jira ticket OPS-4521" in body["prompt"]


# ---------------------------------------------------------------------------
# 404 cases
# ---------------------------------------------------------------------------


def test_unknown_run_returns_404() -> None:
    """GET /runs/<unknown> returns HTTP 404."""
    resp = client.get("/runs/does-not-exist")
    assert resp.status_code == 404


def test_unknown_step_returns_404() -> None:
    """GET /runs/run-fixture-001/steps/99 returns HTTP 404."""
    resp = client.get("/runs/run-fixture-001/steps/99")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/blame
# ---------------------------------------------------------------------------


def test_blame_fixture_run_returns_200_with_root_cause_step_2() -> None:
    """GET /runs/run-fixture-001/blame -> 200; root_cause_step_id == 2; verdict mentions Step 2."""
    resp = client.get("/runs/run-fixture-001/blame")
    assert resp.status_code == 200
    body = resp.json()
    assert body["root_cause_step_id"] == 2
    assert "Step 2" in body["verdict"]
    assert len(body["steps"]) > 0
    assert body["confidence"] is not None


def test_blame_fixture_step2_has_highest_blame_score() -> None:
    """Step 2 entry in blame steps should have blame_score == 1.0 (the resolving step)."""
    resp = client.get("/runs/run-fixture-001/blame")
    assert resp.status_code == 200
    body = resp.json()
    step2 = next((s for s in body["steps"] if s["step_id"] == 2), None)
    assert step2 is not None
    assert step2["blame_score"] == 1.0


def test_blame_ok_run_does_not_500() -> None:
    """GET /runs/run-ok-0002/blame -> 200; no failure so root_cause_step_id is null."""
    resp = client.get("/runs/run-ok-0002/blame")
    assert resp.status_code == 200
    body = resp.json()
    assert body["root_cause_step_id"] is None
    assert "did not fail" in body["verdict"].lower() or "not fail" in body["verdict"].lower()


# ---------------------------------------------------------------------------
# GET /library
# ---------------------------------------------------------------------------


def test_library_returns_200_with_at_least_3_entries() -> None:
    """GET /library -> 200; total >= 3; at least one entry has blame_step == 2."""
    resp = client.get("/library")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 3
    assert any(e["blame_step"] == 2 for e in body["entries"])


def test_library_query_param_filters_by_priority() -> None:
    """GET /library?q=priority -> 200; only entries matching 'priority' are returned."""
    resp = client.get("/library?q=priority")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    for entry in body["entries"]:
        text = (entry["failure_pattern"] + entry["fix_that_worked"]).lower()
        assert "priority" in text


# ---------------------------------------------------------------------------
# GET /metrics
# ---------------------------------------------------------------------------


def test_metrics_returns_200_with_valid_values() -> None:
    """GET /metrics -> 200; pass_rate in [0,1]; contained_pct == 100; runs_24h >= 3."""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert 0.0 <= body["pass_rate"] <= 1.0
    assert body["contained_pct"] == 100
    assert body["runs_24h"] >= 3
