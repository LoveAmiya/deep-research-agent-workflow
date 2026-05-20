import unittest

from search.providers import BaseSearchProvider, MockSearchProvider, SearchProviderResponse
from search.registry import SearchProviderRegistry


class FailingProvider(BaseSearchProvider):
    name = "failing"

    def search(self, query: str, max_results: int = 5) -> SearchProviderResponse:
        return SearchProviderResponse(
            query=query,
            provider=self.name,
            success=False,
            error="forced provider failure",
            metadata={"error_type": "ForcedFailure"},
        )


class EmptyProvider(BaseSearchProvider):
    name = "empty"

    def search(self, query: str, max_results: int = 5) -> SearchProviderResponse:
        return SearchProviderResponse(
            query=query,
            provider=self.name,
            success=True,
            results=[],
            metadata={"result_count": 0},
        )


class TestSearchProviders(unittest.TestCase):
    def test_mock_search_provider_returns_stable_results(self) -> None:
        provider = MockSearchProvider()

        first = provider.search("enterprise LLM adoption", max_results=2)
        second = provider.search("enterprise LLM adoption", max_results=2)

        self.assertTrue(first.success)
        self.assertEqual(first.results, second.results)
        self.assertEqual(len(first.results), 2)
        self.assertEqual(first.results[0].provider, "mock")

    def test_registry_can_register_and_list_provider(self) -> None:
        registry = SearchProviderRegistry()

        registry.register(MockSearchProvider())

        self.assertIsNotNone(registry.get("mock"))
        self.assertIn("mock", registry.list_providers())

    def test_search_with_fallback_uses_second_provider_when_first_fails(self) -> None:
        registry = SearchProviderRegistry()
        registry.register(FailingProvider())
        registry.register(MockSearchProvider())

        response = registry.search_with_fallback(
            "enterprise LLM adoption",
            provider_order=["failing", "mock"],
            max_results=1,
        )

        self.assertTrue(response.success)
        self.assertEqual(response.metadata["attempted_providers"], ["failing", "mock"])
        self.assertEqual(response.metadata["selected_provider"], "mock")
        self.assertTrue(response.metadata["fallback_used"])
        self.assertIn("failing", response.metadata["provider_errors"])

    def test_all_real_providers_failed_can_fallback_to_mock(self) -> None:
        registry = SearchProviderRegistry()
        registry.register(FailingProvider())
        registry.register(MockSearchProvider())

        response = registry.search_with_fallback(
            "AI safety governance",
            provider_order=["failing"],
            max_results=1,
        )

        self.assertTrue(response.success)
        self.assertEqual(response.metadata["attempted_providers"], ["failing", "mock"])
        self.assertEqual(response.metadata["selected_provider"], "mock")
        self.assertTrue(response.metadata["fallback_used"])

    def test_empty_results_are_treated_as_fallback_reason(self) -> None:
        registry = SearchProviderRegistry()
        registry.register(EmptyProvider())
        registry.register(MockSearchProvider())

        response = registry.search_with_fallback(
            "open source sustainability",
            provider_order=["empty"],
            max_results=1,
        )

        self.assertTrue(response.success)
        self.assertTrue(response.metadata["fallback_used"])
        self.assertIn("empty", response.metadata["provider_errors"])


if __name__ == "__main__":
    unittest.main()
