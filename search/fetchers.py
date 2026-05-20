import base64
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from core.config import DEFAULT_USER_AGENT, SearchConfig
from search.content_extraction import clean_text, extract_main_text, extract_title, truncate_text


@dataclass
class WebFetchResult:
    url: str
    title: str
    text: str
    raw_content: Optional[str]
    content_type: Optional[str]
    status_code: Optional[int]
    success: bool
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class BaseWebFetcher:
    name = "base"

    def fetch(self, url: str, max_chars: int = 8000) -> WebFetchResult:
        raise NotImplementedError("Web fetchers must implement fetch().")


class MockWebFetcher(BaseWebFetcher):
    name = "mock"

    def fetch(self, url: str, max_chars: int = 8000) -> WebFetchResult:
        started = time.perf_counter()
        title = f"Mock Web Page for {url}"
        text = (
            f"{title}. This deterministic mock web fetch result contains readable main text. "
            "It discusses governance readiness, integration cost, security review, stakeholder trust, "
            "and measurable business value as important research factors."
        )
        text, truncated = truncate_text(text, max_chars)
        return WebFetchResult(
            url=url,
            title=title,
            text=text,
            raw_content=text,
            content_type="text/plain; charset=utf-8",
            status_code=200,
            success=True,
            error=None,
            metadata={
                "elapsed_ms": _elapsed_ms(started),
                "attempts": 1,
                "final_url": url,
                "content_type": "text/plain; charset=utf-8",
                "status_code": 200,
                "error_type": None,
                "truncated": truncated,
                "original_length": len(text),
                "final_length": len(text),
                "mock": True,
            },
        )


class HTTPWebFetcher(BaseWebFetcher):
    name = "http"

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        user_agent: str = DEFAULT_USER_AGENT,
        max_retries: int = 2,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.max_retries = max(0, max_retries)

    def fetch(self, url: str, max_chars: int = 8000) -> WebFetchResult:
        if url.startswith("mock://"):
            result = MockWebFetcher().fetch(url, max_chars=max_chars)
            result.metadata["fetched_by"] = self.name
            result.metadata["mock_url"] = True
            return result

        started = time.perf_counter()
        attempts = 0
        last_error: Optional[BaseException] = None
        for attempt in range(1, self.max_retries + 2):
            attempts = attempt
            try:
                raw_bytes, content_type, status_code, final_url = self._read_url(url)
                return self._build_result(
                    url=url,
                    raw_bytes=raw_bytes,
                    content_type=content_type,
                    status_code=status_code,
                    final_url=final_url,
                    max_chars=max_chars,
                    started=started,
                    attempts=attempts,
                )
            except Exception as exc:
                last_error = exc

        return WebFetchResult(
            url=url,
            title="",
            text="",
            raw_content=None,
            content_type=None,
            status_code=None,
            success=False,
            error=str(last_error) if last_error else "fetch failed",
            metadata={
                "elapsed_ms": _elapsed_ms(started),
                "attempts": attempts,
                "final_url": None,
                "content_type": None,
                "status_code": None,
                "error_type": last_error.__class__.__name__ if last_error else "FetchError",
                "truncated": False,
                "original_length": 0,
                "final_length": 0,
            },
        )

    def _read_url(self, url: str) -> tuple[bytes, str, Optional[int], str]:
        if url.startswith("data:"):
            return self._read_data_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            status_code = response.getcode()
            final_url = response.geturl()
            return response.read(), content_type, status_code, final_url

    @staticmethod
    def _read_data_url(url: str) -> tuple[bytes, str, Optional[int], str]:
        header, _, data = url.partition(",")
        if not data:
            raise ValueError("malformed data URL")
        content_type = header.removeprefix("data:") or "text/plain"
        is_base64 = content_type.endswith(";base64")
        if is_base64:
            content_type = content_type[: -len(";base64")]
            raw_bytes = base64.b64decode(data)
        else:
            raw_bytes = urllib.parse.unquote_to_bytes(data)
        return raw_bytes, content_type, 200, url

    def _build_result(
        self,
        url: str,
        raw_bytes: bytes,
        content_type: str,
        status_code: Optional[int],
        final_url: str,
        max_chars: int,
        started: float,
        attempts: int,
    ) -> WebFetchResult:
        normalized_content_type = content_type or ""
        if not self._is_supported_text_content(normalized_content_type):
            return WebFetchResult(
                url=url,
                title="",
                text="",
                raw_content=None,
                content_type=normalized_content_type,
                status_code=status_code,
                success=False,
                error=f"unsupported content type: {normalized_content_type}",
                metadata={
                    "elapsed_ms": _elapsed_ms(started),
                    "attempts": attempts,
                    "final_url": final_url,
                    "content_type": normalized_content_type,
                    "status_code": status_code,
                    "error_type": "UnsupportedContentType",
                    "unsupported_content_type": True,
                    "truncated": False,
                    "original_length": len(raw_bytes),
                    "final_length": 0,
                },
            )

        charset = _charset_from_content_type(normalized_content_type) or "utf-8"
        raw_content = raw_bytes.decode(charset, errors="replace")
        if "text/html" in normalized_content_type.lower() or "<html" in raw_content[:500].lower():
            title = extract_title(raw_content)
            text, extraction_metadata = extract_main_text(raw_content, max_chars=max_chars)
        else:
            title = ""
            cleaned = clean_text(raw_content)
            text, truncated = truncate_text(cleaned, max_chars)
            extraction_metadata = {
                "extraction_method": "plain_text",
                "removed_noise_blocks": 0,
                "truncated": truncated,
                "original_length": len(raw_content),
                "final_length": len(text),
            }

        success = bool(text)
        metadata = {
            "elapsed_ms": _elapsed_ms(started),
            "attempts": attempts,
            "final_url": final_url,
            "content_type": normalized_content_type,
            "status_code": status_code,
            "error_type": None if success else "EmptyExtractedText",
            "truncated": extraction_metadata.get("truncated", False),
            "original_length": extraction_metadata.get("original_length", len(raw_content)),
            "final_length": len(text),
        }
        metadata.update(extraction_metadata)
        return WebFetchResult(
            url=url,
            title=title,
            text=text,
            raw_content=raw_content,
            content_type=normalized_content_type,
            status_code=status_code,
            success=success,
            error=None if success else "empty text after extraction",
            metadata=metadata,
        )

    @staticmethod
    def _is_supported_text_content(content_type: str) -> bool:
        lowered = content_type.lower()
        return not lowered or "text/html" in lowered or lowered.startswith("text/")


def create_web_fetcher(config: SearchConfig) -> BaseWebFetcher:
    if config.enabled:
        return HTTPWebFetcher(
            timeout_seconds=config.timeout_seconds,
            user_agent=config.user_agent,
            max_retries=2,
        )
    return MockWebFetcher()


def _charset_from_content_type(content_type: str) -> Optional[str]:
    for part in content_type.split(";"):
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset" and value:
            return value.strip()
    return None


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
