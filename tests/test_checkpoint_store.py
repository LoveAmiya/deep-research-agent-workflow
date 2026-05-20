import json
import tempfile
import unittest
from pathlib import Path

from agents.base_agent import AgentResult
from core.schema import ResearchPlan
from orchestrator.checkpoint import (
    JSONCheckpointStore,
    NodeCheckpoint,
    RunCheckpoint,
    deserialize_checkpoint_output,
    run_checkpoint_from_dict,
    run_checkpoint_to_dict,
    serialize_checkpoint_output,
)


class TestCheckpointStore(unittest.TestCase):
    def test_json_checkpoint_store_saves_and_loads_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JSONCheckpointStore(temp_dir)
            checkpoint = RunCheckpoint.new("task", run_id="run-1")
            checkpoint.node_checkpoints["planner_task"] = NodeCheckpoint(
                node_id="planner_task",
                status="SUCCESS",
                agent_name="PlannerAgent",
                output=serialize_checkpoint_output(
                    AgentResult(
                        agent_name="PlannerAgent",
                        success=True,
                        output=ResearchPlan(question="Q", search_queries=["q"]),
                    )
                ),
            )
            checkpoint.refresh_node_lists(["planner_task"])

            store.save_checkpoint(checkpoint)
            loaded = store.load_checkpoint("run-1")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.run_id, "run-1")
            self.assertIn("planner_task", loaded.completed_node_ids)

    def test_checkpoint_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JSONCheckpointStore(temp_dir)
            checkpoint = RunCheckpoint.new("task", run_id="run-1")

            self.assertFalse(store.checkpoint_exists("run-1"))
            store.save_checkpoint(checkpoint)

            self.assertTrue(store.checkpoint_exists("run-1"))

    def test_corrupted_checkpoint_file_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JSONCheckpointStore(temp_dir)
            store.checkpoint_path("broken").write_text("{not-json", encoding="utf-8")

            self.assertIsNone(store.load_checkpoint("broken"))

    def test_checkpoint_round_trip_serialization(self) -> None:
        checkpoint = RunCheckpoint.new("task", run_id="run-1")
        checkpoint.node_checkpoints["a"] = NodeCheckpoint(node_id="a", status="FAILED", error="boom")

        loaded = run_checkpoint_from_dict(run_checkpoint_to_dict(checkpoint))

        self.assertEqual(loaded.run_id, "run-1")
        self.assertEqual(loaded.node_checkpoints["a"].error, "boom")

    def test_agent_result_output_can_be_serialized_and_restored(self) -> None:
        original = AgentResult(
            agent_name="PlannerAgent",
            success=True,
            output=ResearchPlan(question="Q", search_queries=["q"]),
        )

        restored = deserialize_checkpoint_output(serialize_checkpoint_output(original))

        self.assertIsInstance(restored, AgentResult)
        self.assertIsInstance(restored.output, ResearchPlan)
        self.assertEqual(restored.output.search_queries, ["q"])

    def test_save_uses_temp_file_then_rename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JSONCheckpointStore(temp_dir)
            checkpoint = RunCheckpoint.new("task", run_id="run-1")

            store.save_checkpoint(checkpoint)

            self.assertTrue(store.checkpoint_path("run-1").exists())
            self.assertFalse(Path(str(store.checkpoint_path("run-1")) + ".tmp").exists())
            payload = json.loads(store.checkpoint_path("run-1").read_text(encoding="utf-8"))
            self.assertEqual(payload["run_id"], "run-1")


if __name__ == "__main__":
    unittest.main()
