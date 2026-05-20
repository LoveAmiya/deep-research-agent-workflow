# Phase 1: Minimal Deep Research Pipeline

## Goal

Implement a minimal runnable multi-agent research pipeline that turns a research question into a markdown report using deterministic local logic.

## Pipeline Steps

1. User provides a `ResearchQuestion`
2. `PlannerAgent` generates a `ResearchPlan`
3. `SearcherAgent` returns mock `SearchResult` items for the plan
4. `ReaderAgent` converts search results into `Finding` items
5. `WriterAgent` converts findings into a markdown `ResearchReport`
6. `main.py` prints the final markdown report

## Not Included In Phase 1

- real LLM calls
- real network or web search
- DAG scheduling or concurrency
- shared memory
- red-blue review
- LLM-as-judge
- benchmark or evaluation framework
- heavy external dependencies

## Acceptance Criteria

- `python main.py` prints a markdown report
- The report includes title, `Background`, `Key Findings`, `Conclusion`, and `References`
- Planner, searcher, reader, and writer modules are implemented and testable
- Search remains fully mock-based and deterministic
- `python -m unittest discover -s tests` passes
