"""SDK hook interception: a framework-neutral @record_tool decorator.

Wraps any Python callable so each invocation is recorded as an sdk tool_call
step, and during replay returns the recorded result instead of executing —
side-effecting tools are NEVER run in replay (fail closed).
"""
from __future__ import annotations

import inspect
import time
from functools import wraps

from recorder.session import current_session


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
                                ts_ms=int(t0 * 1000))
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
                            ts_ms=int(t0 * 1000))
            return result
        return wrapper
    return decorator
