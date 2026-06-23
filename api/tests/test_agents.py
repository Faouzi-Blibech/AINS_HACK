"""Tests for POST /agents/run and GET /agents/connect-info.

The _launch_hosted_run helper is monkeypatched in every subprocess test so
no real Python process, network, or external service is spawned.
"""
from __future__ import annotations

import subprocess
import time

import pytest
from fastapi.testclient import TestClient

import api.app as _app_module
from api.app import app, store

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_run(run_id: str, steps: int = 2) -> None:
    """Insert a minimal fake run into the shared store."""
    store.start_run(run_id, agent="hosted_agent", mode="record")
    for i in range(1, steps + 1):
        store.append_step(
            run_id,
            {
                "step_id": i,
                "type": "tool_call",
                "timestamp_ms": int(time.time() * 1000),
                "status": "ok",
                "side_effecting": False,
            },
        )
    store.finish_run(run_id, status="ok")


def _make_success_launcher(steps: int = 2):
    """Return a fake launcher that seeds a run and returns returncode=0."""
    def _launcher(run_id, base_url, model, api_key, task):
        _seed_run(run_id, steps=steps)
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
    return _launcher


def _make_failure_launcher(returncode: int = 1):
    """Return a fake launcher that returns a non-zero returncode."""
    def _launcher(run_id, base_url, model, api_key, task):
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout="", stderr="some internal error"
        )
    return _launcher


# ---------------------------------------------------------------------------
# POST /agents/run -- success path
# ---------------------------------------------------------------------------


def test_agents_run_success(monkeypatch):
    """Launch succeeds: returns 200 with run_id, status ok, step count."""
    monkeypatch.setattr(_app_module, "_launch_hosted_run", _make_success_launcher(steps=3))

    resp = client.post(
        "/agents/run",
        json={
            "provider": "groq",
            "model": "llama3-8b-8192",
            "api_key": "test-key",
            "task": "test task",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    run_id = body["run_id"]
    assert run_id.startswith("agent-")
    assert body["steps"] == 3

    # The run must be retrievable via the standard /runs/{run_id} endpoint.
    detail_resp = client.get(f"/runs/{run_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["run_id"] == run_id


def test_agents_run_explicit_base_url(monkeypatch):
    """Explicit base_url overrides provider preset."""
    monkeypatch.setattr(_app_module, "_launch_hosted_run", _make_success_launcher(steps=1))

    resp = client.post(
        "/agents/run",
        json={
            "base_url": "https://custom.example.com/v1",
            "model": "some-model",
            "api_key": "key",
            "task": "do something",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /agents/run -- validation: neither provider nor base_url
# ---------------------------------------------------------------------------


def test_agents_run_no_provider_no_base_url_returns_422():
    """Omitting both provider and base_url must return 422."""
    resp = client.post(
        "/agents/run",
        json={
            "model": "llama3-8b-8192",
            "api_key": "key",
            "task": "task",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /agents/run -- failure path (launcher returns non-zero)
# ---------------------------------------------------------------------------


def test_agents_run_launcher_failure_returns_5xx(monkeypatch):
    """When the launcher reports failure the endpoint returns 5xx."""
    monkeypatch.setattr(_app_module, "_launch_hosted_run", _make_failure_launcher(returncode=1))

    resp = client.post(
        "/agents/run",
        json={
            "provider": "groq",
            "model": "llama3-8b-8192",
            "api_key": "super-secret-key",
            "task": "task",
        },
    )
    assert resp.status_code in (502, 504)
    body_text = resp.text
    # The api_key must NOT appear anywhere in the response body.
    assert "super-secret-key" not in body_text


def test_agents_run_failure_scrubs_api_key_from_detail(monkeypatch):
    """Stderr containing the api_key must be scrubbed before it appears in the detail."""
    secret_key = "nvapi-super-secret-key-12345"
    base_url = "https://integrate.api.nvidia.com/v1"

    def _bad_launcher(run_id, base_url, model, api_key, task):
        # Simulate stderr that accidentally contains the key and base_url.
        stderr = (
            f"httpx.HTTPStatusError: 401 Unauthorized - key={api_key} "
            f"url={base_url}/chat/completions"
        )
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=stderr
        )

    monkeypatch.setattr(_app_module, "_launch_hosted_run", _bad_launcher)

    resp = client.post(
        "/agents/run",
        json={
            "base_url": base_url,
            "model": "nvidia/nemotron-4-340b-reward",
            "api_key": secret_key,
            "task": "summarise",
        },
    )
    assert resp.status_code == 502
    body_text = resp.text
    assert secret_key not in body_text, "api_key must not appear in response"
    assert base_url not in body_text, "base_url should be scrubbed from response"
    # A reason must still be present so the user understands what happened.
    assert "401" in body_text or "Unauthorized" in body_text


def test_agents_run_timeout_returns_504_with_guidance(monkeypatch):
    """On TimeoutExpired the endpoint must return 504 with a guidance message."""
    def _timeout_launcher(run_id, base_url, model, api_key, task):
        raise subprocess.TimeoutExpired(cmd=[], timeout=300)

    monkeypatch.setattr(_app_module, "_launch_hosted_run", _timeout_launcher)

    resp = client.post(
        "/agents/run",
        json={
            "provider": "nvidia_nim",
            "model": "nvidia/nemotron-4-340b-reward",
            "api_key": "some-key",
            "task": "slow task",
        },
    )
    assert resp.status_code == 504
    detail = resp.json().get("detail", "")
    assert "CASSETTE_AGENT_RUN_TIMEOUT" in detail, (
        f"Expected guidance in 504 detail, got: {detail!r}"
    )


# ---------------------------------------------------------------------------
# GET /agents/connect-info
# ---------------------------------------------------------------------------


def test_agents_connect_info_returns_200_with_required_keys():
    """GET /agents/connect-info returns 200 with http, mcp, sdk keys."""
    resp = client.get("/agents/connect-info")
    assert resp.status_code == 200
    body = resp.json()
    assert "http" in body
    assert "mcp" in body
    assert "sdk" in body
    # http must have env_vars and command sub-fields
    assert "env_vars" in body["http"]
    assert "command" in body["http"]
