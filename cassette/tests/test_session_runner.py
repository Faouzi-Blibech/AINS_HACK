import sys
from cassette import session_runner, paths
from trace_store.store import TraceStore


def test_records_subprocess_http_into_persistent_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    from recorder.mock_upstream import serve
    server, base = serve(0)
    agent = tmp_path / "tiny_agent.py"
    agent.write_text(
        "import os, urllib.request\n"
        "url = os.environ['TINY_URL'] + '/get_priority'\n"
        "req = urllib.request.Request(url, data=b'{\"raw_priority\":\"p1\"}',\n"
        "    headers={'Content-Type':'application/json'})\n"
        "urllib.request.urlopen(req).read()\n"
    )
    try:
        doc = session_runner.record_subprocess(
            [sys.executable, str(agent)],
            run_id="test-run-1",
            port=8951,
            extra_env={"TINY_URL": base},
        )
    finally:
        server.shutdown()
    assert doc["run_id"] == "test-run-1"
    assert len(doc["steps"]) >= 1
    store = TraceStore(str(paths.db_path()))
    assert "test-run-1" in {r["run_id"] for r in store.list_runs()}
    store.close()


def test_safe_runs_unproxied_when_recorder_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    import cassette.session_runner as sr
    monkeypatch.setattr(sr, "Recorder",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    rc = session_runner.record_subprocess_safe(
        [sys.executable, "-c", "import sys; sys.exit(0)"], run_id="r", port=8952)
    assert rc == 0
    assert "un-proxied" in capsys.readouterr().err.lower()
