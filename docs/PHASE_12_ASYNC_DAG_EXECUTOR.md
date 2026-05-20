# Phase 12: Async DAG Executor

## Goal

Add an optional asyncio-based DAG executor that can run dependency-ready tasks concurrently while preserving the existing synchronous `DAGExecutor`.

## Why Add Instead Of Replace

The synchronous `DAGExecutor` is stable, simple, and covered by existing tests. `AsyncDAGExecutor` is additive so the project keeps a deterministic baseline while enabling concurrency experiments behind an explicit switch.

## Execution Model

`AsyncDAGExecutor` schedules a task only when all dependencies have succeeded. If any dependency fails or is skipped, the downstream task is marked `SKIPPED`.

The executor supports:

- async handlers
- sync handlers through `asyncio.to_thread`
- dependency-aware scheduling
- `RUNNING`, `SUCCESS`, `FAILED`, and `SKIPPED` traces
- error collection per task

## max_concurrency

An `asyncio.Semaphore` limits how many tasks may run at the same time. This is useful when a future graph has multiple independent search, read, or review tasks.

## Timeout

`task_timeout_seconds` wraps each task with `asyncio.wait_for`. A timed-out task is marked `FAILED`, and downstream dependent tasks are marked `SKIPPED`.

## Optional Demo

The default demo still uses the synchronous executor. To enable the async executor:

```bash
set DEEP_RESEARCH_USE_ASYNC_DAG=1
set DEEP_RESEARCH_DAG_MAX_CONCURRENCY=3
set DEEP_RESEARCH_DAG_TASK_TIMEOUT_SECONDS=30
python main.py
```

## Current Boundaries

Phase 12 does not implement a distributed task system, checkpoint/resume, persistent memory, multi-round Red/Blue review, LLM-as-Judge, or semantic evidence verification.

## Acceptance Criteria

- existing synchronous DAG tests continue to pass
- async and sync handlers can both run
- independent tasks can run concurrently
- `max_concurrency` limits parallelism
- timeout marks tasks `FAILED`
- dependency failures propagate as `SKIPPED`
- async research pipeline can complete without real network or real LLM calls
