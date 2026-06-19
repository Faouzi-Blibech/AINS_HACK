import httpx
from recorder.mock_upstream import serve

def test_llm_and_tool_endpoints():
    server, base = serve(0)
    try:
        r = httpx.post(f"{base}/v1/chat/completions",
                       json={"model": "m", "messages": []}, timeout=5)
        assert r.status_code == 200
        assert "choices" in r.json() and "usage" in r.json()
        t = httpx.post(f"{base}/get_priority", json={"raw_priority": "P2 / medium?"}, timeout=5)
        assert t.json()["priority"] == "medium"
    finally:
        server.shutdown()
