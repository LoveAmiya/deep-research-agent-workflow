import unittest

from report_workbench import TASK_ORDER, build_report_workbench_payload


class TestReportWorkbench(unittest.TestCase):
    def test_payload_contains_final_report_and_pipeline_impacts(self) -> None:
        payload = build_report_workbench_payload(
            "What are the main factors that affect open-source LLM adoption in enterprises?"
        )

        self.assertTrue(payload["success"])
        self.assertIn("# Research Report:", payload["finalReportMarkdown"])
        self.assertIn("## Key Findings", payload["finalReportMarkdown"])
        self.assertIn("## References", payload["finalReportMarkdown"])
        self.assertGreater(len(payload["findings"]), 0)

        task_ids = [step["taskId"] for step in payload["stepImpacts"]]
        self.assertEqual(task_ids, [task_id for task_id, _, _ in TASK_ORDER])
        self.assertTrue(all(step["impactOnFinalReport"] for step in payload["stepImpacts"]))
        self.assertTrue(all("metrics" in step for step in payload["stepImpacts"]))

    def test_payload_explains_writer_and_blue_outputs(self) -> None:
        payload = build_report_workbench_payload("How should teams evaluate agentic research tools?")
        steps = {step["taskId"]: step for step in payload["stepImpacts"]}

        self.assertGreater(steps["writer_task"]["metrics"]["Characters"], 0)
        self.assertIn("初稿", steps["writer_task"]["impactOnFinalReport"])
        self.assertIn("最终报告", steps["blue_revision_task"]["impactOnFinalReport"])
        self.assertIn("summary", payload["reportDiffSummary"])
        self.assertIn("passed", payload["citationValidation"])


if __name__ == "__main__":
    unittest.main()
