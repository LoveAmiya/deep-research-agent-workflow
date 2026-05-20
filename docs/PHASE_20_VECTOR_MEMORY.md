# Phase 20: Vector Memory / Evidence Memory Store

## Goal

Phase 20 adds a lightweight local Vector Memory Store for persisting and retrieving research artifacts produced during a run.

The store captures:

- evidence
- citation
- summary
- node_output
- failure

The purpose is to make evidence and node outputs reusable after the current DAG context ends, while keeping the implementation deterministic, local, and dependency-light.

## Scope

- Add local memory schemas for stored memory items and search results.
- Add a deterministic hash-based embedding provider for offline tests and demos.
- Add a SQLite-backed vector memory store using Python standard library `sqlite3`.
- Store embeddings as JSON and rank candidates with cosine similarity.
- Support filtering by `memory_type` and `run_id`.
- Add simple fingerprint-based deduplication helpers.
- Add integration helpers that can convert pipeline outputs, citation registry entries, traces, and failures into memory items.
- Keep the pipeline integration optional.

## Non-Goals

- No external vector database such as FAISS, Chroma, Milvus, or Qdrant.
- No real embedding API calls.
- No Phase 21 context compression.
- No L1/L2/L3 context hierarchy.
- No new Red-Blue review behavior.
- No LLM-as-Judge changes.
- No complex semantic contradiction detection.
- No multi-agent memory reasoning.
- No DAG executor rewrite.

## Module Design

- `memory/schema.py`
  - Defines `MemoryItem`, `MemorySearchResult`, memory type constants, and validation helpers.
- `memory/embeddings.py`
  - Defines `EmbeddingProvider` and deterministic `HashEmbeddingProvider`.
- `memory/dedup.py`
  - Defines text normalization and fingerprint helpers.
- `memory/vector_store.py`
  - Defines `SQLiteVectorMemoryStore`.
  - Uses `sqlite3` and stores vectors as JSON.
  - Computes cosine similarity in process.
- `memory/integration.py`
  - Defines helpers for collecting evidence, citations, summaries, node outputs, and failures from a pipeline result.

The existing in-memory `SharedMemory` remains unchanged.

## Acceptance Criteria

- Memory item schemas are explicit dataclasses.
- Hash embeddings are deterministic, fixed-dimension, and offline.
- SQLite vector memory can add, list, get, search, filter, delete by run, and close.
- Deduplication prevents duplicate persisted rows for the same fingerprint.
- Pipeline memory persistence is optional and does not change default behavior.
- Tests do not require network access, API keys, or external vector database services.
- Existing provider-based search, robust fetch, checkpoint/resume, and dynamic replan tests continue to pass.

## Test Command

```bash
python -m unittest discover -s tests
```
