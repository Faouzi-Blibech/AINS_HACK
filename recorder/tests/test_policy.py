from recorder.policy import load_policy

P = load_policy()

def test_classify_llm_by_path():
    assert P.classify("POST", "http://127.0.0.1:9/v1/chat/completions") == "llm_call"

def test_classify_llm_by_host():
    assert P.classify("POST", "https://api.groq.com/openai/v1/chat/completions") == "llm_call"

def test_classify_tool_default():
    assert P.classify("POST", "http://127.0.0.1:9/assign_ticket") == "tool_call"

def test_side_effecting_post_tool():
    assert P.is_side_effecting("POST", "http://h/assign_ticket", "tool_call") is True

def test_get_tool_not_side_effecting():
    assert P.is_side_effecting("GET", "http://h/get_priority", "tool_call") is False

def test_llm_never_side_effecting():
    assert P.is_side_effecting("POST", "http://h/v1/chat/completions", "llm_call") is False

def test_tool_name_is_last_segment():
    assert P.tool_name("http://h/tools/send_email") == "send_email"

def test_should_record_allowlist():
    assert P.should_record("api.groq.com") is True
    assert P.should_record("telemetry.example.com") is False

def test_read_only_path_override():
    # get_priority is a POST but read-only -> must not be flagged side-effecting
    assert P.is_side_effecting("POST", "http://h/get_priority", "tool_call") is False

def test_redact_body_strips_secrets():
    out = P.redact_body('{"api_key": "sk-123", "model": "x"}')
    assert "sk-123" not in out and "<redacted>" in out and "x" in out
