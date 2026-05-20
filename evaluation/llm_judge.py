import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.llm_client import LLMMessage
from core.prompt_loader import load_prompt
from memory.run_serializer import to_jsonable


JUDGE_DIMENSIONS = [
    "answer_relevance",
    "factual_consistency",
    "citation_quality",
    "completeness",
    "clarity",
]


@dataclass
class JudgeRubric:
    dimensions: List[str] = field(default_factory=lambda: list(JUDGE_DIMENSIONS))
    min_score: int = 1
    max_score: int = 5
    pass_threshold: float = 3.5


@dataclass
class JudgeResult:
    case_id: Optional[str]
    overall_score: float
    dimension_scores: Dict[str, float]
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    suggested_improvements: List[str] = field(default_factory=list)
    passed: bool = False
    raw_response: Optional[str] = None
    fallback_used: bool = False
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class LLMJudgeEvaluator:
    def __init__(self, llm_client=None, rubric: Optional[JudgeRubric] = None) -> None:
        self.llm_client = llm_client
        self.rubric = rubric or JudgeRubric()

    def build_judge_input(
        self,
        question,
        report,
        findings,
        citations=None,
        citation_validation=None,
    ) -> str:
        payload = {
            "question": question,
            "report_markdown": getattr(report, "markdown", str(report)),
            "findings": to_jsonable(findings),
            "citations": to_jsonable(citations if citations is not None else getattr(report, "citations", [])),
            "citation_validation": to_jsonable(citation_validation or {}),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def judge(
        self,
        question,
        report,
        findings,
        citations=None,
        citation_validation=None,
        case_id=None,
    ) -> JudgeResult:
        judge_input = self.build_judge_input(
            question=question,
            report=report,
            findings=findings,
            citations=citations,
            citation_validation=citation_validation,
        )
        if self.llm_client is None:
            return self._fallback_result(
                question=question,
                report=report,
                findings=findings,
                citation_validation=citation_validation,
                case_id=case_id,
                reason="no_llm_client",
            )

        try:
            response = self.llm_client.generate(
                [
                    LLMMessage(role="system", content=load_prompt("judge")),
                    LLMMessage(role="user", content=judge_input),
                ],
                temperature=0.0,
            )
            parsed = parse_judge_json(response.content)
            return self._result_from_parsed(parsed, case_id=case_id, raw_response=response.content)
        except Exception as exc:
            return self._fallback_result(
                question=question,
                report=report,
                findings=findings,
                citation_validation=citation_validation,
                case_id=case_id,
                reason="llm_or_parse_failure",
                error=str(exc),
            )

    def _result_from_parsed(self, parsed: dict, case_id=None, raw_response: Optional[str] = None) -> JudgeResult:
        dimension_scores = {}
        raw_scores = parsed.get("dimension_scores", {})
        for dimension in self.rubric.dimensions:
            dimension_scores[dimension] = self._coerce_score(raw_scores.get(dimension, self.rubric.min_score))
        overall_score = self._coerce_overall(parsed.get("overall_score"), dimension_scores)
        return JudgeResult(
            case_id=case_id,
            overall_score=overall_score,
            dimension_scores=dimension_scores,
            strengths=_coerce_string_list(parsed.get("strengths", [])),
            weaknesses=_coerce_string_list(parsed.get("weaknesses", [])),
            suggested_improvements=_coerce_string_list(parsed.get("suggested_improvements", [])),
            passed=bool(parsed.get("passed", overall_score >= self.rubric.pass_threshold)),
            raw_response=raw_response,
            fallback_used=False,
            error=None,
            metadata={"used_llm": True, "fallback_reason": None, "prompt_version": "judge_v1"},
        )

    def _fallback_result(
        self,
        question,
        report,
        findings,
        citation_validation=None,
        case_id=None,
        reason: str = "fallback",
        error: Optional[str] = None,
    ) -> JudgeResult:
        markdown = getattr(report, "markdown", "") or ""
        citation_validation = citation_validation or {}
        has_question_terms = _keyword_overlap(str(question), markdown) > 0
        has_sections = all(section in markdown for section in ["## Background", "## Key Findings", "## Conclusion"])
        has_references = "## References" in markdown
        has_findings = len(findings or []) > 0
        citation_passed = bool(citation_validation.get("passed", False))
        dimension_scores = {
            "answer_relevance": 4.0 if has_question_terms else 3.0,
            "factual_consistency": 4.0 if has_findings else 2.0,
            "citation_quality": 4.0 if citation_passed else 2.0 if has_references else 1.0,
            "completeness": 4.0 if has_sections else 2.0,
            "clarity": 4.0 if len(markdown) > 200 else 3.0,
        }
        overall_score = sum(dimension_scores.values()) / len(dimension_scores)
        return JudgeResult(
            case_id=case_id,
            overall_score=overall_score,
            dimension_scores=dimension_scores,
            strengths=["Report has deterministic structure and local evidence checks."],
            weaknesses=["Fallback judge cannot perform semantic quality assessment."],
            suggested_improvements=["Use a configured LLM judge for richer qualitative review."],
            passed=overall_score >= self.rubric.pass_threshold,
            raw_response=None,
            fallback_used=True,
            error=error,
            metadata={"used_llm": False, "fallback_reason": reason, "prompt_version": "judge_v1"},
        )

    def _coerce_score(self, value) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = float(self.rubric.min_score)
        return min(float(self.rubric.max_score), max(float(self.rubric.min_score), score))

    def _coerce_overall(self, value, dimension_scores: Dict[str, float]) -> float:
        if value is None:
            return sum(dimension_scores.values()) / len(dimension_scores)
        return self._coerce_score(value)


def parse_judge_json(text: str) -> dict:
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty judge response")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        json_object = _extract_first_json_object(stripped)
        if json_object is None:
            raise ValueError("judge response did not contain a JSON object")
        return json.loads(json_object)


def _extract_first_json_object(text: str) -> Optional[str]:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _coerce_string_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _keyword_overlap(question: str, markdown: str) -> int:
    question_terms = {term.lower() for term in re.findall(r"[A-Za-z][A-Za-z-]{2,}", question)}
    markdown_lower = markdown.lower()
    return sum(1 for term in question_terms if term in markdown_lower)
