# Demo Guide

## Run Tests

```bash
python -m unittest discover -s tests
```

This verifies schema objects, agents, DAG execution, SharedMemory, Red/Blue review, and evaluation utilities.

## Run Demo

```bash
python main.py
```

The demo runs the full local pipeline:

```text
ResearchQuestion
-> PlannerAgent
-> SearcherAgent
-> ReaderAgent
-> WriterAgent
-> CriticAgent
-> RedAgent
-> BlueAgent
-> Final Report
```

The final report is generated from mock search results and deterministic local logic.

## Run Evaluation

```bash
python -m evaluation.run_eval
```

This runs the ResearchBench-mini style cases from `evaluation/cases.jsonl` and prints average rule metric scores.

## How To Read main.py Output

`main.py` prints:

- final markdown report
- CriticAgent result
- RedAgent issue count
- BlueAgent fixed and remaining issue IDs
- SharedMemory item counts

The report is a demo artifact, not a real web-researched answer.

## How To Read Eval Summary

The eval summary reports averages across local cases:

- `average_section_coverage`: expected markdown sections present
- `average_citation_coverage`: enough citations for the case target
- `average_finding_coverage`: enough findings for the case target
- `average_keyword_coverage`: expected keywords appear in report text
- `average_red_blue_improvement`: BlueAgent addressed RedAgent issues or no issues were found
- `average_memory_completeness`: expected memory item types were stored

## Recommended Demo Narrative

Start with the pipeline:

```text
Question -> Plan -> Mock Search -> Findings -> Report -> Critic -> Red Review -> Blue Revision -> Evaluation
```

Then show that each stage has a concrete module and tests.

Then explain the boundary: this is a deterministic local architecture prototype, not a production research engine yet.

## If Asked Whether It Really Searches The Web

Answer directly: no. The current `SearcherAgent` returns mock search results with `mock://source/...` URLs. That is intentional for Phase 1 to Phase 7 because the focus is pipeline architecture, agent handoffs, memory, review, and evaluation.

Real search can be added later behind the existing `SearcherAgent` interface.
