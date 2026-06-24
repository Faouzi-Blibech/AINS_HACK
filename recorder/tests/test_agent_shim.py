import os, subprocess, sys, json, textwrap
from pathlib import Path

SHIM_DIR = str(Path(__file__).resolve().parent.parent / "agent_shim")


def test_shim_wraps_manifest_tool_at_startup(tmp_path):
    # a tiny agent module whose tool increments a counter
    mod = tmp_path / "tinyagent.py"
    mod.write_text(textwrap.dedent('''
        CALLS = {"n": 0}
        def tool(x):
            CALLS["n"] += 1
            return x
    '''))
    probe = tmp_path / "probe.py"
    # After import, the attribute must be the wrapped version (has __wrapped__).
    probe.write_text(textwrap.dedent('''
        import tinyagent
        print(hasattr(tinyagent.tool, "__wrapped__"))
    '''))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([SHIM_DIR, str(tmp_path), env.get("PYTHONPATH", "")])
    env["CASSETTE_TOOL_MANIFEST"] = json.dumps({"tinyagent:tool": False})
    out = subprocess.run([sys.executable, str(probe)], env=env,
                         capture_output=True, text=True)
    assert out.stdout.strip() == "True", out.stderr
