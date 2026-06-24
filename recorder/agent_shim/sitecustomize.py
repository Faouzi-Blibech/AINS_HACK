"""Startup shim auto-imported via PYTHONPATH inside the agent's process.

Two install-from-outside jobs, neither edits the agent's source:
  1. CA trust: combine certifi roots + the proxy CA so httpx/requests/ssl trust
     the recording proxy (effect confined to this process).
  2. SDK capture: wrap callables named in CASSETTE_TOOL_MANIFEST with
     recorder.sdk_hooks.record_tool, so native in-process tools are recorded.
Must never crash the agent.
"""
import importlib
import json
import os
import tempfile

# --- 1. CA trust (carried over from the old trust_shim) ---
_ca = os.environ.get("CASSETTE_CA")
if _ca and os.path.exists(_ca):
    try:
        import certifi
        with open(certifi.where(), "rb") as fh:
            _base = fh.read()
        with open(_ca, "rb") as fh:
            _extra = fh.read()
        _fd, _combined = tempfile.mkstemp(prefix="cassette-cabundle-", suffix=".pem")
        with os.fdopen(_fd, "wb") as fh:
            fh.write(_base)
            if not _base.endswith(b"\n"):
                fh.write(b"\n")
            fh.write(_extra)
        certifi.where = lambda _p=_combined: _p  # type: ignore[assignment]
        os.environ["SSL_CERT_FILE"] = _combined
        os.environ["REQUESTS_CA_BUNDLE"] = _combined
    except Exception:
        pass

# --- 2. SDK manifest wrap ---
_manifest = os.environ.get("CASSETTE_TOOL_MANIFEST")
if _manifest:
    try:
        from recorder.sdk_hooks import record_tool
        for spec, side in json.loads(_manifest).items():
            mod_name, _, attr = spec.partition(":")
            try:
                mod = importlib.import_module(mod_name)
                setattr(mod, attr, record_tool(side_effecting=bool(side))(getattr(mod, attr)))
            except Exception:
                # A single bad entry must not break the agent.
                pass
    except Exception:
        pass
