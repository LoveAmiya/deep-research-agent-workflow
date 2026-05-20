from dataclasses import replace
import re
from typing import Any

from compression.schema import CompressedContext, CompressionConfig, EvidenceUnit
from compression.text_rank import rank_sentences
from compression.token_counter import estimate_tokens
from memory.dedup import normalize_text_for_fingerprint
from memory.embeddings import EmbeddingProvider, HashEmbeddingProvider
from memory.vector_store import cosine_similarity


class ContextCompressor:
    def __init__(self, embedding_provider: EmbeddingProvider | None = None) -> None:
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()

    def compress(
        self,
        query: str,
        evidence_units: list[EvidenceUnit],
        config: CompressionConfig | None = None,
    ) -> CompressedContext:
        resolved_config = config or CompressionConfig()
        warnings: list[str] = []
        original_token_estimate = sum(
            estimate_tokens(_original_text_for_estimate(unit)) for unit in evidence_units
        )
        cleaned_units, duplicate_count, short_count = self._clean_evidence(evidence_units, resolved_config)
        if duplicate_count:
            warnings.append(f"Dropped {duplicate_count} duplicate evidence item(s).")
        if short_count:
            warnings.append(f"Dropped {short_count} evidence item(s) below min_evidence_chars.")
        if not cleaned_units:
            warnings.append("No usable evidence available for compression.")
            return CompressedContext(
                query=query,
                compressed_text="",
                selected_evidence=[],
                preserved_quotes=[],
                citations=[],
                dropped_evidence_count=len(evidence_units),
                original_token_estimate=original_token_estimate,
                compressed_token_estimate=0,
                compression_ratio=0.0,
                warnings=warnings,
                metadata={
                    "compression_enabled": True,
                    "l1_selected_count": 0,
                    "l2_selected_sentence_count": 0,
                },
            )

        l1_units = self._l1_select(query, cleaned_units, resolved_config)
        ranked_sentences = rank_sentences(
            query=query,
            texts=[unit.text for unit in l1_units],
            top_k=resolved_config.l2_top_k,
        )
        compressed_text, selected_units, quotes, citations = self._assemble_context(
            query=query,
            l1_units=l1_units,
            ranked_sentences=ranked_sentences,
            config=resolved_config,
        )
        if not compressed_text and l1_units:
            warnings.append("TextRank did not select usable sentences; using first available evidence quote.")
            compressed_text, selected_units, quotes, citations = self._fallback_context(l1_units, resolved_config)

        compressed_token_estimate = estimate_tokens(compressed_text)
        compression_ratio = (
            compressed_token_estimate / original_token_estimate
            if original_token_estimate > 0
            else 0.0
        )
        return CompressedContext(
            query=query,
            compressed_text=compressed_text,
            selected_evidence=selected_units,
            preserved_quotes=quotes,
            citations=citations,
            dropped_evidence_count=len(evidence_units) - len(selected_units),
            original_token_estimate=original_token_estimate,
            compressed_token_estimate=compressed_token_estimate,
            compression_ratio=compression_ratio,
            warnings=warnings,
            metadata={
                "compression_enabled": True,
                "original_evidence_count": len(evidence_units),
                "cleaned_evidence_count": len(cleaned_units),
                "l1_selected_count": len(l1_units),
                "l2_selected_sentence_count": len(ranked_sentences),
                "selected_evidence_count": len(selected_units),
            },
        )

    def compress_from_memory(
        self,
        query: str,
        memory_items: list[Any],
        config: CompressionConfig | None = None,
    ) -> CompressedContext:
        from compression.integration import build_evidence_units_from_memory_items

        evidence_units = build_evidence_units_from_memory_items(memory_items)
        return self.compress(query, evidence_units, config=config)

    def merge_contexts(
        self,
        contexts: list[CompressedContext],
        config: CompressionConfig | None = None,
    ) -> CompressedContext:
        resolved_config = config or CompressionConfig()
        evidence_by_id: dict[str, EvidenceUnit] = {}
        for context in contexts:
            for unit in context.selected_evidence:
                evidence_by_id.setdefault(unit.evidence_id, unit)
        query = " ".join(context.query for context in contexts if context.query).strip()
        if not evidence_by_id:
            warnings = ["No selected evidence available to merge."]
            warnings.extend(warning for context in contexts for warning in context.warnings)
            return CompressedContext(
                query=query,
                compressed_text="",
                warnings=warnings,
                metadata={"merged_context_count": len(contexts)},
            )
        merged = self.compress(
            query=query,
            evidence_units=list(evidence_by_id.values()),
            config=resolved_config,
        )
        merged.metadata["merged_context_count"] = len(contexts)
        return merged

    def _clean_evidence(
        self,
        evidence_units: list[EvidenceUnit],
        config: CompressionConfig,
    ) -> tuple[list[EvidenceUnit], int, int]:
        cleaned = []
        seen = set()
        duplicate_count = 0
        short_count = 0
        for unit in evidence_units:
            text = str(unit.text or "").strip()
            if not text:
                short_count += 1
                continue
            if len(text) < config.min_evidence_chars:
                short_count += 1
                continue
            fingerprint = normalize_text_for_fingerprint(text)
            if fingerprint in seen:
                duplicate_count += 1
                continue
            seen.add(fingerprint)
            cleaned.append(replace(unit, text=text))
        return cleaned, duplicate_count, short_count

    def _l1_select(
        self,
        query: str,
        evidence_units: list[EvidenceUnit],
        config: CompressionConfig,
    ) -> list[EvidenceUnit]:
        query_embedding = self.embedding_provider.embed_text(query)
        scored_units = []
        query_terms = _query_terms(query)
        for unit in evidence_units:
            evidence_embedding = self.embedding_provider.embed_text(unit.text)
            embedding_score = cosine_similarity(query_embedding, evidence_embedding)
            text_terms = _query_terms(unit.text)
            lexical_score = len(query_terms & text_terms) / max(1, len(query_terms))
            score = embedding_score + (5.0 * lexical_score)
            scored_units.append((score, unit.evidence_id, unit))
        scored_units.sort(key=lambda item: (-item[0], item[1]))
        return [unit for _, _, unit in scored_units[: config.l1_top_k]]

    def _assemble_context(
        self,
        query: str,
        l1_units: list[EvidenceUnit],
        ranked_sentences: list[dict[str, Any]],
        config: CompressionConfig,
    ) -> tuple[str, list[EvidenceUnit], list[dict[str, Any]], list[str]]:
        lines: list[str] = []
        selected_by_id: dict[str, EvidenceUnit] = {}
        quotes: list[dict[str, Any]] = []
        citations: list[str] = []
        seen_sentences = set()

        for ranked in ranked_sentences:
            unit = l1_units[ranked["source_index"]]
            sentence = str(ranked["sentence"]).strip()
            if not sentence:
                continue
            sentence_key = normalize_text_for_fingerprint(sentence)
            if sentence_key in seen_sentences:
                continue
            seen_sentences.add(sentence_key)
            candidate_line = self._format_sentence_line(sentence, unit, config)
            candidate_text = "\n".join(lines + [candidate_line])
            if estimate_tokens(candidate_text) > config.max_tokens and lines:
                break
            if estimate_tokens(candidate_line) > config.max_tokens:
                continue
            lines.append(candidate_line)
            selected_by_id[unit.evidence_id] = unit
            quote = self._quote_from_sentence(sentence, unit, config)
            if quote:
                quotes.append(quote)
            if config.preserve_citations and unit.citation and unit.citation not in citations:
                citations.append(unit.citation)

        return "\n".join(lines), list(selected_by_id.values()), quotes, citations

    def _fallback_context(
        self,
        l1_units: list[EvidenceUnit],
        config: CompressionConfig,
    ) -> tuple[str, list[EvidenceUnit], list[dict[str, Any]], list[str]]:
        unit = l1_units[0]
        quote_text = unit.text[: config.max_quote_chars].strip()
        line = self._format_sentence_line(quote_text, unit, config)
        quote = self._quote_from_sentence(quote_text, unit, config)
        citations = [unit.citation] if config.preserve_citations and unit.citation else []
        return line, [unit], [quote] if quote else [], citations

    @staticmethod
    def _format_sentence_line(sentence: str, unit: EvidenceUnit, config: CompressionConfig) -> str:
        parts = [sentence]
        if config.preserve_citations and unit.citation:
            parts.append(f"[{unit.citation}]")
        if unit.title:
            parts.append(f"Title: {unit.title}")
        if unit.source_url:
            parts.append(f"Source: {unit.source_url}")
        return " ".join(parts)

    @staticmethod
    def _quote_from_sentence(
        sentence: str,
        unit: EvidenceUnit,
        config: CompressionConfig,
    ) -> dict[str, Any] | None:
        if not config.preserve_raw_quotes:
            return None
        quote = sentence[: config.max_quote_chars].strip()
        if not quote:
            return None
        return {
            "evidence_id": unit.evidence_id,
            "quote": quote,
            "citation": unit.citation,
            "source_url": unit.source_url,
            "title": unit.title,
            "metadata": dict(unit.metadata),
        }


def _query_terms(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", str(text or "").lower()))


def _original_text_for_estimate(unit: EvidenceUnit) -> str:
    return " ".join(
        part
        for part in [
            unit.text,
            unit.citation,
            unit.source_url,
            unit.title,
        ]
        if part
    )
