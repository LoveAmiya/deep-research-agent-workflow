from typing import List

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.schema import Finding, PageContent, SearchResult
from memory.compression import compress_findings
from search.fetchers import WebFetchResult


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
            "fetcher_name": None,
            "fetched_url_count": 0,
            "successful_fetch_count": 0,
            "failed_fetch_count": 0,
            "fetch_errors": [],
            "content_extraction_used": False,
            "fallback_used": False,
            "grounded_findings_count": 0,
            "citation_count": 0,
        }
        fetch_tool = context.inputs.get("fetch_tool")
        web_fetcher = context.web_fetcher or context.inputs.get("web_fetcher")
        citation_registry = context.inputs.get("citation_registry")
        if web_fetcher is not None:
            metadata["used_fetch"] = True
            metadata["fetcher_name"] = getattr(web_fetcher, "name", web_fetcher.__class__.__name__)
            metadata["content_extraction_used"] = True
        elif fetch_tool is not None:
            metadata["used_fetch"] = True
            metadata["fetcher_name"] = getattr(fetch_tool, "provider", fetch_tool.__class__.__name__)

        findings: List[Finding] = []
        for index, result in enumerate(results, start=1):
            page_content = self._fetch_page(web_fetcher, fetch_tool, result, metadata)
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

    def _fetch_page(
        self,
        web_fetcher,
        fetch_tool,
        result: SearchResult,
        metadata: dict,
    ) -> PageContent | None:
        if web_fetcher is not None:
            return self._fetch_with_web_fetcher(web_fetcher, result, metadata)
        if fetch_tool is None:
            return None
        try:
            page_content = fetch_tool.fetch(result.url)
        except Exception as exc:
            metadata["fetch_failure_count"] += 1
            metadata["fallback_used"] = True
            metadata["fetch_error"] = str(exc)
            metadata["fetch_errors"].append({"url": result.url, "error": str(exc)})
            return None
        if page_content.fetched and page_content.text:
            metadata["fetch_success_count"] += 1
            metadata["successful_fetch_count"] += 1
            metadata["fetched_url_count"] += 1
            return page_content
        metadata["fetch_failure_count"] += 1
        metadata["failed_fetch_count"] += 1
        metadata["fetched_url_count"] += 1
        metadata["fallback_used"] = True
        if page_content.error:
            metadata["fetch_error"] = page_content.error
            metadata["fetch_errors"].append({"url": result.url, "error": page_content.error})
        return None

    def _fetch_with_web_fetcher(
        self,
        web_fetcher,
        result: SearchResult,
        metadata: dict,
    ) -> PageContent | None:
        metadata["fetched_url_count"] += 1
        try:
            fetch_result = web_fetcher.fetch(result.url)
        except Exception as exc:
            metadata["fetch_failure_count"] += 1
            metadata["failed_fetch_count"] += 1
            metadata["fallback_used"] = True
            metadata["fetch_error"] = str(exc)
            metadata["fetch_errors"].append({"url": result.url, "error": str(exc)})
            return None

        if fetch_result.success and fetch_result.text:
            metadata["fetch_success_count"] += 1
            metadata["successful_fetch_count"] += 1
            return PageContent(
                url=fetch_result.url,
                title=fetch_result.title or result.title,
                text=fetch_result.text,
                status_code=fetch_result.status_code,
                fetched=True,
                error=None,
            )

        metadata["fetch_failure_count"] += 1
        metadata["failed_fetch_count"] += 1
        metadata["fallback_used"] = True
        error = fetch_result.error or "web fetcher returned no text"
        metadata["fetch_error"] = error
        metadata["fetch_errors"].append(
            {
                "url": result.url,
                "error": error,
                "fetcher": getattr(web_fetcher, "name", web_fetcher.__class__.__name__),
                "metadata": fetch_result.metadata,
            }
        )
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
