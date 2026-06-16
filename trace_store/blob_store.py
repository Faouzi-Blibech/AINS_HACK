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

BLOB_DIR = os.environ.get("CASSETTE_BLOB_DIR", "./blobs")
os.makedirs(BLOB_DIR, exist_ok=True)


def store_blob(content: str) -> str:
    """Store content and return its sha256:... reference."""
    h = hashlib.sha256(content.encode()).hexdigest()
    path = os.path.join(BLOB_DIR, h)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    return f"sha256:{h}"


def fetch_blob(ref: str) -> str:
    """Resolve a sha256:... reference back to its raw content."""
    h = ref.replace("sha256:", "")
    with open(os.path.join(BLOB_DIR, h), encoding="utf-8") as f:
        return f.read()
