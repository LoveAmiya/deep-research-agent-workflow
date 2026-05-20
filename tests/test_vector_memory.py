import tempfile
import unittest
from pathlib import Path

from memory.embeddings import HashEmbeddingProvider
from memory.schema import (
    MEMORY_TYPE_EVIDENCE,
    MEMORY_TYPE_FAILURE,
    MEMORY_TYPE_NODE_OUTPUT,
    MEMORY_TYPE_SUMMARY,
    MemoryItem,
    validate_memory_type,
)
from memory.vector_store import SQLiteVectorMemoryStore, cosine_similarity
from orchestrator.research_pipeline import run_research_pipeline


class TestHashEmbeddingProvider(unittest.TestCase):
    def test_hash_embedding_is_deterministic_and_fixed_dimension(self) -> None:
        provider = HashEmbeddingProvider(dimensions=16)

        first = provider.embed_text("Evidence about governance and adoption")
        second = provider.embed_text("Evidence about governance and adoption")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)

    def test_empty_text_returns_zero_vector(self) -> None:
        provider = HashEmbeddingProvider(dimensions=8)

        self.assertEqual(provider.embed_text(""), [0.0] * 8)


class TestVectorMemorySchema(unittest.TestCase):
    def test_memory_item_validates_type(self) -> None:
        item = MemoryItem(memory_type=MEMORY_TYPE_EVIDENCE, text="Useful evidence")

        self.assertEqual(item.memory_type, MEMORY_TYPE_EVIDENCE)

    def test_invalid_memory_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            validate_memory_type("unknown")

    def test_empty_text_raises(self) -> None:
        with self.assertRaises(ValueError):
            MemoryItem(memory_type=MEMORY_TYPE_EVIDENCE, text=" ")


class TestSQLiteVectorMemoryStore(unittest.TestCase):
    def test_add_get_and_list_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            memory_id = store.add_item(
                MemoryItem(
                    run_id="run-1",
                    node_id="reader_task",
                    task_id="reader_task",
                    agent_name="ReaderAgent",
                    memory_type=MEMORY_TYPE_EVIDENCE,
                    text="Governance controls influence enterprise adoption.",
                    source_url="mock://source",
                    citation="C1",
                )
            )

            item = store.get_item(memory_id)
            listed = store.list_items(run_id="run-1", memory_type=MEMORY_TYPE_EVIDENCE)

            self.assertIsNotNone(item)
            self.assertEqual(item.memory_id, memory_id)
            self.assertEqual(len(listed), 1)
            store.close()

    def test_search_ranks_matching_item_and_supports_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.add_items(
                [
                    MemoryItem(
                        run_id="run-1",
                        memory_type=MEMORY_TYPE_EVIDENCE,
                        text="Enterprise governance and risk controls shape adoption.",
                    ),
                    MemoryItem(
                        run_id="run-2",
                        memory_type=MEMORY_TYPE_SUMMARY,
                        text="Consumer entertainment trends are unrelated.",
                    ),
                    MemoryItem(
                        run_id="run-1",
                        memory_type=MEMORY_TYPE_FAILURE,
                        text="Reader fetch failed for one source.",
                    ),
                ]
            )

            results = store.search(
                "governance risk adoption",
                top_k=2,
                memory_type=MEMORY_TYPE_EVIDENCE,
                run_id="run-1",
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].memory_type, MEMORY_TYPE_EVIDENCE)
            self.assertGreater(results[0].score, 0.0)
            store.close()

    def test_duplicate_fingerprint_returns_existing_id_per_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            first_id = store.add_item(
                MemoryItem(run_id="run-1", memory_type=MEMORY_TYPE_EVIDENCE, text="Same evidence")
            )
            second_id = store.add_item(
                MemoryItem(run_id="run-1", memory_type=MEMORY_TYPE_EVIDENCE, text="Same evidence")
            )
            other_run_id = store.add_item(
                MemoryItem(run_id="run-2", memory_type=MEMORY_TYPE_EVIDENCE, text="Same evidence")
            )

            self.assertEqual(first_id, second_id)
            self.assertNotEqual(first_id, other_run_id)
            self.assertEqual(len(store.list_items()), 2)
            store.close()

    def test_delete_run_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            store.add_item(MemoryItem(run_id="run-1", memory_type=MEMORY_TYPE_NODE_OUTPUT, text="A"))
            store.add_item(MemoryItem(run_id="run-2", memory_type=MEMORY_TYPE_NODE_OUTPUT, text="B"))

            deleted_count = store.delete_run_memory("run-1")

            self.assertEqual(deleted_count, 1)
            self.assertEqual(len(store.list_items(run_id="run-1")), 0)
            self.assertEqual(len(store.list_items(run_id="run-2")), 1)
            store.close()

    def test_cosine_similarity_handles_mismatched_vectors(self) -> None:
        self.assertEqual(cosine_similarity([1.0], [1.0, 0.0]), 0.0)

    @staticmethod
    def _store(temp_dir: str) -> SQLiteVectorMemoryStore:
        return SQLiteVectorMemoryStore(
            str(Path(temp_dir) / "memory.sqlite3"),
            embedding_provider=HashEmbeddingProvider(dimensions=32),
        )


class TestVectorMemoryPipelineIntegration(unittest.TestCase):
    def test_pipeline_can_optionally_persist_vector_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteVectorMemoryStore(
                str(Path(temp_dir) / "memory.sqlite3"),
                embedding_provider=HashEmbeddingProvider(dimensions=32),
            )

            result = run_research_pipeline(
                "What affects enterprise open-source LLM adoption?",
                checkpoint_enabled=True,
                checkpoint_dir=str(Path(temp_dir) / "checkpoints"),
                run_id="run-20",
                vector_memory_store=store,
            )

            items = store.list_items(run_id="run-20")
            evidence_results = store.search(
                "enterprise adoption governance",
                memory_type=MEMORY_TYPE_EVIDENCE,
                run_id="run-20",
            )

            self.assertTrue(result["success"])
            self.assertIn("vector_memory_ids", result)
            self.assertGreater(len(items), 0)
            self.assertGreater(len(evidence_results), 0)
            store.close()


if __name__ == "__main__":
    unittest.main()
