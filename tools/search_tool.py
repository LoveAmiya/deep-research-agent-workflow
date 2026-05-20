import html
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import List

from core.config import SearchConfig
from core.schema import SearchResult


class SearchToolError(Exception):
    """Raised when a search tool cannot produce usable results."""


class BaseSearchTool:
    provider = "base"

    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        raise NotImplementedError("Search tools must implement search().")


class MockSearchTool(BaseSearchTool):
    provider = "mock"

    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        normalized_query = query.strip() or "research question"
        result_count = max(1, max_results)
        quoted_query = urllib.parse.quote(normalized_query.replace(" ", "-"))
        results = []
        for index in range(1, result_count + 1):
            results.append(
                SearchResult(
                    title=f"Mock Search Result {index} for {normalized_query}",
                    url=f"mock://search/{quoted_query}/{index}",
                    snippet=(
                        f"Mock search evidence for '{normalized_query}' highlights factor {index}: "
                        "adoption depends on governance, integration effort, costs, and measurable value."
                    ),
                    source="mock",
                )
            )
        return results


class DuckDuckGoHTMLSearchTool(BaseSearchTool):
    provider = "duckduckgo_html"

    def __init__(self, config: SearchConfig) -> None:
        self.timeout_seconds = config.timeout_seconds
        self.user_agent = config.user_agent

    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        encoded_query = urllib.parse.urlencode({"q": query})
        url = f"https://duckduckgo.com/html/?{encoded_query}"
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_html = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SearchToolError(f"web search request failed: {exc}") from exc

        results = self._parse_results(raw_html, max_results=max_results)
        if not results:
            raise SearchToolError("web search returned no parseable results")
        return results

    def _parse_results(self, raw_html: str, max_results: int) -> List[SearchResult]:
        results: List[SearchResult] = []
        anchor_pattern = re.compile(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in anchor_pattern.finditer(raw_html):
            href = self._normalize_url(match.group(1))
            title = self._clean_html(match.group(2))
            snippet_area = raw_html[match.end() : match.end() + 1800]
            snippet = self._extract_snippet(snippet_area)
            if href and title:
                results.append(
                    SearchResult(
                        title=title,
                        url=href,
                        snippet=snippet or f"Search result for {title}.",
                        source=self.provider,
                    )
                )
            if len(results) >= max_results:
                break
        return results

    @staticmethod
    def _normalize_url(href: str) -> str:
        decoded_href = html.unescape(href)
        parsed = urllib.parse.urlparse(decoded_href)
        query_params = urllib.parse.parse_qs(parsed.query)
        if "uddg" in query_params and query_params["uddg"]:
            return urllib.parse.unquote(query_params["uddg"][0])
        if decoded_href.startswith("//"):
            return f"https:{decoded_href}"
        if decoded_href.startswith("/"):
            return urllib.parse.urljoin("https://duckduckgo.com", decoded_href)
        return decoded_href

    @classmethod
    def _extract_snippet(cls, snippet_area: str) -> str:
        snippet_match = re.search(
            r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
            snippet_area,
            re.IGNORECASE | re.DOTALL,
        ) or re.search(
            r'<div[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</div>',
            snippet_area,
            re.IGNORECASE | re.DOTALL,
        )
        if not snippet_match:
            return ""
        return cls._clean_html(snippet_match.group(1))

    @staticmethod
    def _clean_html(value: str) -> str:
        text = re.sub(r"<[^>]+>", " ", value)
        text = html.unescape(text)
        return re.sub(r"\s+", " ", text).strip()


def create_search_tool(config: SearchConfig) -> BaseSearchTool:
    if not config.enabled:
        return MockSearchTool()
    if config.provider in {"duckduckgo_html", "simple_web"}:
        return DuckDuckGoHTMLSearchTool(config)
    return MockSearchTool()
