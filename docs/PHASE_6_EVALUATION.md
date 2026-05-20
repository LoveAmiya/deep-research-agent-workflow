# Phase 6: Evaluation

## Goal

Add a local, reproducible evaluation layer for the full DeepResearchAgent pipeline using ResearchBench-mini style JSONL cases and deterministic rule metrics.

## Case Format

Each case in `evaluation/cases.jsonl` is one JSON object:

```json
{
  "id": "case_001",
  "question": "What are the main factors that affect open-source LLM adoption in enterprises?",
  "expected_sections": ["Background", "Key Findings", "Conclusion", "References"],
  "expected_min_findings": 3,
  "expected_min_citations": 3,
  "keywords": ["open-source", "LLM", "enterprise"],
  "optional": false
}
```

## Rule Metrics

- `section_coverage`: expected report section coverage
- `citation_coverage`: citation count against minimum target
- `finding_coverage`: finding count against minimum target
- `keyword_coverage`: keyword presence in final markdown
- `red_blue_improvement`: whether Blue revision addressed Red review issues
- `memory_completeness`: whether all expected memory artifact types exist

## Why No LLM-as-Judge

Phase 6 is intended to be local, deterministic, and dependency-free. LLM-as-Judge would introduce model variance, external calls, and prompt calibration work that belongs in a later evaluation phase.

## Run Eval

```bash
python -m evaluation.run_eval
```

## Acceptance Criteria

- at least five local JSONL cases are available
- every metric is implemented with deterministic Python logic
- `run_eval` can execute all non-optional cases locally
- summary output includes averages and failed case count
- `python -m unittest discover -s tests` passes
