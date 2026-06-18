"""Tests for trace_store/blob_store.py."""
from __future__ import annotations

import os

from trace_store.blob_store import fetch_blob, store_blob


def test_blob_round_trip(monkeypatch, tmp_path):
    # Point the blob store to a temporary directory
    monkeypatch.setenv("CASSETTE_BLOB_DIR", str(tmp_path))
    
    content = '{"prompt": "hello world", "context": "large payload here"}'
    
    # Store it
    ref = store_blob(content)
    assert ref.startswith("sha256:")
    
    # Fetch it back
    fetched = fetch_blob(ref)
    assert fetched == content

def test_blob_deduplication(monkeypatch, tmp_path):
    monkeypatch.setenv("CASSETTE_BLOB_DIR", str(tmp_path))
    
    content = "identical payload"
    
    # Store twice
    ref1 = store_blob(content)
    ref2 = store_blob(content)
    
    # Should get exactly the same hash
    assert ref1 == ref2
    
    # Should only create one file
    assert len(os.listdir(str(tmp_path))) == 1
