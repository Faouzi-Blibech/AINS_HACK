"""Tests for GET /eval.

The endpoint now computes metrics LIVE from the recorded runs in the store
(the demo runs seeded at import), replayed through the real divergence engine,
rather than reading a static results.json file.
"""
from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def _client() -> TestClient:
    import api.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app)


def test_eval_available_with_seeded_runs() -> None:
    """With seeded demo runs present, /eval is available and computed."""
    resp = _client().get("/eval")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["generated_at"]
    keys = {m["key"] for m in body["metrics"]}
    assert {
        "runs_evaluated",
        "pass_rate",
        "determinism_rate",
        "side_effect_containment",
    } <= keys


def test_eval_side_effect_containment_is_zero() -> None:
    """The core safety invariant: zero real side effects executed on replay."""
    body = _client().get("/eval").json()
    containment = next(m for m in body["metrics"] if m["key"] == "side_effect_containment")
    assert containment["value"] == 0
    assert containment["passed"] is True
    assert containment["unit"] == "count"


def test_eval_determinism_is_a_fraction() -> None:
    body = _client().get("/eval").json()
    det = next(m for m in body["metrics"] if m["key"] == "determinism_rate")
    assert det["unit"] == "fraction"
    assert det["value"] is None or 0.0 <= det["value"] <= 1.0


def test_eval_pass_rate_in_range() -> None:
    body = _client().get("/eval").json()
    pr = next(m for m in body["metrics"] if m["key"] == "pass_rate")
    assert pr["unit"] == "fraction"
    assert 0.0 <= pr["value"] <= 1.0
