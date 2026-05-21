from dataclasses import asdict, dataclass, field
from typing import Any

from evaluation.statistics import StatisticalComparison, build_statistical_comparison


@dataclass
class EvaluationComparison:
    baseline_name: str
    candidate_name: str
    case_count: int
    metric_deltas: dict[str, float]
    improved_cases: list[str]
    regressed_cases: list[str]
    unchanged_cases: list[str]
    domain_deltas: dict[str, dict[str, float]]
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
    statistical_summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compare_evaluation_results(
    baseline_result: dict[str, Any],
    candidate_result: dict[str, Any],
    baseline_name: str = "baseline",
    candidate_name: str = "candidate",
    include_statistics: bool = False,
    stats_metric_name: str = "composite_score",
    confidence_level: float = 0.95,
    num_bootstrap: int = 1000,
    seed: int = 42,
) -> EvaluationComparison:
    baseline_cases = _case_map(baseline_result)
    candidate_cases = _case_map(candidate_result)
    shared_case_ids = sorted(set(baseline_cases) & set(candidate_cases))
    improved_cases = []
    regressed_cases = []
    unchanged_cases = []
    for case_id in shared_case_ids:
        delta = _metric(candidate_cases[case_id], "composite_score") - _metric(baseline_cases[case_id], "composite_score")
        if delta > 0.000001:
            improved_cases.append(case_id)
        elif delta < -0.000001:
            regressed_cases.append(case_id)
        else:
            unchanged_cases.append(case_id)
    metric_deltas = {
        "rule_score_delta": _average_delta(baseline_cases, candidate_cases, shared_case_ids, "rule_score"),
        "composite_score_delta": _average_delta(baseline_cases, candidate_cases, shared_case_ids, "composite_score"),
        "citation_coverage_delta": _average_delta(baseline_cases, candidate_cases, shared_case_ids, "citation_count_score"),
        "evidence_count_delta": _average_delta(baseline_cases, candidate_cases, shared_case_ids, "evidence_count_score"),
        "red_blue_issue_count_delta": _average_delta(baseline_cases, candidate_cases, shared_case_ids, "red_blue_issue_count"),
        "judge_score_delta": _average_delta(baseline_cases, candidate_cases, shared_case_ids, "judge_score"),
    }
    domain_deltas = _domain_deltas(baseline_cases, candidate_cases, shared_case_ids)
    summary = (
        f"{candidate_name} vs {baseline_name}: "
        f"{len(improved_cases)} improved, {len(regressed_cases)} regressed, "
        f"{len(unchanged_cases)} unchanged; composite delta "
        f"{metric_deltas['composite_score_delta']:.3f}."
    )
    statistical_summary = None
    if include_statistics:
        statistical_summary = build_statistical_comparison(
            baseline_result,
            candidate_result,
            metric_name=stats_metric_name,
            confidence_level=confidence_level,
            num_bootstrap=num_bootstrap,
            seed=seed,
            baseline_name=baseline_name,
            candidate_name=candidate_name,
        ).to_dict()
    return EvaluationComparison(
        baseline_name=baseline_name,
        candidate_name=candidate_name,
        case_count=len(shared_case_ids),
        metric_deltas=metric_deltas,
        improved_cases=improved_cases,
        regressed_cases=regressed_cases,
        unchanged_cases=unchanged_cases,
        domain_deltas=domain_deltas,
        summary=summary,
        metadata={
            "baseline_case_count": len(baseline_cases),
            "candidate_case_count": len(candidate_cases),
        },
        statistical_summary=statistical_summary,
    )


def _case_map(eval_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(result.get("case_id")): result
        for result in eval_result.get("results", [])
        if result.get("case_id") is not None
    }


def _average_delta(
    baseline_cases: dict[str, dict[str, Any]],
    candidate_cases: dict[str, dict[str, Any]],
    case_ids: list[str],
    metric_name: str,
) -> float:
    if not case_ids:
        return 0.0
    return sum(
        _metric(candidate_cases[case_id], metric_name) - _metric(baseline_cases[case_id], metric_name)
        for case_id in case_ids
    ) / len(case_ids)


def _domain_deltas(
    baseline_cases: dict[str, dict[str, Any]],
    candidate_cases: dict[str, dict[str, Any]],
    case_ids: list[str],
) -> dict[str, dict[str, float]]:
    by_domain: dict[str, list[str]] = {}
    for case_id in case_ids:
        domain = str(candidate_cases[case_id].get("domain") or baseline_cases[case_id].get("domain") or "unknown")
        by_domain.setdefault(domain, []).append(case_id)
    return {
        domain: {
            "case_count": len(ids),
            "rule_score_delta": _average_delta(baseline_cases, candidate_cases, ids, "rule_score"),
            "composite_score_delta": _average_delta(baseline_cases, candidate_cases, ids, "composite_score"),
        }
        for domain, ids in sorted(by_domain.items())
    }


def _metric(case_result: dict[str, Any], metric_name: str) -> float:
    if case_result.get(metric_name) is not None:
        try:
            return float(case_result.get(metric_name) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    metrics = case_result.get("metrics", {})
    try:
        return float(metrics.get(metric_name, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
