# Phase 23: ResearchBench-mini Plus

## Goal

Phase 23 expands the local ResearchBench-mini evaluation into ResearchBench-mini Plus.

The Plus benchmark adds more deterministic cases, richer expected evidence/citation/section/keyword configuration, rule score aggregation, optional LLM-as-Judge aggregation, composite scores, domain and difficulty summaries, before/after comparison, Red-Blue comparison, and JSON/Markdown evaluation reports.

## Why ResearchBench-mini Plus

The original mini benchmark is useful for smoke testing the pipeline, but it has only a small set of cases and limited aggregation. A broader local benchmark gives a better deterministic signal across domains without pulling in external datasets or network-dependent validation.

## Phase 6 Limitations

Phase 6 checked section coverage, citations, findings, keywords, Red-Blue improvement, and memory completeness. It did not define a structured case schema, domain/difficulty summaries, composite scores, report files, or before/after comparison.

## Case Schema

`ResearchBenchCase` supports:

- `case_id`
- `domain`
- `question`
- `difficulty`
- `expected_sections`
- `expected_keywords`
- `expected_evidence_count`
- `expected_citation_count`
- `expected_source_types`
- `judge_focus`
- `tags`
- `metadata`

Legacy mini cases remain compatible through defaults and aliases such as `id`, `keywords`, `expected_min_findings`, and `expected_min_citations`.

## Rule Metrics

Rule scoring aggregates:

- section coverage
- keyword coverage
- evidence/finding count score
- citation count score
- citation grounding score
- finding coverage
- Red-Blue improvement score

`rule_score` is the arithmetic mean of these deterministic metrics.

## Optional Judge Score

LLM-as-Judge remains optional. When disabled, no judge call is made and composite score equals rule score. When enabled, the existing Phase 15 judge is used and its 1-5 overall score is normalized to 0-1.

## Composite Score

- Judge disabled: `composite_score = rule_score`
- Judge enabled: `composite_score = 0.7 * rule_score + 0.3 * judge_score`

If judge output is missing or fails, scoring falls back safely to the rule score.

## Comparison Design

`EvaluationComparison` compares baseline and candidate evaluation reports by case ID. It computes metric deltas, improved/regressed/unchanged case lists, domain-level deltas, and a deterministic text summary.

The comparison is descriptive only.

## Red-Blue Comparison

The evaluation layer can explicitly run Plus cases twice with Red-Blue disabled and enabled, then compare the resulting evaluation reports. This is opt-in and is not part of the default evaluation command.

## Current Non-Goals

- No Bootstrap confidence intervals.
- No Cohen's d.
- No p-values, t-tests, or statistical significance tests.
- No external benchmark downloads.
- No artificial annotation platform.
- No new LLM-as-Judge dimensions.
- No pipeline, agent, or DAG executor rewrite.

## Test Strategy

- Validate the new case schema and legacy compatibility.
- Validate Plus case count and domain coverage.
- Validate evidence, citation, rule, judge, and composite scoring.
- Validate evaluation comparison and Red-Blue comparison summaries.
- Keep default `python -m evaluation.run_eval` behavior compatible.
- Keep tests offline and deterministic.
