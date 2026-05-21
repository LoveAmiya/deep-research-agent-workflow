import json
from pathlib import Path
from typing import Any

from memory.run_serializer import to_jsonable


def write_json_report(eval_result: dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(eval_result), ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def write_markdown_report(eval_result: dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_markdown_report(eval_result), encoding="utf-8")


def build_markdown_report(eval_result: dict[str, Any]) -> str:
    summary = eval_result.get("summary", {})
    lines = [
        f"# {summary.get('benchmark_name', eval_result.get('benchmark_name', 'Evaluation'))}",
        "",
        "## Overview",
        "",
        f"- Case count: {summary.get('case_count', summary.get('total_cases', 0))}",
        f"- Average rule score: {_fmt(summary.get('average_rule_score'))}",
        f"- Average composite score: {_fmt(summary.get('average_composite_score'))}",
        f"- Judge enabled: {summary.get('judge_enabled', False)}",
        "",
        "## Domain Summary",
        "",
        "| Domain | Cases | Rule | Composite |",
        "| --- | ---: | ---: | ---: |",
    ]
    for domain, row in (summary.get("domain_summary") or {}).items():
        lines.append(
            f"| {domain} | {row.get('case_count', 0)} | "
            f"{_fmt(row.get('average_rule_score'))} | {_fmt(row.get('average_composite_score'))} |"
        )
    lines.extend(["", "## Difficulty Summary", "", "| Difficulty | Cases | Rule | Composite |", "| --- | ---: | ---: | ---: |"])
    for difficulty, row in (summary.get("difficulty_summary") or {}).items():
        lines.append(
            f"| {difficulty} | {row.get('case_count', 0)} | "
            f"{_fmt(row.get('average_rule_score'))} | {_fmt(row.get('average_composite_score'))} |"
        )
    results = sorted(
        eval_result.get("results", []),
        key=lambda item: item.get("composite_score", item.get("rule_score", 0.0)),
    )
    lines.extend(["", "## Weakest Cases", ""])
    for result in results[:5]:
        lines.append(f"- {result.get('case_id')}: composite={_fmt(result.get('composite_score'))}")
    lines.extend(["", "## Strongest Cases", ""])
    for result in list(reversed(results[-5:])):
        lines.append(f"- {result.get('case_id')}: composite={_fmt(result.get('composite_score'))}")
    comparison = eval_result.get("comparison_summary")
    if comparison:
        lines.extend(["", "## Comparison Summary", "", str(comparison.get("summary", comparison))])
    statistical_summary = eval_result.get("statistical_summary")
    if statistical_summary:
        delta_ci = statistical_summary.get("delta_ci", {})
        effect_size = statistical_summary.get("effect_size", {})
        lines.extend(
            [
                "",
                "## Statistical Summary",
                "",
                f"- Metric: {statistical_summary.get('metric_name')}",
                f"- Baseline mean: {_fmt(statistical_summary.get('baseline_mean'))}",
                f"- Candidate mean: {_fmt(statistical_summary.get('candidate_mean'))}",
                f"- Mean delta: {_fmt(statistical_summary.get('mean_delta'))}",
                (
                    "- Bootstrap delta CI: "
                    f"[{_fmt(delta_ci.get('lower'))}, {_fmt(delta_ci.get('upper'))}]"
                ),
                (
                    "- Effect size: "
                    f"{_fmt(effect_size.get('value'))} "
                    f"({effect_size.get('interpretation', 'n/a')})"
                ),
                f"- Sample size: {statistical_summary.get('sample_size', 0)}",
                "",
                (
                    "Caveat: this is a deterministic bootstrap/effect-size summary. "
                    "It is not a p-value, t-test, or statistical significance claim."
                ),
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)
