import urllib.parse
import unittest

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

    def test_http_web_fetcher_extracts_title_and_text_from_data_html(self) -> None:
        html = """
        <html>
          <head><title>Local Test Page</title></head>
          <body>
            <nav>Navigation noise</nav>
            <article><h1>Report</h1><p>Main content about evidence grounding.</p></article>
          </body>
        </html>
        """
        url = "data:text/html," + urllib.parse.quote(html)

        result = HTTPWebFetcher(timeout_seconds=0.1, max_retries=0).fetch(url)

        self.assertTrue(result.success)
        self.assertEqual(result.title, "Local Test Page")
        self.assertIn("Report Main content about evidence grounding.", result.text)
        self.assertNotIn("Navigation noise", result.text)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.metadata["attempts"], 1)
        self.assertEqual(result.metadata["extraction_method"], "article")

    def test_non_text_content_type_does_not_raise(self) -> None:
        url = "data:application/octet-stream,abcdef"

        result = HTTPWebFetcher(timeout_seconds=0.1, max_retries=0).fetch(url)

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["error_type"], "UnsupportedContentType")
        self.assertTrue(result.metadata["unsupported_content_type"])

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
