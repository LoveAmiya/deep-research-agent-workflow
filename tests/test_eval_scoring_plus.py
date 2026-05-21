import unittest

from core.schema import Finding, ResearchReport
from evaluation.llm_judge import JudgeResult
from evaluation.research_bench_plus import ResearchBenchCase
from evaluation.scoring_plus import (
    build_composite_score_summary,
    build_rule_score_summary,
    citation_count_score,
    evidence_count_score,
)


class TestEvalScoringPlus(unittest.TestCase):
    def test_evidence_count_score(self) -> None:
        self.assertEqual(evidence_count_score(2, 4), 0.5)
        self.assertEqual(evidence_count_score(5, 4), 1.0)

    def test_citation_count_score(self) -> None:
        self.assertEqual(citation_count_score(1, 2), 0.5)
        self.assertEqual(citation_count_score(3, 2), 1.0)

    def test_rule_score_summary_includes_section_and_keyword_scores(self) -> None:
        summary = build_rule_score_summary(self._case(), self._pipeline_result())

        self.assertEqual(summary.section_coverage, 1.0)
        self.assertEqual(summary.keyword_coverage, 1.0)
        self.assertEqual(summary.evidence_count_score, 1.0)
        self.assertEqual(summary.citation_count_score, 1.0)
        self.assertGreater(summary.rule_score, 0.0)

    def test_composite_score_without_judge_equals_rule_score(self) -> None:
        summary = build_composite_score_summary("case", 0.8, judge_enabled=False)

        self.assertEqual(summary.composite_score, 0.8)
        self.assertFalse(summary.judge_enabled)

    def test_composite_score_with_judge_uses_weighting(self) -> None:
        judge = JudgeResult(
            case_id="case",
            overall_score=4.0,
            dimension_scores={},
        )

        summary = build_composite_score_summary("case", 0.5, judge_result=judge, judge_enabled=True)

        self.assertAlmostEqual(summary.composite_score, (0.7 * 0.5) + (0.3 * 0.8))
        self.assertTrue(summary.judge_enabled)

    def test_missing_judge_does_not_crash(self) -> None:
        summary = build_composite_score_summary("case", 0.7, judge_result=None, judge_enabled=True)

        self.assertEqual(summary.composite_score, 0.7)
        self.assertFalse(summary.judge_enabled)
        self.assertTrue(summary.metadata["judge_missing"])

    @staticmethod
    def _case() -> ResearchBenchCase:
        return ResearchBenchCase(
            case_id="case",
            domain="AI / LLM",
            question="What affects enterprise AI adoption?",
            expected_keywords=["enterprise", "AI"],
            expected_evidence_count=2,
            expected_citation_count=2,
        )

    @staticmethod
    def _pipeline_result() -> dict:
        report = ResearchReport(
            title="Report",
            question="What affects enterprise AI adoption?",
            citations=["C1", "C2"],
            markdown=(
                "# Report\n\n"
                "## Background\n\nEnterprise AI context.\n\n"
                "## Key Findings\n\n- Enterprise AI evidence [C1]\n\n"
                "## Conclusion\n\nAdoption depends on governance.\n\n"
                "## References\n\n[C1] Source - mock://1\n[C2] Source - mock://2"
            ),
        )
        return {
            "report": report,
            "findings": [
                Finding("Claim 1", "Evidence 1", "mock://1"),
                Finding("Claim 2", "Evidence 2", "mock://2"),
            ],
            "red_review": {"issues": []},
            "blue_revision": object(),
            "citation_validation": {
                "passed": True,
                "citation_count": 2,
                "grounded_citation_count": 2,
            },
        }


if __name__ == "__main__":
    unittest.main()
