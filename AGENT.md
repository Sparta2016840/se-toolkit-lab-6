# Agent architecture

## Overview
This agent is a CLI documentation agent for the repository.

## Flow
1. Read the question from command line.
2. Read `LLM_API_KEY`, `LLM_API_BASE`, and `LLM_MODEL` from environment variables.
3. Send the question, system prompt, and tool schemas to an OpenAI-compatible chat completions API.
4. If the model returns tool calls:
   - execute `list_files` or `read_file`
   - append the tool result to the conversation
   - continue the loop
5. If the model returns normal text:
   - extract the answer
   - extract the `Source: ...` line
   - print JSON with `answer`, `source`, and `tool_calls`

## Tools
- `list_files(path)` lists files and directories relative to the project root.
- `read_file(path)` reads file contents relative to the project root.

## Security
Both tools resolve paths relative to the project root and reject paths outside it.

## Prompt strategy
The system prompt tells the model to:
- use `list_files` to discover wiki files
- use `read_file` to inspect relevant documentation
- include a source reference in the final answer
- keep answers concise
