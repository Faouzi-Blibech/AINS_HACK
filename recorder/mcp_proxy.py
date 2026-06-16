"""MCP interception proxy.

Wraps the MCP client layer to capture MCP-protocol tool calls (Jira, Confluence,
etc.). Records the tool name, arguments, and exact response payload as a
tool_call step. In play mode it returns the recorded payload and never reaches
the live MCP server.

Skeleton only.
"""
from __future__ import annotations


class McpProxy:
    def __init__(self, mode: str = "record") -> None:
        self.mode = mode

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Record the call (record) or return the recorded payload (play)."""
        raise NotImplementedError
