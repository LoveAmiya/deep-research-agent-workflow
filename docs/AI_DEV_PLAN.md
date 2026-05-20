# AI Development Plan

This document defines the staged implementation plan for DeepResearchAgent.

## Phase 0: Project Skeleton

- Create repository structure
- Add architecture and phase documentation
- Add minimal schemas and placeholder agent base class
- Add example data and baseline tests

## Phase 1: Minimal Deep Research Pipeline

- Build a sequential research flow
- Support a research question input and a simple plan object
- Add placeholder search and reading steps without real external integration
- Generate a minimal report from deterministic local logic

## Phase 2: DAG Orchestrator

- Introduce DAG-based task modeling
- Add dependency-aware orchestration
- Define node execution contracts and execution tracing

## Phase 3: Multi-Agent Role Split

- Separate planner, searcher, reader, writer, and critic roles
- Define agent interfaces and handoff boundaries
- Support role-specific prompts and execution hooks

## Phase 4: Shared Memory

- Add a shared memory abstraction
- Store intermediate findings, references, and report state
- Support agent read and write access through controlled APIs

## Phase 5: Red-Blue Review

- Add adversarial review between generation and critique roles
- Track disagreements, revisions, and review outcomes
- Improve factual consistency and report quality

## Phase 6: Evaluation

- Add evaluation datasets, metrics, and reproducible runs
- Compare intermediate and final outputs
- Measure coverage, citation quality, and answer usefulness

## Phase 7: Documentation and Interview Materials

- Finalize developer documentation
- Add onboarding and extension guides
- Prepare architecture explanation and interview-oriented materials
