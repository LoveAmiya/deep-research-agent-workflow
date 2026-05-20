import json
import math
import sqlite3
from pathlib import Path
from typing import Optional

from memory.dedup import build_memory_fingerprint
from memory.embeddings import EmbeddingProvider, HashEmbeddingProvider
from memory.schema import MemoryItem, MemorySearchResult, validate_memory_type


class SQLiteVectorMemoryStore:
    def __init__(
        self,
        db_path: str = "data/memory.sqlite3",
        embedding_provider: Optional[EmbeddingProvider] = None,
    ) -> None:
        self.db_path = db_path
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def add_item(self, item: MemoryItem) -> str:
        validate_memory_type(item.memory_type)
        fingerprint = build_memory_fingerprint(
            memory_type=item.memory_type,
            text=item.text,
            source_url=item.source_url,
            citation=item.citation,
            run_id=item.run_id,
        )
        existing_id = self._existing_memory_id(fingerprint)
        if existing_id is not None:
            return existing_id

        embedding = self.embedding_provider.embed_text(item.text)
        self._connection.execute(
            """
            INSERT INTO vector_memory (
                memory_id,
                run_id,
                node_id,
                task_id,
                agent_name,
                memory_type,
                text,
                source_url,
                title,
                citation,
                metadata_json,
                embedding_json,
                fingerprint,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.memory_id,
                item.run_id,
                item.node_id,
                item.task_id,
                item.agent_name,
                item.memory_type,
                item.text,
                item.source_url,
                item.title,
                item.citation,
                json.dumps(item.metadata, ensure_ascii=True, sort_keys=True),
                json.dumps(embedding, ensure_ascii=True),
                fingerprint,
                item.created_at,
            ),
        )
        self._connection.commit()
        return item.memory_id

    def add_items(self, items: list[MemoryItem]) -> list[str]:
        return [self.add_item(item) for item in items]

    def search(
        self,
        query_text: str,
        top_k: int = 5,
        memory_type: str | None = None,
        run_id: str | None = None,
    ) -> list[MemorySearchResult]:
        if memory_type is not None:
            validate_memory_type(memory_type)
        if top_k <= 0:
            return []

        query_embedding = self.embedding_provider.embed_text(query_text)
        scored_results: list[MemorySearchResult] = []
        for row in self._candidate_rows(memory_type=memory_type, run_id=run_id):
            embedding = json.loads(row["embedding_json"] or "[]")
            score = cosine_similarity(query_embedding, embedding)
            scored_results.append(
                MemorySearchResult(
                    memory_id=row["memory_id"],
                    text=row["text"],
                    score=score,
                    memory_type=row["memory_type"],
                    source_url=row["source_url"],
                    citation=row["citation"],
                    metadata=json.loads(row["metadata_json"] or "{}"),
                )
            )
        scored_results.sort(key=lambda result: (-result.score, result.memory_id))
        return scored_results[:top_k]

    def get_item(self, memory_id: str) -> MemoryItem | None:
        row = self._connection.execute(
            """
            SELECT memory_id, run_id, node_id, task_id, agent_name, memory_type, text,
                   source_url, title, citation, metadata_json, created_at
            FROM vector_memory
            WHERE memory_id = ?
            """,
            (memory_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_item(row)

    def list_items(
        self,
        run_id: str | None = None,
        memory_type: str | None = None,
    ) -> list[MemoryItem]:
        if memory_type is not None:
            validate_memory_type(memory_type)
        conditions = []
        parameters = []
        if run_id is not None:
            conditions.append("run_id = ?")
            parameters.append(run_id)
        if memory_type is not None:
            conditions.append("memory_type = ?")
            parameters.append(memory_type)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._connection.execute(
            f"""
            SELECT memory_id, run_id, node_id, task_id, agent_name, memory_type, text,
                   source_url, title, citation, metadata_json, created_at
            FROM vector_memory
            {where_clause}
            ORDER BY created_at ASC, memory_id ASC
            """,
            tuple(parameters),
        ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def delete_run_memory(self, run_id: str) -> int:
        cursor = self._connection.execute(
            "DELETE FROM vector_memory WHERE run_id = ?",
            (run_id,),
        )
        self._connection.commit()
        return cursor.rowcount

    def close(self) -> None:
        self._connection.close()

    def _initialize(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS vector_memory (
                memory_id TEXT PRIMARY KEY,
                run_id TEXT,
                node_id TEXT,
                task_id TEXT,
                agent_name TEXT,
                memory_type TEXT NOT NULL,
                text TEXT NOT NULL,
                source_url TEXT,
                title TEXT,
                citation TEXT,
                metadata_json TEXT,
                embedding_json TEXT NOT NULL,
                fingerprint TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_vector_memory_run_id ON vector_memory(run_id)"
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_vector_memory_type ON vector_memory(memory_type)"
        )
        self._connection.commit()

    def _existing_memory_id(self, fingerprint: str) -> str | None:
        row = self._connection.execute(
            "SELECT memory_id FROM vector_memory WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            return None
        return row["memory_id"]

    def _candidate_rows(
        self,
        memory_type: str | None = None,
        run_id: str | None = None,
    ) -> list[sqlite3.Row]:
        conditions = []
        parameters = []
        if run_id is not None:
            conditions.append("run_id = ?")
            parameters.append(run_id)
        if memory_type is not None:
            conditions.append("memory_type = ?")
            parameters.append(memory_type)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return self._connection.execute(
            f"""
            SELECT memory_id, memory_type, text, source_url, citation, metadata_json, embedding_json
            FROM vector_memory
            {where_clause}
            """,
            tuple(parameters),
        ).fetchall()

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            memory_id=row["memory_id"],
            run_id=row["run_id"],
            node_id=row["node_id"],
            task_id=row["task_id"],
            agent_name=row["agent_name"],
            memory_type=row["memory_type"],
            text=row["text"],
            source_url=row["source_url"],
            title=row["title"],
            citation=row["citation"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
        )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot_product = sum(left_value * right_value for left_value, right_value in zip(left, right))
    return dot_product / (left_norm * right_norm)
