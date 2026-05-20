# Phase 15: Optional LLM-as-Judge Mini Evaluation

## Goal

Add an optional LLM-as-Judge evaluation layer alongside the existing deterministic rule metrics.

## Why Add It

Rule metrics can check sections, citation counts, grounding, and memory completeness, but they cannot assess report quality in a more holistic way. A bounded judge prompt can provide a qualitative mini-evaluation while keeping the default evaluation local and deterministic.

## Judge Dimensions

The judge scores five dimensions from 1 to 5:

- `answer_relevance`: whether the report answers the question
- `factual_consistency`: whether claims are consistent with provided findings and evidence
- `citation_quality`: whether citations are useful and grounded
- `completeness`: whether the report covers the main expected aspects
- `clarity`: whether the report is clear and readable

The judge also returns `overall_score`, strengths, weaknesses, suggested improvements, and `passed`.

## Default Behavior

LLM judge is disabled by default. Normal tests and normal `python -m evaluation.run_eval` do not call a real LLM.

Tests use `MockLLMClient` or fallback behavior so they do not require network access or API keys.

## Enable LLM Judge

```powershell
$env:DEEP_RESEARCH_USE_LLM_JUDGE="1"
python -m evaluation.run_eval
```

To force deterministic mock judge mode:

```powershell
$env:DEEP_RESEARCH_USE_LLM_JUDGE="1"
$env:DEEP_RESEARCH_LLM_JUDGE_USE_MOCK="1"
python -m evaluation.run_eval
```

Optional threshold:

```powershell
$env:DEEP_RESEARCH_LLM_JUDGE_PASS_THRESHOLD="3.5"
```

## Current Boundaries

Phase 15 does not implement multi-judge voting, multi-model judging, Bootstrap confidence intervals, Cohen's d, complex ResearchBench, artificial labeling datasets, or external fact verification.

The judge must evaluate only the provided question, report, findings, citations, and citation validation.

## Acceptance Criteria

- rule evaluation remains unchanged by default
- judge mode is enabled only by environment variable
- mock judge mode is deterministic
- invalid LLM JSON falls back safely
- LLM call failure falls back safely
- judge summary metrics appear only when judge results exist
