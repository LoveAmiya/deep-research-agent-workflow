import os
import unittest
from unittest.mock import patch

from agents.base_agent import AgentContext
from agents.planner_agent import PlannerAgent
from agents.writer_agent import WriterAgent
from core.config import load_llm_config_from_env
from core.llm_client import (
    BaseLLMClient,
    LLMClientError,
    LLMMessage,
    LLMResponse,
    MockLLMClient,
    create_llm_client,
)
from core.prompt_loader import load_prompt
from core.schema import ResearchQuestion
from orchestrator.research_pipeline import run_research_pipeline


class FailingLLMClient(BaseLLMClient):
    def generate(self, messages, temperature=0.2):
        raise LLMClientError("forced failure")


class TestLLMClient(unittest.TestCase):
    def test_mock_llm_client_returns_response(self) -> None:
        client = MockLLMClient()

        response = client.generate([LLMMessage(role="user", content="hello")])

        self.assertIsInstance(response, LLMResponse)
        self.assertIn("hello", response.content)
        self.assertEqual(response.model, "mock-llm")

    def test_load_llm_config_from_env_defaults_disabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = load_llm_config_from_env()

        self.assertFalse(config.enabled)
        self.assertEqual(config.provider, "openai_compatible")

    def test_create_llm_client_without_api_key_returns_mock(self) -> None:
        with patch.dict(os.environ, {"DEEP_RESEARCH_USE_LLM": "1"}, clear=True):
            config = load_llm_config_from_env()

        client = create_llm_client(config)

        self.assertIsInstance(client, MockLLMClient)

    def test_prompt_loader_can_load_planner_prompt(self) -> None:
        prompt = load_prompt("planner")

        self.assertIn("PlannerAgent", prompt)

    def test_agent_context_can_carry_llm_client(self) -> None:
        client = MockLLMClient()
        context = AgentContext(task_id="task", llm_client=client)

        self.assertIs(context.llm_client, client)

    def test_planner_with_mock_llm_preserves_output(self) -> None:
        planner = PlannerAgent()
        question = ResearchQuestion(question="How should enterprises adopt open-source LLMs?")

        result = planner.run(
            AgentContext(
                task_id="planner_task",
                inputs={"question": question},
                llm_client=MockLLMClient(),
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(len(result.output.search_queries), 3)
        self.assertTrue(result.metadata["used_llm"])
        self.assertTrue(result.metadata["fallback_used"])

    def test_writer_with_mock_llm_still_generates_report(self) -> None:
        pipeline_result = run_research_pipeline(
            "How should enterprises adopt open-source LLMs?",
            llm_client=MockLLMClient(),
        )

        self.assertTrue(pipeline_result["success"])
        self.assertIn("## References", pipeline_result["report"].markdown)
        self.assertGreaterEqual(len(pipeline_result["report"].citations), 3)

    def test_planner_falls_back_when_llm_fails(self) -> None:
        planner = PlannerAgent()
        question = ResearchQuestion(question="What affects AI governance?")

        result = planner.run(
            AgentContext(
                task_id="planner_task",
                inputs={"question": question},
                llm_client=FailingLLMClient(),
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(len(result.output.sub_questions), 3)
        self.assertTrue(result.metadata["fallback_used"])
        self.assertIn("forced failure", result.metadata["llm_error"])

    def test_writer_falls_back_when_llm_fails(self) -> None:
        pipeline_result = run_research_pipeline(
            "What affects AI governance?",
            llm_client=FailingLLMClient(),
        )

        report = pipeline_result["report"]

        self.assertTrue(pipeline_result["success"])
        self.assertIn("## Key Findings", report.markdown)
        self.assertIn("## References", report.markdown)

    def test_pipeline_runs_with_mock_llm(self) -> None:
        result = run_research_pipeline(
            "What affects AI governance?",
            llm_client=MockLLMClient(),
        )

        self.assertTrue(result["success"])
        self.assertIn("report", result)
        self.assertIn("blue_revision", result)


if __name__ == "__main__":
    unittest.main()
