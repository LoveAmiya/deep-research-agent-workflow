# Phase 22: Red-Blue Convergence / Oscillation Detection

## Goal

Phase 22 adds structured convergence and oscillation detection to the existing iterative Red-Blue loop.

The loop now records round snapshots, issue fingerprints, report hashes, Blue repair activity, convergence decisions, and a final loop summary. It can stop deterministically when the review converges, reaches the round cap, stops improving, oscillates, or Blue cannot continue fixing issues.

## Phase 13 Limitation

Phase 13 introduced a bounded iterative Red-Blue loop, but its stopping logic was mostly local counters and repeated remaining issue IDs. It did not provide a structured convergence model, stable issue fingerprints, report hashes, convergence scores, or a summary artifact that downstream tooling could inspect.

## Why Convergence Detection

Deep research reports can require multiple review/revision passes. The system needs an explicit answer to whether the loop is getting better, fully converged, stalled, or stopped for a bounded execution reason. A structured convergence decision makes the stop reason auditable and testable.

## Why Oscillation Detection

Some deterministic or LLM-assisted repair loops can alternate between known states. Detecting repeated issue fingerprint sets or report hashes prevents wasting rounds and records that the loop did not make stable progress.

## IssueFingerprint Design

`IssueFingerprint` normalizes issue type, severity, message, citation ID, and evidence ID into a stable SHA-256 fingerprint. It accepts dataclasses, dictionaries, and objects with compatible attributes, with fallbacks for missing fields.

## RoundSnapshot Design

`RedBlueRoundSnapshot` records:

- round index
- issue count
- issue fingerprints
- normalized report hash
- Blue action count
- fixed issue count
- remaining issue count
- Red pass status
- metadata

## ConvergenceDecision Design

`RedBlueConvergenceDecision` records:

- whether the loop should stop
- structured status
- human-readable reason
- convergence score
- oscillation flag
- repeated fingerprints
- metadata

## Stop Conditions

- `CONVERGED`: RedAgent reports no issues.
- `MAX_ROUNDS_REACHED`: configured round cap is reached.
- `NO_IMPROVEMENT`: issue count does not improve for configured patience.
- `OSCILLATION_DETECTED`: issue fingerprint sets or report hashes repeat in a short window.
- `BLUE_UNABLE_TO_FIX`: BlueAgent fails or performs no useful repair when issues remain.
- `ERROR`: RedAgent or loop execution fails unexpectedly.

## Test Strategy

- Unit-test issue text normalization and fingerprint stability.
- Unit-test report hash stability.
- Unit-test convergence decisions for converged, max rounds, no improvement, and oscillation.
- Unit-test RedBlueLoopRunner metadata, snapshots, summaries, and SharedMemory writes.
- Re-run checkpoint/resume, dynamic replan, vector memory, and context compression tests through the full suite.

## Current Non-Goals

- No Bootstrap confidence intervals.
- No Cohen's d.
- No ResearchBench expansion.
- No new LLM-as-Judge dimensions.
- No multi-judge voting.
- No RedAgent or BlueAgent rewrite.
- No WriterAgent or DAGExecutor rewrite.
