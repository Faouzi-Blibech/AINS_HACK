"""Single source of truth for the local Cassette store layout (~/.cassette)."""
from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    env = os.environ.get("CASSETTE_HOME")
    return Path(env) if env else Path.home() / ".cassette"


def db_path() -> Path:
    return home() / "cassette.sqlite3"


def blob_dir() -> Path:
    return home() / "blobs"


def ca_path() -> Path:
    return home() / "ca.pem"


def resolves_path() -> Path:
    return home() / "resolves.json"


def agents_path() -> Path:
    return home() / "agents.json"


def bin_dir() -> Path:
    return home() / "bin"


def ensure_home() -> Path:
    root = home()
    root.mkdir(parents=True, exist_ok=True)
    blob_dir().mkdir(parents=True, exist_ok=True)
    return root
