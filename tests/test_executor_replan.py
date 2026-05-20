import tempfile
import unittest

from orchestrator.checkpoint import JSONCheckpointStore, RunCheckpoint
from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.executor import DAGExecutor
from orchestrator.state import TaskState


class TestExecutorReplan(unittest.TestCase):
    def test_failed_node_triggers_replan_and_new_node_executes(self) -> None:
        graph = self._search_reader_graph()
        calls = []

        result = DAGExecutor(
            graph=graph,
            handlers={
                "search_task": lambda outputs, node: (_ for _ in ()).throw(RuntimeError("search boom")),
                "reader_task": lambda outputs, node: calls.append("reader") or outputs[
                    "search_task_replan_1_alternative_search"
                ],
            },
            replan_enabled=True,
            max_replan_attempts=2,
        ).execute()

        self.assertTrue(result.success)
        self.assertEqual(result.states["search_task"], TaskState.SKIPPED)
        self.assertEqual(result.states["search_task_replan_1_alternative_search"], TaskState.SUCCESS)
        self.assertEqual(result.metadata["replan_attempts"], 1)
        self.assertIn("add_followup_search", result.metadata["replan_actions"])

    def test_replan_checkpoint_metadata_is_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            graph = self._search_reader_graph()
            store = JSONCheckpointStore(temp_dir)
            checkpoint = RunCheckpoint.new("task", run_id="run-1")

            result = DAGExecutor(
                graph=graph,
                handlers={
                    "search_task": lambda outputs, node: (_ for _ in ()).throw(RuntimeError("search boom")),
                    "reader_task": lambda outputs, node: outputs["search_task_replan_1_alternative_search"],
                },
                checkpoint_store=store,
                checkpoint=checkpoint,
                checkpoint_enabled=True,
                replan_enabled=True,
            ).execute()
            loaded = store.load_checkpoint("run-1")

            self.assertTrue(result.success)
            self.assertEqual(loaded.metadata["replan_attempts"], 1)
            self.assertIn("search_task_replan_1_alternative_search", loaded.metadata["generated_replan_nodes"])

    def test_replan_does_not_loop_forever_and_force_synthesis_is_used(self) -> None:
        graph = self._single_search_graph()

        result = DAGExecutor(
            graph=graph,
            handlers={"search_task": lambda outputs, node: (_ for _ in ()).throw(RuntimeError("boom"))},
            replan_enabled=True,
            max_replan_attempts=0,
        ).execute()

        self.assertTrue(result.success)
        self.assertTrue(result.metadata["force_synthesis_used"])
        self.assertEqual(result.metadata["replan_attempts"], 1)
        self.assertTrue(result.outputs["search_task"].metadata["partial_report"])

    def test_max_replan_attempts_limits_followup_nodes(self) -> None:
        graph = self._chain_graph()

        def handler(outputs, node):
            raise RuntimeError(f"{node.task_id} failed")

        result = DAGExecutor(
            graph=graph,
            handlers={"search_task": handler, "reader_task": handler, "writer_task": handler},
            replan_enabled=True,
            max_replan_attempts=1,
        ).execute()

        self.assertTrue(result.metadata["force_synthesis_used"])
        self.assertLessEqual(result.metadata["replan_attempts"], 2)

    def test_metadata_contains_replan_fields(self) -> None:
        graph = self._single_search_graph()

        result = DAGExecutor(
            graph=graph,
            handlers={"search_task": lambda outputs, node: "ok"},
            replan_enabled=True,
        ).execute()

        self.assertIn("replan_attempts", result.metadata)
        self.assertIn("replan_actions", result.metadata)
        self.assertIn("replanned_node_ids", result.metadata)

    @staticmethod
    def _single_search_graph():
        graph = TaskGraph()
        graph.add_node(TaskNode("search_task", "Search", "SearcherAgent"))
        return graph

    @staticmethod
    def _search_reader_graph():
        graph = TaskGraph()
        graph.add_node(TaskNode("search_task", "Search", "SearcherAgent"))
        graph.add_node(TaskNode("reader_task", "Reader", "ReaderAgent", depends_on=["search_task"]))
        return graph

    @staticmethod
    def _chain_graph():
        graph = TaskGraph()
        graph.add_node(TaskNode("search_task", "Search", "SearcherAgent"))
        graph.add_node(TaskNode("reader_task", "Reader", "ReaderAgent", depends_on=["search_task"]))
        graph.add_node(TaskNode("writer_task", "Writer", "WriterAgent", depends_on=["reader_task"]))
        return graph


if __name__ == "__main__":
    unittest.main()
