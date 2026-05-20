from typing import List

from agents.base_agent import BaseAgent
from core.schema import ResearchPlan, SearchResult


class SearcherAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="SearcherAgent", role="searcher")

    def run(self, plan: ResearchPlan) -> List[SearchResult]:
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
