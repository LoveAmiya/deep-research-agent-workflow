import os
import unittest
from io import BytesIO
from urllib.error import HTTPError
from unittest.mock import patch

from agents.base_agent import AgentContext
from agents.planner_agent import PlannerAgent
from agents.writer_agent import WriterAgent
from core.config import LLMConfig
from core.config import load_llm_config_from_env
from core.llm_client import (
    BaseLLMClient,
    LLMClientError,
    LLMMessage,
    LLMResponse,
    MockLLMClient,
    OpenAICompatibleLLMClient,
    create_llm_client,
)
from core.prompt_loader import load_prompt
from core.schema import ResearchQuestion
from orchestrator.research_pipeline import run_research_pipeline


class FailingLLMClient(BaseLLMClient):
    def generate(self, messages, temperature=0.2):
        raise LLMClientError("forced failure")


class FakeHTTPResponse:
    def __init__(self, body: dict) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        import json

        return json.dumps(self.body).encode("utf-8")


class FakeStreamingHTTPResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def __iter__(self):
        return iter(self.lines)


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

    def test_load_llm_config_reads_responses_wire_api(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEP_RESEARCH_USE_LLM": "1",
                "DEEP_RESEARCH_LLM_WIRE_API": "responses",
                "DEEP_RESEARCH_LLM_REASONING_EFFORT": "xhigh",
                "DEEP_RESEARCH_LLM_DISABLE_RESPONSE_STORAGE": "true",
                "DEEP_RESEARCH_LLM_MAX_OUTPUT_TOKENS": "1800",
            },
            clear=True,
        ):
            config = load_llm_config_from_env()

        self.assertEqual(config.wire_api, "responses")
        self.assertEqual(config.reasoning_effort, "xhigh")
        self.assertTrue(config.disable_response_storage)
        self.assertEqual(config.max_output_tokens, 1800)

    def test_create_llm_client_without_api_key_returns_mock(self) -> None:
        with patch.dict(os.environ, {"DEEP_RESEARCH_USE_LLM": "1"}, clear=True):
            config = load_llm_config_from_env()

        client = create_llm_client(config)

        self.assertIsInstance(client, MockLLMClient)

    def test_responses_wire_api_posts_to_responses_endpoint(self) -> None:
        config = LLMConfig(
            enabled=True,
            model="gpt-5.5",
            api_key="test-key",
            base_url="https://crs.ruinique.com",
            wire_api="responses",
            reasoning_effort="xhigh",
            disable_response_storage=True,
            max_output_tokens=1800,
        )
        captured = {}

        def fake_urlopen(request, timeout):
            import json

            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["user_agent"] = request.headers.get("User-agent")
            return FakeHTTPResponse(
                {
                    "model": "gpt-5.5",
                    "output_text": "中文模型响应",
                    "usage": {"input_tokens": 10, "output_tokens": 4},
                }
            )

        client = OpenAICompatibleLLMClient(config)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            response = client.generate(
                [
                    LLMMessage(role="system", content="系统指令"),
                    LLMMessage(role="user", content="你好"),
                ]
            )

        self.assertEqual(captured["url"], "https://crs.ruinique.com/responses")
        self.assertEqual(captured["body"]["model"], "gpt-5.5")
        self.assertEqual(captured["body"]["instructions"], "系统指令")
        self.assertEqual(captured["body"]["input"], "USER:\n你好")
        self.assertEqual(captured["body"]["reasoning"]["effort"], "xhigh")
        self.assertFalse(captured["body"]["store"])
        self.assertEqual(captured["body"]["max_output_tokens"], 1800)
        self.assertEqual(captured["user_agent"], "OpenAI/Python 1.0.0")
        self.assertEqual(response.content, "中文模型响应")

    def test_chat_completions_streams_content_with_existing_config(self) -> None:
        config = LLMConfig(
            enabled=True,
            model="gpt-test",
            api_key="test-key",
            base_url="https://example.test/v1",
        )
        captured = {}
        lines = [
            b'data: {"choices":[{"delta":{"content":"\u4f60\u597d"}}]}\n',
            b"\n",
            b'data: {"choices":[{"delta":{"content":"\u4e16\u754c"}}]}\n',
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]

        def fake_urlopen(request, timeout):
            import json

            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["accept"] = request.headers.get("Accept")
            return FakeStreamingHTTPResponse(lines)

        client = OpenAICompatibleLLMClient(config)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            chunks = list(client.generate_stream([LLMMessage(role="user", content="hello")]))

        self.assertEqual(chunks, ["你好", "世界"])
        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertTrue(captured["body"]["stream"])
        self.assertEqual(captured["body"]["model"], "gpt-test")
        self.assertEqual(captured["accept"], "text/event-stream")

    def test_responses_api_streams_output_text_deltas(self) -> None:
        config = LLMConfig(
            enabled=True,
            model="gpt-test",
            api_key="test-key",
            base_url="https://example.test/v1",
            wire_api="responses",
        )
        lines = [
            b'data: {"type":"response.output_text.delta","delta":"\u4e2d\u6587"}\n',
            b"\n",
        ]

        client = OpenAICompatibleLLMClient(config)
        with patch("urllib.request.urlopen", return_value=FakeStreamingHTTPResponse(lines)):
            chunks = list(client.generate_stream([LLMMessage(role="user", content="hello")]))

        self.assertEqual(chunks, ["中文"])

    def test_http_error_message_includes_sanitized_response_body(self) -> None:
        config = LLMConfig(
            enabled=True,
            model="gpt-5.5",
            api_key="sk-test-secret-key",
            base_url="https://crs.ruinique.com",
            wire_api="responses",
        )
        body = b'{"error":{"message":"bad key sk-test-secret-key","type":"invalid_request_error"}}'

        def fake_urlopen(request, timeout):
            raise HTTPError(
                url=request.full_url,
                code=400,
                msg="Bad Request",
                hdrs={},
                fp=BytesIO(body),
            )

        client = OpenAICompatibleLLMClient(config)
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(LLMClientError) as error:
                client.generate([LLMMessage(role="user", content="你好")])

        message = str(error.exception)
        self.assertIn("HTTP 400", message)
        self.assertIn("invalid_request_error", message)
        self.assertIn("[redacted-api-key]", message)
        self.assertNotIn("sk-test-secret-key", message)

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
        self.assertFalse(result.metadata["used_llm"])
        self.assertTrue(result.metadata["fallback_used"])
        self.assertIn("not a JSON object", result.metadata["llm_error"])

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
