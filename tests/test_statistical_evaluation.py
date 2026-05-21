import json
import unittest

from evaluation.run_eval import run_eval
from evaluation.statistics import (
    StatisticalComparison,
    bootstrap_mean_ci,
    build_statistical_comparison,
    paired_bootstrap_delta_ci,
    paired_cohens_d,
)


class TestStatisticalEvaluation(unittest.TestCase):
    def test_bootstrap_mean_ci_is_deterministic(self) -> None:
        first = bootstrap_mean_ci([0.4, 0.6, 0.8], "score", num_bootstrap=100, seed=7)
        second = bootstrap_mean_ci([0.4, 0.6, 0.8], "score", num_bootstrap=100, seed=7)

        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertAlmostEqual(first.mean, 0.6)
        self.assertLessEqual(first.lower, first.mean)
        self.assertGreaterEqual(first.upper, first.mean)

    def test_single_sample_ci_collapses_to_mean(self) -> None:
        ci = bootstrap_mean_ci([0.75], "score", num_bootstrap=10)

        self.assertEqual(ci.lower, 0.75)
        self.assertEqual(ci.mean, 0.75)
        self.assertEqual(ci.upper, 0.75)

    def test_paired_bootstrap_delta_ci_calculates_candidate_minus_baseline(self) -> None:
        ci = paired_bootstrap_delta_ci(
            [0.5, 0.7, 0.9],
            [0.6, 0.8, 1.0],
            "score_delta",
            num_bootstrap=100,
            seed=3,
        )

        self.assertAlmostEqual(ci.mean, 0.1)
        self.assertEqual(ci.sample_size, 3)

    def test_paired_bootstrap_delta_ci_rejects_length_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            paired_bootstrap_delta_ci([0.5], [0.5, 0.6], "score_delta")

    def test_paired_cohens_d_calculates_effect_size(self) -> None:
        effect = paired_cohens_d([0.5, 0.5, 0.5], [0.6, 0.7, 0.8], "score")

        self.assertIsNotNone(effect.value)
        self.assertEqual(effect.effect_size_type, "cohens_dz")
        self.assertIn(effect.interpretation, {"small", "medium", "large"})

    def test_paired_cohens_d_zero_variance_no_delta(self) -> None:
        effect = paired_cohens_d([0.5, 0.6], [0.5, 0.6], "score")

        self.assertEqual(effect.value, 0.0)
        self.assertEqual(effect.interpretation, "none")

    def test_paired_cohens_d_zero_variance_nonzero_delta(self) -> None:
        effect = paired_cohens_d([0.5, 0.6], [0.6, 0.7], "score")

        self.assertIsNone(effect.value)
        self.assertEqual(effect.interpretation, "zero_variance")

    def test_paired_cohens_d_insufficient_samples(self) -> None:
        effect = paired_cohens_d([0.5], [0.7], "score")

        self.assertIsNone(effect.value)
        self.assertEqual(effect.interpretation, "insufficient_samples")

    def test_effect_size_interpretation(self) -> None:
        negligible = paired_cohens_d([0.4, 0.5, 0.6], [0.4, 0.52, 0.58], "score")
        large = paired_cohens_d([0.3, 0.3, 0.3, 0.3], [0.3, 0.4, 0.5, 0.6], "score")

        self.assertEqual(negligible.interpretation, "negligible")
        self.assertEqual(large.interpretation, "large")

    def test_statistical_comparison_is_json_serializable(self) -> None:
        comparison = build_statistical_comparison(
            self._baseline(),
            self._candidate(),
            num_bootstrap=100,
            seed=5,
        )

        payload = json.dumps(comparison.to_dict())

        self.assertIsInstance(comparison, StatisticalComparison)
        self.assertIn("delta_ci", payload)

    def test_build_statistical_comparison_aligns_by_case_id(self) -> None:
        comparison = build_statistical_comparison(
            self._baseline(),
            self._candidate_with_extra_case(),
            num_bootstrap=100,
        )

        self.assertEqual(comparison.sample_size, 2)
        self.assertAlmostEqual(comparison.mean_delta, 0.1)

    def test_missing_metric_case_is_skipped(self) -> None:
        comparison = build_statistical_comparison(
            self._baseline(),
            self._candidate_missing_metric(),
            num_bootstrap=100,
        )

        self.assertEqual(comparison.sample_size, 1)
        self.assertIn("case-2", comparison.skipped_cases)
        self.assertIn("case-2", comparison.metadata["skipped_cases"])

    def test_default_run_eval_still_returns_summary(self) -> None:
        result = run_eval()

        self.assertIn("summary", result)
        self.assertIn("results", result)

    @staticmethod
    def _baseline() -> dict:
        return {
            "results": [
                {"case_id": "case-1", "domain": "AI / LLM", "composite_score": 0.6, "rule_score": 0.6},
                {"case_id": "case-2", "domain": "Finance", "composite_score": 0.7, "rule_score": 0.7},
            ]
        }

    @staticmethod
    def _candidate() -> dict:
        return {
            "results": [
                {"case_id": "case-1", "domain": "AI / LLM", "composite_score": 0.8, "rule_score": 0.8},
                {"case_id": "case-2", "domain": "Finance", "composite_score": 0.9, "rule_score": 0.9},
            ]
        }

    @staticmethod
    def _candidate_with_extra_case() -> dict:
        return {
            "results": [
                {"case_id": "case-1", "domain": "AI / LLM", "composite_score": 0.7, "rule_score": 0.7},
                {"case_id": "case-2", "domain": "Finance", "composite_score": 0.8, "rule_score": 0.8},
                {"case_id": "case-3", "domain": "Climate", "composite_score": 1.0, "rule_score": 1.0},
            ]
        }

    @staticmethod
    def _candidate_missing_metric() -> dict:
        return {
            "results": [
                {"case_id": "case-1", "domain": "AI / LLM", "composite_score": 0.8, "rule_score": 0.8},
                {"case_id": "case-2", "domain": "Finance", "rule_score": 0.9},
            ]
        }


if __name__ == "__main__":
    unittest.main()
