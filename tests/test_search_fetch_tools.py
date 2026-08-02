import os
import unittest
from unittest.mock import patch

from agents.base_agent import AgentContext
from agents.planner_agent import PlannerAgent
from agents.reader_agent import ReaderAgent
from agents.searcher_agent import SearcherAgent
from core.config import SearchConfig, load_search_config_from_env
from core.schema import PageContent, ResearchQuestion, SearchResult
from orchestrator.research_pipeline import run_research_pipeline
from tools.fetch_tool import MockFetchTool, SimpleFetchTool, create_fetch_tool
from tools.search_tool import BaseSearchTool, MockSearchTool, SearchToolError, create_search_tool


class FailingSearchTool(BaseSearchTool):
    provider = "failing"

    def search(self, query: str, max_results: int = 5):
        raise SearchToolError("forced search failure")


class FailingFetchTool:
    provider = "failing"

    def fetch(self, url: str) -> PageContent:
        return PageContent(
            url=url,
            title=None,
            text="",
            status_code=None,
            fetched=False,
            error="forced fetch failure",
        )


class TestSearchFetchTools(unittest.TestCase):
    def test_mock_search_tool_returns_results(self) -> None:
        tool = MockSearchTool()

        results = tool.search("enterprise LLM adoption", max_results=2)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.source == "mock" for result in results))

    def test_mock_fetch_tool_returns_page_content(self) -> None:
        page = MockFetchTool().fetch("mock://source/1")

        self.assertIsInstance(page, PageContent)
        self.assertTrue(page.fetched)
        self.assertIn("Mock Page", page.title)

    def test_simple_fetch_tool_invalid_url_does_not_crash(self) -> None:
        config = SearchConfig(enabled=True, timeout_seconds=0.1)
        page = SimpleFetchTool(config).fetch("http://127.0.0.1:1/unavailable")

        self.assertFalse(page.fetched)
        self.assertIn("not allowed", page.error)

    def test_simple_fetch_tool_rejects_non_http_urls(self) -> None:
        config = SearchConfig(enabled=True, timeout_seconds=0.1)

        for url in ("data:text/plain,secret", "file:///etc/passwd"):
            with self.subTest(url=url):
                page = SimpleFetchTool(config).fetch(url)
                self.assertFalse(page.fetched)
                self.assertIn("not allowed", page.error)

    def test_create_search_tool_default_returns_mock(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = load_search_config_from_env()

        self.assertFalse(config.enabled)
        self.assertIsInstance(create_search_tool(config), MockSearchTool)

    def test_create_fetch_tool_default_returns_mock(self) -> None:
        config = SearchConfig(enabled=False)

        self.assertIsInstance(create_fetch_tool(config), MockFetchTool)

    def test_load_search_config_from_env_defaults_disabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = load_search_config_from_env()

        self.assertFalse(config.enabled)
        self.assertEqual(config.provider, "mock")
        self.assertEqual(config.max_results, 5)
        self.assertEqual(config.provider_order, ["mock"])

    def test_provider_order_does_not_enable_real_search_by_itself(self) -> None:
        with patch.dict(
            os.environ,
            {"DEEP_RESEARCH_SEARCH_PROVIDER_ORDER": "duckduckgo_html,mock"},
            clear=True,
        ):
            config = load_search_config_from_env()

        self.assertFalse(config.enabled)
        self.assertEqual(config.provider_order, ["mock"])

    def test_searcher_uses_mock_search_tool(self) -> None:
        plan = self._plan()
        result = SearcherAgent().run(
            AgentContext(
                task_id="search_task",
                inputs={"plan": plan, "search_tool": MockSearchTool(), "max_results": 2},
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(len(result.output), 2)
        self.assertEqual(result.metadata["search_provider"], "mock")
        self.assertFalse(result.metadata["used_real_search"])

    def test_searcher_falls_back_when_search_fails(self) -> None:
        plan = self._plan()
        result = SearcherAgent().run(
            AgentContext(
                task_id="search_task",
                inputs={"plan": plan, "search_tool": FailingSearchTool()},
            )
        )

        self.assertTrue(result.success)
        self.assertGreater(len(result.output), 0)
        self.assertTrue(result.metadata["fallback_used"])
        self.assertIn("forced search failure", result.metadata["search_error"])
        self.assertTrue(all(item.source == "mock" for item in result.output))

    def test_reader_uses_mock_fetch_tool(self) -> None:
        search_results = [
            SearchResult(title="T", url="mock://source/1", snippet="Snippet evidence", source="mock")
        ]

        result = ReaderAgent().run(
            AgentContext(
                task_id="reader_task",
                inputs={"search_results": search_results, "fetch_tool": MockFetchTool()},
            )
        )

        self.assertTrue(result.success)
        self.assertGreater(len(result.output), 0)
        self.assertTrue(result.metadata["used_fetch"])
        self.assertEqual(result.metadata["fetch_success_count"], 1)

    def test_reader_fetch_failure_falls_back_to_snippet(self) -> None:
        search_results = [
            SearchResult(title="T", url="https://example.invalid", snippet="Snippet evidence", source="web")
        ]

        result = ReaderAgent().run(
            AgentContext(
                task_id="reader_task",
                inputs={"search_results": search_results, "fetch_tool": FailingFetchTool()},
            )
        )

        self.assertTrue(result.success)
        self.assertTrue(result.metadata["fallback_used"])
        self.assertEqual(result.output[0].evidence, "Snippet evidence")

    def test_pipeline_runs_with_mock_search_and_fetch(self) -> None:
        result = run_research_pipeline(
            "What affects enterprise open-source LLM adoption?",
            search_tool=MockSearchTool(),
            fetch_tool=MockFetchTool(),
        )

        self.assertTrue(result["success"])
        self.assertIn("## References", result["report"].markdown)
        self.assertGreaterEqual(len(result["findings"]), 3)

    @staticmethod
    def _plan():
        question = ResearchQuestion(question="What affects enterprise open-source LLM adoption?")
        return PlannerAgent().run(
            AgentContext(task_id="planner_task", inputs={"question": question})
        ).output


if __name__ == "__main__":
    unittest.main()
