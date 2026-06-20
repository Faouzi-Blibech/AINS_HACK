"""Tests for the GET /eval endpoint.

Uses FastAPI TestClient with the CASSETTE_EVAL_RESULTS env var pointed at
temporary JSON files so the tests are fully self-contained and do not depend
on the presence of eval/results.json in the repo.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Minimal valid results payload that mirrors what eval/harness.py writes.
# Includes an int containment value and a null P/R pair to exercise type
# preservation.
# ---------------------------------------------------------------------------

_SAMPLE_RESULTS = {
    "generated_at": "2026-06-20T22:17:55.800505+00:00",
    "available": True,
    "metrics": [
        {
            "key": "determinism_rate",
            "label": "Determinism Rate",
            "value": 1.0,
            "target_text": "100%",
            "passed": True,
            "unit": "fraction",
        },
        {
            # int containment count - must not be coerced to something lossy
            "key": "side_effect_containment",
            "label": "Side-effect Containment",
            "value": 0,
            "target_text": "0",
            "passed": True,
            "unit": "count",
        },
        {
            # null value and null passed when LLM key absent
            "key": "semantic_match_precision",
            "label": "Semantic Match Precision",
            "value": None,
            "target_text": "> 0.85",
            "passed": None,
            "unit": "fraction",
        },
        {
            "key": "root_cause_accuracy",
            "label": "Root-cause Accuracy",
            "value": 0.8,
            "target_text": "> 75%",
            "passed": True,
            "unit": "fraction",
        },
    ],
    "caveats": ["ScriptedReplay is a stand-in for the real divergence engine."],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_temp_results(data: dict) -> str:
    """Write *data* as JSON to a temp file and return the file path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    Path(path).write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_eval_present_file_returns_200_available_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /eval with a valid results file returns 200 and available=True."""
    path = _write_temp_results(_SAMPLE_RESULTS)
    try:
        monkeypatch.setenv("CASSETTE_EVAL_RESULTS", path)
        # Re-import the app AFTER patching the env so EVAL_RESULTS_PATH picks up the new value.
        import importlib
        import api.app as app_module
        importlib.reload(app_module)
        client = TestClient(app_module.app)

        resp = client.get("/eval")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["generated_at"] == _SAMPLE_RESULTS["generated_at"]
        assert len(body["metrics"]) == 4
        assert len(body["caveats"]) == 1
    finally:
        os.unlink(path)


def test_eval_int_containment_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """The side_effect_containment int value (0) is returned as a number, not null."""
    path = _write_temp_results(_SAMPLE_RESULTS)
    try:
        monkeypatch.setenv("CASSETTE_EVAL_RESULTS", path)
        import importlib
        import api.app as app_module
        importlib.reload(app_module)
        client = TestClient(app_module.app)

        resp = client.get("/eval")
        assert resp.status_code == 200
        body = resp.json()
        containment = next(m for m in body["metrics"] if m["key"] == "side_effect_containment")
        assert containment["value"] == 0
        assert containment["passed"] is True
    finally:
        os.unlink(path)


def test_eval_null_value_and_passed_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Metrics with null value and null passed are returned as null, not coerced."""
    path = _write_temp_results(_SAMPLE_RESULTS)
    try:
        monkeypatch.setenv("CASSETTE_EVAL_RESULTS", path)
        import importlib
        import api.app as app_module
        importlib.reload(app_module)
        client = TestClient(app_module.app)

        resp = client.get("/eval")
        assert resp.status_code == 200
        body = resp.json()
        precision = next(m for m in body["metrics"] if m["key"] == "semantic_match_precision")
        assert precision["value"] is None
        assert precision["passed"] is None
    finally:
        os.unlink(path)


def test_eval_missing_file_returns_200_available_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /eval with a non-existent results path returns 200 and available=False."""
    monkeypatch.setenv("CASSETTE_EVAL_RESULTS", "/nonexistent/path/results.json")
    import importlib
    import api.app as app_module
    importlib.reload(app_module)
    client = TestClient(app_module.app)

    resp = client.get("/eval")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["metrics"] == []
    assert body["caveats"] == []


def test_eval_corrupt_file_returns_200_available_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /eval with unparseable JSON returns 200 and available=False."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    Path(path).write_text("not valid json {{{{", encoding="utf-8")
    try:
        monkeypatch.setenv("CASSETTE_EVAL_RESULTS", path)
        import importlib
        import api.app as app_module
        importlib.reload(app_module)
        client = TestClient(app_module.app)

        resp = client.get("/eval")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is False
        assert body["metrics"] == []
    finally:
        os.unlink(path)
