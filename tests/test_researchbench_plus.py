import json
import unittest

from evaluation.research_bench_plus import ResearchBenchCase, load_plus_cases


class TestResearchBenchPlus(unittest.TestCase):
    def test_research_bench_case_can_be_created(self) -> None:
        case = ResearchBenchCase(
            case_id="case",
            domain="AI / LLM",
            question="What affects AI adoption?",
            expected_keywords=["AI", "adoption"],
        )

        self.assertEqual(case.case_id, "case")
        self.assertEqual(case.expected_evidence_count, 3)

    def test_legacy_case_missing_fields_is_compatible(self) -> None:
        case = ResearchBenchCase.from_dict(
            {
                "id": "legacy",
                "question": "Legacy question?",
                "keywords": ["legacy"],
                "expected_min_findings": 2,
                "expected_min_citations": 2,
            }
        )

        self.assertEqual(case.case_id, "legacy")
        self.assertEqual(case.domain, "general")
        self.assertEqual(case.expected_evidence_count, 2)
        self.assertEqual(case.expected_citation_count, 2)

    def test_plus_benchmark_has_at_least_20_cases(self) -> None:
        self.assertGreaterEqual(len(load_plus_cases()), 20)

    def test_plus_benchmark_covers_at_least_6_domains(self) -> None:
        domains = {case.domain for case in load_plus_cases()}

        self.assertGreaterEqual(len(domains), 6)

    def test_each_case_has_expected_keywords_and_counts(self) -> None:
        for case in load_plus_cases():
            self.assertTrue(case.expected_keywords)
            self.assertGreater(case.expected_evidence_count, 0)
            self.assertGreater(case.expected_citation_count, 0)

    def test_case_is_json_serializable(self) -> None:
        case = load_plus_cases()[0]

        serialized = json.dumps(case.to_dict())

        self.assertIn(case.case_id, serialized)


if __name__ == "__main__":
    unittest.main()
