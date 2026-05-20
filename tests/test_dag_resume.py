import tempfile
import unittest

from agents.base_agent import AgentResult
from orchestrator.checkpoint import JSONCheckpointStore, RunCheckpoint
from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.executor import DAGExecutor
from orchestrator.state import TaskState


class TestDAGResume(unittest.TestCase):
    def test_first_execution_writes_completed_node_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            graph = self._graph([("a", []), ("b", ["a"])])
            store = JSONCheckpointStore(temp_dir)
            checkpoint = RunCheckpoint.new("task", run_id="run-1")

            result = DAGExecutor(
                graph=graph,
                handlers={"a": lambda outputs, node: "A", "b": lambda outputs, node: outputs["a"] + "B"},
                checkpoint_store=store,
                checkpoint=checkpoint,
                checkpoint_enabled=True,
            ).execute()

            loaded = store.load_checkpoint("run-1")
            self.assertTrue(result.success)
            self.assertEqual(loaded.node_checkpoints["a"].status, "SUCCESS")
            self.assertEqual(loaded.node_checkpoints["b"].status, "SUCCESS")

    def test_resume_skips_completed_node_and_reexecutes_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            graph = self._graph([("a", []), ("b", ["a"])])
            store = JSONCheckpointStore(temp_dir)
            initial = RunCheckpoint.new("task", run_id="run-1")
            DAGExecutor(
                graph=graph,
                handlers={"a": lambda outputs, node: "A", "b": lambda outputs, node: "B"},
                checkpoint_store=store,
                checkpoint=initial,
                checkpoint_enabled=True,
            ).execute()
            checkpoint = store.load_checkpoint("run-1")
            del checkpoint.node_checkpoints["b"]
            checkpoint.refresh_node_lists(["a", "b"])
            store.save_checkpoint(checkpoint)
            calls = []

            result = DAGExecutor(
                graph=graph,
                handlers={
                    "a": lambda outputs, node: calls.append("a") or "new-A",
                    "b": lambda outputs, node: calls.append("b") or outputs["a"] + "B",
                },
                checkpoint_store=store,
                checkpoint=store.load_checkpoint("run-1"),
                checkpoint_enabled=True,
                resume=True,
            ).execute()

            self.assertTrue(result.success)
            self.assertEqual(calls, ["b"])
            self.assertEqual(result.outputs["b"], "AB")
            self.assertEqual(result.metadata["skipped_node_count"], 1)
            self.assertEqual(result.metadata["reexecuted_node_count"], 1)

    def test_resume_reexecutes_failed_node(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            graph = self._graph([("a", [])])
            store = JSONCheckpointStore(temp_dir)
            checkpoint = RunCheckpoint.new("task", run_id="run-1")
            DAGExecutor(
                graph=graph,
                handlers={"a": lambda outputs, node: (_ for _ in ()).throw(RuntimeError("boom"))},
                checkpoint_store=store,
                checkpoint=checkpoint,
                checkpoint_enabled=True,
            ).execute()
            calls = []

            result = DAGExecutor(
                graph=graph,
                handlers={"a": lambda outputs, node: calls.append("a") or "recovered"},
                checkpoint_store=store,
                checkpoint=store.load_checkpoint("run-1"),
                checkpoint_enabled=True,
                resume=True,
            ).execute()

            self.assertTrue(result.success)
            self.assertEqual(calls, ["a"])
            self.assertEqual(result.outputs["a"], "recovered")

    def test_resume_reexecutes_pending_node_and_generates_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            graph = self._graph([("a", []), ("b", ["a"]), ("c", ["b"])])
            store = JSONCheckpointStore(temp_dir)
            checkpoint = RunCheckpoint.new("task", run_id="run-1")
            first = DAGExecutor(
                graph=graph,
                handlers={
                    "a": lambda outputs, node: "A",
                    "b": lambda outputs, node: (_ for _ in ()).throw(RuntimeError("boom")),
                    "c": lambda outputs, node: "C",
                },
                checkpoint_store=store,
                checkpoint=checkpoint,
                checkpoint_enabled=True,
            ).execute()

            self.assertFalse(first.success)
            result = DAGExecutor(
                graph=graph,
                handlers={
                    "a": lambda outputs, node: "new-A",
                    "b": lambda outputs, node: outputs["a"] + "B",
                    "c": lambda outputs, node: outputs["b"] + "C",
                },
                checkpoint_store=store,
                checkpoint=store.load_checkpoint("run-1"),
                checkpoint_enabled=True,
                resume=True,
            ).execute()

            self.assertTrue(result.success)
            self.assertEqual(result.outputs["c"], "ABC")
            self.assertEqual(result.states["b"], TaskState.SUCCESS)
            self.assertEqual(result.states["c"], TaskState.SUCCESS)

    def test_agent_result_checkpoint_output_is_reused_for_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            graph = self._graph([("a", []), ("b", ["a"])])
            store = JSONCheckpointStore(temp_dir)
            checkpoint = RunCheckpoint.new("task", run_id="run-1")
            DAGExecutor(
                graph=graph,
                handlers={
                    "a": lambda outputs, node: AgentResult("AgentA", True, output="A"),
                    "b": lambda outputs, node: outputs["a"].output + "B",
                },
                checkpoint_store=store,
                checkpoint=checkpoint,
                checkpoint_enabled=True,
            ).execute()

            result = DAGExecutor(
                graph=graph,
                handlers={
                    "a": lambda outputs, node: AgentResult("AgentA", True, output="new-A"),
                    "b": lambda outputs, node: outputs["a"].output + "B",
                },
                checkpoint_store=store,
                checkpoint=store.load_checkpoint("run-1"),
                checkpoint_enabled=True,
                resume=True,
            ).execute()

            self.assertEqual(result.outputs["b"], "AB")
            self.assertEqual(result.metadata["skipped_node_count"], 2)

    @staticmethod
    def _graph(definitions):
        graph = TaskGraph()
        for task_id, depends_on in definitions:
            graph.add_node(
                TaskNode(
                    task_id=task_id,
                    name=f"Task {task_id}",
                    agent_name=f"Agent{task_id.upper()}",
                    depends_on=depends_on,
                )
            )
        return graph


if __name__ == "__main__":
    unittest.main()
