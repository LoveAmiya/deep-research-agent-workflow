# Architecture

DeepResearchAgent is a multi-agent research workflow prototype. The current implemented flow is:

```text
ResearchQuestion
  -> PlannerAgent
  -> DAGExecutor
  -> SearcherAgent
  -> ReaderAgent
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
- `SearcherAgent`: returns deterministic mock search results by default, or optional tool-backed web search results
- `ReaderAgent`: converts snippets into findings by default, or optional fetched page text into findings
- `CitationRegistry`: stores `EvidenceSpan` and `Citation` records for the current run
- `WriterAgent`: synthesizes findings into a coherent report with `[C#]` citation markers, with optional LLM assistance
- `CriticAgent`: performs deterministic structural and citation grounding checks, with optional LLM notes
- `RedAgent`: raises rule-based structure, evidence, and citation review issues, with optional LLM notes
- `BlueAgent`: applies rule-based revisions including citation marker/reference repair, with optional LLM notes
- `RedBlueLoopRunner`: optional bounded multi-round rule-based Red/Blue review loop
- `SharedMemory`: stores intermediate artifacts
- `SearchTool` / `FetchTool`: optional integration points for web search and simple page retrieval
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

The current system uses mock search/fetch and deterministic local logic by default. Optional LLM calls, optional standard-library web search/fetch, optional local asyncio DAG execution, and optional bounded iterative Red/Blue review are available when configured. Citation grounding is local and rule-based; the system does not implement production-grade webpage parsing, semantic evidence verification, vector memory, distributed execution, checkpoint/resume, LLM-as-Judge, complex scoring, or external benchmark downloads.
