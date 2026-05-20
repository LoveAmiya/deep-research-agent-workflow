from typing import List

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.schema import Finding, SearchResult


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
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=findings,
            metadata={
                "role": self.role,
                "handoff": "search_results -> findings",
                "task_id": context.task_id,
                "finding_count": len(findings),
            },
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
