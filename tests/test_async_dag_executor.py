import asyncio
import time
import unittest

from orchestrator.async_executor import AsyncDAGExecutor
from orchestrator.async_research_pipeline import async_run_research_pipeline
from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.state import TaskState


class TestAsyncDAGExecutor(unittest.TestCase):
    def test_executes_single_node_dag(self) -> None:
        graph = self._graph([("a", [])])

        async def run_test():
            result = await AsyncDAGExecutor(
                graph,
                {"a": lambda outputs, node: "A"},
            ).execute()
            self.assertTrue(result.success)
            self.assertEqual(result.outputs["a"], "A")
            self.assertEqual(result.states["a"], TaskState.SUCCESS)

        asyncio.run(run_test())

    def test_executes_dependency_chain(self) -> None:
        graph = self._graph([("a", []), ("b", ["a"]), ("c", ["b"])])

        async def run_test():
            result = await AsyncDAGExecutor(
                graph,
                {
                    "a": lambda outputs, node: "A",
                    "b": lambda outputs, node: outputs["a"] + "B",
                    "c": lambda outputs, node: outputs["b"] + "C",
                },
            ).execute()
            self.assertEqual(result.outputs["c"], "ABC")
            self.assertTrue(result.success)

        asyncio.run(run_test())

    def test_independent_tasks_can_run_concurrently(self) -> None:
        graph = self._graph([("a", []), ("b", [])])

        async def slow_handler(outputs, node):
            await asyncio.sleep(0.05)
            return node.task_id

        async def run_test():
            start = time.perf_counter()
            result = await AsyncDAGExecutor(
                graph,
                {"a": slow_handler, "b": slow_handler},
                max_concurrency=2,
            ).execute()
            elapsed = time.perf_counter() - start
            self.assertTrue(result.success)
            self.assertLess(elapsed, 0.09)

        asyncio.run(run_test())

    def test_max_concurrency_limits_parallelism(self) -> None:
        graph = self._graph([("a", []), ("b", [])])

        async def slow_handler(outputs, node):
            await asyncio.sleep(0.05)
            return node.task_id

        async def run_test():
            start = time.perf_counter()
            result = await AsyncDAGExecutor(
                graph,
                {"a": slow_handler, "b": slow_handler},
                max_concurrency=1,
            ).execute()
            elapsed = time.perf_counter() - start
            self.assertTrue(result.success)
            self.assertGreaterEqual(elapsed, 0.09)

        asyncio.run(run_test())

    def test_async_handler_executes(self) -> None:
        graph = self._graph([("a", [])])

        async def handler(outputs, node):
            await asyncio.sleep(0)
            return "async"

        async def run_test():
            result = await AsyncDAGExecutor(graph, {"a": handler}).execute()
            self.assertEqual(result.outputs["a"], "async")

        asyncio.run(run_test())

    def test_sync_handler_executes(self) -> None:
        graph = self._graph([("a", [])])

        async def run_test():
            result = await AsyncDAGExecutor(graph, {"a": lambda outputs, node: "sync"}).execute()
            self.assertEqual(result.outputs["a"], "sync")

        asyncio.run(run_test())

    def test_handler_exception_marks_failed(self) -> None:
        graph = self._graph([("a", [])])

        def failing_handler(outputs, node):
            raise RuntimeError("forced failure")

        async def run_test():
            result = await AsyncDAGExecutor(graph, {"a": failing_handler}).execute()
            self.assertFalse(result.success)
            self.assertEqual(result.states["a"], TaskState.FAILED)
            self.assertIn("forced failure", result.errors["a"])

        asyncio.run(run_test())

    def test_dependency_failure_skips_downstream(self) -> None:
        graph = self._graph([("a", []), ("b", ["a"])])

        def failing_handler(outputs, node):
            raise RuntimeError("forced failure")

        async def run_test():
            result = await AsyncDAGExecutor(
                graph,
                {"a": failing_handler, "b": lambda outputs, node: "B"},
            ).execute()
            self.assertEqual(result.states["a"], TaskState.FAILED)
            self.assertEqual(result.states["b"], TaskState.SKIPPED)

        asyncio.run(run_test())

    def test_timeout_marks_task_failed(self) -> None:
        graph = self._graph([("a", [])])

        async def slow_handler(outputs, node):
            await asyncio.sleep(0.05)
            return "late"

        async def run_test():
            result = await AsyncDAGExecutor(
                graph,
                {"a": slow_handler},
                task_timeout_seconds=0.01,
            ).execute()
            self.assertEqual(result.states["a"], TaskState.FAILED)
            self.assertIn("timed out", result.errors["a"])

        asyncio.run(run_test())

    def test_traces_include_lifecycle_states(self) -> None:
        graph = self._graph([("a", []), ("b", ["a"])])

        def failing_handler(outputs, node):
            raise RuntimeError("forced failure")

        async def run_test():
            result = await AsyncDAGExecutor(
                graph,
                {"a": failing_handler, "b": lambda outputs, node: "B"},
            ).execute()
            states = [trace["state"] for trace in result.traces]
            self.assertIn("RUNNING", states)
            self.assertIn("FAILED", states)
            self.assertIn("SKIPPED", states)

        asyncio.run(run_test())

    def test_async_research_pipeline_runs(self) -> None:
        async def run_test():
            result = await async_run_research_pipeline(
                "What affects enterprise open-source LLM adoption?",
                max_concurrency=2,
            )
            self.assertTrue(result["success"])
            self.assertIn("[C1]", result["report"].markdown)
            self.assertTrue(result["citation_validation"]["passed"])

        asyncio.run(run_test())

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
