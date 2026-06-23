"""Per-process CA trust shim. Imported automatically by Python at startup when
this directory is on PYTHONPATH. Builds a combined bundle (the interpreter's own
certifi roots + the Cassette proxy CA) and points certifi/env at it, so httpx
(OpenAI/Anthropic SDKs), requests, and stdlib ssl all trust the recording proxy.
The effect is confined to this process; no on-disk bundle is modified."""
import os
import tempfile

_ca = os.environ.get("CASSETTE_CA")
if _ca and os.path.exists(_ca):
    try:
        import certifi

        _orig = certifi.where()
        with open(_orig, "rb") as fh:
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
        # Trust shim must never crash the agent.
        pass
