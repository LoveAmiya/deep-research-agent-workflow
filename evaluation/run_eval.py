import json
import os
from pathlib import Path
from typing import Any, Dict, List

from core.config import load_llm_config_from_env
from core.llm_client import MockLLMClient, create_llm_client
from evaluation.llm_judge import JudgeRubric, LLMJudgeEvaluator
from evaluation.metrics import (
    citation_coverage,
    citation_grounding_score,
    finding_coverage,
    iterative_red_blue_score,
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


def run_case(case: Dict[str, Any], judge_evaluator: LLMJudgeEvaluator | None = None) -> Dict[str, Any]:
    use_red_blue_loop = bool(case.get("use_red_blue_loop", False))
    pipeline_result = run_research_pipeline(
        case["question"],
        use_red_blue_loop=use_red_blue_loop,
    )
    report = pipeline_result["report"]
    findings = pipeline_result["findings"]
    red_review = pipeline_result["red_review"]
    blue_revision = pipeline_result["blue_revision"]
    citation_validation = pipeline_result["citation_validation"]
    memory_items = pipeline_result["memory_items"]
    metrics = {
        "section_coverage": section_coverage(report, case.get("expected_sections", [])),
        "citation_coverage": citation_coverage(report, case.get("expected_min_citations", 0)),
        "citation_grounding_score": citation_grounding_score(report, citation_validation),
        "finding_coverage": finding_coverage(findings, case.get("expected_min_findings", 0)),
        "keyword_coverage": keyword_coverage(report, case.get("keywords", [])),
        "red_blue_improvement": red_blue_improvement(red_review, blue_revision),
        "memory_completeness": memory_completeness(memory_items),
    }
    if use_red_blue_loop:
        metrics["iterative_red_blue_score"] = iterative_red_blue_score(
            pipeline_result.get("red_blue_loop_result")
        )
    judge_result = None
    if judge_evaluator is not None:
        judge_result = judge_evaluator.judge(
            question=case["question"],
            report=report,
            findings=findings,
            citations=report.citations,
            citation_validation=citation_validation,
            case_id=case.get("id"),
        )
        pipeline_result["judge_result"] = judge_result
    success = pipeline_result["success"] and all(value >= 1.0 for value in metrics.values())
    case_result = {
        "case_id": case["id"],
        "question": case["question"],
        "success": success,
        "metrics": metrics,
        "report_title": report.title,
    }
    if judge_result is not None:
        case_result["judge_result"] = judge_result
    return case_result


def run_eval(cases_path: str = "evaluation/cases.jsonl") -> Dict[str, Any]:
    cases = load_cases(cases_path)
    judge_evaluator = _build_judge_evaluator_from_env()
    results = []
    for case in cases:
        try:
            results.append(run_case(case, judge_evaluator=judge_evaluator))
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


def _build_judge_evaluator_from_env() -> LLMJudgeEvaluator | None:
    enabled = os.getenv("DEEP_RESEARCH_USE_LLM_JUDGE", "").strip().lower() in {"1", "true"}
    if not enabled:
        return None
    use_mock = os.getenv("DEEP_RESEARCH_LLM_JUDGE_USE_MOCK", "").strip().lower() in {"1", "true"}
    pass_threshold_raw = os.getenv("DEEP_RESEARCH_LLM_JUDGE_PASS_THRESHOLD", "3.5")
    try:
        pass_threshold = float(pass_threshold_raw)
    except ValueError:
        pass_threshold = 3.5
    rubric = JudgeRubric(pass_threshold=pass_threshold)
    if use_mock:
        return LLMJudgeEvaluator(llm_client=MockLLMClient(), rubric=rubric)
    config = load_llm_config_from_env(load_dotenv=True)
    return LLMJudgeEvaluator(llm_client=create_llm_client(config), rubric=rubric)


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
            f"grounding={metrics.get('citation_grounding_score', 0.0):.2f}, "
            f"finding={metrics.get('finding_coverage', 0.0):.2f}, "
            f"keyword={metrics.get('keyword_coverage', 0.0):.2f}, "
            f"red_blue={metrics.get('red_blue_improvement', 0.0):.2f}, "
            f"memory={metrics.get('memory_completeness', 0.0):.2f}"
        )
        judge_result = result.get("judge_result")
        if judge_result is not None:
            print(
                f"  judge_overall={judge_result.overall_score:.2f}, "
                f"judge_passed={judge_result.passed}"
            )


if __name__ == "__main__":
    main()
