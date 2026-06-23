# cassette/tests/test_launchers.py
import os
from cassette import launchers, consent, paths


def test_install_creates_launcher_and_marks_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    path = launchers.install("myagent", ["python", "my_agent.py"])
    assert path.exists()
    assert path.parent == paths.bin_dir()
    assert consent.is_enabled(["python", "my_agent.py"]) is True


def test_remove_deletes_and_unmarks(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    launchers.install("myagent", ["python", "my_agent.py"])
    assert launchers.remove("myagent", ["python", "my_agent.py"]) is True
    suffix = ".cmd" if os.name == "nt" else ""
    assert not (paths.bin_dir() / f"myagent{suffix}").exists()
    assert consent.is_enabled(["python", "my_agent.py"]) is False
