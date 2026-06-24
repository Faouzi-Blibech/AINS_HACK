import subprocess, tempfile, os
from pathlib import Path
from recorder.import_agent import source as I


def test_is_url():
    assert I.is_url("https://github.com/x/y.git")
    assert I.is_url("git@github.com:x/y.git")
    assert not I.is_url("/home/me/agent")
    assert not I.is_url("C:/Users/me/agent")


def test_resolve_local_path_marks_local_and_keeps_path(tmp_path):
    repo = tmp_path / "agent"
    repo.mkdir()
    (repo / "main.py").write_text("print('hi')")
    meta = I.resolve_source(str(repo), dest_root=str(tmp_path / "imports"))
    assert meta.is_local is True
    assert Path(meta.path).resolve() == repo.resolve()
    assert meta.commit is None


def test_resolve_git_url_clones_and_pins_commit(tmp_path):
    calls = []
    def fake_runner(cmd, **kw):
        calls.append(cmd)
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    meta = I.resolve_source(
        "https://github.com/x/y.git", ref="main",
        dest_root=str(tmp_path / "imports"), runner=fake_runner,
    )
    assert meta.is_local is False
    assert meta.commit == "abc123"
    # clone happened with depth 1 and the ref/branch
    clone = next(c for c in calls if c[:2] == ["git", "clone"])
    assert "--depth" in clone and "1" in clone
    assert "--branch" in clone and "main" in clone
