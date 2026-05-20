# Project Summary

## One-Sentence Summary

DeepResearchAgent is a deterministic-by-default multi-agent research workflow prototype with optional LLM assistance, optional web search/fetch, citation grounding, sync/async DAG orchestration, shared memory, bounded rule-based Red/Blue review/revision, and local evaluation.

## Tech Stack

- Python standard library
- `dataclasses`
- `unittest`
- JSONL evaluation cases
- optional OpenAI-compatible HTTP LLM client using Python standard library
- optional DuckDuckGo HTML search and simple webpage fetch using Python standard library
- no external runtime dependencies in the current phase

## Core Modules

- `core/schema.py`: data contracts for questions, plans, findings, reports, and review results
- `agents/`: planner, searcher, reader, writer, critic, red, and blue agents
- `agents/red_blue_loop.py`: optional bounded iterative Red/Blue runner
- `orchestrator/`: DAG nodes, graph validation, sync/async executors, trace recording, and pipeline runner
- `memory/`: in-memory shared memory store and simple finding truncation helper
- `tools/`: mock and optional web search/fetch tools
- `tools/citation_tool.py`: in-memory evidence/citation registry and validator
- `evaluation/`: JSONL cases, rule metrics, and eval runner
- `tests/`: coverage for schema, agents, DAG, memory, Red/Blue review, and evaluation

## Execution Flow

```text
ResearchQuestion
-> PlannerAgent
-> DAGExecutor
-> SearcherAgent
-> ReaderAgent
-> WriterAgent
-> CriticAgent
-> RedAgent
-> BlueAgent
-> Final Report
-> Evaluation
```

## Core Highlights

- multi-agent role separation through `AgentContext` and `AgentResult`
- DAG task graph with dependency validation and sequential topological execution
- optional asyncio DAG executor with max concurrency, timeout, and failure propagation
- SharedMemory for intermediate artifacts
- rule-based CriticAgent checks
- single-round RedAgent / BlueAgent review and revision
- optional iterative Red/Blue loop with convergence and oscillation guards
- ResearchBench-mini local evaluation with deterministic rule metrics
- mock search pipeline that keeps runs reproducible and dependency-free
- optional prompt system and LLM client with deterministic fallback
- optional SearchTool and FetchTool integration with deterministic fallback
- evidence spans, citation IDs, `[C#]` report markers, and rule-based citation validation

## Current Boundaries

- web search and fetch are optional lightweight integrations, not production-grade retrieval
- citation grounding is rule-based and does not perform semantic fact verification
- async DAG execution is local asyncio scheduling, not distributed execution
- no vector database or embeddings
- no long-term memory
- no LLM-as-Judge
- no complex scoring or adversarial training
- no complex benchmark framework

## Future Extensions

- stronger search provider integration behind `SearcherAgent`
- LLM-backed planning, reading, writing, and critique behind existing agent interfaces
- source parsing and citation grounding
- persistent memory store
- richer evaluation datasets and human review
- concurrency after DAG correctness is stable

## Resume-Friendly Description

Built DeepResearchAgent, a Python multi-agent research workflow prototype with role-specific agents, DAG task orchestration, shared in-memory state, optional LLM and web search/fetch integrations, rule-based Red/Blue review, and ResearchBench-mini style local evaluation. Implemented deterministic mock defaults with unit-tested schemas, agent handoffs, memory writes, traceable execution, fallback behavior, and reproducible evaluation metrics.
