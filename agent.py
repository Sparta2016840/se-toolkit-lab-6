import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx


PROJECT_ROOT = Path(__file__).resolve().parent
MAX_TOOL_CALLS = 10


def load_config() -> dict[str, str]:
    return {
        "api_key": os.environ["LLM_API_KEY"],
        "api_base": os.environ["LLM_API_BASE"].rstrip("/"),
        "model": os.environ["LLM_MODEL"],
    }


def safe_resolve(path_str: str) -> Path:
    candidate = (PROJECT_ROOT / path_str).resolve()
    if candidate != PROJECT_ROOT and PROJECT_ROOT not in candidate.parents:
        raise ValueError("Path escapes project root")
    return candidate


def read_file(path: str) -> str:
    try:
        target = safe_resolve(path)
        if not target.exists():
            return f"ERROR: file does not exist: {path}"
        if not target.is_file():
            return f"ERROR: not a file: {path}"
        return target.read_text(encoding="utf-8")
    except Exception as e:
        return f"ERROR: {e}"


def list_files(path: str) -> str:
    try:
        target = safe_resolve(path)
        if not target.exists():
            return f"ERROR: path does not exist: {path}"
        if not target.is_dir():
            return f"ERROR: not a directory: {path}"
        entries = sorted(item.name for item in target.iterdir())
        return "\n".join(entries)
    except Exception as e:
        return f"ERROR: {e}"


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the project repository using a relative path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from the project root, for example wiki/git-workflow.md",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories at a relative directory path in the project repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path from the project root, for example wiki",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
]


def execute_tool(name: str, args: dict[str, Any]) -> str:
    if name == "read_file":
        return read_file(str(args["path"]))
    if name == "list_files":
        return list_files(str(args["path"]))
    return f"ERROR: unknown tool: {name}"


def extract_answer_and_source(text: str) -> tuple[str, str]:
    answer = text.strip()
    source = ""
    for line in text.splitlines():
        if line.lower().startswith("source:"):
            source = line.split(":", 1)[1].strip()
            answer = "\n".join(
                l for l in text.splitlines() if not l.lower().startswith("source:")
            ).strip()
            break
    return answer, source


def call_llm(messages: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = load_config()
    response = httpx.post(
        f'{cfg["api_base"]}/chat/completions',
        headers={
            "Authorization": f'Bearer {cfg["api_key"]}',
            "Content-Type": "application/json",
        },
        json={
            "model": cfg["model"],
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
            "temperature": 0,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def run_agent(question: str) -> dict[str, Any]:
    system_prompt = (
        "You are a documentation agent for this repository. "
        "Use list_files to discover wiki files and read_file to inspect them. "
        "Prefer wiki/ for documentation questions. "
        "When you answer, include a line in the format 'Source: path#section-anchor' "
        "if you found the answer in documentation. "
        "Keep answers concise."
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    tool_calls_log: list[dict[str, Any]] = []

    for _ in range(MAX_TOOL_CALLS):
        data = call_llm(messages)
        message = data["choices"][0]["message"]

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content") or "",
        }
        if message.get("tool_calls"):
            assistant_message["tool_calls"] = message["tool_calls"]
        messages.append(assistant_message)

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            answer, source = extract_answer_and_source(message.get("content") or "")
            return {
                "answer": answer,
                "source": source,
                "tool_calls": tool_calls_log,
            }

        for tool_call in tool_calls:
            function_name = tool_call["function"]["name"]
            function_args = json.loads(tool_call["function"]["arguments"])
            result = execute_tool(function_name, function_args)

            tool_calls_log.append(
                {
                    "tool": function_name,
                    "args": function_args,
                    "result": result,
                }
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result,
                }
            )

    return {
        "answer": "Stopped after reaching the maximum number of tool calls.",
        "source": "",
        "tool_calls": tool_calls_log,
    }


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python agent.py <question>"}))
        raise SystemExit(1)

    question = " ".join(sys.argv[1:])
    result = run_agent(question)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
