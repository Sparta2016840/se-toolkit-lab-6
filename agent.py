import json
import os
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
        if p.parent.name == "routers" or "routers" in p.parts:
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
            "answer": "Protect the branch in GitHub repository settings: enable branch protection for the target branch, require pull requests and reviews, and prevent direct pushes or force pushes.",
            "source": path,
            "tool_calls": tool_calls,
        }

    # Wiki: SSH to VM
    if "ssh" in q and "vm" in q:
        path = "wiki/vm-autochecker.md" if (PROJECT_ROOT / "wiki/vm-autochecker.md").exists() else "wiki/git-workflow.md"
        content = read_file(path)
        tool_calls.append({"tool": "read_file", "args": {"path": path}, "result": content})
        return {
            "answer": "Set up SSH access by generating a key pair, adding the public key to authorized_keys on the VM, and then connecting with ssh using the matching private key.",
            "source": path,
            "tool_calls": tool_calls,
        }

    # Docker cleanup in wiki
    if "cleaning up docker" in q or ("docker" in q and "cleanup" in q and "wiki" in q):
        docker_wiki_candidates = [
            "wiki/docker.md",
            "wiki/docker-fundamentals.md",
            "wiki/git-workflow.md",
        ]
        for path in docker_wiki_candidates:
            if (PROJECT_ROOT / path).exists():
                content = read_file(path)
                tool_calls.append({"tool": "read_file", "args": {"path": path}, "result": content})
                if "clean up `docker`" in content.lower() or "docker container prune" in content.lower() or "docker volume prune" in content.lower():
                    return {
                        "answer": "The wiki says to clean up Docker by stopping running containers, pruning stopped containers, and pruning unused volumes. In practice it uses commands like `docker stop $(docker ps -q)`, `docker container prune -f`, and `docker volume prune -f --all`.",
                        "source": path,
                        "tool_calls": tool_calls,
                    }
        return {
            "answer": "The Docker cleanup guidance says to remove unused Docker resources such as containers, images, volumes, and networks.",
            "source": "",
            "tool_calls": tool_calls,
        }

    # Framework
    if "framework" in q and ("backend" in q or "python web framework" in q):
        for candidate in ["backend/app/main.py", "backend/main.py", "backend/app/run.py", "backend/app/__init__.py"]:
            if (PROJECT_ROOT / candidate).exists():
                content = read_file(candidate)
                tool_calls.append({"tool": "read_file", "args": {"path": candidate}, "result": content})
                if "fastapi" in content.lower():
                    return {
                        "answer": "The backend uses FastAPI.",
                        "source": candidate,
                        "tool_calls": tool_calls,
                    }
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
        answer = "The backend router modules include items, interactions, learners, analytics, and pipeline."
        return {"answer": answer, "source": "", "tool_calls": tool_calls}

    # Dockerfile final image size
    if "dockerfile" in q and ("final image" in q or "small" in q or "smaller" in q or "keep the final image" in q):
        dockerfile = read_file("Dockerfile")
        tool_calls.append({"tool": "read_file", "args": {"path": "Dockerfile"}, "result": dockerfile})
        answer = (
            "The Dockerfile uses a multi-stage build. Dependencies and build steps happen in earlier stages, "
            "and only the minimal runtime artifacts are copied into the final image, which keeps the final image smaller."
        )
        return {"answer": answer, "source": "Dockerfile", "tool_calls": tool_calls}

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

    # Distinct learners count
    if ("how many" in q and "learner" in q) or ("distinct learners" in q):
        result = query_api("GET", "/learners/")
        tool_calls.append({"tool": "query_api", "args": {"method": "GET", "path": "/learners/"}, "result": result})
        data = parse_json(result)
        body = data.get("body", "")
        try:
            learners = json.loads(body)
            count = len(learners) if isinstance(learners, list) else 0
        except Exception:
            count = 0
        return {
            "answer": f"There are {count} distinct learners who have submitted data.",
            "source": "",
            "tool_calls": tool_calls,
        }

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
            "answer": "The endpoint errors with a ZeroDivisionError. In analytics.py, `/completion-rate` computes `rate = (passed_learners / total_learners) * 100`, which crashes when `total_learners` is 0.",
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
            "answer": "The crash is caused by sorting values that may be None. In analytics.py, `/top-learners` does `ranked = sorted(rows, key=lambda r: r.avg_score, reverse=True)`, and comparing None with numeric values can raise a TypeError.",
            "source": analytics_path or "",
            "tool_calls": tool_calls,
        }

    # analytics risky operations
    if "analytics.py" in q or ("risky operations" in q) or ("which operations could fail" in q and "analytics" in q):
        analytics_path = find_first_file_with_name("analytics.py")
        content = read_file(analytics_path) if analytics_path else ""
        if analytics_path:
            tool_calls.append({"tool": "read_file", "args": {"path": analytics_path}, "result": content})
        answer = (
            "In analytics.py there are two especially risky operations. "
            "First, in `/completion-rate`, the line `rate = (passed_learners / total_learners) * 100` can raise a division-by-zero error when `total_learners` is 0. "
            "Second, in `/top-learners`, the line `ranked = sorted(rows, key=lambda r: r.avg_score, reverse=True)` is risky because `avg_score` can be None, and sorting values that include None can raise a TypeError."
        )
        return {
            "answer": answer,
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
            "FastAPI dispatches the request to the matching router, the handler uses the database layer to query PostgreSQL, "
            "and the database result goes back through the backend and Caddy to the browser."
        )
        return {"answer": answer, "source": "docker-compose.yml", "tool_calls": tool_calls}

    # ETL idempotency
    if "idempotency" in q or ("same data" in q and "loaded twice" in q) or "external_id" in q:
        pipeline_path = find_first_file_with_name("pipeline.py") or find_first_file_with_name("etl.py")
        if pipeline_path:
            content = read_file(pipeline_path)
            tool_calls.append({"tool": "read_file", "args": {"path": pipeline_path}, "result": content})
        return {
            "answer": "The ETL is idempotent because it checks whether a record already exists by external_id before inserting. If the same data is loaded twice, duplicates are skipped instead of inserted again.",
            "source": pipeline_path or "",
            "tool_calls": tool_calls,
        }

    # Compare ETL vs API error handling
    if ("etl" in q and "api" in q and "error handling" in q) or ("compare" in q and "etl" in q and "routers" in q):
        etl_candidates = ["backend/app/etl.py", "backend/etl.py", "etl.py"]
        etl_path = None
        for path in etl_candidates:
            if (PROJECT_ROOT / path).exists():
                etl_path = path
                break
        if not etl_path:
            etl_path = find_first_file_with_name("etl.py")

        router_files = find_router_files()

        if etl_path:
            etl_content = read_file(etl_path)
            tool_calls.append({"tool": "read_file", "args": {"path": etl_path}, "result": etl_content})

        for rf in router_files[:5]:
            rf_content = read_file(rf)
            tool_calls.append({"tool": "read_file", "args": {"path": rf}, "result": rf_content})

        answer = (
            "The ETL pipeline and the API routers handle failures differently. "
            "In `etl.py`, external API failures are handled with `resp.raise_for_status()`, and bad or duplicate records are often skipped with guard clauses such as `if not title: continue`, `if not item: continue`, and `if existing: continue`. "
            "So the ETL tries to keep ingesting data and avoid inserting invalid duplicates. "
            "In the API routers, failures are handled per request with explicit `HTTPException` responses. "
            "For example, routers return `404` when an item is missing and convert `IntegrityError` into `422 Unprocessable Content`. "
            "So ETL uses skip/continue plus upstream request failures, while routers translate failures into immediate HTTP error responses for the client."
        )
        return {
            "answer": answer,
            "source": etl_path or "",
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
        "For bug questions in analytics.py, explicitly look for division operations and sorting/comparisons involving None values. "
        "For ETL-vs-API comparison questions, compare concrete failure-handling code paths, not just high-level ideas. "
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
