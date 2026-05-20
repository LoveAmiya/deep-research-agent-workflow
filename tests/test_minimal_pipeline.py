import unittest

from agents.planner_agent import PlannerAgent
from agents.reader_agent import ReaderAgent
from agents.searcher_agent import SearcherAgent
from agents.writer_agent import WriterAgent
from core.schema import ResearchQuestion
from main import build_demo_report


class TestMinimalPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.question = ResearchQuestion(
            question="What are the main factors that affect open-source LLM adoption in enterprises?"
        )
        self.planner = PlannerAgent()
        self.searcher = SearcherAgent()
        self.reader = ReaderAgent()
        self.writer = WriterAgent()

    def test_planner_generates_non_empty_plan(self) -> None:
        plan = self.planner.run(self.question)

        self.assertEqual(plan.question, self.question.question)
        self.assertEqual(len(plan.sub_questions), 3)
        self.assertEqual(len(plan.search_queries), 3)
        self.assertIn("Background", plan.expected_sections)
        self.assertIn("Key Findings", plan.expected_sections)
        self.assertIn("Conclusion", plan.expected_sections)

    def test_searcher_returns_non_empty_mock_results(self) -> None:
        plan = self.planner.run(self.question)
        results = self.searcher.run(plan)

        self.assertGreater(len(results), 0)
        self.assertTrue(all(result.source == "mock" for result in results))
        self.assertTrue(all(result.url.startswith("mock://") for result in results))

    def test_reader_returns_non_empty_findings(self) -> None:
        plan = self.planner.run(self.question)
        results = self.searcher.run(plan)
        findings = self.reader.run(results)

        self.assertGreater(len(findings), 0)
        self.assertTrue(all(finding.claim for finding in findings))
        self.assertTrue(all(finding.source_url.startswith("mock://") for finding in findings))

    def test_writer_generates_markdown_report(self) -> None:
        plan = self.planner.run(self.question)
        results = self.searcher.run(plan)
        findings = self.reader.run(results)
        report = self.writer.run(self.question, plan, findings)

        self.assertTrue(report.markdown)
        self.assertIn("# Research Report:", report.markdown)
        self.assertIn("## Key Findings", report.markdown)
        self.assertIn("## References", report.markdown)

    def test_full_pipeline_runs(self) -> None:
        plan = self.planner.run(self.question)
        results = self.searcher.run(plan)
        findings = self.reader.run(results)
        report = self.writer.run(self.question, plan, findings)

        self.assertEqual(report.question, self.question.question)
        self.assertGreater(len(report.sections), 0)
        self.assertGreater(len(report.citations), 0)

    def test_demo_output_contains_expected_sections(self) -> None:
        output = build_demo_report()

        self.assertIn("# Research Report:", output)
        self.assertIn("## Key Findings", output)
        self.assertIn("## References", output)
        self.assertNotIn("http://", output)
        self.assertNotIn("https://", output)


if __name__ == "__main__":
    unittest.main()
