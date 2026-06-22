from cassette import consent


def test_first_time_prompts_and_remembers(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    calls = []
    assert consent.ensure_consent(["claude"], prompt=lambda m: calls.append(m) or "y") is True
    assert len(calls) == 1
    assert "Trust and record" in calls[0]
    assert consent.ensure_consent(["claude"], prompt=lambda m: calls.append(m) or "n") is True
    assert len(calls) == 1


def test_decline_is_remembered(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    assert consent.ensure_consent(["x"], prompt=lambda m: "n") is False
    assert consent.is_trusted(["x"]) is False


def test_enabled_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("CASSETTE_HOME", str(tmp_path))
    assert consent.is_enabled(["a"]) is False
    consent.set_enabled(["a"], True)
    assert consent.is_enabled(["a"]) is True
