from typing import Any

from compression.compressor import ContextCompressor
from compression.schema import CompressedContext, CompressionConfig, EvidenceUnit
from memory.run_serializer import to_jsonable


def build_evidence_units_from_node_outputs(outputs: dict[str, Any]) -> list[EvidenceUnit]:
    units: list[EvidenceUnit] = []
    for node_id, output in (outputs or {}).items():
        agent_name = getattr(output, "agent_name", None)
        content = getattr(output, "output", output)
        units.extend(_units_from_content(content, node_id=node_id, agent_name=agent_name))
    return units


def build_evidence_units_from_memory_items(memory_items: list[Any]) -> list[EvidenceUnit]:
    units: list[EvidenceUnit] = []
    for index, item in enumerate(memory_items):
        text = getattr(item, "text", None)
        if text is None:
            text = getattr(item, "content", "")
        source_url = getattr(item, "source_url", None)
        title = getattr(item, "title", None)
        citation = getattr(item, "citation", None)
        if source_url is None and isinstance(text, dict):
            source_url = text.get("source_url")
        if title is None and isinstance(text, dict):
            title = text.get("title") or text.get("source_title")
        if citation is None and isinstance(text, dict):
            citation = text.get("citation") or text.get("citation_id")
        metadata = dict(getattr(item, "metadata", {}) or {})
        memory_id = getattr(item, "memory_id", None) or getattr(item, "item_id", None) or f"memory-{index + 1}"
        metadata.setdefault("memory_id", memory_id)
        memory_type = getattr(item, "memory_type", None) or getattr(item, "item_type", None)
        units.append(
            EvidenceUnit(
                evidence_id=str(memory_id),
                text=_content_to_text(text),
                source_url=source_url,
                title=title,
                citation=citation,
                source_type=memory_type,
                node_id=getattr(item, "node_id", None) or getattr(item, "task_id", None),
                agent_name=getattr(item, "agent_name", None) or getattr(item, "source_agent", None),
                metadata=metadata,
            )
        )
    return units


def compress_for_writer(
    query: str,
    evidence_units: list[EvidenceUnit] | None = None,
    memory_items: list[Any] | None = None,
    config: CompressionConfig | None = None,
    compressor: ContextCompressor | None = None,
) -> CompressedContext:
    return _compress_for_role(
        query=query,
        role="writer",
        evidence_units=evidence_units,
        memory_items=memory_items,
        config=config,
        compressor=compressor,
    )


def compress_for_reviewer(
    query: str,
    evidence_units: list[EvidenceUnit] | None = None,
    memory_items: list[Any] | None = None,
    config: CompressionConfig | None = None,
    compressor: ContextCompressor | None = None,
) -> CompressedContext:
    return _compress_for_role(
        query=query,
        role="reviewer",
        evidence_units=evidence_units,
        memory_items=memory_items,
        config=config,
        compressor=compressor,
    )


def _compress_for_role(
    query: str,
    role: str,
    evidence_units: list[EvidenceUnit] | None,
    memory_items: list[Any] | None,
    config: CompressionConfig | None,
    compressor: ContextCompressor | None,
) -> CompressedContext:
    units = list(evidence_units or [])
    if memory_items:
        units.extend(build_evidence_units_from_memory_items(memory_items))
    context = (compressor or ContextCompressor()).compress(query, units, config=config)
    context.metadata["target_role"] = role
    return context


def _units_from_content(content: Any, node_id: str, agent_name: str | None) -> list[EvidenceUnit]:
    if content is None:
        return []
    if isinstance(content, list):
        units = []
        for index, item in enumerate(content):
            text = getattr(item, "evidence", None) or getattr(item, "text", None) or _content_to_text(item)
            units.append(
                EvidenceUnit(
                    evidence_id=getattr(item, "evidence_id", None)
                    or getattr(item, "finding_id", None)
                    or f"{node_id}-{index + 1}",
                    text=text,
                    source_url=getattr(item, "source_url", None),
                    title=getattr(item, "source_title", None) or getattr(item, "title", None),
                    citation=getattr(item, "citation_id", None) or getattr(item, "citation", None),
                    source_type="node_output",
                    node_id=node_id,
                    agent_name=agent_name,
                    metadata={
                        "claim": getattr(item, "claim", None),
                        "summary": getattr(item, "summary", None),
                        **dict(getattr(item, "metadata", {}) or {}),
                    },
                )
            )
        return units
    return [
        EvidenceUnit(
            evidence_id=node_id,
            text=_content_to_text(content),
            source_type="node_output",
            node_id=node_id,
            agent_name=agent_name,
            metadata={"node_id": node_id},
        )
    ]


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if hasattr(content, "markdown"):
        return str(content.markdown or "").strip()
    if isinstance(content, list):
        return "\n".join(_content_to_text(item) for item in content).strip()
    return str(to_jsonable(content)).strip()
