# cassette/tests/test_cli.py
from cassette import cli, consent


def test_env_powershell(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    rc = cli.main(["env", "--shell", "powershell", "--port", "8899"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '$env:HTTPS_PROXY' in out
    assert 'http://127.0.0.1:8899' in out
    assert '$env:NODE_EXTRA_CA_CERTS' in out


def test_env_bash(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    cli.main(["env", "--shell", "bash"])
    assert 'export HTTPS_PROXY=' in capsys.readouterr().out


def test_run_declined_does_not_record(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    monkeypatch.setattr(consent, "ensure_consent", lambda cmd, **k: False)
    recorded = {}
    monkeypatch.setattr(cli, "record_subprocess",
                        lambda *a, **k: recorded.setdefault("called", True))
    rc = cli.main(["run", "--", "echo", "hi"])
    assert rc == 0
    assert "called" not in recorded
    assert "not recording" in capsys.readouterr().out.lower()


def test_run_records_when_trusted(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    monkeypatch.setattr(consent, "ensure_consent", lambda cmd, **k: True)
    captured = {}

    def fake_record(cmd, *, run_id, port=8899, extra_env=None):
        captured["cmd"] = cmd
        captured["run_id"] = run_id
        return {"run_id": run_id, "steps": [{"type": "tool_call"}]}

    monkeypatch.setattr(cli, "record_subprocess", fake_record)
    rc = cli.main(["run", "--run-id", "r1", "--", "echo", "hi"])
    assert rc == 0
    assert captured["cmd"] == ["echo", "hi"]
    assert captured["run_id"] == "r1"
