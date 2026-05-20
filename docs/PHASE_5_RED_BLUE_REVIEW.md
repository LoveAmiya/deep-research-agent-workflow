# Phase 5: Red-Blue Review

## Goal

Add a deterministic single-round Red/Blue review mechanism so the pipeline can detect structural report issues and apply simple rule-based fixes.

## Agent Responsibilities

- `RedAgent`: reviews the report and raises structured issues
- `BlueAgent`: revises the report based on the Red review result

## Current Review Mode

Phase 5 only implements rule-based review. It does not call any LLM, does not perform semantic reasoning, and does not run multi-round adversarial convergence.

## Data Structures

- `ReviewIssue`: one concrete issue raised during Red review
- `RedReviewResult`: summary of the Red review pass and all issues
- `BlueRevisionResult`: revised report plus fixed and remaining issue tracking

## Scope In Phase 5

- single-round `red_review_task`
- single-round `blue_revision_task`
- shared memory writes for red and blue outputs
- final report output based on the revised report

## Not Included In Phase 5

- multi-round red/blue loops
- score convergence
- oscillation detection
- LLM-as-judge
- benchmark evaluation

## Acceptance Criteria

- `RedAgent` can detect missing sections, citation gaps, weak evidence coverage, and short reports
- `BlueAgent` can add missing sections and citations when fixable
- DAG includes `red_review_task` and `blue_revision_task`
- `main.py` prints final revised report plus red and blue summaries
- shared memory stores `red_review` and `blue_revision`
- `python -m unittest discover -s tests` passes
