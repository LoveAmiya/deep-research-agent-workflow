import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.llm_client import BaseLLMClient, LLMClientError, LLMMessage, LLMResponse, MockLLMClient
from core.schema import Finding, ResearchReport
from evaluation.llm_judge import JudgeResult, LLMJudgeEvaluator, parse_judge_json
from evaluation.metrics import judge_score_summary
from evaluation.run_eval import run_eval
from memory.run_serializer import to_jsonable


class InvalidJSONLLMClient(BaseLLMClient):
    def generate(self, messages, temperature=0.2):
        return LLMResponse(content="not json")


class FailingJudgeLLMClient(BaseLLMClient):
    def generate(self, messages, temperature=0.2):
        raise LLMClientError("forced judge failure")


class TestLLMJudge(unittest.TestCase):
    def test_parse_judge_json_plain_json(self) -> None:
        parsed = parse_judge_json('{"overall_score": 4, "dimension_scores": {}}')

        self.assertEqual(parsed["overall_score"], 4)

    def test_parse_judge_json_fenced_block(self) -> None:
        parsed = parse_judge_json('```json\n{"overall_score": 4, "dimension_scores": {}}\n```')

        self.assertEqual(parsed["overall_score"], 4)

    def test_parse_judge_json_with_surrounding_text(self) -> None:
        parsed = parse_judge_json('Here is the result: {"overall_score": 4, "dimension_scores": {}} done')

        self.assertEqual(parsed["overall_score"], 4)

    def test_fallback_without_llm_client(self) -> None:
        result = LLMJudgeEvaluator().judge(
            question="What affects enterprise AI adoption?",
            report=self._report(),
            findings=self._findings(),
            citation_validation={"passed": True, "citation_count": 1, "grounded_citation_count": 1},
            case_id="case",
        )

        self.assertIsInstance(result, JudgeResult)
        self.assertTrue(result.fallback_used)
        self.assertIn("answer_relevance", result.dimension_scores)

    def test_mock_llm_client_returns_judge_result(self) -> None:
        result = LLMJudgeEvaluator(llm_client=MockLLMClient()).judge(
            question="What affects enterprise AI adoption?",
            report=self._report(),
            findings=self._findings(),
            citation_validation={"passed": True},
        )

        self.assertFalse(result.fallback_used)
        self.assertEqual(result.overall_score, 4.0)
        self.assertTrue(result.passed)

    def test_invalid_json_falls_back(self) -> None:
        result = LLMJudgeEvaluator(llm_client=InvalidJSONLLMClient()).judge(
            question="Question",
            report=self._report(),
            findings=self._findings(),
        )

        self.assertTrue(result.fallback_used)
        self.assertIn("judge response", result.error)

    def test_llm_exception_falls_back(self) -> None:
        result = LLMJudgeEvaluator(llm_client=FailingJudgeLLMClient()).judge(
            question="Question",
            report=self._report(),
            findings=self._findings(),
        )

        self.assertTrue(result.fallback_used)
        self.assertIn("forced judge failure", result.error)

    def test_judge_result_has_five_dimensions(self) -> None:
        result = LLMJudgeEvaluator(llm_client=MockLLMClient()).judge(
            question="Question",
            report=self._report(),
            findings=self._findings(),
        )

        self.assertEqual(
            set(result.dimension_scores),
            {
                "answer_relevance",
                "factual_consistency",
                "citation_quality",
                "completeness",
                "clarity",
            },
        )

    def test_judge_score_summary_calculates_average(self) -> None:
        result = LLMJudgeEvaluator(llm_client=MockLLMClient()).judge(
            question="Question",
            report=self._report(),
            findings=self._findings(),
        )

        summary = judge_score_summary([result])

        self.assertEqual(summary["average_judge_overall_score"], 4.0)
        self.assertEqual(summary["judge_pass_rate"], 1.0)

    def test_run_eval_default_does_not_enable_judge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cases.jsonl"
            path.write_text(self._case_line(), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                result = run_eval(str(path))

        self.assertNotIn("average_judge_overall_score", result["summary"])
        self.assertNotIn("judge_result", result["results"][0])

    def test_run_eval_mock_judge_adds_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cases.jsonl"
            path.write_text(self._case_line(), encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "DEEP_RESEARCH_USE_LLM_JUDGE": "1",
                    "DEEP_RESEARCH_LLM_JUDGE_USE_MOCK": "1",
                },
                clear=True,
            ):
                result = run_eval(str(path))

        self.assertIn("average_judge_overall_score", result["summary"])
        self.assertIn("judge_result", result["results"][0])

    def test_judge_result_is_jsonable(self) -> None:
        result = LLMJudgeEvaluator(llm_client=MockLLMClient()).judge(
            question="Question",
            report=self._report(),
            findings=self._findings(),
        )

        jsonable = to_jsonable(result)

        self.assertEqual(jsonable["overall_score"], 4.0)

    @staticmethod
    def _report() -> ResearchReport:
        return ResearchReport(
            title="Report",
            question="What affects enterprise AI adoption?",
            citations=["C1"],
            markdown=(
                "# Report\n\n"
                "## Background\n\nEnterprise AI adoption context.\n\n"
                "## Key Findings\n\n- Governance and measurable value matter [C1]\n\n"
                "## Conclusion\n\nAdoption depends on governance and value.\n\n"
                "## References\n\n[C1] Source - mock://1"
            ),
        )

    @staticmethod
    def _findings():
        return [Finding(claim="Governance matters", evidence="Evidence", source_url="mock://1")]

    @staticmethod
    def _case_line() -> str:
        return (
            '{"id": "case_judge_test", '
            '"question": "What affects enterprise AI adoption?", '
            '"expected_sections": ["Background", "Key Findings", "Conclusion", "References"], '
            '"expected_min_findings": 3, "expected_min_citations": 3, '
            '"keywords": ["enterprise", "AI"], "optional": false}\n'
        )


if __name__ == "__main__":
    unittest.main()
