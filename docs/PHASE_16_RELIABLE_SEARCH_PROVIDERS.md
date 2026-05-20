# Phase 16: Reliable Web Search Providers

## Goal

Phase 16 upgrades the Phase 10 search layer from a single optional search tool into a provider-based search system. The objective is reliability: search can try providers in a configured order, record provider metadata, and fall back to deterministic mock results when real providers fail.

## Why This Phase Is Needed

Phase 10 introduced optional real web search and fetch, but a single lightweight HTML search path is fragile. Real search providers can fail because of network errors, parsing changes, missing API keys, timeouts, or rate limits. A provider registry keeps those failures contained and gives `SearcherAgent` a stable interface.

## SearchProvider Abstraction

`SearchProvider` implementations return a normalized `SearchProviderResponse`:

- `SearchProviderResult`: title, URL, snippet, provider name, rank, and metadata
- `SearchProviderResponse`: query, provider, results, success flag, error, and metadata
- `BaseSearchProvider`: common provider interface
- `MockSearchProvider`: deterministic local provider used by tests and fallback
- `DuckDuckGoSearchProvider`: wraps the lightweight DuckDuckGo HTML logic from Phase 10
- `BraveSearchProvider`, `SerpAPIProvider`, `TavilyProvider`: optional interface skeletons that fail safely without API keys

## Provider Fallback Strategy

`SearchProviderRegistry.search_with_fallback(...)` tries providers in `provider_order`.

The first provider with `success=True` and non-empty results is selected. If configured providers fail or return no results, the registry can fall back to `MockSearchProvider`.

Search metadata records:

- attempted providers
- selected provider
- whether fallback was used
- provider errors

## Testing Boundary

Unit tests use `MockSearchProvider` and fake failing providers. Tests do not require network access, external search accounts, or API keys.

## Current Non-Goals

- No complex webpage body extraction; Phase 10's simple fetch layer remains unchanged.
- No dynamic re-planning based on search failures.
- No vector memory, embeddings, or context compression.
- No production-grade source ranking or provider scoring.
- No API key values are stored in code or docs.

## Acceptance Criteria

- Search providers share a normalized result/response structure.
- `SearchProviderRegistry` supports registration, lookup, provider ordering, fallback, and trace metadata.
- `SearcherAgent` can use a provider registry when available.
- Existing mock search and deterministic fallback continue to work.
- Tests cover provider fallback without real network access.
