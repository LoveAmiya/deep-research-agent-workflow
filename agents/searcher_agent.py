from typing import List

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.schema import ResearchPlan, SearchResult
from tools.search_tool import MockSearchTool


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

        metadata = self._base_metadata(context)
        results = self._search_with_tool_or_fallback(plan, context, metadata)
        metadata["result_count"] = len(results)
        self._write_memory(context, results, metadata)
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=results,
            metadata=metadata,
        )

    def _search_with_tool_or_fallback(
        self,
        plan: ResearchPlan,
        context: AgentContext,
        metadata: dict,
    ) -> List[SearchResult]:
        search_tool = context.inputs.get("search_tool")
        max_results = int(context.inputs.get("max_results", 5))
        if search_tool is None:
            return self._deterministic_results(plan)

        provider = getattr(search_tool, "provider", search_tool.__class__.__name__)
        metadata["search_provider"] = provider
        try:
            results: List[SearchResult] = []
            for query in plan.search_queries:
                results.extend(search_tool.search(query, max_results=max_results))
            if not results:
                raise ValueError("search tool returned no results")
            metadata["used_real_search"] = provider != "mock"
            return results[:max_results]
        except Exception as exc:
            metadata["used_real_search"] = False
            metadata["fallback_used"] = True
            metadata["search_error"] = str(exc)
            fallback_tool = MockSearchTool()
            fallback_results: List[SearchResult] = []
            for query in plan.search_queries:
                fallback_results.extend(fallback_tool.search(query, max_results=1))
            return fallback_results or self._deterministic_results(plan)

    def _deterministic_results(self, plan: ResearchPlan) -> List[SearchResult]:
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
        return results

    def _base_metadata(self, context: AgentContext) -> dict:
        metadata = {
            "role": self.role,
            "handoff": "plan -> search_results",
            "task_id": context.task_id,
            "result_count": 0,
            "used_real_search": False,
            "search_provider": "deterministic_mock",
            "fallback_used": False,
            "search_error": None,
        }
        return metadata

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
