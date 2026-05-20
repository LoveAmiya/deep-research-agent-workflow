# Phase 9: LLM Client and Prompt System

## Goal

Add optional LLM calling capability and prompt templates while keeping deterministic local logic as the default execution path.

## LLMClient Responsibilities

- represent chat messages and responses
- provide a deterministic `MockLLMClient` for tests and local default runs
- provide an OpenAI-compatible HTTP client using only Python standard library
- raise `LLMClientError` for network, timeout, parsing, or response-shape failures

## Prompt System Responsibilities

Prompt templates live in `prompts/` and describe each LLM-capable role:

- planner
- writer
- critic
- red agent
- blue agent

Prompts are short, role-specific, and explicitly instruct the model not to invent citations.

## Default Test Behavior

Tests use `MockLLMClient` or fallback behavior. They do not require API keys, network access, or external services.

## Enable Real LLM Calls

Set environment variables before running `python main.py`:

```bash
set DEEP_RESEARCH_USE_LLM=1
set DEEP_RESEARCH_LLM_PROVIDER=openai_compatible
set DEEP_RESEARCH_LLM_MODEL=your-model-name
set DEEP_RESEARCH_LLM_API_KEY=your-api-key
set DEEP_RESEARCH_LLM_BASE_URL=https://api.openai.com/v1
set DEEP_RESEARCH_LLM_TIMEOUT_SECONDS=60
```

Do not commit API keys. If required fields are missing, the system falls back to `MockLLMClient`.

## Current Boundaries

Phase 9 does not implement:

- real web search
- webpage crawling
- evidence grounding
- async DAG execution
- multi-round Red/Blue review
- persistent memory
- LLM-as-Judge
