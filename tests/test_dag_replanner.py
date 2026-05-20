import unittest

from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.dag_replanner import DAGReplanner
from orchestrator.replan import ACTION_ABORT, ACTION_FORCE_SYNTHESIS, ReplanDecision


class TestDAGReplanner(unittest.TestCase):
    def test_injects_new_node(self) -> None:
        graph = self._graph()
        decision = self._decision()

        result = DAGReplanner().apply_decision(graph, decision, {"replan_attempts": 1})

        self.assertEqual(result.inserted_node_ids, ["search_task_replan"])
        node = graph.get_node("search_task_replan")
        self.assertTrue(node.metadata["generated_by_replan"])
        self.assertEqual(node.metadata["parent_failed_node_id"], "search_task")

    def test_injects_new_edge(self) -> None:
        graph = self._graph()
        decision = self._decision(
            new_edges=[{"from": "search_task_replan", "to": "reader_task", "replace_dependency": "search_task"}]
        )

        DAGReplanner().apply_decision(graph, decision, {"replan_attempts": 1})

        self.assertIn("search_task_replan", graph.get_node("reader_task").depends_on)
        self.assertNotIn("search_task", graph.get_node("reader_task").depends_on)

    def test_duplicate_node_id_is_made_unique(self) -> None:
        graph = self._graph()
        graph.add_node(TaskNode("search_task_replan", "Existing", "Agent"))

        result = DAGReplanner().apply_decision(graph, self._decision(), {"replan_attempts": 1})

        self.assertEqual(result.inserted_node_ids, ["search_task_replan_2"])

    def test_force_synthesis_is_marked(self) -> None:
        result = DAGReplanner().apply_decision(
            self._graph(),
            ReplanDecision(True, ACTION_FORCE_SYNTHESIS, reason="force"),
            {"replan_attempts": 1},
        )

        self.assertTrue(result.force_synthesis)
        self.assertFalse(result.aborted)

    def test_abort_is_marked_without_exception(self) -> None:
        result = DAGReplanner().apply_decision(
            self._graph(),
            ReplanDecision(False, ACTION_ABORT, reason="abort"),
            {"replan_attempts": 1},
        )

        self.assertTrue(result.aborted)

    @staticmethod
    def _graph():
        graph = TaskGraph()
        graph.add_node(TaskNode("search_task", "Search", "SearcherAgent"))
        graph.add_node(TaskNode("reader_task", "Reader", "ReaderAgent", depends_on=["search_task"]))
        return graph

    @staticmethod
    def _decision(new_edges=None):
        return ReplanDecision(
            should_replan=True,
            action="add_followup_search",
            new_nodes=[
                {
                    "task_id": "search_task_replan",
                    "name": "Replan Search",
                    "agent_name": "AlternativeSearchAgent",
                    "depends_on": [],
                    "metadata": {"parent_failed_node_id": "search_task"},
                }
            ],
            new_edges=new_edges or [],
            reason="test",
        )


if __name__ == "__main__":
    unittest.main()
