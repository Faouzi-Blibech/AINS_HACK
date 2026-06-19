"""Blob resolution helpers for trace steps.

Resolves content-addressed blob references (sha256:<hash>) to inline content
so that rationale strings can cite what a step actually produced.

The blob layout mirrors trace_store/blob_store.py: one file per hash under a
blob directory, filename is the bare hex hash (no "sha256:" prefix), content
is the raw UTF-8 text stored at record time.

Usage:
    resolver = make_resolver(blob_dir)
    graph = analyze(trace, replay=replay, content_resolver=resolver)
"""
from __future__ import annotations

import json
import os
from typing import Callable


def resolve_blob(ref: str | None, *, blob_dir: str) -> str | None:
    """Resolve a sha256:<hash> reference to its file content.

    Parameters
    ----------
    ref
        A blob reference in "sha256:<hex>" form, or None / empty string.
    blob_dir
        Directory where blobs are stored (filename == bare hex hash).

    Returns
    -------
    str or None
        The file text when the blob exists; None when ref is falsy or the
        file is absent. Never raises.
    """
    if not ref:
        return None
    # Strip the "sha256:" prefix used by the content-addressing layer.
    h = ref.replace("sha256:", "", 1)
    path = os.path.join(blob_dir, h)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def resolve_step_content(step: dict, *, blob_dir: str) -> dict:
    """Resolve a step's blob fields to inline content.

    For llm_call steps, resolves prompt_blob -> "prompt" and
    response_blob -> "response".  For tool_call steps, resolves
    args_blob -> "args" and result_blob -> "result".

    Each resolved value is parsed as JSON when the text is valid JSON;
    otherwise the raw string is kept. Keys whose blob is absent or
    unresolvable are omitted from the returned dict.

    Parameters
    ----------
    step
        A trace step dict (docs/trace_schema.json shape).
    blob_dir
        Directory where blobs are stored.

    Returns
    -------
    dict
        A dict with the resolved inline content; may be empty.
    """
    step_type = step.get("type")
    out: dict = {}

    if step_type == "llm_call":
        pairs = [
            ("prompt_blob", "prompt"),
            ("response_blob", "response"),
        ]
    else:
        # tool_call and any future types default to args/result
        pairs = [
            ("args_blob", "args"),
            ("result_blob", "result"),
        ]

    for blob_key, content_key in pairs:
        ref = step.get(blob_key)
        raw = resolve_blob(ref, blob_dir=blob_dir)
        if raw is None:
            continue
        try:
            out[content_key] = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            out[content_key] = raw

    return out


def describe_step(step: dict, *, blob_dir: str | None = None) -> str:
    """Return a compact one-line description of a trace step.

    Always includes the step_id, type, and label (tool name or model).
    When blob_dir is provided and content resolves, appends the key
    content compactly.

    Example with content:
        "step 2 (tool_call get_priority): result={'priority': 'medium', 'raw': 'P2 / medium?'}"

    Example without blob_dir (structural fallback):
        "step 2 (tool_call get_priority)"

    Parameters
    ----------
    step
        A trace step dict.
    blob_dir
        Directory where blobs are stored; pass None for the structural
        fallback (no blob resolution).

    Returns
    -------
    str
        A non-empty one-line description.
    """
    step_id = step.get("step_id", "?")
    step_type = step.get("type", "unknown")

    if step_type == "llm_call":
        label = step.get("model", "unknown-model")
    else:
        label = step.get("tool", step.get("model", "unknown"))

    base = f"step {step_id} ({step_type} {label})"

    if blob_dir is None:
        return base

    content = resolve_step_content(step, blob_dir=blob_dir)
    if not content:
        return base

    # Build a compact key=value suffix for each resolved field.
    parts = []
    for key, value in content.items():
        parts.append(f"{key}={value!r}")

    return f"{base}: {', '.join(parts)}"


def make_resolver(blob_dir: str) -> Callable[[dict], str]:
    """Return a step -> describe_step(step, blob_dir=blob_dir) callable.

    The returned function is suitable to pass as
    ``analyze(..., content_resolver=...)``.

    Parameters
    ----------
    blob_dir
        Directory where blobs are stored.
    """
    def _resolver(step: dict) -> str:
        return describe_step(step, blob_dir=blob_dir)

    return _resolver
