import tempfile
import unittest
from pathlib import Path

from orchestrator.research_pipeline import run_research_pipeline


class TestPipelineCollaboration(unittest.TestCase):
    def test_pipeline_publishes_dependency_ordered_artifacts_and_handoffs(self) -> None:
        result = run_research_pipeline("What affects enterprise LLM adoption?")

        ledger = result["ledger"]
        artifact_types = [artifact.artifact_type for artifact in ledger.list_artifacts()]

        self.assertTrue(result["success"])
        self.assertEqual(
            artifact_types,
            [
                "research_brief",
                "candidate_sources",
                "approved_findings",
                "initial_report",
                "critic_review",
                "red_review",
                "blue_revision",
            ],
        )
        self.assertEqual(ledger.latest("approved_findings").dependencies, [
            ledger.latest("candidate_sources").artifact_id
        ])
        self.assertGreaterEqual(result["ledger_summary"]["handoffCount"], 6)
        self.assertTrue(any(
            handoff.recipient_agent == "WriterAgent"
            for handoff in ledger.list_handoffs()
        ))

    def test_checkpoint_resume_restores_ledger_without_republishing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint_dir = str(Path(directory) / "checkpoints")
            first = run_research_pipeline(
                "What affects enterprise LLM adoption?",
                checkpoint_enabled=True,
                checkpoint_dir=checkpoint_dir,
                run_id="ledger-resume",
            )
            resumed = run_research_pipeline(
                "What affects enterprise LLM adoption?",
                checkpoint_enabled=True,
                checkpoint_dir=checkpoint_dir,
                resume_from_run_id="ledger-resume",
            )

        self.assertEqual(
            resumed["ledger_summary"]["artifactCount"],
            first["ledger_summary"]["artifactCount"],
        )
        self.assertEqual(
            resumed["ledger_summary"]["handoffCount"],
            first["ledger_summary"]["handoffCount"],
        )
        self.assertTrue(resumed["checkpoint_metadata"]["resumed"])


if __name__ == "__main__":
    unittest.main()
