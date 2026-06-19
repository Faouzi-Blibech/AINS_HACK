"""Pure step construction + request identity for the recorder."""
from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit

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


def build_step(*, step_id, prev_step_id, method, url, req_body, status_code,
               resp_body, latency_ms, ts_ms, policy: Policy) -> dict:
    kind = policy.classify(method, url)
    req_blob = store_blob(policy.redact_body(req_body))
    resp_blob = store_blob(policy.redact_body(resp_body))
    step = {
        "step_id": step_id,
        "type": kind,
        "transport": "http",
        "timestamp_ms": ts_ms,
        "latency_ms": latency_ms,
        "status": "ok" if status_code < 400 else "error",
        "side_effecting": policy.is_side_effecting(method, url, kind),
        "confidence": None,
        "causal_parents": [prev_step_id] if prev_step_id else [],
    }
    step["status_code"] = status_code
    step["request_identity"] = request_identity(method, url, req_body, policy.volatile_fields())
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
        step["tool"] = policy.tool_name(url)
        step["args_blob"] = req_blob
        step["result_blob"] = resp_blob
    return step
