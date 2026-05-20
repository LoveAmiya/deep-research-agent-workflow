# Phase 14: Persistent Run Store

## Goal

Add SQLite-based run-level persistence so completed research runs can be saved, listed, loaded, and summarized for replay/debug workflows.

## Why Run-Level Persistence

`SharedMemory` is in-process and disappears after execution. A persistent run store keeps the full run payload, report markdown, traces, memory snapshots, citation validation, and review outputs for later inspection.

This is not long-term semantic memory.

## SQLiteRunStore Responsibilities

- initialize a local SQLite database
- save `RunRecord` objects
- save complete pipeline results through `save_run_result`
- load a run by `run_id`
- list recent runs
- export a compact run summary
- serialize unknown objects safely instead of failing on non-JSON values

## Saved Artifacts

The payload can include:

- question
- report and final report
- findings
- critic review
- red review
- blue revision
- optional red-blue loop result
- memory items
- traces
- citation validation
- configuration objects represented as JSON-friendly values

The summary includes report length, finding count, citation counts, citation validation status, memory item count, Red/Blue issue counts, loop rounds, and success.

## Enable Run Saving

```powershell
$env:DEEP_RESEARCH_SAVE_RUN="1"
$env:DEEP_RESEARCH_RUN_STORE_PATH="runs/deep_research_runs.sqlite3"
python main.py
```

By default run saving is disabled.

## Current Boundaries

Phase 14 does not implement embeddings, vector databases, cross-task semantic retrieval, long-term user profiles, checkpoint/resume, dynamic replanning, or LLM-as-Judge.

## Acceptance Criteria

- SQLite database initializes automatically
- run records can be saved, loaded, listed, and summarized
- pipeline results can be persisted without real LLM or network access
- default `main.py` behavior does not save runs
- `runs/`, `*.sqlite3`, and `*.db` are ignored by git
- all tests, eval, and demo commands pass
