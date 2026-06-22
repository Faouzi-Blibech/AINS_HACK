"""Locate the trust shim directory and add it to a child's PYTHONPATH."""
from __future__ import annotations

import os
from pathlib import Path


def shim_dir() -> Path:
    return Path(__file__).resolve().parent / "trust_shim"


def with_shim(env: dict[str, str]) -> dict[str, str]:
    out = dict(env)
    existing = out.get("PYTHONPATH", "")
    parts = [str(shim_dir())]
    if existing:
        parts.append(existing)
    out["PYTHONPATH"] = os.pathsep.join(parts)
    return out
