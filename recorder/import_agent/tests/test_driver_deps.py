import subprocess
from pathlib import Path
from recorder.import_agent import driver

def test_install_deps_uses_requirements_when_present(tmp_path):
    (tmp_path / "requirements.txt").write_text("httpx\n")
    calls = []
    driver._install_deps(str(tmp_path), runner=lambda c, **k: calls.append(c) or subprocess.CompletedProcess(c, 0))
    assert any("install" in c and "-r" in c for c in calls)

def test_install_deps_uses_pyproject_when_no_requirements(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    calls = []
    driver._install_deps(str(tmp_path), runner=lambda c, **k: calls.append(c) or subprocess.CompletedProcess(c, 0))
    assert any("install" in c and str(tmp_path) in c for c in calls)

def test_install_deps_noop_when_nothing_declared(tmp_path):
    calls = []
    driver._install_deps(str(tmp_path), runner=lambda c, **k: calls.append(c) or subprocess.CompletedProcess(c, 0))
    assert calls == []
