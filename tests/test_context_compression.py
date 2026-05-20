import inspect
import unittest

import compression.compressor
import compression.text_rank
from compression.compressor import ContextCompressor
from compression.integration import (
    build_evidence_units_from_memory_items,
    build_evidence_units_from_node_outputs,
    compress_for_reviewer,
    compress_for_writer,
)
from compression.schema import CompressedContext, CompressionConfig, EvidenceUnit
from compression.text_rank import rank_sentences
from compression.token_counter import estimate_tokens
from memory.schema import MEMORY_TYPE_EVIDENCE, MemoryItem


class TestTokenCounter(unittest.TestCase):
    def test_estimate_tokens_handles_english(self) -> None:
        self.assertGreaterEqual(estimate_tokens("Enterprise governance affects adoption."), 4)

    def test_estimate_tokens_handles_chinese(self) -> None:
        self.assertGreaterEqual(estimate_tokens("企业治理影响采用。"), 6)

    def test_estimate_tokens_empty_text_returns_zero(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)


class TestCompressionSchemas(unittest.TestCase):
    def test_evidence_unit_can_be_constructed(self) -> None:
        unit = EvidenceUnit(
            evidence_id="E1",
            text="Governance evidence",
            source_url="mock://source",
            title="Source title",
            citation="C1",
            source_type="evidence",
            node_id="reader_task",
            agent_name="ReaderAgent",
            metadata={"k": "v"},
        )

        self.assertEqual(unit.citation, "C1")
        self.assertEqual(unit.metadata["k"], "v")

    def test_compressed_context_can_be_constructed(self) -> None:
        context = CompressedContext(query="q", compressed_text="answer", citations=["C1"])

        self.assertEqual(context.compressed_text, "answer")
        self.assertEqual(context.citations, ["C1"])


class TestTextRank(unittest.TestCase):
    def test_text_rank_selects_query_relevant_sentence(self) -> None:
        ranked = rank_sentences(
            query="governance risk adoption",
            texts=[
                "Entertainment trends are unrelated. Governance risk controls shape enterprise adoption.",
                "Weather changes often affect travel planning.",
            ],
            top_k=1,
        )

        self.assertEqual(len(ranked), 1)
        self.assertIn("Governance risk", ranked[0]["sentence"])


class TestContextCompressor(unittest.TestCase):
    def test_context_compressor_can_compress_evidence(self) -> None:
        context = ContextCompressor().compress(
            "enterprise adoption governance",
            self._evidence_units(),
            CompressionConfig(max_tokens=80, l1_top_k=2, l2_top_k=2),
        )

        self.assertTrue(context.compressed_text)
        self.assertGreater(len(context.selected_evidence), 0)

    def test_compressed_tokens_are_not_more_than_original(self) -> None:
        context = ContextCompressor().compress(
            "governance adoption",
            self._evidence_units(),
            CompressionConfig(max_tokens=40, l1_top_k=2, l2_top_k=1),
        )

        self.assertLessEqual(context.compressed_token_estimate, context.original_token_estimate)

    def test_l1_prefers_query_related_evidence(self) -> None:
        context = ContextCompressor().compress(
            "governance adoption controls",
            self._evidence_units(),
            CompressionConfig(max_tokens=80, l1_top_k=1, l2_top_k=2),
        )

        self.assertEqual(context.selected_evidence[0].evidence_id, "E1")

    def test_l3_preserves_citation_source_url_and_title(self) -> None:
        context = ContextCompressor().compress(
            "governance adoption",
            self._evidence_units(),
            CompressionConfig(max_tokens=120, l1_top_k=1, l2_top_k=2),
        )

        self.assertIn("C1", context.citations)
        self.assertIn("[C1]", context.compressed_text)
        self.assertIn("mock://governance", context.compressed_text)
        self.assertIn("Governance Source", context.compressed_text)

    def test_preserved_quotes_are_bounded(self) -> None:
        context = ContextCompressor().compress(
            "governance adoption",
            self._evidence_units(),
            CompressionConfig(max_tokens=120, l1_top_k=1, l2_top_k=2, max_quote_chars=32),
        )

        self.assertGreater(len(context.preserved_quotes), 0)
        self.assertLessEqual(len(context.preserved_quotes[0]["quote"]), 32)

    def test_duplicate_evidence_is_deduplicated(self) -> None:
        duplicate = EvidenceUnit(
            evidence_id="E1-duplicate",
            text=self._evidence_units()[0].text,
            source_url="mock://duplicate",
        )

        context = ContextCompressor().compress(
            "governance adoption",
            [*self._evidence_units(), duplicate],
            CompressionConfig(max_tokens=120, l1_top_k=5, l2_top_k=3),
        )

        self.assertTrue(any("duplicate" in warning for warning in context.warnings))
        self.assertNotIn("E1-duplicate", [unit.evidence_id for unit in context.selected_evidence])

    def test_empty_evidence_returns_warning(self) -> None:
        context = ContextCompressor().compress("query", [], CompressionConfig())

        self.assertEqual(context.compressed_text, "")
        self.assertGreater(len(context.warnings), 0)

    def test_compress_from_memory_can_work(self) -> None:
        memory_items = [
            MemoryItem(
                memory_id="M1",
                run_id="run-1",
                memory_type=MEMORY_TYPE_EVIDENCE,
                text="Enterprise governance evidence supports adoption decisions.",
                source_url="mock://memory",
                title="Memory Source",
                citation="C7",
            )
        ]

        context = ContextCompressor().compress_from_memory(
            "governance adoption",
            memory_items,
            CompressionConfig(max_tokens=80, min_evidence_chars=5),
        )

        self.assertTrue(context.compressed_text)
        self.assertIn("C7", context.citations)

    def test_merge_contexts_combines_selected_evidence(self) -> None:
        compressor = ContextCompressor()
        first = compressor.compress(
            "governance adoption",
            [self._evidence_units()[0]],
            CompressionConfig(max_tokens=80, min_evidence_chars=5),
        )
        second = compressor.compress(
            "integration readiness",
            [self._evidence_units()[1]],
            CompressionConfig(max_tokens=80, min_evidence_chars=5),
        )

        merged = compressor.merge_contexts([first, second], CompressionConfig(max_tokens=120))

        self.assertTrue(merged.compressed_text)
        self.assertEqual(merged.metadata["merged_context_count"], 2)

    @staticmethod
    def _evidence_units() -> list[EvidenceUnit]:
        return [
            EvidenceUnit(
                evidence_id="E1",
                text=(
                    "Enterprise governance risk controls shape open-source LLM adoption. "
                    "Teams need approval workflows, audit trails, and clear ownership before deployment."
                ),
                source_url="mock://governance",
                title="Governance Source",
                citation="C1",
                source_type="evidence",
                node_id="reader_task",
                agent_name="ReaderAgent",
                metadata={"memory_id": "M1"},
            ),
            EvidenceUnit(
                evidence_id="E2",
                text=(
                    "Integration readiness affects deployment because teams need model serving, monitoring, "
                    "and fallback operations. Operational maturity changes adoption speed."
                ),
                source_url="mock://integration",
                title="Integration Source",
                citation="C2",
            ),
            EvidenceUnit(
                evidence_id="E3",
                text="Sports entertainment schedules are unrelated to enterprise model governance.",
                source_url="mock://unrelated",
                title="Unrelated Source",
                citation="C3",
            ),
        ]


class TestCompressionIntegration(unittest.TestCase):
    def test_memory_item_can_convert_to_evidence_unit(self) -> None:
        item = MemoryItem(
            memory_id="M1",
            memory_type=MEMORY_TYPE_EVIDENCE,
            text="Evidence text from memory",
            source_url="mock://memory",
            title="Memory Title",
            citation="C9",
        )

        units = build_evidence_units_from_memory_items([item])

        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].evidence_id, "M1")
        self.assertEqual(units[0].source_url, "mock://memory")
        self.assertEqual(units[0].title, "Memory Title")

    def test_node_outputs_can_convert_to_evidence_units(self) -> None:
        units = build_evidence_units_from_node_outputs(
            {
                "reader_task": [
                    EvidenceUnit(
                        evidence_id="E1",
                        text="Reader evidence",
                        source_url="mock://source",
                    )
                ]
            }
        )

        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].node_id, "reader_task")

    def test_compress_for_writer_and_reviewer_are_optional_helpers(self) -> None:
        evidence_units = [
            EvidenceUnit(
                evidence_id="E1",
                text="Governance context supports writer and reviewer decisions.",
                citation="C1",
            )
        ]

        writer_context = compress_for_writer(
            "governance",
            evidence_units=evidence_units,
            config=CompressionConfig(max_tokens=80, min_evidence_chars=5),
        )
        reviewer_context = compress_for_reviewer(
            "governance",
            evidence_units=evidence_units,
            config=CompressionConfig(max_tokens=80, min_evidence_chars=5),
        )

        self.assertEqual(writer_context.metadata["target_role"], "writer")
        self.assertEqual(reviewer_context.metadata["target_role"], "reviewer")


class TestCompressionBoundaries(unittest.TestCase):
    def test_compression_does_not_import_external_llm_or_network_clients(self) -> None:
        source = inspect.getsource(compression.compressor) + inspect.getsource(compression.text_rank)

        self.assertNotIn("ollama", source.lower())
        self.assertNotIn("requests", source.lower())
        self.assertNotIn("openai", source.lower())


if __name__ == "__main__":
    unittest.main()
