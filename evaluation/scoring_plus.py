from dataclasses import asdict, dataclass, field
from typing import Any

from evaluation.metrics import (
    citation_coverage,
    citation_grounding_score,
    finding_coverage,
    keyword_coverage,
    red_blue_improvement,
    section_coverage,
)
from evaluation.research_bench_plus import ResearchBenchCase


@dataclass
class RuleScoreSummary:
    case_id: str
    domain: str
    difficulty: str
    section_coverage: float
    keyword_coverage: float
    evidence_count_score: float
    citation_count_score: float
    citation_grounding_score: float
    finding_coverage: float
    red_blue_improvement_score: float
    rule_score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompositeScoreSummary:
    case_id: str
    rule_score: float
    judge_score: float | None = None
    composite_score: float = 0.0
    judge_enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evidence_count_score(actual_count: int, expected_count: int) -> float:
    if expected_count <= 0:
        return 1.0
    return min(1.0, max(0, actual_count) / expected_count)


def citation_count_score(actual_count: int, expected_count: int) -> float:
    if expected_count <= 0:
        return 1.0
    return min(1.0, max(0, actual_count) / expected_count)


def build_rule_score_summary(
    case: ResearchBenchCase,
    pipeline_result: dict,
) -> RuleScoreSummary:
    report = pipeline_result["report"]
    findings = pipeline_result.get("findings") or []
    red_review = pipeline_result.get("red_review")
    blue_revision = pipeline_result.get("blue_revision")
    citation_validation = pipeline_result.get("citation_validation") or {}
    metrics = {
        "section_coverage": section_coverage(report, case.expected_sections),
        "keyword_coverage": keyword_coverage(report, case.expected_keywords),
        "evidence_count_score": evidence_count_score(len(findings), case.expected_evidence_count),
        "citation_count_score": citation_count_score(len(getattr(report, "citations", []) or []), case.expected_citation_count),
        "citation_grounding_score": citation_grounding_score(report, citation_validation),
        "finding_coverage": finding_coverage(findings, case.expected_evidence_count),
        "red_blue_improvement_score": red_blue_improvement(red_review, blue_revision),
    }
    rule_score = sum(metrics.values()) / len(metrics)
    return RuleScoreSummary(
        case_id=case.case_id,
        domain=case.domain,
        difficulty=case.difficulty,
        rule_score=rule_score,
        metadata={
            "expected_evidence_count": case.expected_evidence_count,
            "expected_citation_count": case.expected_citation_count,
            "tags": list(case.tags),
        },
        **metrics,
    )


def normalize_judge_score(judge_result) -> float | None:
    if judge_result is None:
        return None
    try:
        return max(0.0, min(1.0, float(getattr(judge_result, "overall_score", 0.0)) / 5.0))
    except (TypeError, ValueError):
        return None


def build_composite_score_summary(
    case_id: str,
    rule_score: float,
    judge_result=None,
    judge_enabled: bool = False,
) -> CompositeScoreSummary:
    judge_score = normalize_judge_score(judge_result) if judge_enabled else None
    if judge_enabled and judge_score is not None:
        composite_score = (0.7 * rule_score) + (0.3 * judge_score)
    else:
        composite_score = rule_score
    return CompositeScoreSummary(
        case_id=case_id,
        rule_score=rule_score,
        judge_score=judge_score,
        composite_score=composite_score,
        judge_enabled=bool(judge_enabled and judge_score is not None),
        metadata={"judge_missing": judge_enabled and judge_score is None},
    )


def aggregate_by_field(case_results: list[dict[str, Any]], field_name: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for result in case_results:
        key = str(result.get(field_name) or "unknown")
        groups.setdefault(key, []).append(result)
    return {
        key: {
            "case_count": len(items),
            "average_rule_score": _average(items, "rule_score"),
            "average_composite_score": _average(items, "composite_score"),
            "average_citation_count_score": _average(items, "citation_count_score"),
            "average_evidence_count_score": _average(items, "evidence_count_score"),
        }
        for key, items in sorted(groups.items())
    }


def build_plus_summary(
    case_results: list[dict[str, Any]],
    benchmark_name: str,
    judge_enabled: bool,
) -> dict[str, Any]:
    return {
        "benchmark_name": benchmark_name,
        "case_count": len(case_results),
        "average_rule_score": _average(case_results, "rule_score"),
        "average_composite_score": _average(case_results, "composite_score"),
        "judge_enabled": judge_enabled,
        "average_judge_score": _average_present(case_results, "judge_score"),
        "domain_summary": aggregate_by_field(case_results, "domain"),
        "difficulty_summary": aggregate_by_field(case_results, "difficulty"),
        "failed_cases": sum(1 for result in case_results if not result.get("success", False)),
    }


def _average(items: list[dict[str, Any]], key: str) -> float:
    if not items:
        return 0.0
    return sum(float(item.get(key, 0.0) or 0.0) for item in items) / len(items)


def _average_present(items: list[dict[str, Any]], key: str) -> float | None:
    values = [float(item[key]) for item in items if item.get(key) is not None]
    if not values:
        return None
    return sum(values) / len(values)
