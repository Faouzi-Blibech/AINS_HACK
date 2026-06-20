"""Tie the AI analysis layer together: obtain a trace, seed it into a store,
run the blame graph, and demonstrate the end-to-end debug agent.

Three public helpers
--------------------
seed_store_from_fixture(store, fixture_path) -> str
    Populate a TraceStore from the sample fixture JSON; return the run_id.

obtain_recorded_trace(*, prefer_record, fixture_path, blob_dir) -> (trace, blob_dir | None)
    Try the live recorder subprocess; fall back to the fixture on any failure.
    Never raises on the record path.

analyze_recorded(trace, *, blob_dir, resolves_at) -> BlameGraph
    Build the Temporal Blame Graph with ScriptedReplay and optional blob content.

__main__ section provides an offline-safe end-to-end demo.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Paths relative to this file (repo-root anchored)
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DEFAULT_FIXTURE = _REPO_ROOT / "docs" / "fixtures" / "sample_trace.json"
_DEFAULT_BLOB_DIR = _REPO_ROOT / "docs" / "fixtures" / "blobs"


# ---------------------------------------------------------------------------
# seed_store_from_fixture
# ---------------------------------------------------------------------------


def seed_store_from_fixture(store, fixture_path=None) -> str:
    """Read the fixture JSON and populate *store* with a single run.

    Parameters
    ----------
    store:
        A ``TraceStore`` instance (must be open and empty for this run_id).
    fixture_path:
        Path to the fixture JSON file; defaults to docs/fixtures/sample_trace.json.

    Returns
    -------
    str
        The ``run_id`` read from the fixture ("run-fixture-001").
    """
    if fixture_path is None:
        fixture_path = _DEFAULT_FIXTURE

    trace = json.loads(pathlib.Path(fixture_path).read_text(encoding="utf-8"))

    run_id = trace["run_id"]
    store.start_run(
        run_id,
        agent=trace.get("agent", ""),
        mode=trace.get("mode", "record"),
        created_at_ms=trace.get("created_at_ms"),
    )
    for step in trace.get("steps", []):
        store.append_step(run_id, step)
    store.finish_run(run_id, status=trace.get("status", "ok"))

    return run_id


# ---------------------------------------------------------------------------
# obtain_recorded_trace
# ---------------------------------------------------------------------------


def obtain_recorded_trace(
    *,
    prefer_record: bool = True,
    fixture_path=None,
    blob_dir=None,
) -> tuple:
    """Obtain a trace document, preferring the live recorder when asked.

    Parameters
    ----------
    prefer_record:
        When True, attempt to run ``python -m recorder.record --demo`` as a
        subprocess (timeout ~60 s) and parse the printed JSON trace.
        On any failure (non-zero exit, timeout, JSON parse error,
        FileNotFoundError) fall back to the fixture. Never raises.
        When False, skip the subprocess and go straight to the fixture.
    fixture_path:
        Path to the fallback fixture JSON; defaults to
        docs/fixtures/sample_trace.json.
    blob_dir:
        Blob directory for the fixture fallback; defaults to
        docs/fixtures/blobs.

    Returns
    -------
    (trace: dict, blob_dir: str | None)
        ``blob_dir`` is the absolute path to the blob directory when the
        fixture was used, or None when the live recorder produced the trace
        (blobs live in the recorder's own temp dir and their path is not
        returned here).
    """
    if fixture_path is None:
        fixture_path = _DEFAULT_FIXTURE
    if blob_dir is None:
        blob_dir = _DEFAULT_BLOB_DIR

    fixture_path = pathlib.Path(fixture_path)
    blob_dir = pathlib.Path(blob_dir)

    if prefer_record:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "recorder.record", "--demo"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"recorder exited with code {result.returncode}"
                )
            # The recorder prints the JSON trace followed by a summary line.
            # Extract the first valid JSON object from stdout.
            stdout = result.stdout.strip()
            # Find the outermost JSON object: locate first '{' and matching '}'
            start = stdout.index("{")
            # Scan for the matching closing brace
            depth = 0
            end = start
            for i, ch in enumerate(stdout[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            trace = json.loads(stdout[start : end + 1])
            print("[recorded_trace] source: live recorder subprocess")
            return trace, None
        except Exception as exc:  # noqa: BLE001
            print(f"[recorded_trace] live recorder failed ({exc!r}); using fixture")

    # Fallback: read the fixture
    trace = json.loads(fixture_path.read_text(encoding="utf-8"))
    print(f"[recorded_trace] source: fixture ({fixture_path})")
    return trace, str(blob_dir.resolve())


# ---------------------------------------------------------------------------
# analyze_recorded
# ---------------------------------------------------------------------------


def analyze_recorded(
    trace: dict,
    *,
    blob_dir: Optional[str] = None,
    resolves_at=None,
):
    """Run the Temporal Blame Graph on *trace* using ScriptedReplay.

    Parameters
    ----------
    trace:
        A trace document (docs/trace_schema.json shape).
    blob_dir:
        Directory where blobs are stored; passed to ``make_resolver`` when
        provided so rationales include resolved content.
    resolves_at:
        Set of step_ids whose correction resolves the failure. When None,
        defaults to ``{2}`` for the fixture run ("run-fixture-001") and
        ``set()`` for any other run_id.

    Returns
    -------
    BlameGraph
        The result of ``root_cause.analyze``.
    """
    from ai_agents import root_cause, trace_content

    if resolves_at is None:
        resolves_at = {2} if trace.get("run_id") == "run-fixture-001" else set()

    resolver = trace_content.make_resolver(blob_dir) if blob_dir else None
    replay = root_cause.ScriptedReplay(trace, resolves_at=resolves_at)
    return root_cause.analyze(trace, replay=replay, content_resolver=resolver)


# ---------------------------------------------------------------------------
# __main__ demo (offline-safe)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import tempfile

    from ai_agents.llm import LLMNotConfigured
    from ai_agents.root_cause import ScriptedReplay
    from ai_agents.debug_agent import build_injection
    from ai_agents.replay_adapter import StoreReplayEngine
    from trace_store.store import TraceStore

    # ------------------------------------------------------------------
    # Section 1: Live recording pipeline (proves the recorder works)
    # ------------------------------------------------------------------
    print("\n=== Live recording pipeline ===")
    trace_live, _live_blob_dir = obtain_recorded_trace()  # prefer_record=True by default
    print(f"run_id: {trace_live['run_id']}  steps: {len(trace_live['steps'])}")
    for s in trace_live["steps"]:
        print(f"  step {s['step_id']} ({s['type']}) status={s.get('status')}")

    # ------------------------------------------------------------------
    # Section 2: Analytical pipeline on the reference failing trace run-fixture-001
    # ------------------------------------------------------------------
    print("\n=== Analytical pipeline on the reference failing trace run-fixture-001 ===")

    trace_fix, blob_dir_fix = obtain_recorded_trace(prefer_record=False)
    # blob_dir_fix is always the fixture blob dir when prefer_record=False
    os.environ["CASSETTE_BLOB_DIR"] = blob_dir_fix

    with tempfile.TemporaryDirectory(prefix="cassette-demo-") as tmpdir:
        db_path = os.path.join(tmpdir, "demo.sqlite3")
        store = TraceStore(db_path=db_path)

        run_id = seed_store_from_fixture(store)
        engine = StoreReplayEngine(store)

        outcome = engine.replay(run_id)
        print(
            f"[baseline]"
            f"  final_status={outcome.final_status}"
            f"  failed_step_id={outcome.failed_step_id}"
            f"  side_effect_count={outcome.side_effect_count}"
        )

        store.close()

    graph = analyze_recorded(trace_fix, blob_dir=blob_dir_fix)
    print("\n[blame graph]")
    print(json.dumps(graph.to_api_dict(), indent=2))

    # Debug agent step (guarded; only network call in the demo)
    try:
        res = build_injection(trace_fix, "at step 2 the priority should have been high, not medium")
        inj = res.value
        outcome2 = ScriptedReplay(trace_fix, resolves_at={inj.step_id}).replay_with_injection(
            trace_fix["run_id"], inj
        )
        print(
            f"\ndebug agent injection: step={inj.step_id} target={inj.target} value={inj.value}"
            f" -> replay: {outcome2.final_status}"
        )
    except LLMNotConfigured:
        print("\n[debug agent] GROQ_API_KEY not set; skipping the live NL->injection step.")
