from typing import List

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.schema import Finding, SearchResult
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

        findings: List[Finding] = []
        for index, result in enumerate(results, start=1):
            claim = self._summarize_snippet(result.snippet)
            findings.append(
                Finding(
                    claim=claim,
                    evidence=result.snippet,
                    source_url=result.url,
                    finding_id=f"finding-{index}",
                )
            )
        findings = compress_findings(findings)
        metadata = {
            "role": self.role,
            "handoff": "search_results -> findings",
            "task_id": context.task_id,
            "finding_count": len(findings),
        }
        self._write_memory(context, findings, metadata)
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=findings,
            metadata=metadata,
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
