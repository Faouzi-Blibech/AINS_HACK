import os
import subprocess
import sys
from cassette import shim_env


def test_shim_rebinds_certifi_where(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\nCASSETTE-TEST\n-----END CERTIFICATE-----\n")
    env = dict(os.environ)
    env["CASSETTE_CA"] = str(ca)
    env = shim_env.with_shim(env)
    code = (
        "import certifi; p=certifi.where(); "
        "data=open(p,encoding='utf-8').read(); "
        "print('CASSETTE-TEST' in data)"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True)
    assert out.stdout.strip() == "True", out.stderr
