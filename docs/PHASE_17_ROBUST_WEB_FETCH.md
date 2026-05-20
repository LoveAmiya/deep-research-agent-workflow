# Phase 17: Robust Web Fetch and Content Extraction

## Goal

Phase 17 adds a robust URL fetch and lightweight content extraction layer. The system can now fetch a URL into a normalized `WebFetchResult`, extract page title and readable text, record fetch metadata, and fall back without crashing the research pipeline.

## Search Providers vs Fetchers

Phase 16 improved search provider reliability: it decides which search provider returns URL candidates.

Phase 17 handles what happens after URLs are found: fetching each URL, detecting content type, extracting title and main text, cleaning text, truncating long content, and reporting fetch errors.

## Why Robust Fetch Matters

Deep research depends on evidence behind URLs, not just search snippets. Fetching and extracting readable text gives `ReaderAgent` stronger evidence while keeping the pipeline stable when pages fail, return unsupported content types, or contain noisy HTML.

## WebFetchResult

`WebFetchResult` contains:

- `url`
- `title`
- `text`
- `raw_content`
- `content_type`
- `status_code`
- `success`
- `error`
- `metadata`

Metadata includes elapsed time, attempts, final URL, content type, status code, error type, truncation state, original length, and final length.

## Fetchers

- `BaseWebFetcher`: shared fetch interface.
- `MockWebFetcher`: deterministic local fetcher for tests and default fallback.
- `HTTPWebFetcher`: standard-library HTTP/data URL fetcher with timeout, retry, content-type detection, and error metadata.

`MockWebFetcher` is used in tests so test runs never depend on real network access or API keys.

## Content Extraction

`search/content_extraction.py` implements:

- HTML title extraction
- removal of `script`, `style`, `nav`, `footer`, `header`, and similar noise blocks
- simple main/article/body text extraction
- HTML entity unescaping
- whitespace cleanup
- max-length truncation

This is intentionally lightweight and dependency-free. It is not production-grade semantic extraction.

## Current Non-Goals

- No JavaScript-rendered page execution.
- No Playwright, Selenium, or browser automation.
- No dynamic re-planning.
- No checkpoint/resume.
- No vector memory or context compression.
- No Bootstrap CI or Cohen's d.

## Acceptance Criteria

- `ReaderAgent` can use `web_fetcher` when available.
- Fetch success uses extracted page text as evidence.
- Fetch failure falls back to search snippets without crashing.
- Fetch metadata records successes, failures, errors, and extraction use.
- Unit tests cover mock fetch, local HTML extraction, unsupported content types, failure handling, and ReaderAgent fallback.
