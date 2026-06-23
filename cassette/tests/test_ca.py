import pytest
from cassette import ca, paths


def test_proxy_env_has_all_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    env = ca.proxy_env(8899)
    assert env["HTTP_PROXY"] == "http://127.0.0.1:8899"
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:8899"
    bundle_str = str(tmp_path / "ca-bundle.pem")
    for k in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"):
        assert env[k] == bundle_str
    assert env["CASSETTE_CA"] == str(tmp_path / "ca.pem")
    assert env["NO_PROXY"] == "" and env["no_proxy"] == ""


def test_materialize_ca_copies(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    fake_src = tmp_path / "src-ca.pem"
    fake_src.write_text("FAKE CA")
    monkeypatch.setattr(ca, "_SRC_CA", fake_src)
    paths.ensure_home()
    dest = ca.materialize_ca()
    assert dest == tmp_path / "ca.pem"
    assert dest.read_text() == "FAKE CA"
    # The combined bundle is written alongside and includes the proxy CA.
    assert ca.bundle_path().exists()
    assert "FAKE CA" in ca.bundle_path().read_text()


def test_materialize_ca_missing_source(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    monkeypatch.setattr(ca, "_SRC_CA", tmp_path / "nope.pem")
    paths.ensure_home()
    with pytest.raises(FileNotFoundError):
        ca.materialize_ca()
