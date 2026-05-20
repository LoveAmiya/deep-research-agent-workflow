# Phase 4: Shared Memory

## Goal

Add a shared memory layer so agents can save and read intermediate outputs through a unified memory API during DAG execution.

## Why Shared Memory

The current pipeline already has explicit task handoffs, but those handoffs only flow through immediate DAG outputs. A shared memory layer gives the system a central place to retain plans, search results, findings, reports, and reviews for later inspection and future orchestration features.

## Core Responsibilities

- `MemoryItem`: the unit stored in shared memory
- `SharedMemory`: in-memory API for adding, deduplicating, and querying records
- `MemoryStore`: alias for the concrete in-memory shared memory implementation

## Scope In Phase 4

Phase 4 only provides:

- in-process memory storage
- simple item creation and retrieval
- type and agent-based filtering
- simple deduplication based on exact serialized content match
- agent write integration through `AgentContext.memory`

## Not Included In Phase 4

- vector databases
- embeddings
- semantic search
- complex memory compression
- conflict resolution
- long-term memory systems
- cross-run persistence

## Acceptance Criteria

- agents can write intermediate artifacts into a shared memory object
- duplicate records with the same type, source agent, and content are not re-added
- `main.py` prints a shared memory summary after pipeline execution
- the pipeline stores `plan`, `search_results`, `findings`, `report`, and `review`
- `python -m unittest discover -s tests` passes
