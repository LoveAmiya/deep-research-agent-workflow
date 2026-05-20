import unittest

from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.replan import (
    ACTION_ADD_ALTERNATIVE_READER,
    ACTION_ADD_FOLLOWUP_SEARCH,
    ACTION_FORCE_SYNTHESIS,
    ReplanTrigger,
    RuleBasedReplanPolicy,
)


class TestRuleBasedReplanPolicy(unittest.TestCase):
    def test_search_node_failure_adds_followup_search(self) -> None:
        decision = RuleBasedReplanPolicy().decide(
            self._trigger("search_task", "node_failed", failed_agent="SearcherAgent"),
            self._graph(),
            {"replan_attempts": 0, "failed_node_count": 1},
        )

        self.assertTrue(decision.should_replan)
        self.assertEqual(decision.action, ACTION_ADD_FOLLOWUP_SEARCH)
        self.assertEqual(decision.new_nodes[0]["agent_name"], "AlternativeSearchAgent")
        self.assertTrue(decision.metadata["deterministic"])

    def test_reader_failure_adds_alternative_reader(self) -> None:
        decision = RuleBasedReplanPolicy().decide(
            self._trigger("reader_task", "node_failed", failed_agent="ReaderAgent"),
            self._graph(),
            {"replan_attempts": 0, "failed_node_count": 1},
        )

        self.assertEqual(decision.action, ACTION_ADD_ALTERNATIVE_READER)
        self.assertEqual(decision.new_nodes[0]["metadata"]["output_kind"], "findings")

    def test_insufficient_evidence_adds_followup_search(self) -> None:
        decision = RuleBasedReplanPolicy().decide(
            self._trigger("reader_task", "insufficient_evidence", failed_agent="ReaderAgent"),
            self._graph(),
            {"replan_attempts": 0, "failed_node_count": 0},
        )

        self.assertEqual(decision.action, ACTION_ADD_FOLLOWUP_SEARCH)
        self.assertIn("follow-up", decision.reason)

    def test_citation_validation_failed_adds_repair_or_search_node(self) -> None:
        decision = RuleBasedReplanPolicy().decide(
            self._trigger("critic_task", "citation_validation_failed", failed_agent="CriticAgent"),
            self._graph(),
            {"replan_attempts": 0, "failed_node_count": 0},
        )

        self.assertEqual(decision.action, ACTION_ADD_FOLLOWUP_SEARCH)
        self.assertEqual(decision.new_nodes[0]["agent_name"], "CitationRepairAgent")

    def test_exceeding_attempt_limit_forces_synthesis(self) -> None:
        decision = RuleBasedReplanPolicy(max_replan_attempts=1).decide(
            self._trigger("search_task", "node_failed", failed_agent="SearcherAgent"),
            self._graph(),
            {"replan_attempts": 1, "failed_node_count": 1},
        )

        self.assertEqual(decision.action, ACTION_FORCE_SYNTHESIS)
        self.assertTrue(decision.metadata["replan_exhausted"])

    def test_policy_does_not_require_llm(self) -> None:
        policy = RuleBasedReplanPolicy()

        self.assertFalse(hasattr(policy, "llm_client"))

    @staticmethod
    def _trigger(node_id: str, trigger_type: str, failed_agent: str):
        return ReplanTrigger(
            run_id="run-1",
            node_id=node_id,
            trigger_type=trigger_type,
            reason="forced test trigger",
            failed_agent=failed_agent,
            failed_node_type=node_id,
            error="boom",
        )

    @staticmethod
    def _graph():
        graph = TaskGraph()
        graph.add_node(TaskNode("search_task", "Search", "SearcherAgent"))
        graph.add_node(TaskNode("reader_task", "Reader", "ReaderAgent", depends_on=["search_task"]))
        graph.add_node(TaskNode("critic_task", "Critic", "CriticAgent", depends_on=["reader_task"]))
        return graph


if __name__ == "__main__":
    unittest.main()
