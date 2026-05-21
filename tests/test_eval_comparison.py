import json
import unittest

from evaluation.comparison import EvaluationComparison, compare_evaluation_results


class TestEvalComparison(unittest.TestCase):
    def test_compare_evaluation_results_calculates_deltas(self) -> None:
        comparison = compare_evaluation_results(self._baseline(), self._candidate())

        self.assertGreater(comparison.metric_deltas["composite_score_delta"], 0.0)
        self.assertIn("case-1", comparison.improved_cases)
        self.assertIn("case-2", comparison.regressed_cases)
        self.assertIn("AI / LLM", comparison.domain_deltas)

    def test_evaluation_comparison_is_json_serializable(self) -> None:
        comparison = compare_evaluation_results(self._baseline(), self._candidate())

        payload = json.dumps(comparison.to_dict())

        self.assertIn("baseline", payload)

    def test_summary_describes_red_blue_improvement(self) -> None:
        comparison = compare_evaluation_results(
            self._baseline(),
            self._candidate(),
            baseline_name="red_blue_disabled",
            candidate_name="red_blue_enabled",
        )

        self.assertIsInstance(comparison, EvaluationComparison)
        self.assertIn("red_blue_enabled", comparison.summary)
        self.assertIn("improved", comparison.summary)

    @staticmethod
    def _baseline() -> dict:
        return {
            "results": [
                {
                    "case_id": "case-1",
                    "domain": "AI / LLM",
                    "rule_score": 0.6,
                    "composite_score": 0.6,
                    "citation_count_score": 0.5,
                    "evidence_count_score": 0.5,
                    "red_blue_issue_count": 2,
                },
                {
                    "case_id": "case-2",
                    "domain": "Finance",
                    "rule_score": 0.8,
                    "composite_score": 0.8,
                    "citation_count_score": 1.0,
                    "evidence_count_score": 1.0,
                    "red_blue_issue_count": 1,
                },
            ]
        }

    @staticmethod
    def _candidate() -> dict:
        return {
            "results": [
                {
                    "case_id": "case-1",
                    "domain": "AI / LLM",
                    "rule_score": 0.9,
                    "composite_score": 0.9,
                    "citation_count_score": 1.0,
                    "evidence_count_score": 1.0,
                    "red_blue_issue_count": 0,
                },
                {
                    "case_id": "case-2",
                    "domain": "Finance",
                    "rule_score": 0.7,
                    "composite_score": 0.7,
                    "citation_count_score": 1.0,
                    "evidence_count_score": 1.0,
                    "red_blue_issue_count": 0,
                },
            ]
        }


if __name__ == "__main__":
    unittest.main()
