"""Tests for ai_agents/trace_content.py - blob resolution layer.

TDD: these tests are written before the implementation; run them first to see
them fail (RED), then implement to make them pass (GREEN).

Run from repo root:
    python -m pytest ai_agents/tests/test_trace_content.py -q
"""
from __future__ import annotations

import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "docs" / "fixtures" / "sample_trace.json"
BLOB_DIR = str(REPO_ROOT / "docs" / "fixtures" / "blobs")


@pytest.fixture()
def trace() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def step2(trace) -> dict:
    """Step 2 is the get_priority tool_call with known blob content."""
    return next(s for s in trace["steps"] if s["step_id"] == 2)


# ---------------------------------------------------------------------------
# resolve_blob
# ---------------------------------------------------------------------------


class TestResolveBlob:
    def test_resolves_known_hash(self, step2):
        from ai_agents.trace_content import resolve_blob

        ref = step2["result_blob"]  # sha256:3c34e3...
        result = resolve_blob(ref, blob_dir=BLOB_DIR)
        assert result is not None
        assert "medium" in result

    def test_returns_none_for_missing_hash(self):
        from ai_agents.trace_content import resolve_blob

        result = resolve_blob("sha256:deadbeef0000000000000000000000000000000000000000000000000000dead", blob_dir=BLOB_DIR)
        assert result is None

    def test_returns_none_for_none_ref(self):
        from ai_agents.trace_content import resolve_blob

        assert resolve_blob(None, blob_dir=BLOB_DIR) is None

    def test_returns_none_for_empty_string(self):
        from ai_agents.trace_content import resolve_blob

        assert resolve_blob("", blob_dir=BLOB_DIR) is None

    def test_does_not_raise_on_missing_blob(self):
        from ai_agents.trace_content import resolve_blob

        # Must not raise; must return None
        result = resolve_blob("sha256:0000000000000000000000000000000000000000000000000000000000000000", blob_dir=BLOB_DIR)
        assert result is None


# ---------------------------------------------------------------------------
# resolve_step_content
# ---------------------------------------------------------------------------


class TestResolveStepContent:
    def test_step2_result_is_parsed_json(self, step2):
        from ai_agents.trace_content import resolve_step_content

        content = resolve_step_content(step2, blob_dir=BLOB_DIR)
        assert content["result"] == {"priority": "medium", "raw": "P2 / medium?"}

    def test_step2_args_is_parsed_json(self, step2):
        from ai_agents.trace_content import resolve_step_content

        content = resolve_step_content(step2, blob_dir=BLOB_DIR)
        assert content["args"] == {"ticket_key": "OPS-4521"}

    def test_step2_has_both_args_and_result(self, step2):
        from ai_agents.trace_content import resolve_step_content

        content = resolve_step_content(step2, blob_dir=BLOB_DIR)
        assert set(content.keys()) == {"args", "result"}

    def test_llm_step_returns_prompt_and_response_keys(self, trace):
        from ai_agents.trace_content import resolve_step_content

        step1 = next(s for s in trace["steps"] if s["step_id"] == 1)
        content = resolve_step_content(step1, blob_dir=BLOB_DIR)
        # step 1 is an llm_call; should produce prompt and/or response keys
        assert "prompt" in content or "response" in content

    def test_omits_absent_blob_keys(self):
        from ai_agents.trace_content import resolve_step_content

        # A step with a nonexistent blob ref should omit that key
        step = {
            "step_id": 99,
            "type": "tool_call",
            "args_blob": "sha256:deadbeef0000000000000000000000000000000000000000000000000000dead",
            "result_blob": "sha256:3c34e3763cf9d4cddd9e759c33ff6de8fa9e6a27be4564f78a1565403fbe8ae8",
        }
        content = resolve_step_content(step, blob_dir=BLOB_DIR)
        assert "args" not in content  # missing blob -> omitted
        assert "result" in content    # present blob -> included

    def test_empty_step_returns_empty_dict(self):
        from ai_agents.trace_content import resolve_step_content

        step = {"step_id": 99, "type": "tool_call"}
        content = resolve_step_content(step, blob_dir=BLOB_DIR)
        assert content == {}


# ---------------------------------------------------------------------------
# describe_step
# ---------------------------------------------------------------------------


class TestDescribeStep:
    def test_step2_with_blob_dir_contains_medium(self, step2):
        from ai_agents.trace_content import describe_step

        line = describe_step(step2, blob_dir=BLOB_DIR)
        assert "medium" in line

    def test_step2_with_blob_dir_contains_raw_value(self, step2):
        from ai_agents.trace_content import describe_step

        line = describe_step(step2, blob_dir=BLOB_DIR)
        assert "P2 / medium?" in line

    def test_step2_contains_step_id(self, step2):
        from ai_agents.trace_content import describe_step

        line = describe_step(step2, blob_dir=BLOB_DIR)
        assert "2" in line

    def test_step2_contains_tool_name(self, step2):
        from ai_agents.trace_content import describe_step

        line = describe_step(step2, blob_dir=BLOB_DIR)
        assert "get_priority" in line

    def test_no_blob_dir_returns_structural_line(self, step2):
        from ai_agents.trace_content import describe_step

        line = describe_step(step2, blob_dir=None)
        assert isinstance(line, str) and len(line) > 0
        assert "2" in line
        assert "get_priority" in line

    def test_missing_blob_still_returns_nonempty_line(self):
        from ai_agents.trace_content import describe_step

        step = {
            "step_id": 77,
            "type": "tool_call",
            "tool": "unknown_tool",
            "args_blob": "sha256:deadbeef0000000000000000000000000000000000000000000000000000dead",
            "result_blob": "sha256:deadbeef0000000000000000000000000000000000000000000000000000beef",
        }
        line = describe_step(step, blob_dir=BLOB_DIR)
        assert isinstance(line, str) and len(line) > 0
        # Should contain step id and tool name even with no resolved blobs
        assert "77" in line
        assert "unknown_tool" in line


# ---------------------------------------------------------------------------
# make_resolver
# ---------------------------------------------------------------------------


class TestMakeResolver:
    def test_resolver_is_callable(self):
        from ai_agents.trace_content import make_resolver

        resolver = make_resolver(BLOB_DIR)
        assert callable(resolver)

    def test_resolver_produces_describe_step_output(self, step2):
        from ai_agents.trace_content import describe_step, make_resolver

        resolver = make_resolver(BLOB_DIR)
        assert resolver(step2) == describe_step(step2, blob_dir=BLOB_DIR)

    def test_resolver_output_contains_content(self, step2):
        from ai_agents.trace_content import make_resolver

        resolver = make_resolver(BLOB_DIR)
        result = resolver(step2)
        assert "medium" in result
        assert "P2 / medium?" in result
