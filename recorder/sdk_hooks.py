"""SDK hook interception: a framework-neutral @record_tool decorator and
record_llm wrapper for OpenAI-compatible model calls.

record_tool wraps any Python callable so each invocation is recorded as an sdk
tool_call step, and during replay returns the recorded result instead of
executing -- side-effecting tools are NEVER run in replay (fail closed).

record_llm wraps a synchronous model-call function so each invocation is
recorded as an llm_call step.  No active session -> pure passthrough.
"""
from __future__ import annotations

import inspect
import json
import os
import time
from functools import wraps

from recorder.capture import heuristic_confidence
from recorder.session import current_session
from trace_store.blob_store import store_blob


def _tool_status(result) -> str:
    """A tool result signals failure when it returns a dict with an ``error`` key
    or ``ok: False`` -- that step is recorded as status=error so the trace flags
    the failure and the blame graph can attribute it."""
    if isinstance(result, dict) and (result.get("error") is not None or result.get("ok") is False):
        return "error"
    return "ok"


def _bind(fn, args, kwargs) -> dict:
    try:
        bound = inspect.signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)
    except TypeError:
        return {"args": list(args), "kwargs": dict(kwargs)}


def record_tool(side_effecting: bool = False):
    def decorator(fn):
        tool = fn.__name__

        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def awrapper(*args, **kwargs):
                sess = current_session()
                if sess is None:
                    return await fn(*args, **kwargs)
                bound = _bind(fn, args, kwargs)
                if sess.mode == "replay":
                    return sess.replay_sdk(tool=tool, args=bound, side_effecting=side_effecting)
                t0 = time.time()
                result = await fn(*args, **kwargs)
                sess.record_sdk(tool=tool, args=bound, result=result,
                                side_effecting=side_effecting,
                                latency_ms=int((time.time() - t0) * 1000),
                                ts_ms=int(t0 * 1000),
                                status=_tool_status(result))
                return result
            return awrapper

        @wraps(fn)
        def wrapper(*args, **kwargs):
            sess = current_session()
            if sess is None:
                return fn(*args, **kwargs)
            bound = _bind(fn, args, kwargs)
            if sess.mode == "replay":
                return sess.replay_sdk(tool=tool, args=bound, side_effecting=side_effecting)
            t0 = time.time()
            result = fn(*args, **kwargs)
            sess.record_sdk(tool=tool, args=bound, result=result,
                            side_effecting=side_effecting,
                            latency_ms=int((time.time() - t0) * 1000),
                            ts_ms=int(t0 * 1000),
                            status=_tool_status(result))
            return result
        return wrapper
    return decorator


def record_llm(fn):
    """Wrap a synchronous model-call function to record an llm_call step.

    When a RecordingSession is active in record mode the wrapper:
      1. Calls the real function.
      2. Appends an llm_call step to the trace (prompt blob + response blob).

    No active session -> pure passthrough (transparent in replay mode too --
    the hosted runner does not currently support replay; this guard is still
    correct for future use).
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        sess = current_session()
        if sess is None or sess.mode != "record":
            return fn(*args, **kwargs)

        # Capture the messages list (first positional arg or keyword).
        bound = _bind(fn, args, kwargs)
        messages = bound.get("messages") or (list(args)[0] if args else [])

        t0 = time.time()
        result = fn(*args, **kwargs)
        latency_ms = int((time.time() - t0) * 1000)
        ts_ms = int(t0 * 1000)

        # Build and append the llm_call step directly (mirrors record_sdk /
        # build_sdk_step but uses llm_call type + prompt/response blobs).
        sid = sess.next_step_id()
        # Fan-in: the first llm_call after a parallel batch synthesises the
        # siblings' results, so its causal_parents are all the sibling step_ids.
        fanin = sess.consume_fanin_parents()
        if fanin is not None:
            causal_parents = fanin
        else:
            prev = sid - 1 if sid > 1 else None
            causal_parents = [prev] if prev else []
        model = os.environ.get("CASSETTE_HOSTED_MODEL", "")
        prompt_text = sess.policy.redact_body(json.dumps(messages, default=str))
        response_text = sess.policy.redact_body(json.dumps(result, default=str))
        step = {
            "step_id": sid,
            "type": "llm_call",
            "transport": "sdk",
            "timestamp_ms": ts_ms,
            "latency_ms": latency_ms,
            "status": "ok",
            "side_effecting": False,
            "confidence": heuristic_confidence(
                step_type="llm_call", has_content=bool(isinstance(result, dict) and result.get("content"))
            ),
            "causal_parents": causal_parents,
            "model": model,
            "prompt_blob": store_blob(prompt_text),
            "response_blob": store_blob(response_text),
        }
        try:
            sess.store.append_step(sess.run_id, step)
        except Exception as exc:
            print(f"[cassette] failed to record llm step: {exc}")

        # Arm a parallel group when this response dispatched >=2 tool calls so
        # the following tool_call steps share one parallel_group UUID.
        tool_calls = result.get("tool_calls") if isinstance(result, dict) else None
        sess.arm_parallel_group(len(tool_calls or []), sid)

        return result
    return wrapper
