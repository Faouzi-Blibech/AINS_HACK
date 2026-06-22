"""Shared fixtures for the API tests.

Pins CASSETTE_BLOB_DIR to the bundled fixture blobs for every API test. Other
test modules in the repo set this env var to throwaway temp dirs at import
time, and the blob store reads it at call time, so without this an unlucky
collection order leaves the API blob-resolution tests reading from an empty
directory. Setting it here (and letting monkeypatch restore it afterwards)
makes the API tests order-independent.
"""
from __future__ import annotations

import pathlib

import pytest

_BLOBS_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "blobs"
)


@pytest.fixture(autouse=True)
def _pin_blob_dir(monkeypatch):
    monkeypatch.setenv("CASSETTE_BLOB_DIR", _BLOBS_DIR)
