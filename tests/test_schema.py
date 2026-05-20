import unittest

from core.schema import Finding, ResearchPlan, ResearchQuestion, ResearchReport, SearchResult


class TestSchemaInitialization(unittest.TestCase):
    def test_research_question_initialization(self) -> None:
        question = ResearchQuestion(
            question_id="q-001",
            query="What are the risks of synthetic data in evaluation pipelines?",
            context="Focus on model assessment.",
        )

        self.assertEqual(question.question_id, "q-001")
        self.assertEqual(question.query, "What are the risks of synthetic data in evaluation pipelines?")
        self.assertEqual(question.context, "Focus on model assessment.")

    def test_research_plan_initialization(self) -> None:
        plan = ResearchPlan(
            question_id="q-001",
            objective="Investigate evaluation risks.",
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
            finding_id="f-001",
            summary="Synthetic data can distort benchmark validity.",
            evidence=["distribution shift", "label leakage"],
            confidence="medium",
        )
        report = ResearchReport(
            question_id="q-001",
            title="Evaluation Risks Report",
            summary="A minimal Phase 0 report object.",
            findings=[finding],
            references=["https://example.com/source"],
        )

        self.assertEqual(report.question_id, "q-001")
        self.assertEqual(report.findings[0].finding_id, "f-001")
        self.assertEqual(report.references[0], "https://example.com/source")


if __name__ == "__main__":
    unittest.main()
