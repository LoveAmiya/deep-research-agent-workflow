import unittest

from agents.base_agent import AgentContext
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
        plan_result = self.planner.run(
            AgentContext(task_id="planner_task", inputs={"question": self.question})
        )
        plan = plan_result.output

        self.assertTrue(plan_result.success)
        self.assertEqual(plan.question, self.question.question)
        self.assertEqual(len(plan.sub_questions), 3)
        self.assertEqual(len(plan.search_queries), 3)
        self.assertIn("Background", plan.expected_sections)
        self.assertIn("Key Findings", plan.expected_sections)
        self.assertIn("Conclusion", plan.expected_sections)

    def test_searcher_returns_non_empty_mock_results(self) -> None:
        plan = self.planner.run(
            AgentContext(task_id="planner_task", inputs={"question": self.question})
        ).output
        results_result = self.searcher.run(
            AgentContext(task_id="search_task", inputs={"plan": plan})
        )
        results = results_result.output

        self.assertTrue(results_result.success)
        self.assertGreater(len(results), 0)
        self.assertTrue(all(result.source == "mock" for result in results))
        self.assertTrue(all(result.url.startswith("mock://") for result in results))

    def test_reader_returns_non_empty_findings(self) -> None:
        plan = self.planner.run(
            AgentContext(task_id="planner_task", inputs={"question": self.question})
        ).output
        results = self.searcher.run(
            AgentContext(task_id="search_task", inputs={"plan": plan})
        ).output
        findings_result = self.reader.run(
            AgentContext(task_id="reader_task", inputs={"search_results": results})
        )
        findings = findings_result.output

        self.assertTrue(findings_result.success)
        self.assertGreater(len(findings), 0)
        self.assertTrue(all(finding.claim for finding in findings))
        self.assertTrue(all(finding.source_url.startswith("mock://") for finding in findings))

    def test_writer_generates_markdown_report(self) -> None:
        plan = self.planner.run(
            AgentContext(task_id="planner_task", inputs={"question": self.question})
        ).output
        results = self.searcher.run(
            AgentContext(task_id="search_task", inputs={"plan": plan})
        ).output
        findings = self.reader.run(
            AgentContext(task_id="reader_task", inputs={"search_results": results})
        ).output
        report_result = self.writer.run(
            AgentContext(
                task_id="writer_task",
                inputs={"question": self.question, "plan": plan, "findings": findings},
            )
        )
        report = report_result.output

        self.assertTrue(report_result.success)
        self.assertTrue(report.markdown)
        self.assertIn("# Research Report:", report.markdown)
        self.assertIn("## Key Findings", report.markdown)
        self.assertIn("## References", report.markdown)

    def test_full_pipeline_runs(self) -> None:
        plan = self.planner.run(
            AgentContext(task_id="planner_task", inputs={"question": self.question})
        ).output
        results = self.searcher.run(
            AgentContext(task_id="search_task", inputs={"plan": plan})
        ).output
        findings = self.reader.run(
            AgentContext(task_id="reader_task", inputs={"search_results": results})
        ).output
        report = self.writer.run(
            AgentContext(
                task_id="writer_task",
                inputs={"question": self.question, "plan": plan, "findings": findings},
            )
        ).output

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
