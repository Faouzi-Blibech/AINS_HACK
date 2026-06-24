from recorder.import_agent import container as C


def _argv(**kw):
    base = dict(image="img", workspace="/w", store_home="/s", run_id="r1")
    base.update(kw)
    return C.build_run_argv(**base)


def test_argv_mounts_workspace_and_store_readwrite():
    argv = _argv()
    joined = " ".join(argv)
    assert "-v" in argv
    assert "/w:/workspace" in joined
    assert "/s:/root/.cassette" in joined
    assert argv[0] == "docker" and argv[1] == "run"


def test_argv_passes_entry_and_manifest_and_store_paths():
    argv = _argv(entry="pkg.mod:main", manifest='{"pkg.mod:tool": true}')
    joined = " ".join(argv)
    assert "--entry" in argv and "pkg.mod:main" in argv
    assert "--manifest" in argv
    assert "--db" in argv and "/root/.cassette/cassette.sqlite3" in joined
    assert "--blob-dir" in argv and "/root/.cassette/blobs" in joined


def test_argv_forwards_secret_env_with_e_flag_not_values_in_clear_list():
    argv = _argv(env={"OPENAI_API_KEY": "sk-secret"})
    # secret passed by NAME via -e so docker reads it from our process env
    assert "-e" in argv
    assert "OPENAI_API_KEY" in argv
    assert "sk-secret" not in argv  # value is NOT placed on the command line


def test_argv_command_mode_appends_after_double_dash():
    argv = _argv(command=["python", "main.py"])
    assert argv[-3:] == ["--", "python", "main.py"]
