# cassette/launchers.py
"""Per-agent PATH launcher shims for auto-recording future sessions."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from cassette import consent, paths


def _launcher_path(name: str) -> Path:
    suffix = ".cmd" if os.name == "nt" else ""
    return paths.bin_dir() / f"{name}{suffix}"


def install(name: str, cmd) -> Path:
    paths.bin_dir().mkdir(parents=True, exist_ok=True)
    target = _launcher_path(name)
    inner = " ".join(cmd)
    py = sys.executable
    if os.name == "nt":
        body = f'@echo off\r\n"{py}" -m cassette run -- {inner} %*\r\n'
    else:
        body = f'#!/bin/sh\nexec "{py}" -m cassette run -- {inner} "$@"\n'
    target.write_text(body, encoding="utf-8")
    if os.name != "nt":
        target.chmod(0o755)
    consent.set_enabled(cmd, True)
    return target


def remove(name: str, cmd) -> bool:
    target = _launcher_path(name)
    existed = target.exists()
    if existed:
        target.unlink()
    consent.set_enabled(cmd, False)
    return existed
