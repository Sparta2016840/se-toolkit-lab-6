import json
import agent


def test_load_config_reads_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_API_BASE", "https://example.com/v1/")
    monkeypatch.setenv("LLM_MODEL", "demo-model")

    cfg = agent.load_config()

    assert cfg["api_key"] == "k"
    assert cfg["api_base"] == "https://example.com/v1"
    assert cfg["model"] == "demo-model"


def test_main_outputs_json(monkeypatch, capsys):
    monkeypatch.setattr(
        agent,
        "run_agent",
        lambda question: {
            "answer": "mock-answer",
            "source": "wiki/git-workflow.md",
            "tool_calls": [],
        },
    )
    monkeypatch.setattr(agent.sys, "argv", ["agent.py", "hello"])

    agent.main()

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["answer"] == "mock-answer"
    assert data["source"] == "wiki/git-workflow.md"
    assert data["tool_calls"] == []
