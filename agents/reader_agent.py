from typing import List

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.schema import Finding, PageContent, SearchResult
from memory.compression import compress_findings


class ReaderAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="ReaderAgent", role="reader")

    def run(self, context: AgentContext) -> AgentResult:
        results = context.inputs["search_results"]
        if not isinstance(results, list):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="ReaderAgent expected a list of SearchResult in context.inputs['search_results'].",
                metadata={"role": self.role, "handoff": "search_results -> findings"},
            )

        metadata = {
            "role": self.role,
            "handoff": "search_results -> findings",
            "task_id": context.task_id,
            "finding_count": 0,
            "used_fetch": False,
            "fetch_success_count": 0,
            "fetch_failure_count": 0,
            "fallback_used": False,
            "grounded_findings_count": 0,
            "citation_count": 0,
        }
        fetch_tool = context.inputs.get("fetch_tool")
        citation_registry = context.inputs.get("citation_registry")
        if fetch_tool is not None:
            metadata["used_fetch"] = True

        findings: List[Finding] = []
        for index, result in enumerate(results, start=1):
            page_content = self._fetch_page(fetch_tool, result, metadata)
            finding = self._finding_from_result(index, result, page_content)
            self._ground_finding(finding, result, page_content, citation_registry, metadata)
            findings.append(finding)
        findings = compress_findings(findings)
        metadata["finding_count"] = len(findings)
        self._write_memory(context, findings, metadata)
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=findings,
            metadata=metadata,
        )

    def _fetch_page(self, fetch_tool, result: SearchResult, metadata: dict) -> PageContent | None:
        if fetch_tool is None:
            return None
        try:
            page_content = fetch_tool.fetch(result.url)
        except Exception as exc:
            metadata["fetch_failure_count"] += 1
            metadata["fallback_used"] = True
            metadata["fetch_error"] = str(exc)
            return None
        if page_content.fetched and page_content.text:
            metadata["fetch_success_count"] += 1
            return page_content
        metadata["fetch_failure_count"] += 1
        metadata["fallback_used"] = True
        if page_content.error:
            metadata["fetch_error"] = page_content.error
        return None

    def _finding_from_result(
        self,
        index: int,
        result: SearchResult,
        page_content: PageContent | None,
    ) -> Finding:
        if page_content is not None:
            evidence = page_content.text[:500]
            claim = self._summarize_page_content(page_content, fallback_title=result.title)
        else:
            evidence = result.snippet
            claim = self._summarize_snippet(result.snippet)
        return Finding(
            claim=claim,
            evidence=evidence,
            source_url=result.url,
            finding_id=f"finding-{index}",
            source_title=(page_content.title if page_content else result.title),
        )

    @staticmethod
    def _ground_finding(
        finding: Finding,
        result: SearchResult,
        page_content: PageContent | None,
        citation_registry,
        metadata: dict,
    ) -> None:
        if citation_registry is None:
            return
        source_title = page_content.title if page_content and page_content.title else result.title
        evidence_text = finding.evidence
        evidence = citation_registry.add_evidence(
            source_url=finding.source_url,
            text=evidence_text,
            source_title=source_title,
            metadata={"finding_id": finding.finding_id},
        )
        citation = citation_registry.add_citation(
            source_url=finding.source_url,
            evidence_id=evidence.evidence_id,
            source_title=source_title,
            quote=evidence_text[:240],
            metadata={"finding_id": finding.finding_id},
        )
        finding.evidence_id = evidence.evidence_id
        finding.citation_id = citation.citation_id
        finding.source_title = source_title
        metadata["grounded_findings_count"] += 1
        metadata["citation_count"] = len(citation_registry.list_citations())

    @staticmethod
    def _summarize_snippet(snippet: str) -> str:
        normalized = snippet.strip().rstrip(".")
        if not normalized:
            return "No usable evidence was extracted from the mock result."
        prefix = "Mock evidence for "
        if normalized.startswith(prefix):
            _, _, remainder = normalized.partition(" indicates that ")
            if remainder:
                return remainder[:1].upper() + remainder[1:]
        return normalized

    @staticmethod
    def _summarize_page_content(page_content: PageContent, fallback_title: str) -> str:
        title = page_content.title or fallback_title
        first_sentence = page_content.text.strip().split(".")[0].strip()
        if first_sentence:
            return f"{title}: {first_sentence}."
        return f"{title}: page content was fetched and parsed."

    def _write_memory(self, context: AgentContext, findings: List[Finding], metadata: dict) -> None:
        if context.memory is None:
            return
        try:
            context.memory.add_record(
                item_type="findings",
                content=findings,
                source_agent=self.name,
                task_id=context.task_id,
                metadata=metadata,
            )
        except Exception as exc:
            metadata["memory_error"] = str(exc)
