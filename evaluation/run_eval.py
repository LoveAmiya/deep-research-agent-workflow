import json
from pathlib import Path
from typing import Any, Dict, List

from evaluation.metrics import (
    citation_coverage,
    finding_coverage,
    keyword_coverage,
    memory_completeness,
    red_blue_improvement,
    section_coverage,
    summarize_eval_results,
)
from orchestrator.research_pipeline import run_research_pipeline


def load_cases(path: str | Path) -> List[Dict[str, Any]]:
    cases = []
    with Path(path).open("r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if stripped:
                cases.append(json.loads(stripped))
    return cases


def run_case(case: Dict[str, Any]) -> Dict[str, Any]:
    pipeline_result = run_research_pipeline(case["question"])
    report = pipeline_result["report"]
    findings = pipeline_result["findings"]
    red_review = pipeline_result["red_review"]
    blue_revision = pipeline_result["blue_revision"]
    memory_items = pipeline_result["memory_items"]
    metrics = {
        "section_coverage": section_coverage(report, case.get("expected_sections", [])),
        "citation_coverage": citation_coverage(report, case.get("expected_min_citations", 0)),
        "finding_coverage": finding_coverage(findings, case.get("expected_min_findings", 0)),
        "keyword_coverage": keyword_coverage(report, case.get("keywords", [])),
        "red_blue_improvement": red_blue_improvement(red_review, blue_revision),
        "memory_completeness": memory_completeness(memory_items),
    }
    success = pipeline_result["success"] and all(value >= 1.0 for value in metrics.values())
    return {
        "case_id": case["id"],
        "question": case["question"],
        "success": success,
        "metrics": metrics,
        "report_title": report.title,
    }


def run_eval(cases_path: str = "evaluation/cases.jsonl") -> Dict[str, Any]:
    cases = load_cases(cases_path)
    results = []
    for case in cases:
        try:
            results.append(run_case(case))
        except Exception as exc:
            if case.get("optional", False):
                continue
            results.append(
                {
                    "case_id": case.get("id", "unknown"),
                    "question": case.get("question", ""),
                    "success": False,
                    "error": str(exc),
                    "metrics": {},
                }
            )
    summary = summarize_eval_results(results)
    return {"summary": summary, "results": results}


def main() -> None:
    eval_result = run_eval()
    summary = eval_result["summary"]
    print("Eval Summary")
    for key, value in summary.items():
        print(f"{key}: {value}")
    print()
    print("Case Results")
    for result in eval_result["results"]:
        metrics = result.get("metrics", {})
        print(
            f"{result['case_id']}: "
            f"section={metrics.get('section_coverage', 0.0):.2f}, "
            f"citation={metrics.get('citation_coverage', 0.0):.2f}, "
            f"finding={metrics.get('finding_coverage', 0.0):.2f}, "
            f"keyword={metrics.get('keyword_coverage', 0.0):.2f}, "
            f"red_blue={metrics.get('red_blue_improvement', 0.0):.2f}, "
            f"memory={metrics.get('memory_completeness', 0.0):.2f}"
        )


if __name__ == "__main__":
    main()
