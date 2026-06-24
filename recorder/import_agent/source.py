"""Resolve an import source (git URL or local path) into a workspace dir."""
from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

_URL_RE = re.compile(r"^(https?://|git@|ssh://|git://)")


def is_url(source: str) -> bool:
    return bool(_URL_RE.match(source.strip()))


@dataclass
class SourceMeta:
    path: str
    commit: str | None
    is_local: bool
    subdir: str | None


def resolve_source(source, *, ref=None, subdir=None, dest_root, runner=subprocess.run) -> SourceMeta:
    if not is_url(source):
        p = Path(source).expanduser()
        if not p.is_dir():
            raise FileNotFoundError(f"local source not found: {source}")
        return SourceMeta(path=str(p.resolve()), commit=None, is_local=True, subdir=subdir)

    dest = Path(dest_root) / f"import-{uuid.uuid4().hex[:8]}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    clone = ["git", "clone", "--depth", "1"]
    if ref:
        clone += ["--branch", ref]
    clone += [source, str(dest)]
    runner(clone, check=True)
    rev = runner(["git", "rev-parse", "HEAD"], cwd=str(dest),
                 capture_output=True, text=True, check=True)
    commit = (rev.stdout or "").strip() or None
    return SourceMeta(path=str(dest), commit=commit, is_local=False, subdir=subdir)
