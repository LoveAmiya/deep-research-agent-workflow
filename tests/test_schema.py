import unittest

from core.schema import (
    BlueRevisionResult,
    Finding,
    RedReviewResult,
    ResearchPlan,
    ResearchQuestion,
    ResearchReport,
    ReviewIssue,
    SearchResult,
)


class TestSchemaInitialization(unittest.TestCase):
    def test_research_question_initialization(self) -> None:
        question = ResearchQuestion(
            question="What are the risks of synthetic data in evaluation pipelines?",
            question_id="q-001",
            query="What are the risks of synthetic data in evaluation pipelines?",
            context="Focus on model assessment.",
        )

        self.assertEqual(question.question_id, "q-001")
        self.assertEqual(question.question, "What are the risks of synthetic data in evaluation pipelines?")
        self.assertEqual(question.query, "What are the risks of synthetic data in evaluation pipelines?")
        self.assertEqual(question.context, "Focus on model assessment.")

    def test_research_plan_initialization(self) -> None:
        plan = ResearchPlan(
            question="What are the risks of synthetic data in evaluation pipelines?",
            question_id="q-001",
            objective="Investigate evaluation risks.",
            sub_questions=["define risks", "collect examples", "summarize findings"],
            search_queries=["synthetic data evaluation risks"],
            expected_sections=["Background", "Key Findings", "Conclusion"],
            steps=["define risks", "collect examples", "summarize findings"],
        )

        self.assertEqual(plan.question_id, "q-001")
        self.assertEqual(plan.steps[0], "define risks")
        self.assertEqual(len(plan.steps), 3)

    def test_search_result_initialization(self) -> None:
        result = SearchResult(
            title="Example Source",
            url="https://example.com/source",
            snippet="A short summary.",
            source="example",
        )

        self.assertEqual(result.title, "Example Source")
        self.assertEqual(result.url, "https://example.com/source")
        self.assertEqual(result.source, "example")

    def test_finding_and_report_initialization(self) -> None:
        finding = Finding(
            claim="Synthetic data can distort benchmark validity.",
            evidence="distribution shift and label leakage can affect benchmark outcomes.",
            source_url="https://example.com/source",
            finding_id="f-001",
            summary="Synthetic data can distort benchmark validity.",
            confidence=0.7,
        )
        report = ResearchReport(
            title="Evaluation Risks Report",
            question="What are the risks of synthetic data in evaluation pipelines?",
            sections=[{"title": "Key Findings", "content": "Synthetic data can distort benchmark validity."}],
            citations=["https://example.com/source"],
            markdown="# Evaluation Risks Report",
            question_id="q-001",
            summary="A minimal Phase 0 report object.",
            findings=[finding],
            references=["https://example.com/source"],
        )

        self.assertEqual(report.question_id, "q-001")
        self.assertEqual(report.findings[0].finding_id, "f-001")
        self.assertEqual(report.references[0], "https://example.com/source")

    def test_review_related_schema_initialization(self) -> None:
        issue = ReviewIssue(
            issue_id="issue-1",
            category="citation",
            severity="medium",
            message="References section is missing.",
            evidence="No references detected",
            suggestion="Add a References section.",
        )
        report = ResearchReport(
            title="Revised Report",
            question="How should teams evaluate evidence quality?",
            sections=[{"title": "References", "content": "- mock://source/1"}],
            citations=["mock://source/1"],
            markdown="# Revised Report\n\n## References\n\n- mock://source/1",
        )
        red_result = RedReviewResult(
            passed=False,
            issues=[issue],
            summary="Found 1 issue.",
        )
        blue_result = BlueRevisionResult(
            revised_report=report,
            fixed_issue_ids=["issue-1"],
            remaining_issue_ids=[],
            revision_notes=["Added References section."],
        )

        self.assertEqual(red_result.issues[0].issue_id, "issue-1")
        self.assertEqual(blue_result.revised_report.title, "Revised Report")
        self.assertEqual(blue_result.fixed_issue_ids, ["issue-1"])


if __name__ == "__main__":
    unittest.main()
