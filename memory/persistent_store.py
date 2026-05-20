import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from memory.run_serializer import build_run_payload, build_run_summary, to_jsonable


class PersistentStoreError(Exception):
    """Raised when run persistence fails."""


@dataclass
class RunRecord:
    run_id: str
    question: str
    created_at: str
    status: str
    report_markdown: Optional[str]
    summary: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)


class SQLiteRunStore:
    def __init__(self, db_path: str = "runs/deep_research_runs.sqlite3") -> None:
        self.db_path = db_path
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def save_run(self, record: RunRecord) -> RunRecord:
        connection = None
        try:
            connection = self._connect()
            connection.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id,
                    question,
                    created_at,
                    status,
                    report_markdown,
                    summary_json,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.question,
                    record.created_at,
                    record.status,
                    record.report_markdown,
                    json.dumps(to_jsonable(record.summary), ensure_ascii=True, sort_keys=True),
                    json.dumps(to_jsonable(record.payload), ensure_ascii=True, sort_keys=True),
                ),
            )
            connection.commit()
            return record
        except Exception as exc:
            raise PersistentStoreError(f"failed to save run '{record.run_id}': {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def save_run_result(
        self,
        result: dict,
        question: Optional[str] = None,
        status: str = "SUCCESS",
    ) -> RunRecord:
        resolved_question = question or self._question_from_result(result)
        report = result.get("report") or result.get("final_report")
        report_markdown = getattr(report, "markdown", None) if report is not None else None
        record = RunRecord(
            run_id=str(uuid4()),
            question=resolved_question,
            created_at=datetime.now(timezone.utc).isoformat(),
            status=status,
            report_markdown=report_markdown,
            summary=build_run_summary(result, resolved_question),
            payload=build_run_payload(result),
        )
        return self.save_run(record)

    def load_run(self, run_id: str) -> Optional[RunRecord]:
        connection = None
        try:
            connection = self._connect()
            row = connection.execute(
                """
                SELECT run_id, question, created_at, status, report_markdown, summary_json, payload_json
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_record(row)
        except Exception as exc:
            raise PersistentStoreError(f"failed to load run '{run_id}': {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def list_runs(self, limit: int = 20) -> list[RunRecord]:
        connection = None
        try:
            connection = self._connect()
            rows = connection.execute(
                """
                SELECT run_id, question, created_at, status, report_markdown, summary_json, payload_json
                FROM runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        except Exception as exc:
            raise PersistentStoreError(f"failed to list runs: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def export_run_summary(self, run_id: str) -> dict:
        record = self.load_run(run_id)
        if record is None:
            raise PersistentStoreError(f"run not found: {run_id}")
        return {
            "run_id": record.run_id,
            "question": record.question,
            "created_at": record.created_at,
            "status": record.status,
            "summary": record.summary,
        }

    def delete_run(self, run_id: str) -> bool:
        connection = None
        try:
            connection = self._connect()
            cursor = connection.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            connection.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            raise PersistentStoreError(f"failed to delete run '{run_id}': {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _initialize(self) -> None:
        connection = None
        try:
            connection = self._connect()
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    question TEXT,
                    created_at TEXT,
                    status TEXT,
                    report_markdown TEXT,
                    summary_json TEXT,
                    payload_json TEXT
                )
                """
            )
            connection.commit()
        except Exception as exc:
            raise PersistentStoreError(f"failed to initialize run store: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _row_to_record(row) -> RunRecord:
        return RunRecord(
            run_id=row[0],
            question=row[1],
            created_at=row[2],
            status=row[3],
            report_markdown=row[4],
            summary=json.loads(row[5]) if row[5] else {},
            payload=json.loads(row[6]) if row[6] else {},
        )

    @staticmethod
    def _question_from_result(result: dict) -> str:
        question = result.get("question")
        if isinstance(question, str):
            return question
        if hasattr(question, "question"):
            return question.question
        report = result.get("report") or result.get("final_report")
        if hasattr(report, "question"):
            return report.question
        return ""
