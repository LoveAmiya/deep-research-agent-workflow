import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from core.schema import Finding
from memory.persistent_store import RunRecord, SQLiteRunStore
from memory.run_serializer import build_run_summary, to_jsonable
from orchestrator.research_pipeline import run_research_pipeline


@dataclass
class ExampleDataclass:
    name: str
    count: int


class UnknownObject:
    def __str__(self) -> str:
        return "unknown-object"


class TestPersistentRunStore(unittest.TestCase):
    def test_initializes_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "runs.sqlite3")
            SQLiteRunStore(db_path)

            self.assertTrue(Path(db_path).exists())
            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
                ).fetchone()
            finally:
                connection.close()
            self.assertIsNotNone(row)

    def test_save_and_load_run_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteRunStore(str(Path(temp_dir) / "runs.sqlite3"))
            record = self._record("run-1")

            store.save_run(record)
            loaded = store.load_run("run-1")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.question, "Question")
            self.assertEqual(loaded.summary["success"], True)

    def test_list_runs_returns_recent_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteRunStore(str(Path(temp_dir) / "runs.sqlite3"))
            store.save_run(self._record("run-1", created_at="2026-01-01T00:00:00+00:00"))
            store.save_run(self._record("run-2", created_at="2026-01-02T00:00:00+00:00"))

            runs = store.list_runs(limit=1)

            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].run_id, "run-2")

    def test_save_run_result_persists_pipeline_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteRunStore(str(Path(temp_dir) / "runs.sqlite3"))
            result = run_research_pipeline("What affects enterprise AI adoption?")

            record = store.save_run_result(result)
            loaded = store.load_run(record.run_id)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.summary["finding_count"], len(result["findings"]))
            self.assertTrue(loaded.report_markdown)

    def test_export_run_summary_returns_summary_dict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteRunStore(str(Path(temp_dir) / "runs.sqlite3"))
            saved = store.save_run(self._record("run-1"))

            summary = store.export_run_summary(saved.run_id)

            self.assertEqual(summary["run_id"], "run-1")
            self.assertIn("summary", summary)

    def test_to_jsonable_handles_dataclass(self) -> None:
        value = to_jsonable(ExampleDataclass(name="x", count=1))

        self.assertEqual(value, {"name": "x", "count": 1})

    def test_to_jsonable_handles_unknown_object(self) -> None:
        value = to_jsonable({"object": UnknownObject()})

        self.assertEqual(value["object"], "unknown-object")

    def test_build_run_summary_contains_counts(self) -> None:
        result = {
            "question": "Question",
            "findings": [Finding(claim="c", evidence="e", source_url="mock://1")],
            "memory_items": [{"item_type": "findings"}],
            "citation_validation": {
                "citation_count": 1,
                "grounded_citation_count": 1,
                "passed": True,
            },
            "success": True,
        }

        summary = build_run_summary(result, "Question")

        self.assertEqual(summary["finding_count"], 1)
        self.assertEqual(summary["citation_count"], 1)
        self.assertEqual(summary["memory_item_count"], 1)

    def test_main_pipeline_result_can_be_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteRunStore(str(Path(temp_dir) / "runs.sqlite3"))
            result = run_research_pipeline("What affects cybersecurity risk analysis?")

            record = store.save_run_result(result, status="SUCCESS")

            self.assertEqual(record.status, "SUCCESS")
            self.assertTrue(store.load_run(record.run_id))

    @staticmethod
    def _record(run_id: str, created_at: str = "2026-01-01T00:00:00+00:00") -> RunRecord:
        return RunRecord(
            run_id=run_id,
            question="Question",
            created_at=created_at,
            status="SUCCESS",
            report_markdown="# Report",
            summary={"success": True},
            payload={"report": "# Report"},
        )


if __name__ == "__main__":
    unittest.main()
