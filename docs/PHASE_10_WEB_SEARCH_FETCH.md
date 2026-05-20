# Phase 10: Real Web Search + Fetch

## Goal

Add optional real web search and webpage fetch capabilities while keeping mock search and deterministic fallback as the default behavior.

## SearchTool Responsibilities

- expose a common `search(query, max_results)` interface
- provide `MockSearchTool` for deterministic local runs and tests
- provide `DuckDuckGoHTMLSearchTool` for optional standard-library web search
- fail with clear `SearchToolError` when real search cannot produce usable results

## FetchTool Responsibilities

- expose a common `fetch(url)` interface
- provide `MockFetchTool` for deterministic local runs and tests
- provide `SimpleFetchTool` for optional standard-library HTML/text fetching
- return `PageContent(fetched=False, error=...)` instead of crashing the pipeline on fetch failure

## Default Behavior

The default project behavior is still mock search and deterministic local logic. Unit tests do not require real network access or API keys.

## Enable Real Web Search

Set environment variables before running the demo, or put them in a local `.env` file. `main.py` loads `.env` explicitly; library calls do not load it unless requested.

```bash
set DEEP_RESEARCH_USE_WEB_SEARCH=1
set DEEP_RESEARCH_SEARCH_PROVIDER=duckduckgo_html
set DEEP_RESEARCH_SEARCH_MAX_RESULTS=5
set DEEP_RESEARCH_SEARCH_TIMEOUT_SECONDS=15
set DEEP_RESEARCH_USER_AGENT=your-user-agent
```

If real search or fetch fails, `SearcherAgent` and `ReaderAgent` fall back to mock snippets rather than failing the whole DAG.

## Current Boundaries

Phase 10 does not implement production-grade evidence grounding, citation verification, robust webpage extraction, async DAG execution, persistent memory, multi-round Red/Blue review, or LLM-as-Judge.

## Acceptance Criteria

- mock search and mock fetch remain deterministic
- optional real search and fetch use only Python standard library
- `SearcherAgent` can use `search_tool` and fallback safely
- `ReaderAgent` can use `fetch_tool` and fallback to snippets safely
- `main.py` can enable search/fetch through environment configuration
- all tests, local eval, and demo commands continue to pass without real network access
