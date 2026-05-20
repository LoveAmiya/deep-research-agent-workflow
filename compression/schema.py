from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceUnit:
    evidence_id: str
    text: str
    source_url: str | None = None
    title: str | None = None
    citation: str | None = None
    source_type: str | None = None
    node_id: str | None = None
    agent_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompressedContext:
    query: str
    compressed_text: str
    selected_evidence: list[EvidenceUnit] = field(default_factory=list)
    preserved_quotes: list[dict[str, Any]] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    dropped_evidence_count: int = 0
    original_token_estimate: int = 0
    compressed_token_estimate: int = 0
    compression_ratio: float = 0.0
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompressionConfig:
    max_tokens: int = 3000
    l1_top_k: int = 20
    l2_top_k: int = 12
    preserve_citations: bool = True
    preserve_raw_quotes: bool = True
    min_evidence_chars: int = 20
    max_quote_chars: int = 240

    def __post_init__(self) -> None:
        self.max_tokens = max(1, int(self.max_tokens))
        self.l1_top_k = max(1, int(self.l1_top_k))
        self.l2_top_k = max(1, int(self.l2_top_k))
        self.min_evidence_chars = max(0, int(self.min_evidence_chars))
        self.max_quote_chars = max(1, int(self.max_quote_chars))
