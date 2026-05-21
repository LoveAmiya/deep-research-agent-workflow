import tempfile
import unittest

from main import _parse_cli_args, build_demo_execution
from orchestrator.research_pipeline import run_research_pipeline


class TestMainResume(unittest.TestCase):
    def test_pipeline_runs_without_resume_parameter(self) -> None:
        result = run_research_pipeline("What affects enterprise LLM adoption?")

        self.assertTrue(result["success"])
        self.assertIsNone(result["run_id"])

    def test_resume_from_missing_run_id_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_research_pipeline(
                "What affects enterprise LLM adoption?",
                checkpoint_enabled=True,
                resume_from_run_id="missing-run",
                checkpoint_dir=temp_dir,
            )

            self.assertTrue(result["success"])
            self.assertFalse(result["checkpoint_metadata"]["resumed"])
            self.assertTrue(result["checkpoint_metadata"]["resume_checkpoint_missing"])

    def test_resume_from_existing_checkpoint_loads_completed_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = run_research_pipeline(
                "What affects enterprise LLM adoption?",
                checkpoint_enabled=True,
                checkpoint_dir=temp_dir,
                run_id="run-1",
            )
            resumed = run_research_pipeline(
                "What affects enterprise LLM adoption?",
                checkpoint_enabled=True,
                resume_from_run_id="run-1",
                checkpoint_dir=temp_dir,
            )

            self.assertTrue(first["success"])
            self.assertTrue(resumed["success"])
            self.assertTrue(resumed["checkpoint_metadata"]["resumed"])
            self.assertEqual(resumed["checkpoint_metadata"]["skipped_node_count"], 7)
            self.assertTrue(resumed["citation_validation"]["passed"])
            self.assertGreater(len(resumed["memory"].list_by_type("findings")), 0)

    def test_build_demo_execution_accepts_resume_argument(self) -> None:
        execution = build_demo_execution(load_dotenv=False, resume_from_run_id="missing-run")

        self.assertTrue(execution["success"])
        self.assertIn("checkpoint_metadata", execution)

    def test_parse_cli_args_enables_red_blue_loop(self) -> None:
        parsed = _parse_cli_args(["--red-blue-loop"])

        self.assertTrue(parsed["red_blue_loop_enabled"])
        self.assertIsNone(parsed["resume_from_run_id"])

    def test_parse_cli_args_keeps_resume_argument(self) -> None:
        parsed = _parse_cli_args(["--red-blue-loop", "--resume", "run-1"])

        self.assertTrue(parsed["red_blue_loop_enabled"])
        self.assertEqual(parsed["resume_from_run_id"], "run-1")


if __name__ == "__main__":
    unittest.main()
