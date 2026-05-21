# Phase 24: Statistical Evaluation

## Goal

Phase 24 adds lightweight statistical evaluation on top of the Phase 23 ResearchBench-mini Plus comparison layer.

It supports bootstrap confidence intervals for evaluation scores, paired bootstrap confidence intervals for score deltas, and paired Cohen's d effect size summaries. The implementation is deterministic, dependency-free, and optional.

## Why Statistical Evaluation

Phase 23 can say whether a candidate evaluation report is better or worse than a baseline by comparing average scores and case-level deltas. That is useful, but it does not show uncertainty around those averages or the magnitude of paired changes across cases.

Phase 24 adds enough statistical context to make before/after summaries more informative without turning the project into a full statistical testing framework.

## Phase 23 Comparison Limitations

Phase 23 comparison is descriptive:

- average rule/composite deltas
- improved, regressed, and unchanged cases
- domain-level deltas
- Red-Blue enabled/disabled comparison

It does not compute confidence intervals, paired uncertainty over deltas, or effect size.

## Bootstrap CI

`bootstrap_mean_ci` estimates a confidence interval for the mean of one metric.

The algorithm:

1. Use the observed metric values as the empirical sample.
2. Resample `n` values with replacement, where `n` is the original sample size.
3. Compute the resampled mean.
4. Repeat for `num_bootstrap` iterations.
5. Sort resampled means and take percentile bounds.

For a 95% confidence interval, the implementation uses the 2.5% and 97.5% percentile bounds.

## Paired Bootstrap Delta CI

`paired_bootstrap_delta_ci` estimates uncertainty around the mean candidate-minus-baseline delta.

The resampling unit is the paired case:

```text
delta_i = candidate_i - baseline_i
```

Each bootstrap sample resamples these paired deltas with replacement and computes the mean delta. This preserves the case-level pairing from Phase 23 comparison.

## Cohen's d / Paired Effect Size

Phase 24 implements paired Cohen's d, also called Cohen's dz:

```text
mean_delta = mean(candidate_i - baseline_i)
std_delta = sample_standard_deviation(candidate_i - baseline_i)
cohens_dz = mean_delta / std_delta
```

Interpretation uses common heuristic thresholds:

- `abs(d) < 0.2`: negligible
- `0.2 <= abs(d) < 0.5`: small
- `0.5 <= abs(d) < 0.8`: medium
- `abs(d) >= 0.8`: large

These labels are descriptive heuristics. They are not a statistical significance claim.

## Small Samples and Zero Variance

- Empty samples raise a clear `ValueError` at the statistical API boundary.
- One-sample bootstrap CI returns `lower = mean = upper`.
- Effect size with fewer than two paired samples returns `value = None` and `interpretation = insufficient_samples`.
- If paired deltas have zero variance and mean delta is zero, effect size is `0.0` with `interpretation = none`.
- If paired deltas have zero variance and mean delta is nonzero, effect size returns `value = None` with `interpretation = zero_variance`.

## Why No p-value / t-test

Phase 24 intentionally does not implement p-values, t-tests, or formal significance testing. The benchmark is small, deterministic, and local. Confidence intervals and effect sizes are enough for the current before/after evaluation workflow without implying stronger statistical claims.

## CLI Usage

Default evaluation remains unchanged:

```bash
python -m evaluation.run_eval
```

ResearchBench-mini Plus remains unchanged:

```bash
python -m evaluation.run_eval --bench plus
```

Statistical comparison is opt-in:

```bash
python -m evaluation.run_eval --compare baseline.json candidate.json --stats
```

Optional parameters:

```bash
python -m evaluation.run_eval --compare baseline.json candidate.json --stats --stats-metric composite_score --num-bootstrap 1000 --confidence-level 0.95 --seed 42
```

Red-Blue comparison can also include statistics:

```bash
python -m evaluation.run_eval --bench plus --compare-red-blue --stats
```

## Report Output

JSON and Markdown reports can include `statistical_summary` when `--stats` is used with comparison output.

The summary includes:

- metric name
- baseline mean
- candidate mean
- mean delta
- baseline CI
- candidate CI
- paired delta CI
- effect size
- sample size
- skipped cases
- caveat that the result is not a p-value or t-test

## Test Strategy

- Unit-test deterministic bootstrap output.
- Unit-test single-sample CI handling.
- Unit-test paired bootstrap delta CI.
- Unit-test length mismatch errors.
- Unit-test paired Cohen's d and zero-variance handling.
- Unit-test effect size interpretation.
- Unit-test `StatisticalComparison` JSON serialization.
- Unit-test case ID alignment and skipped metrics.
- Re-run default `evaluation.run_eval` and ResearchBench-mini Plus to confirm backward compatibility.

## Current Non-Goals

- No p-values.
- No t-tests.
- No statistical significance testing.
- No scipy, numpy, or pandas dependency.
- No ResearchBench expansion.
- No LLM judge changes.
- No pipeline, agent, or DAG executor changes.
