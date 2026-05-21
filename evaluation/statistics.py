from dataclasses import asdict, dataclass, field
import math
import random
from typing import Any


@dataclass
class BootstrapCI:
    metric_name: str
    mean: float
    lower: float
    upper: float
    confidence_level: float
    num_bootstrap: int
    sample_size: int
    seed: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EffectSizeSummary:
    metric_name: str
    effect_size_type: str
    value: float | None
    interpretation: str
    sample_size: int
    mean_delta: float | None
    std_delta: float | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StatisticalComparison:
    baseline_name: str
    candidate_name: str
    metric_name: str
    sample_size: int
    baseline_mean: float
    candidate_mean: float
    mean_delta: float
    baseline_ci: BootstrapCI
    candidate_ci: BootstrapCI
    delta_ci: BootstrapCI
    effect_size: EffectSizeSummary
    improved: bool
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
    skipped_cases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def bootstrap_mean_ci(
    values: list[float],
    metric_name: str,
    confidence_level: float = 0.95,
    num_bootstrap: int = 1000,
    seed: int = 42,
) -> BootstrapCI:
    resolved_values = _coerce_float_list(values, "values")
    _validate_bootstrap_inputs(resolved_values, confidence_level, num_bootstrap)
    mean_value = _mean(resolved_values)
    if len(resolved_values) == 1:
        return BootstrapCI(
            metric_name=metric_name,
            mean=mean_value,
            lower=mean_value,
            upper=mean_value,
            confidence_level=confidence_level,
            num_bootstrap=num_bootstrap,
            sample_size=1,
            seed=seed,
            metadata={"method": "percentile", "single_sample": True},
        )
    bootstrap_means = _bootstrap_means(resolved_values, num_bootstrap, seed)
    lower, upper = _percentile_bounds(bootstrap_means, confidence_level)
    return BootstrapCI(
        metric_name=metric_name,
        mean=mean_value,
        lower=lower,
        upper=upper,
        confidence_level=confidence_level,
        num_bootstrap=num_bootstrap,
        sample_size=len(resolved_values),
        seed=seed,
        metadata={"method": "percentile"},
    )


def paired_bootstrap_delta_ci(
    baseline_values: list[float],
    candidate_values: list[float],
    metric_name: str,
    confidence_level: float = 0.95,
    num_bootstrap: int = 1000,
    seed: int = 42,
) -> BootstrapCI:
    baseline = _coerce_float_list(baseline_values, "baseline_values")
    candidate = _coerce_float_list(candidate_values, "candidate_values")
    if len(baseline) != len(candidate):
        raise ValueError("baseline_values and candidate_values must have the same length")
    deltas = [candidate_value - baseline_value for baseline_value, candidate_value in zip(baseline, candidate)]
    _validate_bootstrap_inputs(deltas, confidence_level, num_bootstrap)
    mean_delta = _mean(deltas)
    if len(deltas) == 1:
        return BootstrapCI(
            metric_name=metric_name,
            mean=mean_delta,
            lower=mean_delta,
            upper=mean_delta,
            confidence_level=confidence_level,
            num_bootstrap=num_bootstrap,
            sample_size=1,
            seed=seed,
            metadata={"method": "paired_percentile", "single_sample": True},
        )
    bootstrap_means = _bootstrap_means(deltas, num_bootstrap, seed)
    lower, upper = _percentile_bounds(bootstrap_means, confidence_level)
    return BootstrapCI(
        metric_name=metric_name,
        mean=mean_delta,
        lower=lower,
        upper=upper,
        confidence_level=confidence_level,
        num_bootstrap=num_bootstrap,
        sample_size=len(deltas),
        seed=seed,
        metadata={"method": "paired_percentile"},
    )


def paired_cohens_d(
    baseline_values: list[float],
    candidate_values: list[float],
    metric_name: str,
) -> EffectSizeSummary:
    baseline = _coerce_float_list(baseline_values, "baseline_values")
    candidate = _coerce_float_list(candidate_values, "candidate_values")
    if len(baseline) != len(candidate):
        raise ValueError("baseline_values and candidate_values must have the same length")
    if not baseline:
        raise ValueError("paired effect size requires at least one paired sample")
    deltas = [candidate_value - baseline_value for baseline_value, candidate_value in zip(baseline, candidate)]
    mean_delta = _mean(deltas)
    if len(deltas) < 2:
        return EffectSizeSummary(
            metric_name=metric_name,
            effect_size_type="cohens_dz",
            value=None,
            interpretation="insufficient_samples",
            sample_size=len(deltas),
            mean_delta=mean_delta,
            std_delta=None,
            metadata={},
        )
    std_delta = _sample_std(deltas)
    if abs(std_delta) < 1e-12:
        if abs(mean_delta) < 1e-12:
            return EffectSizeSummary(
                metric_name=metric_name,
                effect_size_type="cohens_dz",
                value=0.0,
                interpretation="none",
                sample_size=len(deltas),
                mean_delta=mean_delta,
                std_delta=std_delta,
                metadata={"zero_variance": True},
            )
        return EffectSizeSummary(
            metric_name=metric_name,
            effect_size_type="cohens_dz",
            value=None,
            interpretation="zero_variance",
            sample_size=len(deltas),
            mean_delta=mean_delta,
            std_delta=std_delta,
            metadata={"zero_variance": True},
        )
    value = mean_delta / std_delta
    return EffectSizeSummary(
        metric_name=metric_name,
        effect_size_type="cohens_dz",
        value=value,
        interpretation=interpret_effect_size(value),
        sample_size=len(deltas),
        mean_delta=mean_delta,
        std_delta=std_delta,
        metadata={},
    )


def interpret_effect_size(value: float | None) -> str:
    if value is None:
        return "insufficient_samples"
    magnitude = abs(value)
    if magnitude < 0.2:
        return "negligible"
    if magnitude < 0.5:
        return "small"
    if magnitude < 0.8:
        return "medium"
    return "large"


def build_statistical_comparison(
    baseline_result: dict[str, Any],
    candidate_result: dict[str, Any],
    metric_name: str = "composite_score",
    confidence_level: float = 0.95,
    num_bootstrap: int = 1000,
    seed: int = 42,
    baseline_name: str = "baseline",
    candidate_name: str = "candidate",
) -> StatisticalComparison:
    baseline_cases = _case_map(baseline_result)
    candidate_cases = _case_map(candidate_result)
    shared_case_ids = sorted(set(baseline_cases) & set(candidate_cases))
    baseline_values = []
    candidate_values = []
    compared_case_ids = []
    skipped_cases = []
    for case_id in shared_case_ids:
        baseline_value = _extract_numeric_metric(baseline_cases[case_id], metric_name)
        candidate_value = _extract_numeric_metric(candidate_cases[case_id], metric_name)
        if baseline_value is None or candidate_value is None:
            skipped_cases.append(case_id)
            continue
        baseline_values.append(baseline_value)
        candidate_values.append(candidate_value)
        compared_case_ids.append(case_id)
    if not compared_case_ids:
        raise ValueError(f"No comparable cases found for metric '{metric_name}'")

    baseline_ci = bootstrap_mean_ci(
        baseline_values,
        metric_name=metric_name,
        confidence_level=confidence_level,
        num_bootstrap=num_bootstrap,
        seed=seed,
    )
    candidate_ci = bootstrap_mean_ci(
        candidate_values,
        metric_name=metric_name,
        confidence_level=confidence_level,
        num_bootstrap=num_bootstrap,
        seed=seed,
    )
    delta_ci = paired_bootstrap_delta_ci(
        baseline_values,
        candidate_values,
        metric_name=f"{metric_name}_delta",
        confidence_level=confidence_level,
        num_bootstrap=num_bootstrap,
        seed=seed,
    )
    effect_size = paired_cohens_d(baseline_values, candidate_values, metric_name=metric_name)
    baseline_mean = _mean(baseline_values)
    candidate_mean = _mean(candidate_values)
    mean_delta = candidate_mean - baseline_mean
    summary = (
        f"{candidate_name} vs {baseline_name} on {metric_name}: "
        f"mean delta {mean_delta:.3f}; "
        f"{confidence_level:.0%} paired bootstrap CI "
        f"[{delta_ci.lower:.3f}, {delta_ci.upper:.3f}]; "
        f"effect size {effect_size.interpretation}."
    )
    return StatisticalComparison(
        baseline_name=baseline_name,
        candidate_name=candidate_name,
        metric_name=metric_name,
        sample_size=len(compared_case_ids),
        baseline_mean=baseline_mean,
        candidate_mean=candidate_mean,
        mean_delta=mean_delta,
        baseline_ci=baseline_ci,
        candidate_ci=candidate_ci,
        delta_ci=delta_ci,
        effect_size=effect_size,
        improved=mean_delta > 0.0,
        summary=summary,
        metadata={
            "baseline_case_count": len(baseline_cases),
            "candidate_case_count": len(candidate_cases),
            "shared_case_count": len(shared_case_ids),
            "compared_case_ids": compared_case_ids,
            "skipped_cases": skipped_cases,
            "skipped_case_count": len(skipped_cases),
            "non_significance_test": True,
        },
        skipped_cases=skipped_cases,
    )


def _case_map(eval_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(result.get("case_id")): result
        for result in eval_result.get("results", [])
        if result.get("case_id") is not None
    }


def _extract_numeric_metric(case_result: dict[str, Any], metric_name: str) -> float | None:
    if metric_name in case_result and case_result.get(metric_name) is not None:
        return _coerce_optional_float(case_result.get(metric_name))
    metrics = case_result.get("metrics") or {}
    if isinstance(metrics, dict) and metric_name in metrics and metrics.get(metric_name) is not None:
        return _coerce_optional_float(metrics.get(metric_name))
    return None


def _coerce_optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_float_list(values: list[float], name: str) -> list[float]:
    resolved = []
    for value in values:
        try:
            resolved.append(float(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} contains a non-numeric value: {value}") from exc
    return resolved


def _validate_bootstrap_inputs(values: list[float], confidence_level: float, num_bootstrap: int) -> None:
    if not values:
        raise ValueError("bootstrap CI requires at least one value")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")
    if num_bootstrap < 1:
        raise ValueError("num_bootstrap must be at least 1")


def _bootstrap_means(values: list[float], num_bootstrap: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    sample_size = len(values)
    means = []
    for _ in range(num_bootstrap):
        total = 0.0
        for _ in range(sample_size):
            total += values[rng.randrange(sample_size)]
        means.append(total / sample_size)
    means.sort()
    return means


def _percentile_bounds(sorted_values: list[float], confidence_level: float) -> tuple[float, float]:
    alpha = 1.0 - confidence_level
    lower = _percentile(sorted_values, alpha / 2.0)
    upper = _percentile(sorted_values, 1.0 - (alpha / 2.0))
    return lower, upper


def _percentile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        raise ValueError("percentile requires at least one value")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = quantile * (len(sorted_values) - 1)
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return sorted_values[lower_index]
    weight = position - lower_index
    return (sorted_values[lower_index] * (1.0 - weight)) + (sorted_values[upper_index] * weight)


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean requires at least one value")
    return sum(values) / len(values)


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = _mean(values)
    variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)
