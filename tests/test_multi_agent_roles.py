import unittest

from agents.base_agent import AgentContext, AgentResult
from agents.critic_agent import CriticAgent
from agents.planner_agent import PlannerAgent
from agents.reader_agent import ReaderAgent
from agents.searcher_agent import SearcherAgent
from agents.writer_agent import WriterAgent
from core.schema import ResearchQuestion, ResearchReport
from orchestrator.executor import DAGExecutor
from orchestrator.research_pipeline import build_minimal_research_graph
from orchestrator.state import TaskState


class TestMultiAgentRoles(unittest.TestCase):
    def setUp(self) -> None:
        self.question = ResearchQuestion(
            question="What are the main factors that affect open-source LLM adoption in enterprises?"
        )
        self.planner = PlannerAgent()
        self.searcher = SearcherAgent()
        self.reader = ReaderAgent()
        self.writer = WriterAgent()
        self.critic = CriticAgent()

    def test_planner_returns_agent_result(self) -> None:
        result = self.planner.run(
            AgentContext(task_id="planner_task", inputs={"question": self.question})
        )

        self.assertIsInstance(result, AgentResult)
        self.assertTrue(result.success)
        self.assertEqual(result.metadata["role"], "planner")

    def test_searcher_returns_agent_result(self) -> None:
        plan = self.planner.run(
            AgentContext(task_id="planner_task", inputs={"question": self.question})
        ).output
        result = self.searcher.run(
            AgentContext(task_id="search_task", inputs={"plan": plan})
        )

        self.assertIsInstance(result, AgentResult)
        self.assertTrue(result.success)
        self.assertEqual(result.metadata["role"], "searcher")

    def test_reader_returns_agent_result(self) -> None:
        plan = self.planner.run(
            AgentContext(task_id="planner_task", inputs={"question": self.question})
        ).output
        search_results = self.searcher.run(
            AgentContext(task_id="search_task", inputs={"plan": plan})
        ).output
        result = self.reader.run(
            AgentContext(task_id="reader_task", inputs={"search_results": search_results})
        )

        self.assertIsInstance(result, AgentResult)
        self.assertTrue(result.success)
        self.assertEqual(result.metadata["role"], "reader")

    def test_writer_returns_agent_result(self) -> None:
        plan = self.planner.run(
            AgentContext(task_id="planner_task", inputs={"question": self.question})
        ).output
        search_results = self.searcher.run(
            AgentContext(task_id="search_task", inputs={"plan": plan})
        ).output
        findings = self.reader.run(
            AgentContext(task_id="reader_task", inputs={"search_results": search_results})
        ).output
        result = self.writer.run(
            AgentContext(
                task_id="writer_task",
                inputs={"question": self.question, "plan": plan, "findings": findings},
            )
        )

        self.assertIsInstance(result, AgentResult)
        self.assertTrue(result.success)
        self.assertEqual(result.metadata["role"], "writer")

    def test_critic_reviews_complete_report(self) -> None:
        report, findings = self._build_report_and_findings()
        result = self.critic.run(
            AgentContext(
                task_id="critic_task",
                inputs={"report": report, "findings": findings},
            )
        )

        self.assertTrue(result.success)
        self.assertTrue(result.output["passed"])
        self.assertEqual(result.output["issues"], [])

    def test_critic_detects_missing_references(self) -> None:
        report = ResearchReport(
            title="Incomplete Report",
            question="Test question",
            sections=[{"title": "Key Findings", "content": "Missing refs"}],
            citations=[],
            markdown="# Incomplete Report\n\n## Key Findings\n\nMissing refs",
        )
        result = self.critic.run(
            AgentContext(
                task_id="critic_task",
                inputs={"report": report, "findings": []},
            )
        )

        self.assertTrue(result.success)
        self.assertFalse(result.output["passed"])
        self.assertIn("Report is missing the References section.", result.output["issues"])
        self.assertIn("Report does not contain any citations.", result.output["issues"])

    def test_dag_contains_critic_task(self) -> None:
        graph = build_minimal_research_graph()

        self.assertIn("critic_task", graph.nodes)
        self.assertEqual(graph.get_node("critic_task").depends_on, ["writer_task"])

    def test_full_dag_pipeline_reaches_critic_task(self) -> None:
        result = self._run_success_dag()

        self.assertIn("critic_task", result.outputs)
        self.assertTrue(result.outputs["critic_task"].output["passed"])

    def test_critic_task_state_is_success(self) -> None:
        result = self._run_success_dag()

        self.assertEqual(result.states["critic_task"], TaskState.SUCCESS)

    def _build_report_and_findings(self):
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
        return report, findings

    def _run_success_dag(self):
        graph = build_minimal_research_graph()
        handlers = {
            "planner_task": lambda outputs, node: self.planner.run(
                AgentContext(task_id=node.task_id, inputs={"question": self.question})
            ),
            "search_task": lambda outputs, node: self.searcher.run(
                AgentContext(
                    task_id=node.task_id,
                    inputs={"plan": outputs["planner_task"].output},
                )
            ),
            "reader_task": lambda outputs, node: self.reader.run(
                AgentContext(
                    task_id=node.task_id,
                    inputs={"search_results": outputs["search_task"].output},
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
                )
            ),
            "critic_task": lambda outputs, node: self.critic.run(
                AgentContext(
                    task_id=node.task_id,
                    inputs={
                        "report": outputs["writer_task"].output,
                        "findings": outputs["reader_task"].output,
                    },
                )
            ),
        }
        return DAGExecutor(graph=graph, handlers=handlers).execute()


if __name__ == "__main__":
    unittest.main()
