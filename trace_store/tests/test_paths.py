from pathlib import Path
from trace_store import paths


def test_home_honors_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path / "store"))
    assert paths.home() == tmp_path / "store"


def test_home_defaults_under_user_home(monkeypatch):
    monkeypatch.delenv("CASSETTE_HOME", raising=False)
    assert paths.home() == Path.home() / ".cassette"


def test_derived_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    assert paths.db_path() == tmp_path / "cassette.sqlite3"
    assert paths.blob_dir() == tmp_path / "blobs"
    assert paths.ca_path() == tmp_path / "ca.pem"
    assert paths.resolves_path() == tmp_path / "resolves.json"
    assert paths.agents_path() == tmp_path / "agents.json"
    assert paths.bin_dir() == tmp_path / "bin"


def test_ensure_home_creates_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path / "store"))
    paths.ensure_home()
    assert (tmp_path / "store").is_dir()
    assert (tmp_path / "store" / "blobs").is_dir()
