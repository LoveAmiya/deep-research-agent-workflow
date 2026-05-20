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
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=results,
            metadata={
                "role": self.role,
                "handoff": "plan -> search_results",
                "task_id": context.task_id,
                "result_count": len(results),
            },
        )
