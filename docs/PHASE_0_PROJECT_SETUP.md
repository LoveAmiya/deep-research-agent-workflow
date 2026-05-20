# Phase 0: Project Setup

## Goal

Establish a clean, testable repository skeleton for DeepResearchAgent without implementing runtime research features.

## In Scope

- repository structure
- package boundaries
- architecture and development docs
- minimal dataclass schemas
- placeholder base agent class
- simple entrypoint
- example input file
- unit tests for schema initialization

## Out of Scope

- real LLM integration
- real web search
- DAG execution
- shared memory implementation
- red-blue review workflow
- judge-based evaluation
- benchmark integration
- heavy third-party dependencies

## Prohibited

- Implementing later phases early
- Modifying `.venv`
- Referencing the Clash Royale / `皇室战争` project
- Referencing `agentscope-doc-qa` project code
- Adding nonessential framework dependencies

## Acceptance Criteria

- All required files and directories exist
- `python main.py` prints the Phase 0 initialization message
- `python -m unittest discover -s tests` passes
- Schema classes can be instantiated in tests
- The repository clearly documents current scope and future phases
