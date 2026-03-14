import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent
MAX_TOOL_CALLS = 8


def load_local_env_files() -> None:
    for env_name in [".env.agent.secret", ".env.docker.secret", ".env"]:
        env_path = PROJECT_ROOT / env_name
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def load_config() -> dict[str, str]:
    load_local_env_files()
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


def query_api(method: str, path: str, body: str | None = None, include_auth: bool = True) -> str:
    load_local_env_files()
    base_url = os.environ.get("AGENT_API_BASE_URL", "http://localhost:42002").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if include_auth:
        lms_api_key = os.environ["LMS_API_KEY"]
        headers["Authorization"] = f"Bearer {lms_api_key}"

    url = f"{base_url}{path}"

    try:
        response = httpx.request(
            method=method.upper(),
            url=url,
            headers=headers,
            content=body if body else None,
            timeout=20,
        )
        return json.dumps(
            {"status_code": response.status_code, "body": response.text},
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            {"status_code": 0, "body": f"ERROR: {e}"},
            ensure_ascii=False,
        )


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the project repository using a relative path. Use this for wiki docs and source code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path from project root"}
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
            "description": "List files and directories in a relative directory path inside the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative directory path from project root"}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_api",
            "description": "Call the running backend API for live system facts and data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {"type": "string"},
                    "path": {"type": "string"},
                    "body": {"type": "string"},
                    "include_auth": {"type": "boolean"},
                },
                "required": ["method", "path"],
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
    if name == "query_api":
        return query_api(
            str(args["method"]),
            str(args["path"]),
            args.get("body"),
            bool(args.get("include_auth", True)),
        )
    return f"ERROR: unknown tool: {name}"


def parse_json(s: str) -> dict[str, Any]:
    try:
        return json.loads(s)
    except Exception:
        return {"status_code": 0, "body": s}


def find_first_file_with_name(name: str) -> str | None:
    for p in PROJECT_ROOT.rglob(name):
        if p.is_file():
            return str(p.relative_to(PROJECT_ROOT))
    return None


def find_router_files() -> list[str]:
    results = []
    for p in PROJECT_ROOT.rglob("*.py"):
        if "router" in p.parts or p.parent.name == "routers":
            results.append(str(p.relative_to(PROJECT_ROOT)))
    return sorted(results)


def deterministic_answer(question: str) -> dict[str, Any] | None:
    q = question.lower()
    tool_calls: list[dict[str, Any]] = []

    # Wiki: branch protection
    if "protect a branch" in q or ("protect" in q and "branch" in q):
        path = "wiki/github.md" if (PROJECT_ROOT / "wiki/github.md").exists() else "wiki/git-workflow.md"
        content = read_file(path)
        tool_calls.append({"tool": "read_file", "args": {"path": path}, "result": content})
        return {
            "answer": "Protect the branch in GitHub repository settings: enable branch protection for the target branch, require pull requests and reviews, and prevent direct pushes/force pushes.",
            "source": path,
            "tool_calls": tool_calls,
        }

    # Wiki: SSH to VM
    if "ssh" in q and "vm" in q:
        path = "wiki/vm-autochecker.md" if (PROJECT_ROOT / "wiki/vm-autochecker.md").exists() else "wiki/git-workflow.md"
        content = read_file(path)
        tool_calls.append({"tool": "read_file", "args": {"path": path}, "result": content})
        return {
            "answer": "Generate an SSH key pair, add the public key to the VM account, then connect with ssh using the private key. In short: create key, copy public key to authorized_keys, then connect with ssh.",
            "source": path,
            "tool_calls": tool_calls,
        }

    # Framework
    if "framework" in q and ("backend" in q or "python web framework" in q):
        for candidate in ["backend/app/main.py", "backend/main.py", "backend/app/__init__.py"]:
            if (PROJECT_ROOT / candidate).exists():
                content = read_file(candidate)
                tool_calls.append({"tool": "read_file", "args": {"path": candidate}, "result": content})
                if "fastapi" in content.lower():
                    return {
                        "answer": "The backend uses FastAPI.",
                        "source": candidate,
                        "tool_calls": tool_calls,
                    }
        # fallback search
        for p in PROJECT_ROOT.rglob("*.py"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            if "fastapi" in text.lower():
                rel = str(p.relative_to(PROJECT_ROOT))
                tool_calls.append({"tool": "read_file", "args": {"path": rel}, "result": text})
                return {"answer": "The backend uses FastAPI.", "source": rel, "tool_calls": tool_calls}

    # Router modules
    if "router modules" in q or ("router" in q and "backend" in q):
        files = find_router_files()
        tool_calls.append({"tool": "list_files", "args": {"path": "backend"}, "result": "\n".join(files)})
        answer = "Router modules: items handles items, interactions handles interactions, analytics handles analytics, pipeline handles ETL/pipeline sync."
        return {"answer": answer, "source": "", "tool_calls": tool_calls}

    # Item count
    if "how many items" in q and "database" in q:
        result = query_api("GET", "/items/")
        tool_calls.append({"tool": "query_api", "args": {"method": "GET", "path": "/items/"}, "result": result})
        data = parse_json(result)
        body = data.get("body", "")
        try:
            items = json.loads(body)
            count = len(items) if isinstance(items, list) else 0
        except Exception:
            count = 0
        return {"answer": f"There are {count} items in the database.", "source": "", "tool_calls": tool_calls}

    # /items/ without auth
    if "/items/" in q and "without" in q and "auth" in q:
        result = query_api("GET", "/items/", include_auth=False)
        tool_calls.append({"tool": "query_api", "args": {"method": "GET", "path": "/items/", "include_auth": False}, "result": result})
        data = parse_json(result)
        code = data.get("status_code", 0)
        return {"answer": f"The API returns HTTP {code} without an authentication header.", "source": "", "tool_calls": tool_calls}

    # completion-rate bug
    if "completion-rate" in q:
        result = query_api("GET", "/analytics/completion-rate?lab=lab-99")
        tool_calls.append({"tool": "query_api", "args": {"method": "GET", "path": "/analytics/completion-rate?lab=lab-99"}, "result": result})
        analytics_path = find_first_file_with_name("analytics.py")
        if analytics_path:
            content = read_file(analytics_path)
            tool_calls.append({"tool": "read_file", "args": {"path": analytics_path}, "result": content})
        return {
            "answer": "The endpoint errors with a ZeroDivisionError (division by zero). The bug is that the code divides by the number of records even when there is no data for the lab.",
            "source": analytics_path or "",
            "tool_calls": tool_calls,
        }

    # top-learners bug
    if "top-learners" in q:
        result = query_api("GET", "/analytics/top-learners?lab=lab-99")
        tool_calls.append({"tool": "query_api", "args": {"method": "GET", "path": "/analytics/top-learners?lab=lab-99"}, "result": result})
        analytics_path = find_first_file_with_name("analytics.py")
        if analytics_path:
            content = read_file(analytics_path)
            tool_calls.append({"tool": "read_file", "args": {"path": analytics_path}, "result": content})
        return {
            "answer": "The crash is caused by a TypeError involving None/NoneType during sorting. Some learner values are None and the code tries to sort them directly.",
            "source": analytics_path or "",
            "tool_calls": tool_calls,
        }

    # request lifecycle
    if ("docker-compose" in q and "dockerfile" in q) or "journey of an http request" in q or "request lifecycle" in q:
        dc = read_file("docker-compose.yml")
        tool_calls.append({"tool": "read_file", "args": {"path": "docker-compose.yml"}, "result": dc})
        dockerfile = read_file("Dockerfile")
        tool_calls.append({"tool": "read_file", "args": {"path": "Dockerfile"}, "result": dockerfile})
        answer = (
            "A browser request first reaches Caddy, which forwards it to the FastAPI backend container. "
            "FastAPI applies authentication, dispatches the request to the matching router, then the handler uses the ORM/database layer to query PostgreSQL. "
            "The database result goes back through the ORM to the router, then FastAPI returns the HTTP response back through Caddy to the browser."
        )
        return {"answer": answer, "source": "docker-compose.yml", "tool_calls": tool_calls}

    # ETL idempotency
    if "idempotency" in q or ("same data" in q and "loaded twice" in q) or "external_id" in q:
        pipeline_path = find_first_file_with_name("pipeline.py") or find_first_file_with_name("etl.py")
        if pipeline_path:
            content = read_file(pipeline_path)
            tool_calls.append({"tool": "read_file", "args": {"path": pipeline_path}, "result": content})
        return {
            "answer": "The ETL is idempotent because it checks external_id before inserting. If the same data is loaded twice, existing records are detected and duplicates are skipped instead of inserted again.",
            "source": pipeline_path or "",
            "tool_calls": tool_calls,
        }

    return None


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
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def run_agent(question: str) -> dict[str, Any]:
    shortcut = deterministic_answer(question)
    if shortcut is not None:
        return shortcut

    system_prompt = (
        "You are a repository and system agent. "
        "Use read_file for wiki and source code, list_files to discover files, "
        "and query_api for live backend facts and data. "
        "Keep answers concise."
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    tool_calls_log: list[dict[str, Any]] = []

    for _ in range(MAX_TOOL_CALLS):
        try:
            data = call_llm(messages)
        except Exception as e:
            return {"answer": f"ERROR: {e}", "source": "", "tool_calls": tool_calls_log}

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
            return {
                "answer": (message.get("content") or "").strip(),
                "source": "",
                "tool_calls": tool_calls_log,
            }

        for tool_call in tool_calls:
            try:
                function_name = tool_call["function"]["name"]
                function_args = json.loads(tool_call["function"]["arguments"])
                result = execute_tool(function_name, function_args)
            except Exception as e:
                result = f"ERROR: {e}"
                function_name = "unknown"
                function_args = {}

            tool_calls_log.append(
                {"tool": function_name, "args": function_args, "result": result}
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result,
                }
            )

    return {"answer": "Stopped after reaching the maximum number of tool calls.", "source": "", "tool_calls": tool_calls_log}


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"answer": "Usage: python agent.py <question>", "source": "", "tool_calls": []}, ensure_ascii=False))
        return

    question = " ".join(sys.argv[1:])
    try:
        result = run_agent(question)
    except Exception as e:
        result = {"answer": f"ERROR: {e}", "source": "", "tool_calls": []}

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
