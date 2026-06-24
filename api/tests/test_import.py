"""POST /agents/import. _launch_import_run is monkeypatched so no real docker,
git, or network is used (mirrors test_agents.py)."""
import subprocess, time
from fastapi.testclient import TestClient
import api.app as _app_module
from api.app import app, store

client = TestClient(app)


def _seed(run_id, steps=2):
    store.start_run(run_id, agent="imported", mode="record")
    for i in range(1, steps + 1):
        store.append_step(run_id, {"step_id": i, "type": "tool_call",
                                   "timestamp_ms": int(time.time() * 1000),
                                   "status": "ok", "side_effecting": False})
    store.finish_run(run_id, status="ok")


def test_import_success(monkeypatch):
    def fake(run_id, source, ref, subdir, command, env, task=None):
        _seed(run_id, steps=3)
        return subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
    monkeypatch.setattr(_app_module, "_launch_import_run", fake)
    resp = client.post("/agents/import", json={"source": "https://github.com/x/y.git"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok" and body["steps"] == 3
    assert client.get(f"/runs/{body['run_id']}").status_code == 200


def test_import_requires_source():
    resp = client.post("/agents/import", json={})
    assert resp.status_code == 422


def test_import_runner_failure_scrubs_and_502(monkeypatch):
    def fake(run_id, source, ref, subdir, command, env, task=None):
        return subprocess.CompletedProcess([], 1, stdout="", stderr="boom sk-secret")
    monkeypatch.setattr(_app_module, "_launch_import_run", fake)
    resp = client.post("/agents/import",
                       json={"source": "/tmp/x", "env": {"OPENAI_API_KEY": "sk-secret"}})
    assert resp.status_code == 502
    assert "sk-secret" not in resp.text
