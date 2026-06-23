"""One-time trust consent + enabled-agent registry, persisted in agents.json."""
from __future__ import annotations

import json

from cassette import paths

_PROMPT = (
    "Cassette will route this agent's traffic through a local recording proxy "
    "and trust its CA for this process only. Trust and record? [y/N] "
)


def agent_key(cmd) -> str:
    return " ".join(cmd)


def load_registry() -> dict:
    p = paths.agents_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_registry(reg: dict) -> None:
    paths.ensure_home()
    paths.agents_path().write_text(json.dumps(reg, indent=2), encoding="utf-8")


def _entry(cmd) -> dict:
    return load_registry().get(agent_key(cmd), {})


def is_trusted(cmd) -> bool:
    return bool(_entry(cmd).get("trusted"))


def record_consent(cmd, trusted: bool) -> None:
    reg = load_registry()
    reg.setdefault(agent_key(cmd), {})["trusted"] = bool(trusted)
    save_registry(reg)


def ensure_consent(cmd, *, prompt=input) -> bool:
    reg = load_registry()
    entry = reg.get(agent_key(cmd), {})
    if "trusted" in entry:
        return bool(entry["trusted"])
    answer = str(prompt(_PROMPT)).strip().lower()
    trusted = answer in ("y", "yes")
    record_consent(cmd, trusted)
    return trusted


def set_enabled(cmd, enabled: bool) -> None:
    reg = load_registry()
    reg.setdefault(agent_key(cmd), {})["enabled"] = bool(enabled)
    save_registry(reg)


def is_enabled(cmd) -> bool:
    return bool(_entry(cmd).get("enabled"))
