# cassette/trust.py
"""Reversible certifi-append trust for agents Cassette cannot launch."""
from __future__ import annotations

import subprocess
from pathlib import Path

from cassette import paths


def certifi_path(python_exe: str) -> str:
    out = subprocess.run(
        [python_exe, "-c", "import certifi; print(certifi.where())"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def trust(python_exe: str) -> str:
    bundle = Path(certifi_path(python_exe))
    ca_text = paths.ca_path().read_text(encoding="utf-8")
    backup = bundle.with_suffix(bundle.suffix + ".cassette-bak")
    if not backup.exists():
        backup.write_bytes(bundle.read_bytes())
    current = bundle.read_text(encoding="utf-8")
    if ca_text.strip() not in current:
        sep = "" if current.endswith("\n") else "\n"
        bundle.write_text(current + sep + ca_text, encoding="utf-8")
    return str(bundle)


def untrust(python_exe: str) -> bool:
    bundle = Path(certifi_path(python_exe))
    backup = bundle.with_suffix(bundle.suffix + ".cassette-bak")
    if backup.exists():
        bundle.write_bytes(backup.read_bytes())
        backup.unlink()
        return True
    return False
