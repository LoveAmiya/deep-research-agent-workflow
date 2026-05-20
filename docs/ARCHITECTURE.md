# Architecture

DeepResearchAgent is a multi-agent research workflow prototype. The current implemented flow is:

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

## Component Responsibilities

- `ResearchQuestion`: the user-provided research task
- `PlannerAgent`: decomposes the task into actionable steps
- `DAGExecutor`: runs task nodes in dependency order
- `SearcherAgent`: returns deterministic mock search results by default, or optional tool-backed web search results
- `ReaderAgent`: converts snippets into findings by default, or optional fetched page text into findings
- `WriterAgent`: synthesizes findings into a coherent report, with optional LLM assistance
- `CriticAgent`: performs deterministic structural checks, with optional LLM notes
- `RedAgent`: raises rule-based review issues, with optional LLM notes
- `BlueAgent`: applies rule-based revisions, with optional LLM notes
- `SharedMemory`: stores intermediate artifacts
- `SearchTool` / `FetchTool`: optional integration points for web search and simple page retrieval
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

The current system uses mock search/fetch and deterministic local logic by default. Optional LLM calls and optional standard-library web search/fetch are available when configured, but the system does not implement production-grade webpage parsing, complete evidence grounding, vector memory, concurrent DAG execution, LLM-as-Judge, or external benchmark downloads.
