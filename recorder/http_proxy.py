"""HTTP/TLS interception proxy.

Routes the agent's LLM API traffic and REST tool calls through a local proxy.
In record mode it forwards to the live endpoint and captures the exchange; in
play mode it matches the request to the recorded tape and returns the recorded
response without forwarding.

Skeleton only.
"""
from __future__ import annotations


class HttpProxy:
    def __init__(self, mode: str = "record") -> None:
        # mode in {"record", "play", "record-over"}
        self.mode = mode

    def handle_request(self, request: dict) -> dict:
        """Capture (record) or serve from tape (play). Returns the response."""
        raise NotImplementedError

    def request_identity(self, request: dict) -> str:
        """Stable key for matching a replayed request to a recorded step."""
        raise NotImplementedError
