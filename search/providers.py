import time
import urllib.parse
from dataclasses import dataclass, field
from typing import List, Optional

from core.config import SearchConfig
from tools.search_tool import DuckDuckGoHTMLSearchTool


@dataclass
class SearchProviderResult:
    title: str
    url: str
    snippet: str
    provider: str
    rank: int
    metadata: dict = field(default_factory=dict)


@dataclass
class SearchProviderResponse:
    query: str
    provider: str
    results: List[SearchProviderResult] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class BaseSearchProvider:
    name = "base"

    def search(self, query: str, max_results: int = 5) -> SearchProviderResponse:
        raise NotImplementedError("Search providers must implement search().")


class MockSearchProvider(BaseSearchProvider):
    name = "mock"

    def search(self, query: str, max_results: int = 5) -> SearchProviderResponse:
        normalized_query = query.strip() or "research question"
        result_count = max(1, max_results)
        quoted_query = urllib.parse.quote(normalized_query.replace(" ", "-"))
        results = []
        for rank in range(1, result_count + 1):
            results.append(
                SearchProviderResult(
                    title=f"Mock Provider Result {rank} for {normalized_query}",
                    url=f"mock://provider-search/{quoted_query}/{rank}",
                    snippet=(
                        f"Mock provider evidence for '{normalized_query}' highlights factor {rank}: "
                        "adoption depends on governance, integration effort, costs, and measurable value."
                    ),
                    provider=self.name,
                    rank=rank,
                    metadata={"mock": True},
                )
            )
        return SearchProviderResponse(
            query=query,
            provider=self.name,
            results=results,
            success=True,
            metadata={"result_count": len(results), "mock": True},
        )


class DuckDuckGoSearchProvider(BaseSearchProvider):
    name = "duckduckgo_html"

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        user_agent: Optional[str] = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent or SearchConfig().user_agent

    def search(self, query: str, max_results: int = 5) -> SearchProviderResponse:
        started = time.perf_counter()
        try:
            config = SearchConfig(
                enabled=True,
                provider=self.name,
                max_results=max_results,
                timeout_seconds=self.timeout_seconds,
                user_agent=self.user_agent,
            )
            raw_results = DuckDuckGoHTMLSearchTool(config).search(query, max_results=max_results)
            results = [
                SearchProviderResult(
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet,
                    provider=self.name,
                    rank=index,
                    metadata={"source": result.source},
                )
                for index, result in enumerate(raw_results, start=1)
            ]
            return SearchProviderResponse(
                query=query,
                provider=self.name,
                results=results,
                success=bool(results),
                error=None if results else "duckduckgo_html returned no results",
                metadata={
                    "elapsed_ms": _elapsed_ms(started),
                    "result_count": len(results),
                },
            )
        except Exception as exc:
            return SearchProviderResponse(
                query=query,
                provider=self.name,
                success=False,
                error=str(exc),
                metadata={
                    "elapsed_ms": _elapsed_ms(started),
                    "error_type": exc.__class__.__name__,
                },
            )


class _APIKeySearchProvider(BaseSearchProvider):
    provider_label = "api_key_provider"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key

    def search(self, query: str, max_results: int = 5) -> SearchProviderResponse:
        started = time.perf_counter()
        if not self.api_key:
            error = f"{self.name} API key is not configured"
            error_type = "MissingAPIKey"
        else:
            error = f"{self.name} provider interface is a Phase 16 skeleton"
            error_type = "NotImplemented"
        return SearchProviderResponse(
            query=query,
            provider=self.name,
            success=False,
            error=error,
            metadata={
                "elapsed_ms": _elapsed_ms(started),
                "error_type": error_type,
                "configured": bool(self.api_key),
                "max_results": max_results,
            },
        )


class BraveSearchProvider(_APIKeySearchProvider):
    name = "brave"


class SerpAPIProvider(_APIKeySearchProvider):
    name = "serpapi"


class TavilyProvider(_APIKeySearchProvider):
    name = "tavily"


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
