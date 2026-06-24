import os, tempfile, time, types, sys
from trace_store.store import TraceStore
from recorder.import_agent import driver as run_imported


def _make_fake_agent():
    """A module with a side-effecting tool + a main that calls it. No network.

    Built via exec() into the module's own __dict__ (not plain attribute
    assignment of test-file closures) so do_thing/main's __globals__ is the
    module's __dict__, matching how a real imported module behaves: calling
    main() resolves the *current* module attribute for do_thing, so
    _instrument_sdk's setattr(mod, "do_thing", wrapped) is actually observed.
    """
    mod = types.ModuleType("fake_imported_agent")
    mod.EXECUTED = {"n": 0}
    src = (
        "def do_thing(x):\n"
        "    EXECUTED['n'] += 1\n"
        "    return {'ok': x}\n"
        "def main():\n"
        "    do_thing('hi')\n"
    )
    exec(compile(src, "fake_imported_agent", "exec"), mod.__dict__)
    sys.modules["fake_imported_agent"] = mod
    return mod


def test_record_imported_inprocess_captures_sdk_tool():
    _make_fake_agent()
    work = tempfile.mkdtemp(prefix="imp-")
    os.environ["CASSETTE_BLOB_DIR"] = os.path.join(work, "blobs")
    store = TraceStore(db_path=os.path.join(work, "tape.sqlite3"))
    try:
        trace = run_imported.record_imported(
            run_id="imp-test-1",
            store=store,
            entry="fake_imported_agent:main",
            sdk_tools={"fake_imported_agent:do_thing": True},
            port=8951,  # distinct from the 8899 default used by test_full_stack
        )
    finally:
        store.close()
    kinds = [(s.get("transport"), s.get("type")) for s in trace["steps"]]
    assert ("sdk", "tool_call") in kinds, kinds


def test_parse_manifest_roundtrip():
    assert run_imported._parse_manifest(None) is None
    assert run_imported._parse_manifest('{"m:f": true, "m:g": false}') == {"m:f": True, "m:g": False}


def test_record_imported_requires_entry_or_command():
    import pytest
    store = TraceStore(db_path=":memory:")
    try:
        with pytest.raises(ValueError):
            run_imported.record_imported(run_id="x", store=store)
    finally:
        store.close()
