import math
import re
from collections import Counter
from typing import Any


_SENTENCE_PATTERN = re.compile(r"[^.!?。！？\n]+[.!?。！？]?")
_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}


def split_sentences(text: str) -> list[str]:
    sentences = []
    for match in _SENTENCE_PATTERN.finditer(str(text or "")):
        sentence = match.group(0).strip()
        if sentence:
            sentences.append(sentence)
    return sentences


def rank_sentences(query: str, texts: list[str], top_k: int) -> list[dict[str, Any]]:
    sentence_records = []
    for source_index, text in enumerate(texts):
        for sentence_index, sentence in enumerate(split_sentences(text)):
            tokens = _tokenize(sentence)
            if not tokens:
                continue
            sentence_records.append(
                {
                    "sentence": sentence,
                    "source_index": source_index,
                    "sentence_index": sentence_index,
                    "tokens": tokens,
                }
            )
    if not sentence_records or top_k <= 0:
        return []

    query_tokens = _tokenize(query)
    graph = _build_similarity_graph(sentence_records)
    scores = _page_rank(graph)
    query_counter = Counter(query_tokens)
    ranked = []
    for index, record in enumerate(sentence_records):
        query_score = _cosine_from_counters(Counter(record["tokens"]), query_counter)
        score = scores[index] + (0.35 * query_score)
        ranked.append(
            {
                "sentence": record["sentence"],
                "score": score,
                "source_index": record["source_index"],
                "sentence_index": record["sentence_index"],
            }
        )
    ranked.sort(key=lambda item: (-item["score"], item["source_index"], item["sentence_index"]))
    return ranked[:top_k]


def _tokenize(text: str) -> list[str]:
    tokens = []
    for token in _WORD_PATTERN.findall(str(text or "").lower()):
        if token in _STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _build_similarity_graph(sentence_records: list[dict[str, Any]]) -> list[list[float]]:
    counters = [Counter(record["tokens"]) for record in sentence_records]
    graph = [[0.0 for _ in sentence_records] for _ in sentence_records]
    for left_index in range(len(sentence_records)):
        for right_index in range(left_index + 1, len(sentence_records)):
            similarity = _cosine_from_counters(counters[left_index], counters[right_index])
            if similarity <= 0:
                continue
            graph[left_index][right_index] = similarity
            graph[right_index][left_index] = similarity
    return graph


def _page_rank(
    graph: list[list[float]],
    damping: float = 0.85,
    iterations: int = 20,
) -> list[float]:
    count = len(graph)
    if count == 0:
        return []
    scores = [1.0 / count for _ in graph]
    for _ in range(iterations):
        next_scores = [(1.0 - damping) / count for _ in graph]
        for source_index, edges in enumerate(graph):
            edge_total = sum(edges)
            if edge_total == 0:
                share = damping * scores[source_index] / count
                for target_index in range(count):
                    next_scores[target_index] += share
                continue
            for target_index, weight in enumerate(edges):
                if weight > 0:
                    next_scores[target_index] += damping * scores[source_index] * (weight / edge_total)
        scores = next_scores
    return scores


def _cosine_from_counters(left: Counter, right: Counter) -> float:
    if not left or not right:
        return 0.0
    overlap = set(left) & set(right)
    dot_product = sum(left[token] * right[token] for token in overlap)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot_product / (left_norm * right_norm)
