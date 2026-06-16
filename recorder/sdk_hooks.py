"""SDK hook interception.

A decorator / middleware applied to native function-calling tool definitions.
Wraps each tool so that every invocation is recorded as a tool_call step, and
during replay returns the recorded result instead of executing the function.

Skeleton only.
"""
from __future__ import annotations

from functools import wraps


def record_tool(side_effecting: bool = False):
    """Decorator that records a native function tool.

    side_effecting=True marks the call so it is ALWAYS mocked during replay.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            raise NotImplementedError
        return wrapper
    return decorator
