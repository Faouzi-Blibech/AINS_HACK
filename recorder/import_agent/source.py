"""Resolve an import source (git URL or local path) into a workspace dir."""
from __future__ import annotations

import re
import shutil
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
            raise FileNotFoundError(
                f"local source not found: {source}. Under docker compose the API "
                "runs in a container and cannot see host paths (e.g. a Windows "
                "path). Use a path inside the container such as /app/agent or "
                "examples/http_agent, or pass a git URL."
            )
        return SourceMeta(path=str(p.resolve()), commit=None, is_local=True, subdir=subdir)

    dest = Path(dest_root) / f"import-{uuid.uuid4().hex[:8]}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    base = ["git", "clone", "--depth", "1"]

    if ref:
        # Try the requested branch/ref first; if it does not exist (a common
        # mistake is typing "main" for a repo whose default branch is "master"),
        # fall back to the repo's default branch instead of failing.
        try:
            runner(base + ["--branch", ref, source, str(dest)], check=True)
        except subprocess.CalledProcessError:
            shutil.rmtree(dest, ignore_errors=True)
            runner(base + [source, str(dest)], check=True)
    else:
        runner(base + [source, str(dest)], check=True)

    rev = runner(["git", "rev-parse", "HEAD"], cwd=str(dest),
                 capture_output=True, text=True, check=True)
    commit = (rev.stdout or "").strip() or None
    return SourceMeta(path=str(dest), commit=commit, is_local=False, subdir=subdir)
