# Phase 21: Context Compression

## Goal

Phase 21 adds a deterministic context compression module that turns large research artifacts into a shorter, citation-preserving context for writer, synthesizer, or reviewer use.

The module compresses evidence, web text, citations, summaries, node outputs, and vector memory items without calling a real LLM, external embedding API, network service, or external vector database.

## Scope

- Add `EvidenceUnit`, `CompressedContext`, and `CompressionConfig` schemas.
- Add a dependency-free token estimator.
- Add lightweight TextRank for sentence ranking using standard library data structures.
- Add a `ContextCompressor` with L1-L2-L3 compression.
- Add integration helpers for converting node outputs and Phase 20 memory objects into evidence units.
- Keep compression optional and independent from DAG execution, checkpoint/resume, replan, and vector memory storage.

## L1 / L2 / L3 Compression

- L1: embedding coarse filtering with Phase 20 `HashEmbeddingProvider`.
- L2: sentence-level TextRank reranking using lexical overlap and query weighting.
- L3: source-preserving output assembly with short quotes, citations, source URLs, titles, and metadata.

## Non-Goals

- No Phase 22 behavior.
- No Red-Blue convergence changes.
- No oscillation detection changes.
- No LLM-as-Judge changes.
- No Bootstrap CI or Cohen's d.
- No complex multi-round reflection.
- No external vector database.
- No real embedding API.
- No real LLM dependency.
- No checkpoint format changes.
- No DAG executor rewrite.

## Module Design

- `compression/schema.py`
  - `EvidenceUnit`
  - `CompressedContext`
  - `CompressionConfig`
- `compression/token_counter.py`
  - `estimate_tokens`
- `compression/text_rank.py`
  - `split_sentences`
  - `rank_sentences`
- `compression/compressor.py`
  - `ContextCompressor`
- `compression/integration.py`
  - node output and memory conversion helpers
  - writer/reviewer compression helpers

## Acceptance Criteria

- Empty evidence returns a warning instead of raising.
- Duplicate evidence is removed before ranking.
- L1 selects query-relevant evidence using deterministic hash embeddings.
- L2 ranks and selects important sentences without third-party graph libraries.
- L3 preserves quote, citation, source URL, title, and metadata.
- Compressed token estimate does not exceed the original token estimate.
- Phase 18 checkpoint/resume tests still pass.
- Phase 19 dynamic replan tests still pass.
- Phase 20 vector memory tests still pass.

## Test Command

```bash
python -m unittest discover -s tests
```
