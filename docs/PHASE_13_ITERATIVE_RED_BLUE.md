# Phase 13: Iterative Red-Blue Loop

## Goal

Upgrade the existing deterministic single-round Red/Blue review into an optional multi-round rule-based review and revision loop.

## Why Multi-Round Red-Blue

A single review pass can fix simple missing sections or citations, but some issues may remain after the first Blue revision. A bounded loop allows the system to retry review and repair while keeping execution deterministic and testable.

## RedBlueLoopRunner Responsibilities

- run `RedAgent` against the current report
- stop when Red passes if configured
- run `BlueAgent` to revise the report when issues exist
- carry the revised report into the next round
- track fixed and remaining issue IDs
- stop on configured convergence or oscillation conditions
- write a `red_blue_loop` item to `SharedMemory`

## Configuration

- `max_rounds`: hard cap on loop rounds
- `stop_on_pass`: stop immediately when Red passes
- `stop_if_no_improvement_rounds`: stop after repeated rounds without fewer remaining issues
- `enable_oscillation_detection`: stop when remaining issue signatures repeat

## Stop Conditions

The loop stops when:

- `RedAgent.passed=True` and `stop_on_pass=True`
- `max_rounds` is reached
- the remaining issue count does not improve for the configured number of rounds
- the same remaining issue ID set repeats
- RedAgent or BlueAgent returns an unsuccessful result

## Current Boundaries

This is not LLM-as-Judge, not complex adversarial training, not a scoring model, and not a persistent memory mechanism. It does not add new search or fetch capability.

## Acceptance Criteria

- single-round Red/Blue tests continue to pass
- loop runner handles pass, multi-round revision, max rounds, no improvement, and oscillation
- BlueAgent failure stops the loop without crashing
- optional pipeline flag can run the loop
- default pipeline remains single-round
- evaluation can report an iterative Red/Blue score when enabled per case
