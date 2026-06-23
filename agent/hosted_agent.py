# agent/hosted_agent.py
"""Generic OpenAI-compatible tool-calling agent.

ZERO Cassette imports. The runner (recorder/run_hosted.py) instruments
call_model, lookup_info, and submit_result from the outside -- exactly the
same pattern that recorder/record_session.py uses for full_stack_agent.py.
"""
from __future__ import annotations

import json
import os

import httpx

# Module-level effect counter so tests can verify side-effecting tools are
# not executed during replay (mirrors the EXECUTED pattern in full_stack_agent).
EXECUTED = {"lookup": 0, "submit": 0}

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "lookup_info",
            "description": "Look up a fact or piece of information by query string. Read-only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The information to look up."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_result",
            "description": "Submit a final result or summary. Side-effecting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "The result to submit."}
                },
                "required": ["summary"],
            },
        },
    },
]


def lookup_info(query: str) -> dict:
    """Read-only tool: returns a small derived fact for the query."""
    EXECUTED["lookup"] += 1
    return {"query": query, "result": f"info about {query}"}


def submit_result(summary: str) -> dict:
    """Side-effecting tool: in production would persist or send; here returns a receipt."""
    EXECUTED["submit"] += 1
    return {"submitted": True, "summary": summary}


def call_model(messages: list[dict]) -> dict:
    """POST to the configured OpenAI-compatible endpoint and return the assistant message dict.

    Tools fallback: if the first request with tools returns a 4xx, retry once
    without the tools field (required for reasoning models like NVIDIA nemotron
    that reject the tools parameter).
    """
    base_url = os.environ["CASSETTE_HOSTED_BASE_URL"]
    model = os.environ["CASSETTE_HOSTED_MODEL"]
    key = os.environ["CASSETTE_HOSTED_KEY"]

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    payload = {
        "model": model,
        "messages": messages,
        "tools": TOOLS_SCHEMA,
        "temperature": 0,
    }
    r = httpx.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=60)

    if r.status_code >= 400 and r.status_code < 500:
        # Retry without tools (reasoning models often reject the tools field).
        payload_no_tools = {k: v for k, v in payload.items() if k != "tools"}
        r = httpx.post(
            f"{base_url}/chat/completions",
            json=payload_no_tools,
            headers=headers,
            timeout=60,
        )

    if not r.is_success:
        raise RuntimeError(
            f"Model request failed: HTTP {r.status_code} - {r.text[:400]}"
        )

    msg = r.json()["choices"][0]["message"]

    # Reasoning field tolerance: some models (e.g. NVIDIA nemotron) put the
    # answer in reasoning_content with an empty content field.  Normalise so
    # the rest of the agent always sees a non-empty content when available.
    if not msg.get("content") and msg.get("reasoning_content"):
        msg = dict(msg, content=msg["reasoning_content"])

    return msg


def _dispatch_tool(name: str, arguments: dict) -> dict:
    """Dispatch a tool call by name using the current module-level bindings.

    Referencing the module-level names (not a captured dict) ensures the
    runner's external instrumentation (which replaces the module attributes)
    is always honoured.
    """
    import agent.hosted_agent as _self  # import self to resolve current bindings
    fn = getattr(_self, name, None)
    if fn is None or not callable(fn):
        return {"error": f"unknown tool {name!r}"}
    return fn(**arguments)


def main() -> int:
    task = os.environ.get("CASSETTE_AGENT_TASK", "Look up the status of project Alpha and submit a one-sentence summary.")

    messages: list[dict] = [
        {"role": "system", "content": (
            "You are a task agent with two tools: lookup_info (read-only) and "
            "submit_result (side-effecting, use last). Complete the user task."
        )},
        {"role": "user", "content": task},
    ]

    assistant_msg: dict = {}
    for _ in range(4):
        assistant_msg = call_model(messages)
        messages.append(assistant_msg)

        tool_calls = assistant_msg.get("tool_calls") or []
        if not tool_calls:
            # Model returned a plain content reply (or reasoning-only reply) -- done.
            # Always records the llm_call step; no error raised.
            break

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = json.loads(tc["function"]["arguments"])
            result = _dispatch_tool(fn_name, fn_args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result),
            })

    # Use reasoning_content as fallback if content is empty.
    final = (
        assistant_msg.get("content")
        or assistant_msg.get("reasoning_content")
        or "(no text reply)"
    )
    print(f"agent done: {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
