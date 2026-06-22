import os
from cassette import shim_env


def test_shim_dir_contains_sitecustomize():
    assert (shim_env.shim_dir() / "sitecustomize.py").is_file()
    assert not (shim_env.shim_dir() / "__init__.py").exists()


def test_with_shim_prepends_pythonpath():
    out = shim_env.with_shim({"PYTHONPATH": "/existing"})
    parts = out["PYTHONPATH"].split(os.pathsep)
    assert parts[0] == str(shim_env.shim_dir())
    assert "/existing" in parts


def test_with_shim_no_existing_pythonpath():
    out = shim_env.with_shim({})
    assert out["PYTHONPATH"] == str(shim_env.shim_dir())
