from typing import Iterable, List, Optional

from core.config import SearchConfig
from search.providers import (
    BaseSearchProvider,
    BraveSearchProvider,
    DuckDuckGoSearchProvider,
    MockSearchProvider,
    SearchProviderResponse,
    SerpAPIProvider,
    TavilyProvider,
)


class SearchProviderRegistry:
    def __init__(self, allow_mock_fallback: bool = True) -> None:
        self._providers: dict[str, BaseSearchProvider] = {}
        self.allow_mock_fallback = allow_mock_fallback
        self._aliases = {
            "duckduckgo": "duckduckgo_html",
            "simple_web": "duckduckgo_html",
            "brave_search": "brave",
            "serp_api": "serpapi",
        }

    def register(self, provider: BaseSearchProvider) -> BaseSearchProvider:
        self._providers[provider.name] = provider
        return provider

    def get(self, name: str) -> Optional[BaseSearchProvider]:
        return self._providers.get(name) or self._providers.get(self._aliases.get(name, ""))

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())

    def search_with_fallback(
        self,
        query: str,
        provider_order: Iterable[str] | None,
        max_results: int = 5,
    ) -> SearchProviderResponse:
        ordered_names = list(provider_order or ["mock"])
        attempted_providers: list[str] = []
        provider_errors: dict[str, str] = {}

        for index, provider_name in enumerate(ordered_names):
            response = self._try_provider(provider_name, query, max_results)
            attempted_providers.append(provider_name)
            if response.success and response.results:
                response.metadata.update(
                    {
                        "attempted_providers": attempted_providers,
                        "selected_provider": response.provider,
                        "fallback_used": index > 0,
                        "provider_errors": provider_errors,
                    }
                )
                return response
            provider_errors[provider_name] = response.error or "provider returned no results"

        if self.allow_mock_fallback and "mock" not in attempted_providers:
            response = self._try_provider("mock", query, max_results)
            attempted_providers.append("mock")
            if response.success and response.results:
                response.metadata.update(
                    {
                        "attempted_providers": attempted_providers,
                        "selected_provider": response.provider,
                        "fallback_used": True,
                        "provider_errors": provider_errors,
                    }
                )
                return response
            provider_errors["mock"] = response.error or "provider returned no results"

        return SearchProviderResponse(
            query=query,
            provider="none",
            success=False,
            error="all search providers failed",
            metadata={
                "attempted_providers": attempted_providers,
                "selected_provider": None,
                "fallback_used": self.allow_mock_fallback and "mock" in attempted_providers,
                "provider_errors": provider_errors,
            },
        )

    def _try_provider(self, provider_name: str, query: str, max_results: int) -> SearchProviderResponse:
        provider = self.get(provider_name)
        if provider is None:
            return SearchProviderResponse(
                query=query,
                provider=provider_name,
                success=False,
                error=f"search provider not registered: {provider_name}",
            )
        try:
            return provider.search(query, max_results=max_results)
        except Exception as exc:
            return SearchProviderResponse(
                query=query,
                provider=provider.name,
                success=False,
                error=str(exc),
                metadata={"error_type": exc.__class__.__name__},
            )


def create_search_provider_registry(config: SearchConfig) -> SearchProviderRegistry:
    registry = SearchProviderRegistry(allow_mock_fallback=True)
    registry.register(MockSearchProvider())
    registry.register(
        DuckDuckGoSearchProvider(
            timeout_seconds=config.timeout_seconds,
            user_agent=config.user_agent,
        )
    )
    registry.register(BraveSearchProvider(api_key=config.brave_api_key))
    registry.register(SerpAPIProvider(api_key=config.serpapi_api_key))
    registry.register(TavilyProvider(api_key=config.tavily_api_key))
    return registry
