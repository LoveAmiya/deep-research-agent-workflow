from typing import List

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.schema import ResearchPlan, SearchResult


class SearcherAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="SearcherAgent", role="searcher")

    def run(self, context: AgentContext) -> AgentResult:
        plan = context.inputs["plan"]
        if not isinstance(plan, ResearchPlan):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="SearcherAgent expected a ResearchPlan in context.inputs['plan'].",
                metadata={"role": self.role, "handoff": "plan -> search_results"},
            )

        results: List[SearchResult] = []
        for index, query in enumerate(plan.search_queries, start=1):
            snippet = (
                f"Mock evidence for '{query}' indicates that enterprise adoption depends on "
                "cost control, governance readiness, integration effort, and measurable business value."
            )
            results.append(
                SearchResult(
                    title=f"Mock Source {index} for {plan.question}",
                    url=f"mock://source/{index}",
                    snippet=snippet,
                    source="mock",
                )
            )
        metadata = {
            "role": self.role,
            "handoff": "plan -> search_results",
            "task_id": context.task_id,
            "result_count": len(results),
        }
        self._write_memory(context, results, metadata)
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=results,
            metadata=metadata,
        )

    def _write_memory(self, context: AgentContext, results: List[SearchResult], metadata: dict) -> None:
        if context.memory is None:
            return
        try:
            context.memory.add_record(
                item_type="search_results",
                content=results,
                source_agent=self.name,
                task_id=context.task_id,
                metadata=metadata,
            )
        except Exception as exc:
            metadata["memory_error"] = str(exc)
