# cassette/tests/test_trust.py
import sys
from pathlib import Path
from cassette import trust, paths


def test_trust_untrust_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    paths.ensure_home()
    paths.ca_path().write_text("CASSETTE-CA-PEM\n")
    bundle = tmp_path / "cacert.pem"
    original = "ROOT-CERTS\n"
    bundle.write_text(original)
    monkeypatch.setattr(trust, "certifi_path", lambda exe: str(bundle))

    trust.trust(sys.executable)
    after = bundle.read_text()
    assert "ROOT-CERTS" in after and "CASSETTE-CA-PEM" in after
    assert (tmp_path / "cacert.pem.cassette-bak").exists()

    trust.trust(sys.executable)  # idempotent
    assert bundle.read_text().count("CASSETTE-CA-PEM") == 1

    assert trust.untrust(sys.executable) is True
    assert bundle.read_text() == original
