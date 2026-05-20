from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


MEMORY_TYPE_EVIDENCE = "evidence"
MEMORY_TYPE_SUMMARY = "summary"
MEMORY_TYPE_CITATION = "citation"
MEMORY_TYPE_FAILURE = "failure"
MEMORY_TYPE_NODE_OUTPUT = "node_output"

SUPPORTED_MEMORY_TYPES = {
    MEMORY_TYPE_EVIDENCE,
    MEMORY_TYPE_SUMMARY,
    MEMORY_TYPE_CITATION,
    MEMORY_TYPE_FAILURE,
    MEMORY_TYPE_NODE_OUTPUT,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_memory_type(memory_type: str) -> str:
    if memory_type not in SUPPORTED_MEMORY_TYPES:
        supported = ", ".join(sorted(SUPPORTED_MEMORY_TYPES))
        raise ValueError(f"Unsupported memory_type '{memory_type}'. Supported values: {supported}")
    return memory_type


@dataclass
class MemoryItem:
    memory_type: str
    text: str
    memory_id: str = field(default_factory=lambda: str(uuid4()))
    run_id: Optional[str] = None
    node_id: Optional[str] = None
    task_id: Optional[str] = None
    agent_name: Optional[str] = None
    source_url: Optional[str] = None
    title: Optional[str] = None
    citation: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        validate_memory_type(self.memory_type)
        self.text = str(self.text or "").strip()
        if not self.text:
            raise ValueError("MemoryItem.text must not be empty.")


@dataclass
class MemorySearchResult:
    memory_id: str
    text: str
    score: float
    memory_type: str
    source_url: Optional[str] = None
    citation: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
