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
        }
        fetch_tool = context.inputs.get("fetch_tool")
        if fetch_tool is not None:
            metadata["used_fetch"] = True

        findings: List[Finding] = []
        for index, result in enumerate(results, start=1):
            page_content = self._fetch_page(fetch_tool, result, metadata)
            findings.append(self._finding_from_result(index, result, page_content))
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
        )

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
