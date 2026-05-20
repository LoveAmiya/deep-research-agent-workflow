from dataclasses import asdict, is_dataclass
from typing import Any, Dict


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(to_jsonable(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "to_dict_list"):
        try:
            return to_jsonable(value.to_dict_list())
        except Exception:
            return str(value)
    return str(value)


def build_run_payload(result: dict) -> dict:
    return to_jsonable(result)


def build_run_summary(result: dict, question: str) -> Dict[str, Any]:
    report = result.get("report") or result.get("final_report")
    findings = result.get("findings") or []
    citation_validation = result.get("citation_validation") or {}
    memory_items = result.get("memory_items") or []
    red_review = result.get("red_review")
    blue_revision = result.get("blue_revision")
    loop_result = result.get("red_blue_loop_result")
    report_markdown = getattr(report, "markdown", None) if report is not None else None

    summary = {
        "question": question,
        "report_length": len(report_markdown or ""),
        "finding_count": len(findings),
        "citation_count": citation_validation.get(
            "citation_count",
            len(getattr(report, "citations", []) if report is not None else []),
        ),
        "grounded_citation_count": citation_validation.get("grounded_citation_count", 0),
        "citation_validation_passed": citation_validation.get("passed", False),
        "memory_item_count": len(memory_items),
        "red_issues": len(getattr(red_review, "issues", [])) if red_review is not None else 0,
        "blue_fixed_issues": len(getattr(blue_revision, "fixed_issue_ids", []))
        if blue_revision is not None
        else 0,
        "red_blue_loop_rounds": len(getattr(loop_result, "rounds", [])) if loop_result else 0,
        "success": bool(result.get("success", False)),
    }
    return to_jsonable(summary)
