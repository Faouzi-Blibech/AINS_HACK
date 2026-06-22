import json
from api import app


def test_sidecar_hint_in_cassette_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    (tmp_path / "resolves.json").write_text(json.dumps({"run-x": [3]}))
    assert app.resolves_at_for("run-x", {"steps": []}) == {3}


def test_trace_marker_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    doc = {"steps": [{"step_id": 1}, {"step_id": 2, "expected_root_cause": True}]}
    assert app.resolves_at_for("unknown", doc) == {2}


def test_fixture_still_resolves_run_fixture_001(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    assert app.resolves_at_for("run-fixture-001", {"steps": []}) == {2}


def test_unknown_run_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    assert app.resolves_at_for("nope", {"steps": []}) == set()
