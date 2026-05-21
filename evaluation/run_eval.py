import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from agents.red_blue_loop import RedBlueLoopConfig
from core.config import load_llm_config_from_env
from core.llm_client import MockLLMClient, create_llm_client
from evaluation.comparison import compare_evaluation_results
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
from evaluation.reporting import write_json_report, write_markdown_report
from evaluation.research_bench_plus import ResearchBenchCase, load_plus_cases
from evaluation.scoring_plus import (
    build_composite_score_summary,
    build_plus_summary,
    build_rule_score_summary,
)
from memory.run_serializer import to_jsonable
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


def run_plus_case(
    case: ResearchBenchCase | dict[str, Any],
    judge_evaluator: LLMJudgeEvaluator | None = None,
    use_red_blue_loop: bool = False,
) -> dict[str, Any]:
    resolved_case = case if isinstance(case, ResearchBenchCase) else ResearchBenchCase.from_dict(case)
    red_blue_config = RedBlueLoopConfig(max_rounds=3) if use_red_blue_loop else None
    pipeline_result = run_research_pipeline(
        resolved_case.question,
        use_red_blue_loop=use_red_blue_loop,
        red_blue_loop_config=red_blue_config,
    )
    judge_result = None
    if judge_evaluator is not None:
        judge_result = judge_evaluator.judge(
            question=resolved_case.question,
            report=pipeline_result["report"],
            findings=pipeline_result["findings"],
            citations=pipeline_result["report"].citations,
            citation_validation=pipeline_result["citation_validation"],
            case_id=resolved_case.case_id,
        )
        pipeline_result["judge_result"] = judge_result
    rule_summary = build_rule_score_summary(resolved_case, pipeline_result)
    composite_summary = build_composite_score_summary(
        case_id=resolved_case.case_id,
        rule_score=rule_summary.rule_score,
        judge_result=judge_result,
        judge_enabled=judge_evaluator is not None,
    )
    loop_result = pipeline_result.get("red_blue_loop_result")
    red_blue_issue_count = getattr(loop_result, "remaining_issue_count", 0) if loop_result is not None else 0
    result = {
        **rule_summary.to_dict(),
        **composite_summary.to_dict(),
        "case_id": resolved_case.case_id,
        "domain": resolved_case.domain,
        "difficulty": resolved_case.difficulty,
        "question": resolved_case.question,
        "success": bool(pipeline_result.get("success", False)),
        "red_blue_enabled": use_red_blue_loop,
        "red_blue_issue_count": red_blue_issue_count,
        "judge_result": judge_result,
        "report_title": pipeline_result["report"].title,
        "metadata": {
            **rule_summary.metadata,
            **composite_summary.metadata,
            "tags": list(resolved_case.tags),
            "judge_focus": list(resolved_case.judge_focus),
        },
    }
    return result


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


def run_plus_eval(
    judge_evaluator: LLMJudgeEvaluator | None = None,
    use_red_blue_loop: bool = False,
    benchmark_name: str = "ResearchBench-mini Plus",
) -> dict[str, Any]:
    cases = load_plus_cases()
    results = [run_plus_case(case, judge_evaluator=judge_evaluator, use_red_blue_loop=use_red_blue_loop) for case in cases]
    summary = build_plus_summary(
        results,
        benchmark_name=benchmark_name,
        judge_enabled=judge_evaluator is not None,
    )
    return {
        "run_id": str(uuid4()),
        "benchmark_name": benchmark_name,
        "summary": summary,
        "results": results,
        "metadata": {
            "red_blue_enabled": use_red_blue_loop,
            "judge_enabled": judge_evaluator is not None,
        },
    }


def run_red_blue_comparison(judge_evaluator: LLMJudgeEvaluator | None = None) -> dict[str, Any]:
    baseline = run_plus_eval(judge_evaluator=judge_evaluator, use_red_blue_loop=False, benchmark_name="ResearchBench-mini Plus red-blue disabled")
    candidate = run_plus_eval(judge_evaluator=judge_evaluator, use_red_blue_loop=True, benchmark_name="ResearchBench-mini Plus red-blue enabled")
    comparison = compare_evaluation_results(
        baseline,
        candidate,
        baseline_name="red_blue_disabled",
        candidate_name="red_blue_enabled",
    )
    return {
        "baseline": baseline,
        "candidate": candidate,
        "comparison": comparison.to_dict(),
        "comparison_summary": comparison.to_dict(),
    }


def run_red_blue_statistical_comparison(
    judge_evaluator: LLMJudgeEvaluator | None = None,
    stats_metric_name: str = "composite_score",
    confidence_level: float = 0.95,
    num_bootstrap: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    baseline = run_plus_eval(judge_evaluator=judge_evaluator, use_red_blue_loop=False, benchmark_name="ResearchBench-mini Plus red-blue disabled")
    candidate = run_plus_eval(judge_evaluator=judge_evaluator, use_red_blue_loop=True, benchmark_name="ResearchBench-mini Plus red-blue enabled")
    comparison = compare_evaluation_results(
        baseline,
        candidate,
        baseline_name="red_blue_disabled",
        candidate_name="red_blue_enabled",
        include_statistics=True,
        stats_metric_name=stats_metric_name,
        confidence_level=confidence_level,
        num_bootstrap=num_bootstrap,
        seed=seed,
    )
    comparison_dict = comparison.to_dict()
    return {
        "baseline": baseline,
        "candidate": candidate,
        "comparison": comparison_dict,
        "comparison_summary": comparison_dict,
        "statistical_summary": comparison.statistical_summary,
    }


def _build_judge_evaluator_from_env(force_enabled: bool = False) -> LLMJudgeEvaluator | None:
    enabled = force_enabled or os.getenv("DEEP_RESEARCH_USE_LLM_JUDGE", "").strip().lower() in {"1", "true"}
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", choices=["mini", "plus"], default="mini")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--compare", nargs=2, metavar=("BASELINE_JSON", "CANDIDATE_JSON"))
    parser.add_argument("--enable-judge", action="store_true")
    parser.add_argument("--compare-red-blue", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--stats-metric", default="composite_score")
    parser.add_argument("--num-bootstrap", type=int, default=1000)
    parser.add_argument("--confidence-level", type=float, default=0.95)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.compare:
        try:
            baseline = _load_eval_json(args.compare[0])
            candidate = _load_eval_json(args.compare[1])
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
        try:
            comparison = compare_evaluation_results(
                baseline,
                candidate,
                include_statistics=args.stats,
                stats_metric_name=args.stats_metric,
                confidence_level=args.confidence_level,
                num_bootstrap=args.num_bootstrap,
                seed=args.seed,
            )
        except ValueError as exc:
            parser.error(str(exc))
        comparison_dict = comparison.to_dict()
        comparison_report = _build_comparison_report(comparison_dict)
        if args.output_json:
            write_json_report(comparison_report, args.output_json)
        if args.output_md:
            write_markdown_report(comparison_report, args.output_md)
        print(json.dumps(to_jsonable(comparison_dict), ensure_ascii=True, indent=2, sort_keys=True))
        return

    judge_evaluator = _build_judge_evaluator_from_env(force_enabled=args.enable_judge)
    if args.compare_red_blue:
        try:
            if args.stats:
                eval_result = run_red_blue_statistical_comparison(
                    judge_evaluator=judge_evaluator,
                    stats_metric_name=args.stats_metric,
                    confidence_level=args.confidence_level,
                    num_bootstrap=args.num_bootstrap,
                    seed=args.seed,
                )
            else:
                eval_result = run_red_blue_comparison(judge_evaluator=judge_evaluator)
        except ValueError as exc:
            parser.error(str(exc))
        printable_summary = eval_result["comparison"]["summary"]
        print(f"Comparison Summary: {printable_summary}")
        if args.stats:
            _print_statistical_summary(eval_result.get("statistical_summary"))
    elif args.bench == "plus":
        eval_result = run_plus_eval(judge_evaluator=judge_evaluator)
        _print_plus_result(eval_result)
    else:
        eval_result = run_eval()
        _print_mini_result(eval_result)

    if args.output_json:
        write_json_report(eval_result, args.output_json)
    if args.output_md:
        write_markdown_report(eval_result, args.output_md)


def _load_eval_json(path: str) -> dict[str, Any]:
    result_path = Path(path)
    if not result_path.exists():
        raise FileNotFoundError(f"Evaluation result file not found: {path}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def _build_comparison_report(comparison: dict[str, Any]) -> dict[str, Any]:
    return {
        "benchmark_name": "Evaluation Comparison",
        "summary": {
            "benchmark_name": "Evaluation Comparison",
            "case_count": comparison.get("case_count", 0),
        },
        "comparison": comparison,
        "comparison_summary": comparison,
        "statistical_summary": comparison.get("statistical_summary"),
        "results": [],
    }


def _print_mini_result(eval_result: dict[str, Any]) -> None:
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


def _print_plus_result(eval_result: dict[str, Any]) -> None:
    summary = eval_result["summary"]
    print("ResearchBench-mini Plus Summary")
    print(f"case_count: {summary['case_count']}")
    print(f"average_rule_score: {summary['average_rule_score']:.3f}")
    print(f"average_composite_score: {summary['average_composite_score']:.3f}")
    print(f"judge_enabled: {summary['judge_enabled']}")
    print()
    print("Domain Summary")
    for domain, row in summary["domain_summary"].items():
        print(
            f"{domain}: cases={row['case_count']}, "
            f"rule={row['average_rule_score']:.3f}, "
            f"composite={row['average_composite_score']:.3f}"
        )


def _print_statistical_summary(statistical_summary: dict[str, Any] | None) -> None:
    if not statistical_summary:
        return
    delta_ci = statistical_summary.get("delta_ci", {})
    effect_size = statistical_summary.get("effect_size", {})
    print(
        "Statistical Summary: "
        f"metric={statistical_summary.get('metric_name')}, "
        f"mean_delta={statistical_summary.get('mean_delta', 0.0):.3f}, "
        f"delta_ci=[{delta_ci.get('lower', 0.0):.3f}, {delta_ci.get('upper', 0.0):.3f}], "
        f"effect={effect_size.get('interpretation')}"
    )


if __name__ == "__main__":
    main()
