# Phase 2: DAG Orchestrator

## Goal

Introduce a lightweight DAG orchestrator so the Phase 1 research pipeline can run as a dependency-aware task graph instead of hard-coded sequential calls.

## Why A DAG Orchestrator

The research pipeline already has clear task boundaries:

- planner
- searcher
- reader
- writer

Representing these steps as graph nodes creates a cleaner execution model, makes dependencies explicit, and prepares the codebase for later orchestration features without introducing concurrency in this phase.

## Scope In Phase 2

Phase 2 adds:

- `TaskNode`
- `TaskGraph`
- `TaskState`
- `TraceRecorder`
- `DAGExecutor`
- a minimal research graph builder for planner, searcher, reader, and writer tasks

## What Phase 2 Does Not Do

- real LLM calls
- real network search
- concurrent execution
- `asyncio` or semaphore-based scheduling
- shared memory
- red-blue review
- critic agent
- judge-based evaluation
- benchmark integration

## Execution Model

Phase 2 only supports sequential topological execution:

1. validate the graph
2. sort nodes into a legal topological order
3. execute each task one by one
4. skip downstream tasks if a dependency fails
5. record execution traces in memory

## Component Responsibilities

- `TaskNode`: describes one executable task and its dependencies
- `TaskGraph`: stores nodes, validates dependencies, detects cycles, and produces execution order
- `TaskState`: defines lifecycle states such as `PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, and `SKIPPED`
- `TraceRecorder`: stores in-memory task lifecycle events
- `DAGExecutor`: executes handlers in topological order and returns outputs, states, and traces

## Acceptance Criteria

- `python main.py` runs the research pipeline through the DAG executor
- The final output is still a markdown `ResearchReport`
- Graph validation catches duplicate ids, missing dependencies, and cycles
- Failed tasks are marked `FAILED`
- Downstream tasks with failed dependencies are marked `SKIPPED`
- `python -m unittest discover -s tests` passes
