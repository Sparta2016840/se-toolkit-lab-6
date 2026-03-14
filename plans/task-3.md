# Task 3 plan

## Goal
Extend the documentation agent into a system agent that can query the running backend API.

## New tool
Add `query_api(method, path, body?)` as a function-calling tool schema.

## Authentication
Read `LMS_API_KEY` from environment variables and send it with backend API requests.
Read `AGENT_API_BASE_URL` from environment variables, defaulting to `http://localhost:42002`.

## Tool strategy
- Use `read_file` for wiki and source code questions.
- Use `list_files` for discovering source files.
- Use `query_api` for runtime facts and data-dependent answers.

## Benchmark plan
Run `uv run run_eval.py`.
Record the first score and fix failures one by one:
- wrong tool choice -> improve the system prompt and tool descriptions
- wrong API path -> improve prompt examples
- poor diagnosis -> combine query_api + read_file
