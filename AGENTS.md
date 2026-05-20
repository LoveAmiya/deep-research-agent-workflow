# DeepResearchAgent Rules

DeepResearchAgent is a multi-agent deep research project for complex open-ended research tasks.

## Working Rules

- Work only in the current repository root.
- Implement only the active phase.
- For Phase 0, create project skeleton, documentation, and minimal placeholder code only.
- Keep all code testable with `unittest`.
- Prefer small, explicit, dependency-light modules.

## Prohibited During Phase 0

- Do not implement real LLM calls.
- Do not implement real network search.
- Do not implement DAG concurrency.
- Do not implement Shared Memory.
- Do not implement Red-Blue review.
- Do not implement LLM-as-Judge.
- Do not implement ResearchBench.
- Do not add complex dependencies.
- Do not create a nested `deep-research-agent/deep-research-agent` directory.
- Do not modify `.venv`.
- Do not reference the Clash Royale / `皇室战争` project.
- Do not reference `agentscope-doc-qa` project code.
- Do not pull in later-phase features early.

## Test Command

```bash
python -m unittest discover -s tests
```

## Phase Discipline

- Phase 0: project skeleton only
- Later phases must be added incrementally
- Each implementation pass should clearly state the current phase and its scope
