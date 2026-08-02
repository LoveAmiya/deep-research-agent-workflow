import html
import re
import urllib.error

from core.config import SearchConfig
from core.safe_http import read_public_url
from core.schema import PageContent


class BaseFetchTool:
    provider = "base"

    def fetch(self, url: str) -> PageContent:
        raise NotImplementedError("Fetch tools must implement fetch().")


class MockFetchTool(BaseFetchTool):
    provider = "mock"

    def fetch(self, url: str) -> PageContent:
        title = f"Mock Page for {url}"
        text = (
            f"{title}. This deterministic mock page summarizes the source. "
            "It describes governance readiness, integration cost, security review, "
            "stakeholder trust, and measurable business value as important research factors."
        )
        return PageContent(
            url=url,
            title=title,
            text=text,
            status_code=200,
            fetched=True,
            error=None,
        )


class SimpleFetchTool(BaseFetchTool):
    provider = "simple"

    def __init__(self, config: SearchConfig, max_text_length: int = 12000) -> None:
        self.timeout_seconds = config.timeout_seconds
        self.user_agent = config.user_agent
        self.max_text_length = max_text_length
        self.max_response_bytes = config.max_response_bytes

    def fetch(self, url: str) -> PageContent:
        try:
            result = read_public_url(
                url,
                timeout_seconds=self.timeout_seconds,
                user_agent=self.user_agent,
                max_response_bytes=self.max_response_bytes,
            )
            status_code = result.status_code
            content_type = result.content_type
            if not self._is_text_content(content_type):
                return PageContent(
                    url=url,
                    title=None,
                    text="",
                    status_code=status_code,
                    fetched=False,
                    error=f"unsupported content type: {content_type}",
                )
            raw_text = result.body.decode(result.charset or "utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return PageContent(
                url=url,
                title=None,
                text="",
                status_code=None,
                fetched=False,
                error=str(exc),
            )

        title = self._extract_title(raw_text)
        text = self._html_to_text(raw_text)
        if not text:
            return PageContent(
                url=url,
                title=title,
                text="",
                status_code=status_code,
                fetched=False,
                error="empty text after parsing",
            )
        return PageContent(
            url=url,
            title=title,
            text=text[: self.max_text_length],
            status_code=status_code,
            fetched=True,
            error=None,
        )

    @staticmethod
    def _is_text_content(content_type: str) -> bool:
        lowered = content_type.lower()
        return not lowered or "text/html" in lowered or lowered.startswith("text/")

    @staticmethod
    def _extract_title(raw_html: str) -> str | None:
        match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip() or None

    @staticmethod
    def _html_to_text(raw_html: str) -> str:
        without_scripts = re.sub(
            r"<(script|style)[^>]*>.*?</\1>",
            " ",
            raw_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(r"<[^>]+>", " ", without_scripts)
        text = html.unescape(text)
        return re.sub(r"\s+", " ", text).strip()


def create_fetch_tool(config: SearchConfig) -> BaseFetchTool:
    if config.enabled:
        return SimpleFetchTool(config)
    return MockFetchTool()
