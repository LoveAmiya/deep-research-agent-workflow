import unittest

from agents.planner_agent import PlannerAgent
from agents.reader_agent import ReaderAgent
from agents.searcher_agent import SearcherAgent
from agents.writer_agent import WriterAgent
from core.schema import ResearchQuestion, ResearchReport
from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.executor import DAGExecutor
from orchestrator.research_pipeline import build_minimal_research_graph
from orchestrator.state import TaskState
from orchestrator.trace import TraceRecorder


class TestTaskGraph(unittest.TestCase):
    def test_task_graph_can_add_node(self) -> None:
        graph = TaskGraph()
        node = TaskNode(task_id="planner_task", name="Planner Task", agent_name="PlannerAgent")

        graph.add_node(node)

        self.assertIs(graph.get_node("planner_task"), node)

    def test_topological_sort_order_is_correct(self) -> None:
        graph = build_minimal_research_graph()

        order = graph.topological_sort()

        self.assertEqual(
            [node.task_id for node in order],
            ["planner_task", "search_task", "reader_task", "writer_task"],
        )

    def test_missing_dependency_raises_error(self) -> None:
        graph = TaskGraph()
        graph.add_node(
            TaskNode(
                task_id="reader_task",
                name="Reader Task",
                agent_name="ReaderAgent",
                depends_on=["search_task"],
            )
        )

        with self.assertRaises(ValueError):
            graph.validate()

    def test_cycle_dependency_raises_error(self) -> None:
        graph = TaskGraph()
        graph.add_node(
            TaskNode(
                task_id="task_a",
                name="Task A",
                agent_name="AgentA",
                depends_on=["task_b"],
            )
        )
        graph.add_node(
            TaskNode(
                task_id="task_b",
                name="Task B",
                agent_name="AgentB",
                depends_on=["task_a"],
            )
        )

        with self.assertRaises(ValueError):
            graph.topological_sort()


class TestDAGExecutor(unittest.TestCase):
    def setUp(self) -> None:
        self.question = ResearchQuestion(
            question="What are the main factors that affect open-source LLM adoption in enterprises?"
        )
        self.planner = PlannerAgent()
        self.searcher = SearcherAgent()
        self.reader = ReaderAgent()
        self.writer = WriterAgent()

    def test_executor_runs_pipeline_in_order(self) -> None:
        graph = build_minimal_research_graph()
        call_order = []
        handlers = {
            "planner_task": lambda outputs, node: self._record_and_run(
                call_order, "planner_task", self.planner.run, self.question
            ),
            "search_task": lambda outputs, node: self._record_and_run(
                call_order, "search_task", self.searcher.run, outputs["planner_task"]
            ),
            "reader_task": lambda outputs, node: self._record_and_run(
                call_order, "reader_task", self.reader.run, outputs["search_task"]
            ),
            "writer_task": lambda outputs, node: self._record_and_run(
                call_order,
                "writer_task",
                self.writer.run,
                self.question,
                outputs["planner_task"],
                outputs["reader_task"],
            ),
        }

        result = DAGExecutor(graph=graph, handlers=handlers).execute()

        self.assertTrue(result.success)
        self.assertEqual(
            call_order,
            ["planner_task", "search_task", "reader_task", "writer_task"],
        )

    def test_execution_result_contains_research_report(self) -> None:
        result = self._run_success_pipeline()

        self.assertIn("writer_task", result.outputs)
        self.assertIsInstance(result.outputs["writer_task"], ResearchReport)

    def test_success_execution_sets_all_states_to_success(self) -> None:
        result = self._run_success_pipeline()

        self.assertTrue(all(state == TaskState.SUCCESS for state in result.states.values()))

    def test_failed_handler_marks_failed_state(self) -> None:
        graph = TaskGraph()
        graph.add_node(
            TaskNode(task_id="failing_task", name="Failing Task", agent_name="FailingAgent")
        )
        handlers = {
            "failing_task": lambda outputs, node: (_ for _ in ()).throw(RuntimeError("boom"))
        }

        result = DAGExecutor(graph=graph, handlers=handlers).execute()

        self.assertFalse(result.success)
        self.assertEqual(result.states["failing_task"], TaskState.FAILED)

    def test_dependency_failure_marks_downstream_skipped(self) -> None:
        graph = TaskGraph()
        graph.add_node(
            TaskNode(task_id="task_a", name="Task A", agent_name="AgentA")
        )
        graph.add_node(
            TaskNode(
                task_id="task_b",
                name="Task B",
                agent_name="AgentB",
                depends_on=["task_a"],
            )
        )
        handlers = {
            "task_a": lambda outputs, node: (_ for _ in ()).throw(RuntimeError("upstream failure")),
            "task_b": lambda outputs, node: "should not run",
        }

        result = DAGExecutor(graph=graph, handlers=handlers).execute()

        self.assertEqual(result.states["task_a"], TaskState.FAILED)
        self.assertEqual(result.states["task_b"], TaskState.SKIPPED)

    def test_trace_recorder_records_lifecycle_states(self) -> None:
        recorder = TraceRecorder()

        recorder.record("task_1", "Task 1", TaskState.RUNNING)
        recorder.record("task_1", "Task 1", TaskState.SUCCESS)
        recorder.record("task_2", "Task 2", TaskState.FAILED, error="boom")
        recorder.record("task_3", "Task 3", TaskState.SKIPPED)

        states = [event["state"] for event in recorder.to_dict_list()]
        self.assertEqual(states, ["RUNNING", "SUCCESS", "FAILED", "SKIPPED"])

    def _run_success_pipeline(self):
        graph = build_minimal_research_graph()
        handlers = {
            "planner_task": lambda outputs, node: self.planner.run(self.question),
            "search_task": lambda outputs, node: self.searcher.run(outputs["planner_task"]),
            "reader_task": lambda outputs, node: self.reader.run(outputs["search_task"]),
            "writer_task": lambda outputs, node: self.writer.run(
                self.question,
                outputs["planner_task"],
                outputs["reader_task"],
            ),
        }
        return DAGExecutor(graph=graph, handlers=handlers).execute()

    @staticmethod
    def _record_and_run(call_order, task_id, fn, *args):
        call_order.append(task_id)
        return fn(*args)


if __name__ == "__main__":
    unittest.main()
