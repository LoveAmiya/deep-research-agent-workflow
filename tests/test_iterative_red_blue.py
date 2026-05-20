import unittest

from agents.base_agent import AgentContext, AgentResult
from agents.blue_agent import BlueAgent
from agents.red_agent import RedAgent
from agents.red_blue_loop import (
    RedBlueLoopConfig,
    RedBlueLoopResult,
    RedBlueLoopRunner,
)
from core.schema import (
    BlueRevisionResult,
    Finding,
    RedReviewResult,
    ResearchReport,
    ReviewIssue,
)
from evaluation.metrics import iterative_red_blue_score
from main import build_demo_execution
from memory.store import SharedMemory
from orchestrator.research_pipeline import run_research_pipeline


class SequenceRedAgent(RedAgent):
    def __init__(self, issue_counts):
        super().__init__()
        self.issue_counts = list(issue_counts)
        self.calls = 0

    def run(self, context):
        count = self.issue_counts[min(self.calls, len(self.issue_counts) - 1)]
        self.calls += 1
        issues = [
            ReviewIssue(
                issue_id=f"issue-{index}",
                category="structure",
                severity="low",
                message=f"Issue {index}",
            )
            for index in range(count)
        ]
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=RedReviewResult(
                passed=count == 0,
                issues=issues,
                summary=f"{count} issues",
            ),
        )


class SequenceBlueAgent(BlueAgent):
    def __init__(self, remaining_sequences):
        super().__init__()
        self.remaining_sequences = list(remaining_sequences)
        self.calls = 0

    def run(self, context):
        remaining = self.remaining_sequences[min(self.calls, len(self.remaining_sequences) - 1)]
        self.calls += 1
        red_review = context.inputs["red_review"]
        fixed = [issue.issue_id for issue in red_review.issues if issue.issue_id not in remaining]
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=BlueRevisionResult(
                revised_report=context.inputs["report"],
                fixed_issue_ids=fixed,
                remaining_issue_ids=list(remaining),
                revision_notes=["fake revision"],
            ),
        )


class FailingBlueAgent(BlueAgent):
    def run(self, context):
        return AgentResult(agent_name=self.name, success=False, error="forced blue failure")


class TestIterativeRedBlue(unittest.TestCase):
    def test_stops_after_one_round_when_red_passes(self) -> None:
        result = self._runner([0], [[]]).run(
            self._context(),
            self._report(),
            self._findings(),
        )

        self.assertTrue(result.passed)
        self.assertEqual(len(result.rounds), 1)
        self.assertEqual(result.stop_reason, "red_passed")

    def test_can_execute_multiple_rounds(self) -> None:
        result = self._runner([2, 1, 0], [["issue-1"], []]).run(
            self._context(),
            self._report(),
            self._findings(),
        )

        self.assertTrue(result.passed)
        self.assertEqual(len(result.rounds), 3)

    def test_stops_at_max_rounds(self) -> None:
        result = self._runner(
            [2, 2, 2],
            [["issue-1"], ["issue-1"], ["issue-1"]],
            max_rounds=2,
            no_improvement_rounds=3,
            oscillation=False,
        ).run(self._context(), self._report(), self._findings())

        self.assertFalse(result.passed)
        self.assertEqual(len(result.rounds), 2)
        self.assertEqual(result.stop_reason, "max_rounds_reached")

    def test_stops_when_issue_count_does_not_improve(self) -> None:
        runner = RedBlueLoopRunner(
            SequenceRedAgent([2, 2, 2]),
            SequenceBlueAgent([["issue-1"], ["issue-1"]]),
            RedBlueLoopConfig(
                max_rounds=3,
                stop_if_no_improvement_rounds=1,
                enable_oscillation_detection=False,
            ),
        )

        result = runner.run(self._context(), self._report(), self._findings())

        self.assertEqual(result.stop_reason, "no_improvement")
        self.assertTrue(result.rounds[-1].stopped)

    def test_oscillation_detection_stops_repeated_remaining_signature(self) -> None:
        result = self._runner(
            [2, 2, 2],
            [["issue-1"], ["issue-1"]],
            max_rounds=3,
            no_improvement_rounds=3,
            oscillation=True,
        ).run(self._context(), self._report(), self._findings())

        self.assertEqual(result.stop_reason, "oscillation_detected")

    def test_blue_failure_does_not_crash(self) -> None:
        runner = RedBlueLoopRunner(
            SequenceRedAgent([1]),
            FailingBlueAgent(),
            RedBlueLoopConfig(max_rounds=2),
        )

        result = runner.run(self._context(), self._report(), self._findings())

        self.assertFalse(result.passed)
        self.assertEqual(result.stop_reason, "blue_agent_failed")

    def test_loop_result_contains_final_report(self) -> None:
        result = self._runner([1, 0], [[]]).run(
            self._context(),
            self._report(),
            self._findings(),
        )

        self.assertIsInstance(result.final_report, ResearchReport)

    def test_loop_writes_shared_memory(self) -> None:
        memory = SharedMemory()
        context = self._context(memory=memory)

        self._runner([0], [[]]).run(context, self._report(), self._findings())

        self.assertEqual(len(memory.list_by_type("red_blue_loop")), 1)

    def test_pipeline_runs_with_red_blue_loop_enabled(self) -> None:
        result = run_research_pipeline(
            "What affects enterprise LLM adoption?",
            use_red_blue_loop=True,
            red_blue_loop_config=RedBlueLoopConfig(max_rounds=2),
        )

        self.assertTrue(result["success"])
        self.assertIsInstance(result["red_blue_loop_result"], RedBlueLoopResult)
        self.assertIn("final_report", result)

    def test_main_default_single_round_not_broken(self) -> None:
        result = build_demo_execution(load_dotenv=False)

        self.assertIsNone(result["red_blue_loop_result"])
        self.assertIn("blue_revision", result)

    def test_iterative_red_blue_score(self) -> None:
        loop_result = RedBlueLoopResult(
            final_report=self._report(),
            passed=False,
            total_fixed_issues=2,
            remaining_issue_count=2,
            stop_reason="max_rounds_reached",
        )

        self.assertEqual(iterative_red_blue_score(loop_result), 0.5)

    def _runner(
        self,
        issue_counts,
        remaining_sequences,
        max_rounds=3,
        no_improvement_rounds=2,
        oscillation=True,
    ) -> RedBlueLoopRunner:
        return RedBlueLoopRunner(
            SequenceRedAgent(issue_counts),
            SequenceBlueAgent(remaining_sequences),
            RedBlueLoopConfig(
                max_rounds=max_rounds,
                stop_if_no_improvement_rounds=no_improvement_rounds,
                enable_oscillation_detection=oscillation,
            ),
        )

    @staticmethod
    def _context(memory=None) -> AgentContext:
        return AgentContext(task_id="loop_task", inputs={}, memory=memory)

    @staticmethod
    def _report() -> ResearchReport:
        return ResearchReport(
            title="Report",
            question="Question",
            sections=[],
            citations=[],
            markdown="# Report",
        )

    @staticmethod
    def _findings():
        return [Finding(claim="Claim", evidence="Evidence", source_url="mock://1")]


if __name__ == "__main__":
    unittest.main()
