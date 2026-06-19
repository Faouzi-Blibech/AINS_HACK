"""Declarative, agent-agnostic classification + redaction policy."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import yaml

_DEFAULT = Path(__file__).with_name("policy.yaml")


class Policy:
    def __init__(self, cfg: dict) -> None:
        self._record_hosts = set(cfg.get("record_hosts", []))
        self._llm_hosts = set(cfg.get("llm", {}).get("hosts", []))
        self._llm_paths = list(cfg.get("llm", {}).get("path_patterns", []))
        self._read_only = {m.upper() for m in cfg.get("read_only_methods", [])}
        self._read_only_paths = list(cfg.get("read_only_paths", []))
        self._redact = {f.lower() for f in cfg.get("redact_fields", [])}
        self._volatile = list(cfg.get("volatile_fields", []))

    def should_record(self, host: str) -> bool:
        return not self._record_hosts or host in self._record_hosts

    def classify(self, method: str, url: str) -> str:
        p = urlsplit(url)
        if p.hostname in self._llm_hosts or any(s in p.path for s in self._llm_paths):
            return "llm_call"
        return "tool_call"

    def is_side_effecting(self, method: str, url: str, kind: str) -> bool:
        if kind == "llm_call":
            return False
        if any(urlsplit(url).path.endswith(p) for p in self._read_only_paths):
            return False
        return method.upper() not in self._read_only

    def tool_name(self, url: str) -> str:
        return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]

    def volatile_fields(self) -> list[str]:
        return list(self._volatile)

    def redact_body(self, text: str) -> str:
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            return text
        return json.dumps(self._scrub(obj))

    def _scrub(self, obj):
        if isinstance(obj, dict):
            return {k: ("<redacted>" if k.lower() in self._redact else self._scrub(v))
                    for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._scrub(v) for v in obj]
        return obj


def load_policy(path: str | None = None) -> Policy:
    src = Path(path) if path else _DEFAULT
    return Policy(yaml.safe_load(src.read_text(encoding="utf-8")))
