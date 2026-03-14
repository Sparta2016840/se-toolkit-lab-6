import json
import agent


def test_query_api_uses_env(monkeypatch):
    captured = {}

    def fake_request(method, url, headers=None, content=None, timeout=None):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers

        class Resp:
            status_code = 200
            text = '{"ok": true}'
        return Resp()

    monkeypatch.setenv("LMS_API_KEY", "secret-key")
    monkeypatch.setenv("AGENT_API_BASE_URL", "http://localhost:42002")
    monkeypatch.setattr(agent.httpx, "request", fake_request)

    result = agent.query_api("GET", "/items/")
    data = json.loads(result)

    assert captured["method"] == "GET"
    assert captured["url"] == "http://localhost:42002/items/"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert data["status_code"] == 200


def test_query_api_tool_schema_exists():
    names = [tool["function"]["name"] for tool in agent.TOOLS]
    assert "query_api" in names
