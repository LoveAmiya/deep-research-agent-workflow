# AI Development Plan

This document defines the staged implementation plan for DeepResearchAgent.

## Phase 0: Project Skeleton

- Create repository structure
- Add architecture and phase documentation
- Add minimal schemas and placeholder agent base class
- Add example data and baseline tests
- Status: completed

## Phase 1: Minimal Deep Research Pipeline

- Build a sequential research flow
- Support a research question input and a simple plan object
- Add placeholder search and reading steps without real external integration
- Generate a minimal report from deterministic local logic
- Status: completed

## Phase 2: DAG Orchestrator

- Introduce DAG-based task modeling
- Add dependency-aware orchestration
- Define node execution contracts and execution tracing
- Status: completed with sequential topological execution

## Phase 3: Multi-Agent Role Split

- Separate planner, searcher, reader, writer, and critic roles
- Define agent interfaces and handoff boundaries
- Support role-specific prompts and execution hooks
- Status: completed with `AgentContext`, `AgentResult`, and `CriticAgent`

## Phase 4: Shared Memory

- Add a shared memory abstraction
- Store intermediate findings, references, and report state
- Support agent read and write access through controlled APIs
- Status: completed with in-memory storage and simple deduplication

## Phase 5: Red-Blue Review

- Add adversarial review between generation and critique roles
- Track disagreements, revisions, and review outcomes
- Improve factual consistency and report quality
- Status: completed as a deterministic single-round rule-based review/revision pass

## Phase 6: Evaluation

- Add evaluation datasets, metrics, and reproducible runs
- Compare intermediate and final outputs
- Measure coverage, citation quality, and answer usefulness
- Status: completed with local ResearchBench-mini JSONL cases and rule metrics

## Phase 7: Documentation and Interview Materials

- Finalize developer documentation
- Add onboarding and extension guides
- Prepare architecture explanation and interview-oriented materials
- Status: completed as documentation-only finalization

## Phase 8: Final Acceptance and Packaging

- Run final tests, evaluation, and demo commands
- Check documentation consistency against the implemented code
- Remove generated caches and temporary artifacts from the package
- Create the final distributable zip archive
- Status: completed prototype backup

## Phase 9: LLM Client and Prompt System

- Add LLM configuration loading from environment variables
- Add `MockLLMClient` for deterministic tests and fallback
- Add OpenAI-compatible HTTP client using Python standard library
- Add prompt templates for Planner, Writer, Critic, Red, and Blue agents
- Allow selected agents to optionally call LLM and fall back to deterministic local logic
- Status: completed

## Phase 10: Real Web Search and Fetch

- Add `SearchTool` and `FetchTool` interfaces
- Keep `MockSearchTool` and `MockFetchTool` as deterministic defaults
- Add optional DuckDuckGo HTML search using Python standard library
- Add optional simple webpage fetching and text extraction using Python standard library
- Let SearcherAgent and ReaderAgent fall back safely when real search/fetch fails
- Status: completed

## Phase 11: Evidence Grounding and Citation

- Add `EvidenceSpan`, `Citation`, and `GroundedFinding` data structures
- Add in-memory `CitationRegistry` and rule-based `CitationValidator`
- Let ReaderAgent create evidence/citation IDs for findings
- Let WriterAgent generate `[C1]` citation markers and registry-backed References
- Extend Critic/Red/Blue and evaluation with citation grounding checks
- Status: completed

## Phase 12: Async DAG Executor

- Add an optional asyncio-based `AsyncDAGExecutor`
- Support dependency-aware scheduling after prerequisites succeed
- Support sync and async handlers
- Add `max_concurrency`, per-task timeout, async traces, and failure propagation
- Keep the synchronous `DAGExecutor` as the default stable path
- Status: completed

## Phase 13: Iterative Red-Blue Loop

- Add `RedBlueLoopRunner` for bounded rule-based multi-round review/revision
- Add loop config, round result, and loop result dataclasses
- Stop on Red pass, max rounds, no improvement, repeated issue signatures, or agent failure
- Keep single-round Red/Blue behavior as the default path
- Add optional evaluation metric for iterative Red/Blue score
- Status: completed

## Phase 14: Persistent Run Store

- Add SQLite-based run-level persistence
- Save complete pipeline results, report markdown, traces, memory items, reviews, and citation validation
- Support loading runs, listing recent runs, and exporting summaries
- Keep persistence disabled by default
- Status: completed

## Phase 15: Optional LLM-as-Judge Mini Evaluation

- Add optional judge rubric and result structures
- Add judge prompt and JSON parser with safe fallback
- Evaluate answer relevance, factual consistency, citation quality, completeness, and clarity
- Keep rule metrics as the default evaluation path
- Use mock/fallback judge behavior in tests
- Status: completed

## Phase 16: Reliable Search Providers

- Add normalized search provider result and response structures
- Add provider registry with ordered fallback and trace metadata
- Keep `MockSearchProvider` as the deterministic default and fallback
- Wrap Phase 10 DuckDuckGo HTML search behind a provider interface
- Add optional Brave, SerpAPI, and Tavily provider skeletons that fail safely without keys
- Let `SearcherAgent` use provider registry when available while preserving old fallback paths
- Status: completed

## Phase 17: Robust Web Fetch and Content Extraction

- Add normalized `WebFetchResult`
- Add `BaseWebFetcher`, `MockWebFetcher`, and `HTTPWebFetcher`
- Add lightweight HTML title and main text extraction
- Track timeout, retry, content type, truncation, and error metadata
- Let `ReaderAgent` use web fetchers before falling back to snippets
- Keep tests deterministic without real network access
- Status: completed

## Phase 18: Checkpoint / Resume for DAG Runs

- Add `RunCheckpoint` and `NodeCheckpoint`
- Add `CheckpointStore` and `JSONCheckpointStore`
- Save checkpoints on node state transitions
- Resume from completed node outputs when available
- Re-execute failed, pending, skipped, missing, or incomplete nodes
- Expose `main.py --resume <run_id>` for demo resume
- Status: completed

## Phase 19: Dynamic Replan

- Add `ReplanTrigger` and `ReplanDecision`
- Add deterministic `RuleBasedReplanPolicy`
- Add `DAGReplanner` for remedial node injection
- Trigger replan on node failure, timeout, evidence/citation insufficiency, or fetch failure
- Bound replan attempts and support force synthesis fallback
- Store replan metadata in execution results and checkpoints
- Status: completed

## Phase 20: Vector Memory / Evidence Memory Store

- Add local memory schemas for evidence, citation, summary, node output, and failure records
- Add deterministic hash embeddings for offline tests and demos
- Add SQLite-backed vector memory storage and cosine similarity search
- Add optional integration helpers for persisting pipeline artifacts
- Keep external vector databases and real embedding APIs out of scope
- Status: completed

## Phase 21: Context Compression

- Add deterministic context compression for evidence, citation, summary, node output, and memory item inputs
- Add L1 embedding coarse filtering with local hash embeddings
- Add lightweight TextRank sentence reranking without external dependencies
- Preserve citations, source URLs, titles, quotes, and metadata in compressed contexts
- Keep compression optional and separate from checkpoint, replan, and vector memory storage
- Status: current phase

## Current Implementation Boundary

The project remains deterministic by default and uses mock search/fetch. It can optionally call an OpenAI-compatible LLM, optional provider-based web search and HTTP fetch, optional local asyncio DAG execution, node-level checkpoint/resume, deterministic dynamic replan, optional bounded iterative Red/Blue review, optional SQLite run persistence, optional local SQLite vector memory, optional local context compression, and optional LLM-as-Judge mini evaluation when configured. Citation grounding is rule-based through local evidence/citation IDs; the project does not perform JavaScript-rendered page extraction, production-grade semantic extraction, semantic fact verification, distributed execution, multi-judge voting, statistical significance testing, complex benchmark evaluation, external vector database retrieval, or real embedding API calls.
