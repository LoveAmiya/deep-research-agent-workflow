"""Provider-based search layer for DeepResearchAgent."""

from search.providers import (
    BaseSearchProvider,
    BraveSearchProvider,
    DuckDuckGoSearchProvider,
    MockSearchProvider,
    SearchProviderResponse,
    SearchProviderResult,
    SerpAPIProvider,
    TavilyProvider,
)
from search.fetchers import (
    BaseWebFetcher,
    HTTPWebFetcher,
    MockWebFetcher,
    WebFetchResult,
    create_web_fetcher,
)
from search.registry import SearchProviderRegistry, create_search_provider_registry

__all__ = [
    "BaseWebFetcher",
    "BaseSearchProvider",
    "BraveSearchProvider",
    "DuckDuckGoSearchProvider",
    "HTTPWebFetcher",
    "MockWebFetcher",
    "MockSearchProvider",
    "SearchProviderResponse",
    "SearchProviderResult",
    "SearchProviderRegistry",
    "SerpAPIProvider",
    "TavilyProvider",
    "WebFetchResult",
    "create_search_provider_registry",
    "create_web_fetcher",
]
