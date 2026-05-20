import unittest

from agents.base_agent import AgentContext
from agents.blue_agent import BlueAgent
from agents.critic_agent import CriticAgent
from agents.planner_agent import PlannerAgent
from agents.reader_agent import ReaderAgent
from agents.red_agent import RedAgent
from agents.searcher_agent import SearcherAgent
from agents.writer_agent import WriterAgent
from core.schema import RedReviewResult, ResearchQuestion, ResearchReport
from memory.store import SharedMemory
from orchestrator.executor import DAGExecutor
from orchestrator.research_pipeline import build_minimal_research_graph
from orchestrator.state import TaskState


class TestRedBlueReview(unittest.TestCase):
    def setUp(self) -> None:
        self.question = ResearchQuestion(
            question="What are the main factors that affect open-source LLM adoption in enterprises?"
        )
        self.planner = PlannerAgent()
        self.searcher = SearcherAgent()
        self.reader = ReaderAgent()
        self.writer = WriterAgent()
        self.critic = CriticAgent()
        self.red = RedAgent()
        self.blue = BlueAgent()

    def test_red_agent_passes_complete_report(self) -> None:
        report, findings, critic_review = self._build_report_context()

        result = self.red.run(
            AgentContext(
                task_id="red_review_task",
                inputs={
                    "report": report,
                    "findings": findings,
                    "critic_review": critic_review,
                },
            )
        )

        self.assertTrue(result.success)
        self.assertIsInstance(result.output, RedReviewResult)
        self.assertTrue(result.output.passed or len(result.output.issues) == 0)

    def test_red_agent_detects_missing_references(self) -> None:
        report = ResearchReport(
            title="Test Report",
            question="Test question",
            sections=[
                {"title": "Background", "content": "bg"},
                {"title": "Key Findings", "content": "- point"},
                {"title": "Conclusion", "content": "done"},
            ],
            citations=[],
            markdown="# Test Report\n\n## Background\n\nbg\n\n## Key Findings\n\n- point\n\n## Conclusion\n\ndone",
        )
        result = self.red.run(
            AgentContext(
                task_id="red_review_task",
                inputs={"report": report, "findings": [], "critic_review": None},
            )
        )

        self.assertFalse(result.output.passed)
        messages = [issue.message for issue in result.output.issues]
        self.assertIn("Report is missing the References section.", messages)

    def test_red_agent_detects_missing_key_findings(self) -> None:
        report = ResearchReport(
            title="Test Report",
            question="Test question",
            sections=[
                {"title": "Background", "content": "bg"},
                {"title": "Conclusion", "content": "done"},
                {"title": "References", "content": "- mock://1"},
            ],
            citations=["mock://1"],
            markdown="# Test Report\n\n## Background\n\nbg\n\n## Conclusion\n\ndone\n\n## References\n\n- mock://1",
        )
        result = self.red.run(
            AgentContext(
                task_id="red_review_task",
                inputs={"report": report, "findings": [], "critic_review": None},
            )
        )

        self.assertFalse(result.output.passed)
        messages = [issue.message for issue in result.output.issues]
        self.assertIn("Report is missing the Key Findings section.", messages)

    def test_blue_agent_adds_references(self) -> None:
        report, findings, critic_review = self._build_report_context()
        stripped = ResearchReport(
            title=report.title,
            question=report.question,
            sections=[section for section in report.sections if section["title"] != "References"],
            citations=[],
            markdown=report.markdown.replace("## References", "## Removed References"),
        )
        red_review = self.red.run(
            AgentContext(
                task_id="red_review_task",
                inputs={"report": stripped, "findings": findings, "critic_review": critic_review},
            )
        ).output

        result = self.blue.run(
            AgentContext(
                task_id="blue_revision_task",
                inputs={"report": stripped, "red_review": red_review, "findings": findings},
            )
        )

        self.assertTrue(result.success)
        self.assertIn("## References", result.output.revised_report.markdown)
        self.assertGreater(len(result.output.revised_report.citations), 0)

    def test_blue_agent_adds_key_findings(self) -> None:
        report, findings, critic_review = self._build_report_context()
        stripped = ResearchReport(
            title=report.title,
            question=report.question,
            sections=[section for section in report.sections if section["title"] != "Key Findings"],
            citations=report.citations,
            markdown=report.markdown.replace("## Key Findings", "## Removed Key Findings"),
        )
        red_review = self.red.run(
            AgentContext(
                task_id="red_review_task",
                inputs={"report": stripped, "findings": findings, "critic_review": critic_review},
            )
        ).output

        result = self.blue.run(
            AgentContext(
                task_id="blue_revision_task",
                inputs={"report": stripped, "red_review": red_review, "findings": findings},
            )
        )

        self.assertTrue(result.success)
        self.assertIn("## Key Findings", result.output.revised_report.markdown)

    def test_blue_revision_result_contains_revised_report(self) -> None:
        report, findings, critic_review = self._build_report_context()
        red_review = self.red.run(
            AgentContext(
                task_id="red_review_task",
                inputs={"report": report, "findings": findings, "critic_review": critic_review},
            )
        ).output
        result = self.blue.run(
            AgentContext(
                task_id="blue_revision_task",
                inputs={"report": report, "red_review": red_review, "findings": findings},
            )
        )

        self.assertIsInstance(result.output.revised_report, ResearchReport)

    def test_red_agent_writes_shared_memory(self) -> None:
        memory = SharedMemory()
        report, findings, critic_review = self._build_report_context()

        result = self.red.run(
            AgentContext(
                task_id="red_review_task",
                inputs={"report": report, "findings": findings, "critic_review": critic_review},
                memory=memory,
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(len(memory.list_by_type("red_review")), 1)

    def test_blue_agent_writes_shared_memory(self) -> None:
        memory = SharedMemory()
        report, findings, critic_review = self._build_report_context()
        red_review = self.red.run(
            AgentContext(
                task_id="red_review_task",
                inputs={"report": report, "findings": findings, "critic_review": critic_review},
            )
        ).output

        result = self.blue.run(
            AgentContext(
                task_id="blue_revision_task",
                inputs={"report": report, "red_review": red_review, "findings": findings},
                memory=memory,
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(len(memory.list_by_type("blue_revision")), 1)

    def test_research_dag_contains_red_and_blue_tasks(self) -> None:
        graph = build_minimal_research_graph()

        self.assertIn("red_review_task", graph.nodes)
        self.assertIn("blue_revision_task", graph.nodes)
        self.assertEqual(graph.get_node("red_review_task").depends_on, ["critic_task"])
        self.assertEqual(graph.get_node("blue_revision_task").depends_on, ["red_review_task"])

    def test_full_pipeline_reaches_blue_revision_task(self) -> None:
        result = self._run_success_dag()

        self.assertIn("blue_revision_task", result.outputs)
        self.assertTrue(result.outputs["blue_revision_task"].success)

    def test_blue_revision_task_state_is_success(self) -> None:
        result = self._run_success_dag()

        self.assertEqual(result.states["blue_revision_task"], TaskState.SUCCESS)

    def _build_report_context(self):
        plan = self.planner.run(
            AgentContext(task_id="planner_task", inputs={"question": self.question})
        ).output
        search_results = self.searcher.run(
            AgentContext(task_id="search_task", inputs={"plan": plan})
        ).output
        findings = self.reader.run(
            AgentContext(task_id="reader_task", inputs={"search_results": search_results})
        ).output
        report = self.writer.run(
            AgentContext(
                task_id="writer_task",
                inputs={"question": self.question, "plan": plan, "findings": findings},
            )
        ).output
        critic_review = self.critic.run(
            AgentContext(
                task_id="critic_task",
                inputs={"report": report, "findings": findings},
            )
        ).output
        return report, findings, critic_review

    def _run_success_dag(self):
        memory = SharedMemory()
        graph = build_minimal_research_graph()
        handlers = {
            "planner_task": lambda outputs, node: self.planner.run(
                AgentContext(task_id=node.task_id, inputs={"question": self.question}, memory=memory)
            ),
            "search_task": lambda outputs, node: self.searcher.run(
                AgentContext(
                    task_id=node.task_id,
                    inputs={"plan": outputs["planner_task"].output},
                    memory=memory,
                )
            ),
            "reader_task": lambda outputs, node: self.reader.run(
                AgentContext(
                    task_id=node.task_id,
                    inputs={"search_results": outputs["search_task"].output},
                    memory=memory,
                )
            ),
            "writer_task": lambda outputs, node: self.writer.run(
                AgentContext(
                    task_id=node.task_id,
                    inputs={
                        "question": self.question,
                        "plan": outputs["planner_task"].output,
                        "findings": outputs["reader_task"].output,
                    },
                    memory=memory,
                )
            ),
            "critic_task": lambda outputs, node: self.critic.run(
                AgentContext(
                    task_id=node.task_id,
                    inputs={
                        "report": outputs["writer_task"].output,
                        "findings": outputs["reader_task"].output,
                    },
                    memory=memory,
                )
            ),
            "red_review_task": lambda outputs, node: self.red.run(
                AgentContext(
                    task_id=node.task_id,
                    inputs={
                        "report": outputs["writer_task"].output,
                        "findings": outputs["reader_task"].output,
                        "critic_review": outputs["critic_task"].output,
                    },
                    memory=memory,
                )
            ),
            "blue_revision_task": lambda outputs, node: self.blue.run(
                AgentContext(
                    task_id=node.task_id,
                    inputs={
                        "report": outputs["writer_task"].output,
                        "red_review": outputs["red_review_task"].output,
                        "findings": outputs["reader_task"].output,
                    },
                    memory=memory,
                )
            ),
        }
        return DAGExecutor(graph=graph, handlers=handlers).execute()


if __name__ == "__main__":
    unittest.main()
