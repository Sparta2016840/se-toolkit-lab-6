# Agent architecture

Minimal CLI agent for Task 1.

## Flow
1. Read question from command line.
2. Read `LLM_API_KEY`, `LLM_API_BASE`, `LLM_MODEL` from environment variables.
3. Send OpenAI-compatible chat completion request.
4. Print JSON with the answer.
