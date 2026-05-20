import unittest

from agents.base_agent import AgentContext
from agents.reader_agent import ReaderAgent
from core.schema import SearchResult
from search.fetchers import MockWebFetcher, WebFetchResult


class FailingWebFetcher:
    name = "failing"

    def fetch(self, url: str, max_chars: int = 8000) -> WebFetchResult:
        return WebFetchResult(
            url=url,
            title="",
            text="",
            raw_content=None,
            content_type=None,
            status_code=None,
            success=False,
            error="forced fetch failure",
            metadata={"error_type": "ForcedFailure"},
        )


class TestReaderAgentWebFetcher(unittest.TestCase):
    def test_reader_uses_web_fetcher_content(self) -> None:
        search_results = [
            SearchResult(
                title="Search Title",
                url="mock://source/1",
                snippet="Snippet fallback evidence",
                source="mock",
            )
        ]

        result = ReaderAgent().run(
            AgentContext(
                task_id="reader_task",
                inputs={"search_results": search_results, "web_fetcher": MockWebFetcher()},
                web_fetcher=MockWebFetcher(),
            )
        )

        self.assertTrue(result.success)
        self.assertIn("deterministic mock web fetch result", result.output[0].evidence)
        self.assertEqual(result.metadata["fetcher_name"], "mock")
        self.assertEqual(result.metadata["successful_fetch_count"], 1)
        self.assertTrue(result.metadata["content_extraction_used"])
        self.assertFalse(result.metadata["fallback_used"])

    def test_reader_falls_back_to_snippet_when_web_fetch_fails(self) -> None:
        search_results = [
            SearchResult(
                title="Search Title",
                url="https://example.invalid",
                snippet="Snippet fallback evidence",
                source="web",
            )
        ]

        result = ReaderAgent().run(
            AgentContext(
                task_id="reader_task",
                inputs={"search_results": search_results, "web_fetcher": FailingWebFetcher()},
                web_fetcher=FailingWebFetcher(),
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output[0].evidence, "Snippet fallback evidence")
        self.assertTrue(result.metadata["fallback_used"])
        self.assertEqual(result.metadata["failed_fetch_count"], 1)
        self.assertEqual(result.metadata["fetcher_name"], "failing")
        self.assertIn("forced fetch failure", result.metadata["fetch_error"])


if __name__ == "__main__":
    unittest.main()
