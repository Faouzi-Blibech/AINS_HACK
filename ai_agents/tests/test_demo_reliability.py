"""Tests for ai_agents.demo_reliability (offline; no network, no API key required).

All tests monkeypatch ``ai_agents.llm.llm_complete`` so the live LLM is never
called. The harness checks are exercised with canned good outputs, a deliberate
miss, a LLMNotConfigured scenario, and an HTTP 429 rate-limit scenario.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

import ai_agents.llm
from ai_agents.llm import LLMNotConfigured
from ai_agents.demo_reliability import (
    load_demo_trace,
    check_debug_agent,
    check_blame_verdict,
    check_counterfactual,
    check_matcher,
    run_reliability,
)
from ai_agents.trace_content import make_resolver
import pathlib

BLOB_DIR = str(
    pathlib.Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "blobs"
)


# ---------------------------------------------------------------------------
# Canned LLM responses that satisfy the correctness criteria
# ---------------------------------------------------------------------------

def _good_debug_response() -> str:
    """LLM response for debug_agent: step_id=2, value contains 'high'."""
    return json.dumps({
        "step_id": 2,
        "target": "result",
        "value": '{"priority": "high"}',
        "rationale": "Step 2 returned medium priority; should be high.",
        "confidence": 0.90,
    })


def _good_verdict_response() -> str:
    """LLM response for verdict_via_llm: mentions step 2."""
    return json.dumps({
        "verdict": "Step 4 is where it failed. Step 2 is why.",
        "rationale": "Step 2 returned ambiguous priority which caused step 4 to fail.",
        "confidence": 0.88,
    })


def _good_variants_response() -> str:
    """LLM response for counterfactual.repair: 4 variants."""
    return json.dumps({
        "variants": [
            "Return HIGH when priority is ambiguous.",
            "Return the most restrictive priority when uncertain.",
            "Validate priority field before returning.",
            "Ensure priority is never medium when ticket urgency is high.",
        ]
    })


def _good_match_response(equivalent: bool) -> str:
    """LLM response for semantic_matcher.match."""
    return json.dumps({
        "equivalent": equivalent,
        "score": 0.95 if equivalent else 0.05,
        "rationale": "The outputs express the same routing intent." if equivalent else "Different teams.",
        "confidence": 0.90,
    })


# ---------------------------------------------------------------------------
# Helper: build a fake llm_complete that routes responses by call count
# ---------------------------------------------------------------------------

class _SequencedLLM:
    """Returns responses in order from a sequence; repeats last if exhausted."""

    def __init__(self, responses: list[str]):
        self._responses = responses
        self._idx = 0

    def __call__(self, **kwargs) -> str:
        resp = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return resp


# ---------------------------------------------------------------------------
# Helper: build a fake httpx response for rate-limit errors
# ---------------------------------------------------------------------------

def _make_429_error() -> httpx.HTTPStatusError:
    """Return an httpx.HTTPStatusError with status_code 429."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 429
    return httpx.HTTPStatusError(
        message="Too Many Requests",
        request=MagicMock(spec=httpx.Request),
        response=response,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def trace():
    return load_demo_trace()


@pytest.fixture()
def resolver():
    return make_resolver(BLOB_DIR)


# ---------------------------------------------------------------------------
# 1. load_demo_trace
# ---------------------------------------------------------------------------

class TestLoadDemoTrace:
    def test_returns_dict_with_run_id(self):
        t = load_demo_trace()
        assert isinstance(t, dict)
        assert t.get("run_id") == "run-fixture-001"

    def test_has_four_steps(self):
        t = load_demo_trace()
        assert len(t.get("steps", [])) == 4


# ---------------------------------------------------------------------------
# 2. check_debug_agent - all correct
# ---------------------------------------------------------------------------

class TestCheckDebugAgentAllCorrect:
    def test_rate_is_1_when_all_runs_good(self, monkeypatch, trace):
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: _good_debug_response())
        result = check_debug_agent(trace, runs=3)
        assert result["check"] == "debug_agent"
        assert result["correct"] == 3
        assert result["total"] == 3
        assert result["rate"] == pytest.approx(1.0)

    def test_returns_expected_keys(self, monkeypatch, trace):
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: _good_debug_response())
        result = check_debug_agent(trace, runs=2)
        assert set(result.keys()) >= {"check", "correct", "total", "errored", "rate", "notes"}

    def test_errored_is_zero_on_clean_run(self, monkeypatch, trace):
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: _good_debug_response())
        result = check_debug_agent(trace, runs=2)
        assert result["errored"] == 0


# ---------------------------------------------------------------------------
# 3. check_debug_agent - one bad run among N (proves harness measures)
# ---------------------------------------------------------------------------

class TestCheckDebugAgentMiss:
    def test_rate_reflects_miss(self, monkeypatch, trace):
        """2 correct + 1 wrong step_id => rate 2/3, not 1.0."""
        wrong_response = json.dumps({
            "step_id": 1,          # wrong step
            "target": "prompt",    # valid for llm_call
            "value": "high priority",
            "rationale": "wrong step",
            "confidence": 0.5,
        })
        responses = [
            _good_debug_response(),
            _good_debug_response(),
            wrong_response,
        ]
        seq = _SequencedLLM(responses)
        monkeypatch.setattr("ai_agents.llm.llm_complete", seq)

        result = check_debug_agent(trace, runs=3)
        assert result["correct"] == 2
        assert result["total"] == 3
        assert result["errored"] == 0
        assert result["rate"] == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# 4. check_blame_verdict - all correct
# ---------------------------------------------------------------------------

class TestCheckBlameVerdictAllCorrect:
    def test_rate_is_1_when_all_runs_good(self, monkeypatch, trace, resolver):
        # verdict_via_llm calls llm_complete once per run
        monkeypatch.setattr("ai_agents.llm.llm_complete", lambda **kw: _good_verdict_response())
        result = check_blame_verdict(trace, resolver, runs=3)
        assert result["check"] == "blame_verdict"
        assert result["correct"] == 3
        assert result["total"] == 3
        assert result["rate"] == pytest.approx(1.0)
        assert result["errored"] == 0


# ---------------------------------------------------------------------------
# 5. check_counterfactual - all correct
# ---------------------------------------------------------------------------

class TestCheckCounterfactualAllCorrect:
    def test_rate_is_1_when_all_runs_good(self, monkeypatch, trace):
        # counterfactual.repair calls llm_complete for variant generation
        # and potentially semantic_matcher.match (via llm_failure_resolved)
        # We provide a sequence: variants first, then match responses if needed.
        def fake_llm(**kwargs):
            user = kwargs.get("user", "")
            # If it's asking about equivalence (matcher), return not-equivalent
            # (because the perturbed engine resolves the failure, and the matcher
            # checks whether outputs are NOT equivalent to confirm resolution).
            if "equivalent" in kwargs.get("system", "").lower() or "routed" in user.lower() or "backend" in user.lower():
                return _good_match_response(False)
            return _good_variants_response()

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm)
        result = check_counterfactual(trace, runs=3)
        assert result["check"] == "counterfactual"
        assert result["correct"] == 3
        assert result["total"] == 3
        assert result["rate"] == pytest.approx(1.0)
        assert result["errored"] == 0


# ---------------------------------------------------------------------------
# 6. check_matcher - all correct
# ---------------------------------------------------------------------------

class TestCheckMatcherAllCorrect:
    def test_rate_is_1_when_all_runs_good(self, monkeypatch):
        """Two sub-calls per run: first equivalent=True, second equivalent=False."""
        call_count = [0]

        def fake_llm(**kwargs):
            call_count[0] += 1
            # Alternate: odd calls -> equivalent, even calls -> not equivalent
            return _good_match_response(call_count[0] % 2 == 1)

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm)
        result = check_matcher(runs=3)
        assert result["check"] == "semantic_matcher"
        assert result["correct"] == 3
        assert result["total"] == 3
        assert result["rate"] == pytest.approx(1.0)
        assert result["errored"] == 0


# ---------------------------------------------------------------------------
# 7. LLMNotConfigured - all checks skipped
# ---------------------------------------------------------------------------

class TestLLMNotConfiguredSkipsAll:
    def test_run_reliability_does_not_raise_when_no_key(self, monkeypatch):
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: (_ for _ in ()).throw(LLMNotConfigured("no key")),
        )
        results = run_reliability(runs=2)
        assert isinstance(results, list)
        assert len(results) == 4
        for r in results:
            assert r["rate"] is None
            assert r["total"] == 0
            assert "skip" in r["notes"].lower()

    def test_skipped_records_have_correct_zero_counts(self, monkeypatch):
        monkeypatch.setattr(
            "ai_agents.llm.llm_complete",
            lambda **kw: (_ for _ in ()).throw(LLMNotConfigured("no key")),
        )
        results = run_reliability(runs=3)
        for r in results:
            assert r["correct"] == 0
            assert r["total"] == 0
            assert r["errored"] == 0


# ---------------------------------------------------------------------------
# 8. run_reliability - all checks at rate 1.0 with good mocks
# ---------------------------------------------------------------------------

class TestRunReliabilityAllGood:
    def test_all_rates_are_1_with_good_mocks(self, monkeypatch):
        call_count = [0]

        def fake_llm(**kw):
            call_count[0] += 1
            system = kw.get("system", "")
            user = kw.get("user", "")
            # Debug agent response
            if "injection" in system.lower() or "step_id" in system.lower() or "debug" in system.lower():
                return _good_debug_response()
            # Verdict response
            if "verdict" in system.lower() or "blame" in system.lower():
                return _good_verdict_response()
            # Counterfactual variants
            if "variant" in system.lower() or "counterfactual" in system.lower() or "repair" in system.lower():
                return _good_variants_response()
            # Matcher / equivalence
            if "equivalent" in system.lower() or "equivalence" in system.lower():
                # First call within each run: should be True (backend pair)
                # Second call: should be False (data team pair)
                # We return True first by default; caller logic handles alternation
                return _good_match_response(call_count[0] % 2 == 1)
            return _good_debug_response()

        monkeypatch.setattr("ai_agents.llm.llm_complete", fake_llm)
        results = run_reliability(runs=2)
        assert isinstance(results, list)
        assert len(results) == 4
        for r in results:
            assert r["rate"] is not None, f"Check {r['check']} was unexpectedly skipped"
            assert r["total"] > 0
            assert "errored" in r


# ---------------------------------------------------------------------------
# 9. Per-call error (not LLMNotConfigured) counts as incorrect, no crash
# ---------------------------------------------------------------------------

class TestPerCallErrorCountsAsIncorrect:
    def test_value_error_counts_as_incorrect_not_a_crash(self, monkeypatch, trace):
        responses = [
            _good_debug_response(),
            "this is not valid json at all!!!",  # will cause ValueError -> incorrect
            _good_debug_response(),
        ]
        seq = _SequencedLLM(responses)
        monkeypatch.setattr("ai_agents.llm.llm_complete", seq)

        # Should not raise; the bad run counts as incorrect
        result = check_debug_agent(trace, runs=3)
        assert result["total"] == 3
        assert result["correct"] < 3   # at least one incorrect due to error
        assert result["errored"] == 0  # ValueError is not a transient HTTP error


# ---------------------------------------------------------------------------
# 10. HTTP 429 rate-limit errors are counted as errored, not incorrect
# ---------------------------------------------------------------------------

class TestHTTP429CountsAsErrored:
    def test_all_429_runs_excluded_from_rate(self, monkeypatch, trace):
        """When ALL calls raise 429 after retries, errored==total, rate is None."""
        # Patch time.sleep so the retry backoff does not actually wait.
        monkeypatch.setattr("ai_agents.demo_reliability.time.sleep", lambda s: None)

        def always_429(**kwargs):
            raise _make_429_error()

        monkeypatch.setattr("ai_agents.llm.llm_complete", always_429)

        result = check_debug_agent(trace, runs=3)

        assert result["total"] == 3
        assert result["correct"] == 0
        assert result["errored"] == 3
        # rate must be None (not 0.0) because all runs were excluded
        assert result["rate"] is None

    def test_429_note_appears_in_notes(self, monkeypatch, trace):
        """The notes field mentions the errored count when runs are excluded."""
        monkeypatch.setattr("ai_agents.demo_reliability.time.sleep", lambda s: None)

        def always_429(**kwargs):
            raise _make_429_error()

        monkeypatch.setattr("ai_agents.llm.llm_complete", always_429)

        result = check_debug_agent(trace, runs=2)
        assert "errored" in result["notes"] or "rate-limited" in result["notes"]

    def test_partial_429_excluded_from_denominator(self, monkeypatch, trace):
        """1 success + 1 exhausted-rate-limit run => rate 1/1 = 1.0, errored=1.

        The second run exhausts all retries (4 calls total: 1 initial + 3 retries)
        and still gets 429, so it counts as errored and is excluded from the rate.
        """
        monkeypatch.setattr("ai_agents.demo_reliability.time.sleep", lambda s: None)

        run_idx = [0]

        def mixed_llm(**kwargs):
            # run_idx tracks which "logical run" we're in by watching for
            # the good response on run 0. For run 1 we always return 429 so
            # all retries are exhausted.
            if run_idx[0] == 0:
                run_idx[0] += 1
                return _good_debug_response()
            raise _make_429_error()

        monkeypatch.setattr("ai_agents.llm.llm_complete", mixed_llm)

        result = check_debug_agent(trace, runs=2)
        assert result["total"] == 2
        assert result["errored"] == 1
        assert result["correct"] == 1
        assert result["rate"] == pytest.approx(1.0)

    def test_check_matcher_all_429_rate_is_none(self, monkeypatch):
        """Same semantics for check_matcher: all 429 => errored==total, rate None."""
        monkeypatch.setattr("ai_agents.demo_reliability.time.sleep", lambda s: None)

        def always_429(**kwargs):
            raise _make_429_error()

        monkeypatch.setattr("ai_agents.llm.llm_complete", always_429)

        result = check_matcher(runs=3)
        assert result["total"] == 3
        assert result["correct"] == 0
        assert result["errored"] == 3
        assert result["rate"] is None
