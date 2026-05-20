from typing import Any

from memory.run_serializer import to_jsonable
from memory.schema import (
    MEMORY_TYPE_CITATION,
    MEMORY_TYPE_EVIDENCE,
    MEMORY_TYPE_FAILURE,
    MEMORY_TYPE_NODE_OUTPUT,
    MEMORY_TYPE_SUMMARY,
    MemoryItem,
)


def build_memory_items_from_pipeline_result(
    result: dict,
    run_id: str | None = None,
) -> list[MemoryItem]:
    resolved_run_id = run_id or result.get("run_id")
    items: list[MemoryItem] = []
    items.extend(_evidence_items(result, resolved_run_id))
    items.extend(_citation_items(result, resolved_run_id))
    items.extend(_summary_items(result, resolved_run_id))
    items.extend(_node_output_items(result, resolved_run_id))
    items.extend(_failure_items(result, resolved_run_id))
    return items


def persist_pipeline_result_to_vector_memory(
    result: dict,
    vector_memory_store,
    run_id: str | None = None,
) -> list[str]:
    items = build_memory_items_from_pipeline_result(result, run_id=run_id)
    return vector_memory_store.add_items(items)


def _evidence_items(result: dict, run_id: str | None) -> list[MemoryItem]:
    items: list[MemoryItem] = []
    for finding in result.get("findings") or []:
        evidence = getattr(finding, "evidence", "")
        if not evidence:
            continue
        items.append(
            MemoryItem(
                run_id=run_id,
                node_id="reader_task",
                task_id="reader_task",
                agent_name="ReaderAgent",
                memory_type=MEMORY_TYPE_EVIDENCE,
                text=evidence,
                source_url=getattr(finding, "source_url", None),
                title=getattr(finding, "source_title", None),
                citation=getattr(finding, "citation_id", None),
                metadata={
                    "finding_id": getattr(finding, "finding_id", ""),
                    "evidence_id": getattr(finding, "evidence_id", None),
                    "claim": getattr(finding, "claim", ""),
                },
            )
        )

    registry = result.get("citation_registry")
    if registry is None or not hasattr(registry, "list_evidence"):
        return items
    for evidence in registry.list_evidence():
        evidence_text = getattr(evidence, "text", "")
        if not evidence_text:
            continue
        items.append(
            MemoryItem(
                run_id=run_id,
                node_id="reader_task",
                task_id="reader_task",
                agent_name="ReaderAgent",
                memory_type=MEMORY_TYPE_EVIDENCE,
                text=evidence_text,
                source_url=getattr(evidence, "source_url", None),
                title=getattr(evidence, "source_title", None),
                citation=getattr(evidence, "evidence_id", None),
                metadata={
                    "evidence_id": getattr(evidence, "evidence_id", None),
                    **dict(getattr(evidence, "metadata", {}) or {}),
                },
            )
        )
    return items


def _citation_items(result: dict, run_id: str | None) -> list[MemoryItem]:
    registry = result.get("citation_registry")
    if registry is None or not hasattr(registry, "list_citations"):
        return []

    items: list[MemoryItem] = []
    for citation in registry.list_citations():
        citation_id = getattr(citation, "citation_id", None)
        source_url = getattr(citation, "source_url", None)
        quote = getattr(citation, "quote", None)
        title = getattr(citation, "source_title", None)
        text = quote or " ".join(part for part in [citation_id, title, source_url] if part)
        if not text:
            continue
        items.append(
            MemoryItem(
                run_id=run_id,
                node_id="writer_task",
                task_id="writer_task",
                agent_name="WriterAgent",
                memory_type=MEMORY_TYPE_CITATION,
                text=text,
                source_url=source_url,
                title=title,
                citation=citation_id,
                metadata={
                    "citation_id": citation_id,
                    "evidence_id": getattr(citation, "evidence_id", None),
                    **dict(getattr(citation, "metadata", {}) or {}),
                },
            )
        )
    return items


def _summary_items(result: dict, run_id: str | None) -> list[MemoryItem]:
    report = result.get("report") or result.get("final_report")
    if report is None:
        return []

    summary = getattr(report, "summary", "") or getattr(report, "question", "")
    markdown = getattr(report, "markdown", "")
    text = summary or markdown[:1000]
    if not text:
        return []
    return [
        MemoryItem(
            run_id=run_id,
            node_id="writer_task",
            task_id="writer_task",
            agent_name="WriterAgent",
            memory_type=MEMORY_TYPE_SUMMARY,
            text=text,
            title=getattr(report, "title", None),
            metadata={
                "question": getattr(report, "question", ""),
                "citation_count": len(getattr(report, "citations", []) or []),
            },
        )
    ]


def _node_output_items(result: dict, run_id: str | None) -> list[MemoryItem]:
    execution = result.get("execution")
    outputs = getattr(execution, "outputs", {}) if execution is not None else {}
    if not isinstance(outputs, dict):
        return []

    items: list[MemoryItem] = []
    for node_id, output in outputs.items():
        text = _text_from_output(output)
        if not text:
            continue
        items.append(
            MemoryItem(
                run_id=run_id,
                node_id=node_id,
                task_id=node_id,
                agent_name=getattr(output, "agent_name", None),
                memory_type=MEMORY_TYPE_NODE_OUTPUT,
                text=text,
                metadata={"node_id": node_id},
            )
        )
    return items


def _failure_items(result: dict, run_id: str | None) -> list[MemoryItem]:
    traces = result.get("traces") or []
    items: list[MemoryItem] = []
    for trace in traces:
        if not isinstance(trace, dict) or trace.get("state") != "FAILED":
            continue
        error = trace.get("error") or "node failed"
        node_id = trace.get("task_id")
        items.append(
            MemoryItem(
                run_id=run_id,
                node_id=node_id,
                task_id=node_id,
                agent_name=(trace.get("metadata") or {}).get("agent_name"),
                memory_type=MEMORY_TYPE_FAILURE,
                text=error,
                metadata={
                    "task_name": trace.get("task_name"),
                    "timestamp_ms": trace.get("timestamp_ms"),
                },
            )
        )
    return items


def _text_from_output(output: Any) -> str:
    content = getattr(output, "output", output)
    if content is None:
        return ""
    if hasattr(content, "markdown"):
        return str(content.markdown or "").strip()
    if isinstance(content, list):
        lines = []
        for item in content:
            claim = getattr(item, "claim", None)
            evidence = getattr(item, "evidence", None)
            if claim or evidence:
                lines.append(" ".join(part for part in [claim, evidence] if part))
            else:
                lines.append(str(to_jsonable(item)))
        return "\n".join(lines).strip()
    if isinstance(content, str):
        return content.strip()
    return str(to_jsonable(content)).strip()
