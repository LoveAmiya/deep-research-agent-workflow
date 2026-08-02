import unittest
from unittest.mock import patch

from search.fetchers import HTTPWebFetcher, MockWebFetcher, WebFetchResult


class TestWebFetchers(unittest.TestCase):
    def test_mock_web_fetcher_returns_stable_content(self) -> None:
        fetcher = MockWebFetcher()

        first = fetcher.fetch("mock://source/1")
        second = fetcher.fetch("mock://source/1")

        self.assertIsInstance(first, WebFetchResult)
        self.assertTrue(first.success)
        self.assertEqual(first.title, second.title)
        self.assertEqual(first.text, second.text)
        self.assertEqual(first.metadata["attempts"], 1)

    def test_http_web_fetcher_extracts_title_and_text_from_html_bytes(self) -> None:
        html = """
        <html>
          <head><title>Local Test Page</title></head>
          <body>
            <nav>Navigation noise</nav>
            <article><h1>Report</h1><p>Main content about evidence grounding.</p></article>
          </body>
        </html>
        """
        fetcher = HTTPWebFetcher(timeout_seconds=0.1, max_retries=0)
        result = fetcher._build_result(
            url="https://example.com/report",
            raw_bytes=html.encode("utf-8"),
            content_type="text/html; charset=utf-8",
            status_code=200,
            final_url="https://example.com/report",
            max_chars=8000,
            started=0.0,
            attempts=1,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.title, "Local Test Page")
        self.assertIn("Report Main content about evidence grounding.", result.text)
        self.assertNotIn("Navigation noise", result.text)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.metadata["attempts"], 1)
        self.assertEqual(result.metadata["extraction_method"], "article")

    def test_non_text_content_type_does_not_raise(self) -> None:
        fetcher = HTTPWebFetcher(timeout_seconds=0.1, max_retries=0)
        result = fetcher._build_result(
            url="https://example.com/file",
            raw_bytes=b"abcdef",
            content_type="application/octet-stream",
            status_code=200,
            final_url="https://example.com/file",
            max_chars=8000,
            started=0.0,
            attempts=1,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["error_type"], "UnsupportedContentType")
        self.assertTrue(result.metadata["unsupported_content_type"])

    def test_http_web_fetcher_rejects_non_http_and_loopback_urls(self) -> None:
        fetcher = HTTPWebFetcher(timeout_seconds=0.1, max_retries=0)

        for url in ("data:text/plain,secret", "file:///etc/passwd", "http://127.0.0.1/private"):
            with self.subTest(url=url):
                result = fetcher.fetch(url)
                self.assertFalse(result.success)
                self.assertEqual(result.metadata["error_type"], "UnsafeURL")

    def test_http_web_fetcher_rejects_private_redirect_target(self) -> None:
        class RedirectedResponse:
            headers = {"Content-Type": "text/plain"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def getcode(self):
                return 200

            def geturl(self):
                return "http://127.0.0.1/private"

            def read(self, _size):
                return b"private data"

        public_dns = [(2, 1, 6, "", ("93.184.216.34", 443))]
        with (
            patch("socket.getaddrinfo", return_value=public_dns),
            patch("core.safe_http._OPENER.open", return_value=RedirectedResponse()),
        ):
            result = HTTPWebFetcher(timeout_seconds=0.1, max_retries=0).fetch(
                "https://example.com/start"
            )

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["error_type"], "UnsafeURL")

    def test_http_web_fetcher_stops_at_response_byte_limit(self) -> None:
        class OversizedResponse:
            headers = {"Content-Type": "text/plain"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def getcode(self):
                return 200

            def geturl(self):
                return "https://example.com/large"

            def read(self, size):
                return b"x" * size

        public_dns = [(2, 1, 6, "", ("93.184.216.34", 443))]
        with (
            patch("socket.getaddrinfo", return_value=public_dns),
            patch("core.safe_http._OPENER.open", return_value=OversizedResponse()),
        ):
            result = HTTPWebFetcher(
                timeout_seconds=0.1,
                max_retries=0,
                max_response_bytes=32,
            ).fetch("https://example.com/large")

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["error_type"], "ResponseTooLarge")

    def test_fetch_failure_returns_failed_result(self) -> None:
        result = HTTPWebFetcher(timeout_seconds=0.1, max_retries=0).fetch("not-a-valid-url")

        self.assertFalse(result.success)
        self.assertTrue(result.error)
        self.assertEqual(result.metadata["attempts"], 1)
        self.assertTrue(result.metadata["error_type"])

    def test_metadata_contains_trace_fields(self) -> None:
        result = HTTPWebFetcher(timeout_seconds=0.1, max_retries=0).fetch("not-a-valid-url")

        for key in ["elapsed_ms", "attempts", "error_type", "truncated", "final_length"]:
            self.assertIn(key, result.metadata)


if __name__ == "__main__":
    unittest.main()
