"""Materialize an uploaded agent (file tree or single zip) into a workspace dir.

This is the server-side trust boundary for browser uploads: client-supplied
relative paths are never trusted. Used by POST /agents/import/upload.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from uuid import uuid4

MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_FILES = 5000


class UploadError(Exception):
    """Raised on an invalid upload (bad path, empty, or over a cap)."""


def _safe_target(workspace: Path, rel: str) -> Path:
    """Resolve rel under workspace, rejecting absolute / drive / traversal paths."""
    rel = (rel or "").replace("\\", "/").strip()
    if not rel or rel.startswith("/"):
        raise UploadError("invalid path in upload")
    parts: list[str] = []
    for seg in rel.split("/"):
        if seg in ("", "."):
            continue
        if seg == ".." or ":" in seg:
            raise UploadError("invalid path in upload")
        parts.append(seg)
    if not parts:
        raise UploadError("invalid path in upload")
    target = (workspace / Path(*parts)).resolve()
    if not target.is_relative_to(workspace.resolve()):
        raise UploadError("invalid path in upload")
    return target


def _write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _extract_zip(data: bytes, workspace: Path) -> str:
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_FILES:
            raise UploadError(f"too many files (> {MAX_FILES})")
        for info in infos:
            target = _safe_target(workspace, info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_TOTAL_BYTES:
                        raise UploadError("upload exceeds 50 MB")
                    dst.write(chunk)
    return str(workspace)


def materialize_upload(items: list[tuple[str, bytes]], dest_root) -> str:
    """Write uploaded items into a new workspace dir under dest_root; return it."""
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    workspace = dest_root / f"upload-{uuid4().hex[:8]}"
    workspace.mkdir(parents=True)

    if not items:
        raise UploadError("no files uploaded")

    if len(items) == 1 and items[0][0].lower().endswith(".zip"):
        return _extract_zip(items[0][1], workspace)

    total = 0
    for idx, (name, data) in enumerate(items):
        if idx + 1 > MAX_FILES:
            raise UploadError(f"too many files (> {MAX_FILES})")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise UploadError("upload exceeds 50 MB")
        _write(_safe_target(workspace, name), data)
    return str(workspace)
