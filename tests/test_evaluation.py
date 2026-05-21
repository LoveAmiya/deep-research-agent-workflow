import tempfile
import unittest
from pathlib import Path

from core.schema import BlueRevisionResult, Finding, RedReviewResult, ResearchReport, ReviewIssue
from evaluation.metrics import (
    citation_coverage,
    finding_coverage,
    keyword_coverage,
    memory_completeness,
    red_blue_improvement,
    section_coverage,
)
from evaluation.run_eval import _load_eval_json, load_cases, run_case, run_eval


class TestEvaluation(unittest.TestCase):
    def test_load_cases_can_load_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cases.jsonl"
            path.write_text(
                '{"id": "case_test", "question": "Test?", "expected_sections": [], '
                '"expected_min_findings": 0, "expected_min_citations": 0, '
                '"keywords": [], "optional": false}\n',
                encoding="utf-8",
            )

            cases = load_cases(path)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["id"], "case_test")

    def test_section_coverage_calculates_ratio(self) -> None:
        report = self._report(markdown="# T\n\n## Background\n\nA\n\n## References\n\n- mock://1")

        score = section_coverage(report, ["Background", "Key Findings", "References"])

        self.assertEqual(score, 2 / 3)

    def test_citation_coverage_calculates_ratio(self) -> None:
        report = self._report(citations=["mock://1"])

        score = citation_coverage(report, 2)

        self.assertEqual(score, 0.5)

    def test_finding_coverage_calculates_ratio(self) -> None:
        findings = [Finding(claim="a", evidence="e", source_url="mock://1")]

        score = finding_coverage(findings, 2)

        self.assertEqual(score, 0.5)

    def test_keyword_coverage_calculates_ratio(self) -> None:
        report = self._report(markdown="Open-source LLM enterprise adoption")

        score = keyword_coverage(report, ["open-source", "LLM", "missing"])

        self.assertEqual(score, 2 / 3)

    def test_memory_completeness_detects_required_items(self) -> None:
        items = [{"item_type": item_type} for item_type in [
            "plan",
            "search_results",
            "findings",
            "report",
            "review",
            "red_review",
            "blue_revision",
        ]]

        score = memory_completeness(items)

        self.assertEqual(score, 1.0)

    def test_red_blue_improvement_scores_fixed_issues(self) -> None:
        issue = ReviewIssue(
            issue_id="red-1",
            category="citation",
            severity="high",
            message="Missing references",
        )
        red_review = RedReviewResult(passed=False, issues=[issue], summary="Found 1 issue")
        blue_revision = BlueRevisionResult(
            revised_report=self._report(),
            fixed_issue_ids=["red-1"],
            remaining_issue_ids=[],
            revision_notes=["Fixed references"],
        )

        score = red_blue_improvement(red_review, blue_revision)

        self.assertEqual(score, 1.0)

    def test_run_case_runs_local_pipeline(self) -> None:
        case = {
            "id": "case_eval_test",
            "question": "What affects open-source LLM adoption in enterprise AI?",
            "expected_sections": ["Background", "Key Findings", "Conclusion", "References"],
            "expected_min_findings": 3,
            "expected_min_citations": 3,
            "keywords": ["open-source", "LLM", "enterprise"],
            "optional": False,
        }

        result = run_case(case)

        self.assertEqual(result["case_id"], "case_eval_test")
        self.assertIn("section_coverage", result["metrics"])
        self.assertTrue(result["success"])

    def test_run_eval_returns_summary_dict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cases.jsonl"
            path.write_text(
                '{"id": "case_eval_test", '
                '"question": "What affects open-source LLM adoption in enterprise AI?", '
                '"expected_sections": ["Background", "Key Findings", "Conclusion", "References"], '
                '"expected_min_findings": 3, "expected_min_citations": 3, '
                '"keywords": ["open-source", "LLM", "enterprise"], "optional": false}\n',
                encoding="utf-8",
            )

            result = run_eval(str(path))

        self.assertEqual(result["summary"]["total_cases"], 1)
        self.assertEqual(result["summary"]["failed_cases"], 0)

    def test_load_eval_json_missing_file_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.json"

            with self.assertRaises(FileNotFoundError) as context:
                _load_eval_json(str(missing_path))

        self.assertIn("Evaluation result file not found", str(context.exception))

    @staticmethod
    def _report(markdown: str = "# T", citations=None) -> ResearchReport:
        return ResearchReport(
            title="T",
            question="Q",
            sections=[],
            citations=citations or [],
            markdown=markdown,
        )


if __name__ == "__main__":
    unittest.main()
