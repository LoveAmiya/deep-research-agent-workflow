import json
import unittest
from dataclasses import asdict

from agents.red_blue_convergence import (
    STATUS_CONVERGED,
    STATUS_MAX_ROUNDS_REACHED,
    STATUS_NO_IMPROVEMENT,
    STATUS_OSCILLATION_DETECTED,
    RedBlueConvergenceDecision,
    RedBlueLoopSummary,
    RedBlueRoundSnapshot,
    compute_convergence_score,
    decide_convergence,
    detect_no_improvement,
    detect_oscillation,
    fingerprint_issue,
    hash_report,
    normalize_issue_text,
)
from core.schema import ReviewIssue


class TestRedBlueConvergence(unittest.TestCase):
    def test_fingerprint_issue_is_stable_for_same_issue(self) -> None:
        first = fingerprint_issue(
            ReviewIssue(
                issue_id="red-1",
                category="citation",
                severity="high",
                message=" Citation marker is missing. ",
            )
        )
        second = fingerprint_issue(
            {
                "category": "citation",
                "severity": "HIGH",
                "message": "citation   marker is missing.",
            }
        )

        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_normalize_issue_text_handles_case_and_whitespace(self) -> None:
        self.assertEqual(
            normalize_issue_text("  Missing   Citation\nMarker "),
            "missing citation marker",
        )

    def test_hash_report_is_stable(self) -> None:
        self.assertEqual(hash_report("# Report\nText"), hash_report("# report text"))

    def test_decide_convergence_with_no_issues(self) -> None:
        decision = decide_convergence(
            [
                RedBlueRoundSnapshot(
                    round_index=1,
                    issue_count=0,
                    issue_fingerprints=[],
                    report_hash=hash_report("ok"),
                    blue_action_count=0,
                    fixed_issue_count=0,
                    remaining_issue_count=0,
                    passed=True,
                )
            ],
            max_rounds=3,
        )

        self.assertTrue(decision.should_stop)
        self.assertEqual(decision.status, STATUS_CONVERGED)

    def test_decide_convergence_at_max_rounds(self) -> None:
        decision = decide_convergence(
            [
                self._snapshot(1, ["a"], "A", 1),
                self._snapshot(2, ["b"], "B", 1),
            ],
            max_rounds=2,
            no_improvement_patience=3,
            enable_oscillation_detection=False,
        )

        self.assertEqual(decision.status, STATUS_MAX_ROUNDS_REACHED)

    def test_detects_no_improvement(self) -> None:
        history = [
            self._snapshot(1, ["a"], "A", 2),
            self._snapshot(2, ["b"], "B", 2),
            self._snapshot(3, ["c"], "C", 2),
        ]

        self.assertTrue(detect_no_improvement(history, patience=2))
        self.assertEqual(
            decide_convergence(
                history,
                max_rounds=5,
                no_improvement_patience=2,
                enable_oscillation_detection=False,
            ).status,
            STATUS_NO_IMPROVEMENT,
        )

    def test_issue_fingerprint_set_repetition_detects_oscillation(self) -> None:
        history = [
            self._snapshot(1, ["a"], "A", 1),
            self._snapshot(2, ["b"], "B", 1),
            self._snapshot(3, ["a"], "C", 1),
        ]

        detected, metadata = detect_oscillation(history, window=4)

        self.assertTrue(detected)
        self.assertEqual(metadata["repeated_fingerprints"], ["a"])
        self.assertEqual(
            decide_convergence(history, max_rounds=5).status,
            STATUS_OSCILLATION_DETECTED,
        )

    def test_report_hash_abab_detects_oscillation(self) -> None:
        history = [
            self._snapshot(1, ["a1"], "A", 1),
            self._snapshot(2, ["b1"], "B", 1),
            self._snapshot(3, ["a2"], "A", 1),
            self._snapshot(4, ["b2"], "B", 1),
        ]

        detected, metadata = detect_oscillation(history, window=4)

        self.assertTrue(detected)
        self.assertTrue(metadata["alternating_report_hash"])

    def test_convergence_score_improves_when_issues_drop(self) -> None:
        history = [
            self._snapshot(1, ["a", "b", "c"], "A", 3),
            self._snapshot(2, ["a"], "B", 1),
        ]

        self.assertGreater(compute_convergence_score(history), 0.0)

    def test_loop_summary_is_json_serializable(self) -> None:
        decision = RedBlueConvergenceDecision(
            should_stop=True,
            status=STATUS_CONVERGED,
            reason="done",
            convergence_score=1.0,
            oscillation_detected=False,
        )
        summary = RedBlueLoopSummary(
            total_rounds=1,
            final_status=decision.status,
            stop_reason=decision.reason,
            issue_count_history=[0],
            convergence_score_history=[1.0],
            oscillation_detected=False,
            repeated_fingerprints=[],
            final_issue_count=0,
        )

        self.assertTrue(json.dumps(asdict(summary)))

    @staticmethod
    def _snapshot(
        round_index: int,
        fingerprints: list[str],
        report_text: str,
        remaining_issue_count: int,
    ) -> RedBlueRoundSnapshot:
        return RedBlueRoundSnapshot(
            round_index=round_index,
            issue_count=len(fingerprints),
            issue_fingerprints=fingerprints,
            report_hash=hash_report(report_text),
            blue_action_count=1,
            fixed_issue_count=0,
            remaining_issue_count=remaining_issue_count,
            passed=False,
        )


if __name__ == "__main__":
    unittest.main()
