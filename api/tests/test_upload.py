"""Unit tests for api.upload.materialize_upload (the upload trust boundary)."""
from pathlib import Path
import io
import zipfile

import pytest

from api.upload import materialize_upload, UploadError, MAX_FILES


def test_reconstructs_tree(tmp_path):
    items = [("main.py", b"print('hi')"), ("util/helper.py", b"x = 1\n")]
    ws = Path(materialize_upload(items, tmp_path))
    assert (ws / "main.py").read_bytes() == b"print('hi')"
    assert (ws / "util" / "helper.py").read_bytes() == b"x = 1\n"
    assert ws.parent == tmp_path


def test_rejects_traversal(tmp_path):
    for bad in ["../evil.py", "/etc/passwd", "a/../../b.py", "C:/x.py"]:
        with pytest.raises(UploadError):
            materialize_upload([(bad, b"x")], tmp_path)


def test_rejects_empty(tmp_path):
    with pytest.raises(UploadError):
        materialize_upload([], tmp_path)


def test_enforces_total_size_cap(tmp_path):
    big = b"a" * (51 * 1024 * 1024)
    with pytest.raises(UploadError):
        materialize_upload([("big.bin", big)], tmp_path)


def test_enforces_file_count_cap(tmp_path):
    items = [(f"f{i}.txt", b"x") for i in range(MAX_FILES + 1)]
    with pytest.raises(UploadError):
        materialize_upload(items, tmp_path)


def test_extracts_zip(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("main.py", "print('zip')")
        zf.writestr("pkg/mod.py", "y = 2\n")
    ws = Path(materialize_upload([("agent.zip", buf.getvalue())], tmp_path))
    assert (ws / "main.py").read_bytes() == b"print('zip')"
    assert (ws / "pkg" / "mod.py").read_bytes() == b"y = 2\n"


def test_zip_rejects_traversal(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.py", "bad")
    with pytest.raises(UploadError):
        materialize_upload([("agent.zip", buf.getvalue())], tmp_path)


def test_zip_enforces_real_size_cap(tmp_path):
    # A zip that is tiny on disk but decompresses past the cap must be rejected,
    # proving the cap counts real decompressed bytes, not the declared size.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.bin", b"\0" * (51 * 1024 * 1024))
    with pytest.raises(UploadError):
        materialize_upload([("bomb.zip", buf.getvalue())], tmp_path)


def test_zip_enforces_file_count_cap(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(MAX_FILES + 1):
            zf.writestr(f"f{i}.txt", "x")
    with pytest.raises(UploadError):
        materialize_upload([("many.zip", buf.getvalue())], tmp_path)


import subprocess
import time
from fastapi.testclient import TestClient
import api.app as _app_module
from api.app import app, store

_client = TestClient(app)


def _seed(run_id, steps=2):
    store.start_run(run_id, agent="imported", mode="record")
    for i in range(1, steps + 1):
        store.append_step(run_id, {"step_id": i, "type": "tool_call",
                                   "timestamp_ms": int(time.time() * 1000),
                                   "status": "ok", "side_effecting": False})
    store.finish_run(run_id, status="ok")


def test_upload_endpoint_materializes_and_launches(monkeypatch):
    captured = {}

    def fake(run_id, source, ref, subdir, command, env, task=None):
        captured.update(source=source, command=command, env=env, task=task)
        _seed(run_id, steps=2)
        return subprocess.CompletedProcess([], 0, stdout="ok", stderr="")

    monkeypatch.setattr(_app_module, "_launch_import_run", fake)
    resp = _client.post(
        "/agents/import/upload",
        files=[("files", ("main.py", b"print(1)")),
               ("files", ("util/h.py", b"x=1"))],
        data={"command": "python main.py", "task": "hi",
              "env": '{"OPENAI_API_KEY": "sk-x"}'},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["steps"] == 2
    ws = Path(captured["source"])
    assert (ws / "main.py").exists() and (ws / "util" / "h.py").exists()
    assert captured["command"] == "python main.py"
    assert captured["env"] == {"OPENAI_API_KEY": "sk-x"}
    assert captured["task"] == "hi"


def test_upload_endpoint_bad_env_json(monkeypatch):
    monkeypatch.setattr(_app_module, "_launch_import_run",
                        lambda *a, **k: subprocess.CompletedProcess([], 0, "ok", ""))
    resp = _client.post("/agents/import/upload",
                        files=[("files", ("main.py", b"x"))],
                        data={"env": "not-json"})
    assert resp.status_code == 422


def test_upload_endpoint_requires_files():
    resp = _client.post("/agents/import/upload", data={"command": "python main.py"})
    assert resp.status_code == 422
