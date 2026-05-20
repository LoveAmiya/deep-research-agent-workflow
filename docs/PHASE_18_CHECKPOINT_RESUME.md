# Phase 18: Checkpoint / Resume for DAG Runs

## Goal

Phase 18 adds checkpoint and resume support for DAG runs. If a run is interrupted or partially failed, the system can load the previous checkpoint, skip completed nodes with saved outputs, and re-run failed, pending, or incomplete nodes.

## Persistent Run Store vs Checkpoint/Resume

The Phase 14 SQLite run store saves completed run artifacts for inspection, replay, and summary export.

Checkpoint/resume is execution-oriented. It stores node-level status and output while the DAG is running so execution can continue from the latest usable state. It is not a semantic memory system.

## Why Resume Matters

Long-horizon deep research workflows can involve many search, fetch, read, write, and review tasks. Re-running everything after a transient failure wastes time and can duplicate external calls. Checkpoint/resume keeps completed work reusable while preserving deterministic task graph semantics.

## RunCheckpoint

`RunCheckpoint` contains:

- `run_id`
- `task`
- `status`
- `created_at`
- `updated_at`
- `node_checkpoints`
- `completed_node_ids`
- `failed_node_ids`
- `pending_node_ids`
- `metadata`

## NodeCheckpoint

`NodeCheckpoint` contains:

- `node_id`
- `status`
- `agent_name`
- `input_hash`
- `output`
- `error`
- `started_at`
- `finished_at`
- `metadata`

Outputs are serialized with lightweight type metadata for `AgentResult` and core dataclasses so downstream nodes can resume with compatible objects.

## When Checkpoints Are Saved

The DAG executor saves after each node state transition:

- `RUNNING` before a handler starts
- `SUCCESS` after output is available
- `FAILED` when a handler raises or returns unsuccessful agent output
- `SKIPPED` when dependencies failed or were skipped

The final run status is saved after DAG completion.

## Resume Behavior

On resume, a node is skipped only when its checkpoint status is `SUCCESS` and output exists. The saved output is deserialized and injected into the executor outputs map.

Nodes with `FAILED`, `PENDING`, `SKIPPED`, missing checkpoints, or missing output are executed again if their dependencies are successful.

## Storage

`JSONCheckpointStore` writes one JSON file per run under `runs/checkpoints/` by default. Writes use a temporary file followed by atomic rename to avoid half-written checkpoint files. Corrupted checkpoint files return `None` instead of crashing the pipeline.

## Current Non-Goals

- No dynamic re-planning.
- No vector memory or embeddings.
- No context compression.
- No cross-run semantic memory.
- No database requirement for checkpoints.
- No Bootstrap CI or Cohen's d.

## Acceptance Criteria

- Checkpoints can be saved and loaded from JSON.
- Corrupted checkpoint files do not crash execution.
- Completed nodes with output are skipped during resume.
- Failed, pending, skipped, missing, or incomplete nodes are re-executed.
- Resume metadata records skipped and re-executed node counts.
- `main.py --resume <run_id>` can load a checkpoint when available.
- Tests remain deterministic and do not require network or API keys.
