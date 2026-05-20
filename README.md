# DeepResearchAgent

DeepResearchAgent is a multi-agent system for complex, open-ended research workflows. The long-term goal is to coordinate planning, evidence collection, synthesis, critique, and report generation in a structured research pipeline.

## Current Status

The repository is currently at Phase 0: Project Setup.

Phase 0 provides only:

- project directory skeleton
- architecture and development documentation
- minimal schema definitions
- a placeholder base agent abstraction
- a simple entrypoint
- example input data
- unit tests for core schema initialization

This phase does not include real LLM calls, online search, orchestration, memory systems, or evaluation pipelines.

## Run

```bash
python main.py
```

Expected output:

```text
DeepResearchAgent project initialized.
Current phase: Phase 0 project setup.
```

## Test

```bash
python -m unittest discover -s tests
```

## Planned Roadmap

- Phase 0: Project skeleton
- Phase 1: Minimal deep research pipeline
- Phase 2: DAG orchestrator
- Phase 3: Multi-agent role split
- Phase 4: Shared memory
- Phase 5: Red-Blue review
- Phase 6: Evaluation
- Phase 7: Documentation and interview materials
