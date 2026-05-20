import unittest

from agents.base_agent import AgentContext
from agents.planner_agent import PlannerAgent
from agents.searcher_agent import SearcherAgent
from core.schema import ResearchQuestion
from search.providers import BaseSearchProvider, MockSearchProvider, SearchProviderResponse
from search.registry import SearchProviderRegistry


class FailingProvider(BaseSearchProvider):
    name = "failing"

    def search(self, query: str, max_results: int = 5) -> SearchProviderResponse:
        return SearchProviderResponse(
            query=query,
            provider=self.name,
            success=False,
            error="forced registry failure",
            metadata={"error_type": "ForcedFailure"},
        )


class TestSearcherAgentProviderRegistry(unittest.TestCase):
    def test_searcher_uses_provider_registry(self) -> None:
        registry = SearchProviderRegistry()
        registry.register(MockSearchProvider())

        result = SearcherAgent().run(
            AgentContext(
                task_id="search_task",
                inputs={
                    "plan": self._plan(),
                    "search_provider_registry": registry,
                    "search_provider_order": ["mock"],
                    "real_search_enabled": False,
                    "max_results": 2,
                },
                search_provider_registry=registry,
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(len(result.output), 2)
        self.assertEqual(result.metadata["search_provider"], "mock")
        self.assertEqual(result.metadata["attempted_providers"], ["mock"])
        self.assertFalse(result.metadata["fallback_used"])
        self.assertFalse(result.metadata["real_search_enabled"])

    def test_searcher_provider_failure_does_not_crash_pipeline_step(self) -> None:
        registry = SearchProviderRegistry()
        registry.register(FailingProvider())
        registry.register(MockSearchProvider())

        result = SearcherAgent().run(
            AgentContext(
                task_id="search_task",
                inputs={
                    "plan": self._plan(),
                    "search_provider_registry": registry,
                    "search_provider_order": ["failing"],
                    "real_search_enabled": True,
                },
                search_provider_registry=registry,
            )
        )

        self.assertTrue(result.success)
        self.assertGreater(len(result.output), 0)
        self.assertEqual(result.metadata["search_provider"], "mock")
        self.assertTrue(result.metadata["fallback_used"])
        self.assertTrue(result.metadata["real_search_enabled"])
        self.assertIn("failing", result.metadata["attempted_providers"])
        self.assertIn("failing", result.metadata["provider_errors"])

    @staticmethod
    def _plan():
        question = ResearchQuestion(question="What affects enterprise open-source LLM adoption?")
        return PlannerAgent().run(
            AgentContext(task_id="planner_task", inputs={"question": question})
        ).output


if __name__ == "__main__":
    unittest.main()
