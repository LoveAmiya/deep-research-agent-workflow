# Target Architecture

DeepResearchAgent is intended to evolve into a multi-agent research system with the following high-level flow:

```text
Research Question
  -> PlannerAgent
  -> DAG Orchestrator
  -> SearcherAgent / ReaderAgent
  -> Shared Memory
  -> WriterAgent
  -> CriticAgent
  -> Final Report
```

## Component Intent

- `Research Question`: the user-provided research task
- `PlannerAgent`: decomposes the task into actionable steps
- `DAG Orchestrator`: schedules research tasks with explicit dependencies
- `SearcherAgent / ReaderAgent`: gather and interpret source material
- `Shared Memory`: stores plans, findings, evidence, and revisions
- `WriterAgent`: synthesizes findings into a coherent report
- `CriticAgent`: reviews report quality, logic, and evidence support
- `Final Report`: the final user-facing research output

## Phase 0 Limitation

Phase 0 does not implement the full architecture above. It only creates documentation, package structure, and minimal placeholder code so later phases can be developed on a clean foundation.
