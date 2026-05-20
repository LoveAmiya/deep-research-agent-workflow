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
- `SearcherAgent`: returns deterministic mock search results
- `ReaderAgent`: converts mock snippets into findings
- `WriterAgent`: synthesizes findings into a coherent report
- `CriticAgent`: performs deterministic structural checks
- `RedAgent`: raises rule-based review issues
- `BlueAgent`: applies rule-based revisions
- `SharedMemory`: stores intermediate artifacts
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

The current system uses mock search results and deterministic local logic. It does not implement real LLM calls, real web search, vector memory, concurrent DAG execution, LLM-as-Judge, or external benchmark downloads.
