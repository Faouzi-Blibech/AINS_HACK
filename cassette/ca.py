"""Materialize the proxy CA to a stable path and build the agent attach env."""
from __future__ import annotations

import shutil
from pathlib import Path

from cassette import paths
from recorder.http_proxy import CA_PATH as _SRC_CA  # mitmproxy CA, generated on first proxy start


def bundle_path() -> Path:
    """Combined CA bundle (public roots + proxy CA).

    Used for the attach env vars so non-shimmed agents (Node, stdlib ssl, the
    remote `cassette env` path) can verify both the proxy and real upstreams.
    Python agents under `cassette run` are handled by the in-process shim.
    """
    return paths.home() / "ca-bundle.pem"


def _write_combined_bundle(ca_pem: Path) -> None:
    try:
        import certifi
        roots = Path(certifi.where()).read_bytes()
    except Exception:
        roots = b""
    data = roots
    if data and not data.endswith(b"\n"):
        data += b"\n"
    data += ca_pem.read_bytes()
    bundle_path().write_bytes(data)


def materialize_ca() -> Path:
    """Copy the mitmproxy CA to ~/.cassette/ca.pem and build the combined bundle."""
    src = _SRC_CA
    if not Path(src).exists():
        raise FileNotFoundError(f"proxy CA not found at {src}; start the proxy once to generate it")
    dest = paths.ca_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    _write_combined_bundle(dest)
    return dest


def proxy_env(port: int) -> dict[str, str]:
    url = f"http://127.0.0.1:{port}"
    bundle = str(bundle_path())
    return {
        "HTTP_PROXY": url,
        "HTTPS_PROXY": url,
        "SSL_CERT_FILE": bundle,
        "REQUESTS_CA_BUNDLE": bundle,
        "NODE_EXTRA_CA_CERTS": bundle,
        "CASSETTE_CA": str(paths.ca_path()),
        "NO_PROXY": "",
        "no_proxy": "",
    }
