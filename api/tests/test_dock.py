"""Tests for the Trace dock endpoints: /inject, /diverge, /counterfactual.

All tests are offline-safe (no LLM, no network). Uses FastAPI TestClient.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)

RUN_ID = "run-fixture-001"


# ---------------------------------------------------------------------------
# POST /runs/{run_id}/inject
# ---------------------------------------------------------------------------


class TestInject:

    def test_inject_missing_run_returns_404(self) -> None:
        resp = client.post("/runs/does-not-exist/inject", json={"instruction": "test"})
        assert resp.status_code == 404

    def test_inject_without_llm_key_returns_200_available_false(self, monkeypatch) -> None:
        """When GROQ_API_KEY is absent, /inject returns 200 with available=false."""
        import ai_agents.llm as _llm

        def _raise(*args, **kwargs):
            raise _llm.LLMNotConfigured("no key")

        monkeypatch.setattr("ai_agents.debug_agent.llm.llm_complete", _raise)

        resp = client.post(f"/runs/{RUN_ID}/inject", json={"instruction": "make step 2 high priority"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is False
        assert "detail" in body

    def test_inject_with_stub_returns_injection_shape(self, monkeypatch) -> None:
        """When build_injection is monkeypatched, /inject returns the injection shape."""
        from ai_agents.replay_interface import Injection
        from ai_agents.confidence import wrap

        fake_injection = Injection(step_id=2, target="result", value='{"priority": "high"}')
        fake_result = wrap(fake_injection, confidence=0.9, rationale="test rationale")

        monkeypatch.setattr("ai_agents.debug_agent.build_injection", lambda *a, **kw: fake_result)

        resp = client.post(f"/runs/{RUN_ID}/inject", json={"instruction": "make step 2 high priority"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["injection"]["step_id"] == 2
        assert body["injection"]["target"] == "result"
        assert body["confidence"] == pytest.approx(0.9, abs=1e-6)
        assert body["rationale"] == "test rationale"


# ---------------------------------------------------------------------------
# POST /runs/{run_id}/diverge
# ---------------------------------------------------------------------------


class TestDiverge:

    def test_diverge_missing_run_returns_404(self) -> None:
        resp = client.post(
            "/runs/does-not-exist/diverge",
            json={"step_id": 2, "target": "result", "value": '{"priority": "high"}'},
        )
        assert resp.status_code == 404

    def test_diverge_invalid_step_returns_422(self) -> None:
        resp = client.post(
            f"/runs/{RUN_ID}/diverge",
            json={"step_id": 999, "target": "result", "value": '{"priority": "high"}'},
        )
        assert resp.status_code == 422

    def test_diverge_step2_returns_fork_and_diff(self) -> None:
        resp = client.post(
            f"/runs/{RUN_ID}/diverge",
            json={"step_id": 2, "target": "result", "value": '{"priority": "high"}'},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "fork_run_id" in body
        assert body["fork_run_id"] != RUN_ID
        assert "diff" in body
        diff = body["diff"]
        assert "edited_fields" in diff
        assert len(diff["edited_fields"]) > 0
        assert body["side_effect_count"] == 0

    def test_diverge_side_effect_count_is_zero(self) -> None:
        resp = client.post(
            f"/runs/{RUN_ID}/diverge",
            json={"step_id": 2, "target": "result", "value": '{"priority": "high"}'},
        )
        assert resp.status_code == 200
        assert resp.json()["side_effect_count"] == 0


# ---------------------------------------------------------------------------
# POST /runs/{run_id}/counterfactual
# ---------------------------------------------------------------------------


class TestCounterfactual:

    def test_counterfactual_missing_run_returns_404(self) -> None:
        resp = client.post("/runs/does-not-exist/counterfactual", json={})
        assert resp.status_code == 404

    def test_counterfactual_returns_variants_offline(self) -> None:
        """Works without any GROQ key (offline fallback generates template variants)."""
        resp = client.post(f"/runs/{RUN_ID}/counterfactual", json={"n": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert len(body["variants"]) >= 1
        assert "winner" in body
        assert "confidence" in body
        assert "rationale" in body

    def test_counterfactual_variants_side_effect_count_is_zero(self) -> None:
        resp = client.post(f"/runs/{RUN_ID}/counterfactual", json={"n": 2})
        assert resp.status_code == 200
        body = resp.json()
        for v in body["variants"]:
            assert v["side_effect_count"] == 0

    def test_counterfactual_with_explicit_step_id(self) -> None:
        resp = client.post(f"/runs/{RUN_ID}/counterfactual", json={"step_id": 2, "n": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert len(body["variants"]) >= 1
