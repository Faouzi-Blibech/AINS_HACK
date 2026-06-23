"""Pure step construction + request identity for the recorder."""
from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit

from recorder import mcp_proxy
from recorder.mcp_proxy import _strip_volatile
from recorder.policy import Policy
from trace_store.blob_store import store_blob


def _canonical(body: str, volatile: list[str]) -> bytes:
    try:
        obj = json.loads(body)
    except (ValueError, TypeError):
        return body.encode()
    if isinstance(obj, dict):
        obj = {k: v for k, v in obj.items() if k not in volatile}
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def request_identity(method: str, url: str, body: str, volatile: list[str]) -> str:
    path = urlsplit(url).path
    digest = hashlib.sha256(_canonical(body, volatile)).hexdigest()
    return f"{method.upper()} {path}\n{digest}"


def compute_identity(method: str, url: str, body: str, policy: Policy) -> str:
    """Transport router: MCP (JSON-RPC) requests get an id-independent identity,
    everything else the HTTP method+path+body identity. Used by both the record
    path (build_step) and the replay path (ReplayAddon) so they always agree."""
    call = mcp_proxy.parse_request(body)
    if call is not None:
        return mcp_proxy.mcp_identity(call, policy.volatile_fields())
    return request_identity(method, url, body, policy.volatile_fields())


def build_step(*, step_id, prev_step_id, method, url, req_body, status_code,
               resp_body, latency_ms, ts_ms, policy: Policy) -> dict:
    call = mcp_proxy.parse_request(req_body)
    transport = "mcp" if call is not None else "http"
    if transport == "mcp":
        kind = "tool_call"
        side_effecting = policy.is_side_effecting_mcp(call)
        identity = mcp_proxy.mcp_identity(call, policy.volatile_fields())
    else:
        kind = policy.classify(method, url)
        side_effecting = policy.is_side_effecting(method, url, kind)
        identity = request_identity(method, url, req_body, policy.volatile_fields())
    req_blob = store_blob(policy.redact_body(req_body))
    resp_blob = store_blob(policy.redact_body(resp_body))
    step = {
        "step_id": step_id,
        "type": kind,
        "transport": transport,
        "timestamp_ms": ts_ms,
        "latency_ms": latency_ms,
        "status": "ok" if status_code < 400 else "error",
        "side_effecting": side_effecting,
        "confidence": None,
        "causal_parents": [prev_step_id] if prev_step_id else [],
    }
    step["status_code"] = status_code
    step["request_identity"] = identity
    if kind == "llm_call":
        step["prompt_blob"] = req_blob
        step["response_blob"] = resp_blob
        try:
            body = json.loads(req_body)
            step["model"] = body.get("model")
        except (ValueError, TypeError):
            pass
        try:
            usage = json.loads(resp_body).get("usage", {})
            if usage:
                step["token_usage"] = {
                    "prompt": usage.get("prompt_tokens"),
                    "completion": usage.get("completion_tokens"),
                }
        except (ValueError, TypeError):
            pass
    else:
        step["tool"] = (call.tool or call.method) if transport == "mcp" else policy.tool_name(url)
        step["args_blob"] = req_blob
        step["result_blob"] = resp_blob
    return step


def sdk_identity(tool: str, args: dict, volatile: list[str]) -> str:
    """Id for a native (SDK) tool call: tool name + canonical, volatile-stripped args."""
    stripped = _strip_volatile(args or {}, set(volatile)) if volatile else (args or {})
    blob = json.dumps(stripped, sort_keys=True, separators=(",", ":")).encode()
    return f"sdk {tool}\n{hashlib.sha256(blob).hexdigest()}"


def build_sdk_step(*, step_id, prev_step_id, tool, args, result, side_effecting,
                   latency_ms, ts_ms, policy: Policy,
                   parallel_group: str | None = None,
                   causal_parents: list | None = None) -> dict:
    args = args or {}
    args_blob = store_blob(policy.redact_body(json.dumps(args, default=str)))
    result_blob = store_blob(policy.redact_body(json.dumps(result, default=str)))
    step = {
        "step_id": step_id,
        "type": "tool_call",
        "transport": "sdk",
        "timestamp_ms": ts_ms,
        "latency_ms": latency_ms,
        "status": "ok",
        "status_code": 200,
        "side_effecting": side_effecting,
        "confidence": None,
        "causal_parents": (causal_parents if causal_parents is not None
                           else ([prev_step_id] if prev_step_id else [])),
        "tool": tool,
        "args_blob": args_blob,
        "result_blob": result_blob,
        "request_identity": sdk_identity(tool, args, policy.volatile_fields()),
    }
    # parallel_group (schema v1.1): present only for tool_calls dispatched in a
    # single multi-tool model response; omitted for sequential calls.
    if parallel_group is not None:
        step["parallel_group"] = parallel_group
    return step
