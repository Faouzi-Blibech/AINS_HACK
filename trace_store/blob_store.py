"""Content-addressed blob store.

Key = sha256 of the content, value = the raw content (prompt text, tool
response JSON, etc.). Deduplicates: identical content is stored exactly once,
so storage stays linear in the number of distinct payloads.

This is the minimal file-based implementation; upgrade to S3 / object storage
later without changing the interface.
"""
from __future__ import annotations

import hashlib
import os
import re

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _get_blob_dir() -> str:
    d = os.environ.get("CASSETTE_BLOB_DIR", "./blobs")
    os.makedirs(d, exist_ok=True)
    return d


def store_blob(content: str) -> str:
    """Store content and return its sha256:... reference."""
    h = hashlib.sha256(content.encode()).hexdigest()
    path = os.path.join(_get_blob_dir(), h)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    return f"sha256:{h}"


def fetch_blob(ref: str) -> str:
    """Resolve a sha256:... reference back to its raw content."""
    h = ref.replace("sha256:", "")
    if not _HEX64.match(h):
        raise ValueError(f"invalid blob digest: {h!r}")
    with open(os.path.join(_get_blob_dir(), h), encoding="utf-8") as f:
        content = f.read()
    if hashlib.sha256(content.encode()).hexdigest() != h:
        raise ValueError(f"blob integrity check failed: {ref}")
    return content
