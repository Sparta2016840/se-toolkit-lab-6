# Task 2 plan

## Goal
Extend the CLI agent into a documentation agent that can inspect the repository wiki using tool calling.

## Tools
- `list_files(path)`: list files/directories under a relative path inside the project root
- `read_file(path)`: read a file under a relative path inside the project root

## Security
Both tools must reject paths outside the project root and prevent `..` traversal.

## Agent loop
1. Send the user question and tool schemas to the LLM.
2. If the LLM returns tool calls, execute them.
3. Append tool results as `tool` messages.
4. Repeat until the model returns a final text answer or the agent reaches 10 tool calls.

## Output
Return JSON with:
- `answer`
- `source`
- `tool_calls`

## Tests
Add regression tests for:
- reading wiki content via `read_file`
- listing wiki files via `list_files`
