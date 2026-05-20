import unittest

from agents.base_agent import AgentContext
from agents.blue_agent import BlueAgent
from agents.reader_agent import ReaderAgent
from agents.red_agent import RedAgent
from agents.writer_agent import WriterAgent
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
from evaluation.metrics import citation_grounding_score
from orchestrator.research_pipeline import run_research_pipeline
from tools.citation_tool import CitationRegistry, CitationValidator


class TestCitationGrounding(unittest.TestCase):
    def test_registry_can_add_evidence(self) -> None:
        registry = CitationRegistry()

        evidence = registry.add_evidence("mock://1", "Evidence text", source_title="Source 1")

        self.assertEqual(evidence.evidence_id, "E1")
        self.assertEqual(evidence.source_url, "mock://1")

    def test_registry_can_add_citation(self) -> None:
        registry = CitationRegistry()
        evidence = registry.add_evidence("mock://1", "Evidence text")

        citation = registry.add_citation("mock://1", evidence_id=evidence.evidence_id)

        self.assertEqual(citation.citation_id, "C1")
        self.assertEqual(citation.evidence_id, "E1")

    def test_registry_deduplicates_evidence(self) -> None:
        registry = CitationRegistry()

        first = registry.add_evidence("mock://1", "Evidence text")
        second = registry.add_evidence("mock://1", "Evidence text")

        self.assertEqual(first.evidence_id, second.evidence_id)
        self.assertEqual(len(registry.list_evidence()), 1)

    def test_references_markdown_contains_citation_and_url(self) -> None:
        registry = CitationRegistry()
        evidence = registry.add_evidence("mock://1", "Evidence text", source_title="Source 1")
        registry.add_citation("mock://1", evidence_id=evidence.evidence_id, source_title="Source 1")

        markdown = registry.to_references_markdown()

        self.assertIn("[C1]", markdown)
        self.assertIn("mock://1", markdown)

    def test_validator_accepts_complete_report(self) -> None:
        registry = CitationRegistry()
        evidence = registry.add_evidence("mock://1", "Evidence text", source_title="Source 1")
        registry.add_citation("mock://1", evidence_id=evidence.evidence_id, source_title="Source 1")
        report = ResearchReport(
            title="Report",
            question="Question",
            citations=["C1"],
            markdown="# Report\n\n## Key Findings\n\n- Claim [C1]\n\n## References\n\n[C1] Source 1 - mock://1",
        )

        result = CitationValidator().validate_report_citations(report, registry)

        self.assertTrue(result["passed"])
        self.assertEqual(result["grounded_citation_count"], 1)

    def test_validator_detects_missing_citation_marker(self) -> None:
        registry = CitationRegistry()
        evidence = registry.add_evidence("mock://1", "Evidence text")
        registry.add_citation("mock://1", evidence_id=evidence.evidence_id)
        report = ResearchReport(
            title="Report",
            question="Question",
            citations=["C1"],
            markdown="# Report\n\n## References\n\n[C1] Untitled - mock://1",
        )

        result = CitationValidator().validate_report_citations(report, registry)

        self.assertFalse(result["passed"])
        self.assertIn("Some report citations are missing from markdown markers.", result["issues"])

    def test_reader_adds_citation_id_to_findings(self) -> None:
        registry = CitationRegistry()
        search_results = [
            SearchResult(title="Source 1", url="mock://1", snippet="Evidence text", source="mock")
        ]

        result = ReaderAgent().run(
            AgentContext(
                task_id="reader_task",
                inputs={"search_results": search_results, "citation_registry": registry},
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output[0].evidence_id, "E1")
        self.assertEqual(result.output[0].citation_id, "C1")

    def test_writer_generates_citation_markers(self) -> None:
        registry, findings = self._grounded_findings()
        question = ResearchQuestion(question="What matters?")
        plan = ResearchPlan(question=question.question)

        result = WriterAgent().run(
            AgentContext(
                task_id="writer_task",
                inputs={
                    "question": question,
                    "plan": plan,
                    "findings": findings,
                    "citation_registry": registry,
                },
            )
        )

        self.assertTrue(result.success)
        self.assertIn("[C1]", result.output.markdown)
        self.assertEqual(result.output.citations, ["C1"])

    def test_red_agent_detects_citation_issue(self) -> None:
        registry, findings = self._grounded_findings()
        report = ResearchReport(
            title="Report",
            question="Question",
            citations=["C1"],
            markdown="# Report\n\n## Background\n\nbg\n\n## Key Findings\n\n- Claim without marker\n\n## Conclusion\n\ndone\n\n## References\n\n[C1] Source - mock://1",
        )

        result = RedAgent().run(
            AgentContext(
                task_id="red_review_task",
                inputs={
                    "report": report,
                    "findings": findings,
                    "critic_review": None,
                    "citation_registry": registry,
                },
            )
        )

        self.assertFalse(result.output.passed)
        self.assertTrue(any(issue.category == "citation" for issue in result.output.issues))

    def test_blue_agent_repairs_references_or_marker(self) -> None:
        registry, findings = self._grounded_findings()
        report = ResearchReport(
            title="Report",
            question="Question",
            sections=[
                {"title": "Background", "content": "bg"},
                {"title": "Key Findings", "content": "- Claim without marker"},
                {"title": "Conclusion", "content": "done"},
            ],
            citations=["C1"],
            markdown="# Report\n\n## Background\n\nbg\n\n## Key Findings\n\n- Claim without marker\n\n## Conclusion\n\ndone",
        )
        red_review = RedReviewResult(
            passed=False,
            issues=[
                ReviewIssue(
                    issue_id="red-1",
                    category="citation",
                    severity="high",
                    message="Report is missing the References section.",
                )
            ],
            summary="citation issue",
        )

        result = BlueAgent().run(
            AgentContext(
                task_id="blue_revision_task",
                inputs={
                    "report": report,
                    "red_review": red_review,
                    "findings": findings,
                    "citation_registry": registry,
                },
            )
        )

        self.assertIsInstance(result.output, BlueRevisionResult)
        self.assertIn("## References", result.output.revised_report.markdown)
        self.assertIn("[C1]", result.output.revised_report.markdown)

    def test_pipeline_returns_citation_validation(self) -> None:
        result = run_research_pipeline("What affects enterprise LLM adoption?")

        self.assertIn("citation_validation", result)
        self.assertTrue(result["citation_validation"]["passed"])
        self.assertIn("[C1]", result["report"].markdown)

    def test_citation_grounding_score_calculates_ratio(self) -> None:
        report = ResearchReport(title="R", question="Q", citations=["C1", "C2"], markdown="")
        validation = {
            "passed": False,
            "citation_count": 2,
            "grounded_citation_count": 1,
        }

        score = citation_grounding_score(report, validation)

        self.assertEqual(score, 0.5)

    @staticmethod
    def _grounded_findings():
        registry = CitationRegistry()
        evidence = registry.add_evidence("mock://1", "Evidence text", source_title="Source")
        citation = registry.add_citation(
            "mock://1",
            evidence_id=evidence.evidence_id,
            source_title="Source",
            quote="Evidence text",
        )
        findings = [
            Finding(
                claim="Claim",
                evidence="Evidence text",
                source_url="mock://1",
                evidence_id=evidence.evidence_id,
                citation_id=citation.citation_id,
                source_title="Source",
            )
        ]
        return registry, findings


if __name__ == "__main__":
    unittest.main()
