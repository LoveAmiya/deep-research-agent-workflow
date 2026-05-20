# Architecture

DeepResearchAgent is a multi-agent research workflow prototype. The current implemented flow is:

```text
ResearchQuestion
  -> PlannerAgent
  -> DAGExecutor
  -> CheckpointStore
  -> DAGReplanner
  -> SearcherAgent
  -> SearchProviderRegistry
  -> ReaderAgent
  -> WebFetcher
  -> CitationRegistry
  -> WriterAgent
  -> CriticAgent
  -> RedAgent
  -> BlueAgent
  -> Final Report
  -> Evaluation
```

## Component Responsibilities

- `ResearchQuestion`: the user-provided research task
- `PlannerAgent`: decomposes the task into actionable steps
- `DAGExecutor`: runs task nodes in dependency order
- `AsyncDAGExecutor`: optional asyncio executor for dependency-ready concurrent task scheduling
- `CheckpointStore`: saves and loads node-level execution checkpoints for resume
- `DAGReplanner`: injects deterministic remedial nodes or force synthesis fallback after bounded replan decisions
- `SearcherAgent`: returns deterministic mock search results by default, or provider/tool-backed web search results when configured
- `SearchProviderRegistry`: coordinates ordered search providers, fallback, and provider trace metadata
- `ReaderAgent`: converts snippets into findings by default, or web-fetched/extracted page text into findings
- `WebFetcher`: fetches URLs into title, text, content type, status, error, and trace metadata
- `CitationRegistry`: stores `EvidenceSpan` and `Citation` records for the current run
- `WriterAgent`: synthesizes findings into a coherent report with `[C#]` citation markers, with optional LLM assistance
- `CriticAgent`: performs deterministic structural and citation grounding checks, with optional LLM notes
- `RedAgent`: raises rule-based structure, evidence, and citation review issues, with optional LLM notes
- `BlueAgent`: applies rule-based revisions including citation marker/reference repair, with optional LLM notes
- `RedBlueLoopRunner`: optional bounded multi-round rule-based Red/Blue review loop
- `SharedMemory`: stores intermediate artifacts
- `SearchProvider` / `SearchTool` / `WebFetcher` / `FetchTool`: optional integration points for web search and page retrieval
- `CitationValidator`: rule-checks report citation IDs, markers, and References URLs
- `Evaluation`: runs local JSONL cases and deterministic metrics

## Implemented DAG

```text
planner_task
  -> search_task
  -> reader_task
  -> writer_task
  -> critic_task
  -> red_review_task
  -> blue_revision_task
```

## Current Boundaries

The current system uses mock search/fetch and deterministic local logic by default. Optional LLM calls, optional provider-based web search and HTTP fetch, optional local asyncio DAG execution, checkpoint/resume, deterministic dynamic replan, and optional bounded iterative Red/Blue review are available when configured. Citation grounding is local and rule-based; the system does not implement vector memory, context compression, JavaScript-rendered page extraction, production-grade webpage parsing, semantic evidence verification, distributed execution, complex scoring, or external benchmark downloads.
