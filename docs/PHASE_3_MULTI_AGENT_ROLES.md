# Phase 3: Multi-Agent Role Split

## Goal

Strengthen multi-agent role boundaries by introducing a unified agent interface, explicit handoff objects, and a new `CriticAgent` for basic report review.

## Role Boundaries

- `PlannerAgent`: converts a `ResearchQuestion` into a `ResearchPlan`
- `SearcherAgent`: converts a `ResearchPlan` into mock `SearchResult` items
- `ReaderAgent`: converts search results into `Finding` items
- `WriterAgent`: converts question, plan, and findings into a `ResearchReport`
- `CriticAgent`: reviews the generated report for basic structural completeness

## BaseAgent, AgentContext, AgentResult

- `BaseAgent`: defines the common interface for all agent roles
- `AgentContext`: packages task id, inputs, and metadata for an agent invocation
- `AgentResult`: standardizes the return shape for all agents, including success state, output, error, and handoff metadata

## CriticAgent Responsibility

The `CriticAgent` performs a deterministic structural review of the generated report. It checks for:

- report title
- `Key Findings` section
- `References` section
- non-empty citations

It does not call any LLM and does not perform adversarial review.

## Not Included In Phase 3

- red-blue review
- LLM-as-judge
- real model-based critique
- scoring models
- shared memory
- concurrent orchestration

## Acceptance Criteria

- all agents implement `run(context: AgentContext) -> AgentResult`
- DAG pipeline includes `critic_task`
- `main.py` prints the final report and a critic review summary
- `CriticAgent` can detect missing report sections or citations
- existing Phase 1 and Phase 2 test coverage remains valid after minimal compatibility updates
- `python -m unittest discover -s tests` passes
