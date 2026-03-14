import json
import os
import sys
import httpx


def load_config() -> dict[str, str]:
    return {
        "api_key": os.environ["LLM_API_KEY"],
        "api_base": os.environ["LLM_API_BASE"].rstrip("/"),
        "model": os.environ["LLM_MODEL"],
    }


def ask_llm(question: str) -> str:
    cfg = load_config()
    response = httpx.post(
        f'{cfg["api_base"]}/chat/completions',
        headers={
            "Authorization": f'Bearer {cfg["api_key"]}',
            "Content-Type": "application/json",
        },
        json={
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": "You are a concise helpful assistant."},
                {"role": "user", "content": question},
            ],
            "temperature": 0,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python agent.py <question>"}))
        raise SystemExit(1)

    question = " ".join(sys.argv[1:])
    answer = ask_llm(question)
    print(json.dumps({"answer": answer}, ensure_ascii=False))


if __name__ == "__main__":
    main()
