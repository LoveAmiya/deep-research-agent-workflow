# Interview Notes

## What is this project?

DeepResearchAgent is a multi-agent research workflow prototype for complex open-ended research tasks. It takes a research question, builds a plan, creates mock search results, extracts findings, writes a markdown report, reviews it, performs one rule-based Red/Blue revision pass, stores intermediate artifacts in SharedMemory, and evaluates outputs with local rule metrics.

The current version is deterministic and local. It does not call real LLMs and does not perform real web search.

## How is it different from the first Clash Royale project?

The Clash Royale project was a Skill-based single-agent project focused on one domain. DeepResearchAgent is a multi-agent workflow project. Its emphasis is role separation, DAG task orchestration, shared memory, review/revision, and evaluation.

This project should not be described as reusing Clash Royale code. It is a separate research-system prototype.

## Why is this a multi-agent project?

The system separates the research workflow into distinct agents with explicit responsibilities and handoffs:

- `PlannerAgent` plans the research task
- `SearcherAgent` creates mock search results
- `ReaderAgent` extracts findings
- `WriterAgent` writes the report
- `CriticAgent` checks report structure
- `RedAgent` raises rule-based review issues
- `BlueAgent` revises fixable issues

Each agent receives an `AgentContext` and returns an `AgentResult`.

## What does PlannerAgent do?

`PlannerAgent` reads a `ResearchQuestion` from `AgentContext.inputs["question"]` and returns a `ResearchPlan`. The plan contains sub-questions, mock search queries, and expected sections.

It does not call an LLM.

## What does SearcherAgent do?

`SearcherAgent` reads a `ResearchPlan` and returns deterministic `SearchResult` objects. These are mock results with `mock://source/...` URLs.

It does not use the internet.

## What does ReaderAgent do?

`ReaderAgent` reads mock search results and converts each snippet into a `Finding`. It also applies a simple local truncation helper for findings.

It does not summarize with an LLM.

## What does WriterAgent do?

`WriterAgent` reads the question, plan, and findings, then produces a `ResearchReport` with markdown sections:

- Background
- Key Findings
- Conclusion
- References

## What does CriticAgent do?

`CriticAgent` performs a deterministic structural check. It verifies that the report has a title, Key Findings, References, and non-empty citations.

It is not LLM-as-Judge.

## What do RedAgent and BlueAgent do?

`RedAgent` performs one rule-based review pass. It checks missing sections, citation gaps, finding coverage, and short reports.

`BlueAgent` performs one rule-based revision pass. It can add missing Background, Key Findings, Conclusion, References, and collect citations from findings.

This is not multi-round adversarial debate.

## What does the DAG Orchestrator do?

The DAG Orchestrator represents the workflow as dependent tasks:

```text
planner_task -> search_task -> reader_task -> writer_task -> critic_task -> red_review_task -> blue_revision_task
```

`DAGExecutor` validates the graph, topologically sorts tasks, runs them sequentially, records trace events, and skips downstream tasks if dependencies fail.

It does not run tasks concurrently.

## What does SharedMemory do?

`SharedMemory` stores intermediate artifacts in memory:

- plan
- search_results
- findings
- report
- review
- red_review
- blue_revision

It supports simple add/get/list operations and exact deduplication. It is not vector memory and does not use embeddings.

## How does Evaluation work?

Evaluation uses local JSONL cases in `evaluation/cases.jsonl`. Each case defines a question, expected sections, minimum findings, minimum citations, and keywords.

Rule metrics compute:

- section coverage
- citation coverage
- finding coverage
- keyword coverage
- Red/Blue improvement
- memory completeness

No external benchmark is downloaded.

## Why does the first version not use real search?

The first version isolates orchestration, interfaces, memory, review, and evaluation before adding network behavior. Mock search makes tests deterministic and keeps the project runnable without API keys or network access.

## Why does the first version not use real LLMs?

The current goal is to validate architecture and data flow. Real LLM calls would introduce external dependencies, latency, cost, nondeterminism, and prompt-engineering work before the pipeline contracts are stable.

## What are the current limitations?

- no real LLM calls
- no real web search
- no concurrent DAG execution
- no vector database
- no embeddings
- no long-term memory
- no LLM-as-Judge
- no complex ResearchBench
- no multi-round Red/Blue convergence
- mock evidence only

## How would this extend to real deep research?

The current interfaces are designed so later phases can replace deterministic components with real implementations:

- replace `SearcherAgent` mock output with search API retrieval
- add `ReaderAgent` source parsing and evidence extraction
- add LLM-backed planning, synthesis, and critique behind the same `AgentContext` / `AgentResult` interface
- persist SharedMemory
- add richer evaluation and human review
- add concurrency only after DAG behavior remains stable
