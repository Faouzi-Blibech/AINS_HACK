"""Import-and-run an external agent in an isolated Docker container, with
recording wired in automatically. Public API re-exported here.
"""
from __future__ import annotations

from recorder.import_agent.source import SourceMeta, is_url, resolve_source
from recorder.import_agent.image import IMAGE_TAG, ensure_image, image_exists
from recorder.import_agent.container import build_run_argv, run_container
from recorder.import_agent.driver import record_imported

__all__ = [
    "SourceMeta", "is_url", "resolve_source",
    "IMAGE_TAG", "ensure_image", "image_exists",
    "build_run_argv", "run_container",
    "record_imported",
]
