from typing import Any, Dict, List


REQUIRED_MEMORY_TYPES = {
    "plan",
    "search_results",
    "findings",
    "report",
    "review",
    "red_review",
    "blue_revision",
}


def section_coverage(report, expected_sections: List[str]) -> float:
    if not expected_sections:
        return 1.0
    markdown = report.markdown or ""
    covered = sum(1 for section in expected_sections if f"## {section}" in markdown)
    return covered / len(expected_sections)


def citation_coverage(report, min_citations: int) -> float:
    if min_citations <= 0:
        return 1.0
    return min(1.0, len(report.citations) / min_citations)


def citation_grounding_score(report, citation_validation: Dict[str, Any]) -> float:
    if citation_validation.get("passed", False):
        return 1.0
    citation_count = citation_validation.get("citation_count", len(getattr(report, "citations", [])))
    if citation_count == 0:
        return 0.0
    grounded_count = citation_validation.get("grounded_citation_count", 0)
    return min(1.0, grounded_count / citation_count)


def finding_coverage(findings: list, min_findings: int) -> float:
    if min_findings <= 0:
        return 1.0
    return min(1.0, len(findings) / min_findings)


def keyword_coverage(report, keywords: List[str]) -> float:
    if not keywords:
        return 1.0
    markdown = (report.markdown or "").lower()
    covered = sum(1 for keyword in keywords if keyword.lower() in markdown)
    return covered / len(keywords)


def red_blue_improvement(red_review, blue_revision) -> float:
    issues = getattr(red_review, "issues", [])
    if not issues and getattr(blue_revision, "revised_report", None) is not None:
        return 1.0
    if not issues:
        return 0.0
    fixed = len(getattr(blue_revision, "fixed_issue_ids", []))
    return min(1.0, fixed / len(issues))


def memory_completeness(memory_items: List[Dict[str, Any]]) -> float:
    if not REQUIRED_MEMORY_TYPES:
        return 1.0
    present_types = {item.get("item_type") for item in memory_items}
    return len(REQUIRED_MEMORY_TYPES.intersection(present_types)) / len(REQUIRED_MEMORY_TYPES)


def summarize_eval_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_cases = len(results)
    if total_cases == 0:
        return {
            "total_cases": 0,
            "failed_cases": 0,
            "average_section_coverage": 0.0,
            "average_citation_coverage": 0.0,
            "average_citation_grounding_score": 0.0,
            "average_finding_coverage": 0.0,
            "average_keyword_coverage": 0.0,
            "average_red_blue_improvement": 0.0,
            "average_memory_completeness": 0.0,
        }

    failed_cases = sum(1 for result in results if not result.get("success", False))
    return {
        "total_cases": total_cases,
        "failed_cases": failed_cases,
        "average_section_coverage": _average(results, "section_coverage"),
        "average_citation_coverage": _average(results, "citation_coverage"),
        "average_citation_grounding_score": _average(results, "citation_grounding_score"),
        "average_finding_coverage": _average(results, "finding_coverage"),
        "average_keyword_coverage": _average(results, "keyword_coverage"),
        "average_red_blue_improvement": _average(results, "red_blue_improvement"),
        "average_memory_completeness": _average(results, "memory_completeness"),
    }


def _average(results: List[Dict[str, Any]], key: str) -> float:
    return sum(result.get("metrics", {}).get(key, 0.0) for result in results) / len(results)
