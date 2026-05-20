# Phase 19: Dynamic Replan for Failed / Insufficient DAG Runs

## Goal

Phase 19 adds deterministic rule-based dynamic replan for DAG runs. When a node fails, times out, has insufficient evidence, fails citation validation, or hits fetch failures, the executor can generate a bounded remedial action and continue instead of immediately failing the whole run.

## Checkpoint/Resume vs Dynamic Replan

Checkpoint/resume recovers previous successful work from disk and skips completed nodes. It does not change the graph.

Dynamic replan changes the active DAG during the run by injecting remedial nodes or falling back to force synthesis. It is execution recovery, not semantic memory.

## Why Replan Matters

Deep research workflows are long-running and depend on search, fetch, reading, synthesis, and review steps. A single failed search or reader step should not always invalidate the whole run. A bounded replan layer lets the system attempt deterministic recovery while keeping failure modes explicit.

## Replan Triggers

The current trigger types are:

- `node_failed`
- `node_timeout`
- `insufficient_evidence`
- `citation_validation_failed`
- `fetch_failed`
- `batch_failure`

## ReplanTrigger

`ReplanTrigger` contains:

- `run_id`
- `node_id`
- `trigger_type`
- `reason`
- `failed_agent`
- `failed_node_type`
- `error`
- `metadata`

## ReplanDecision

`ReplanDecision` contains:

- `should_replan`
- `action`
- `new_nodes`
- `new_edges`
- `reason`
- `metadata`

Supported actions include:

- `retry_node`
- `add_followup_search`
- `add_alternative_reader`
- `skip_optional_node`
- `force_synthesis`
- `abort`

## RuleBasedReplanPolicy

The default policy is deterministic and does not call an LLM.

Rules:

- Search failure adds an alternative deterministic search node.
- Reader/fetch failure adds an alternative reader node that can rely on snippet fallback.
- Insufficient evidence adds a follow-up search node.
- Citation validation failure adds a citation repair/follow-up search node.
- Writer failure uses force synthesis.
- Exceeding the replan attempt limit uses force synthesis by default.
- Too many failed nodes uses force synthesis by default.

## DAGReplanner

`DAGReplanner` applies a `ReplanDecision` to the current `TaskGraph`.

It:

- injects new nodes
- injects or replaces edges when requested
- avoids duplicate node IDs
- marks generated nodes with `generated_by_replan=true`
- records parent failed node ID, replan attempt, action, and reason
- returns force synthesis or abort status without raising uncaught exceptions

## Attempt Limit

`max_replan_attempts` prevents unbounded graph mutation. If the limit is exhausted, the system uses force synthesis by default so the run can return an explicit partial result rather than loop forever.

## Force Synthesis

Force synthesis creates a controlled partial output for the failed node. The metadata records:

- `partial_report=true`
- `force_synthesis_used=true`
- failed nodes
- evidence limitations

This is not pretending the run fully succeeded; it records that evidence or execution was incomplete.

## Current Non-Goals

- No vector memory.
- No context compression.
- No complex LLM planner.
- No Bootstrap CI or Cohen's d.
- No Red/Blue convergence changes.

## Acceptance Criteria

- Replan policy decisions are deterministic and unit-tested.
- Failed nodes can inject remedial nodes.
- Replanned DAGs continue executing.
- Replan attempts are bounded.
- Force synthesis fallback works.
- Replan metadata is available in execution results and checkpoints.
- Tests do not require real network access or API keys.
