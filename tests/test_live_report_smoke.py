import os
import unittest
from unittest.mock import patch

from argparse import Namespace

from evaluation.run_live_report_smoke import (
    RELAY_BASE_URL,
    _copy_openai_env_to_deep_research,
    build_report,
)
from core.llm_client import BaseLLMClient, LLMMessage, LLMResponse, MockLLMClient
from orchestrator.model_workbench import ModelWorkbenchRunner


class TestLiveReportSmokeEnvironment(unittest.TestCase):
    def test_dedicated_deep_research_settings_take_precedence(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_BASE_URL": "https://other-relay.example/v1",
                "OPENAI_MODEL": "openai-model",
                "DEEP_RESEARCH_LLM_API_KEY": "dedicated-key",
                "DEEP_RESEARCH_LLM_BASE_URL": "https://dedicated-relay.example/v1",
                "DEEP_RESEARCH_LLM_MODEL": "dedicated-model",
            },
            clear=True,
        ):
            _copy_openai_env_to_deep_research()
            self.assertEqual(os.environ["DEEP_RESEARCH_LLM_API_KEY"], "dedicated-key")
            self.assertEqual(os.environ["DEEP_RESEARCH_LLM_BASE_URL"], "https://dedicated-relay.example/v1")
            self.assertEqual(os.environ["DEEP_RESEARCH_LLM_MODEL"], "dedicated-model")

    def test_official_machine_url_falls_back_to_the_configured_relay(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_BASE_URL": "https://api.openai.com/v1",
                "OPENAI_MODEL": "gpt-5.5",
            },
            clear=True,
        ):
            _copy_openai_env_to_deep_research()
            self.assertEqual(os.environ["DEEP_RESEARCH_LLM_BASE_URL"], RELAY_BASE_URL)
            self.assertEqual(os.environ["DEEP_RESEARCH_LLM_API_KEY"], "openai-key")
            self.assertEqual(os.environ["DEEP_RESEARCH_LLM_MODEL"], "gpt-5.5")

    def test_openai_reasoning_effort_does_not_override_medium_smoke_default(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_MODEL": "gpt-5.5",
                "OPENAI_REASONING_EFFORT": "xhigh",
            },
            clear=True,
        ):
            _copy_openai_env_to_deep_research()
            self.assertEqual(os.environ["DEEP_RESEARCH_LLM_REASONING_EFFORT"], "medium")

    @patch("evaluation.run_live_report_smoke.build_report_workbench_payload")
    def test_model_workbench_metrics_use_the_current_model_calls_contract(self, build_payload):
        build_payload.return_value = {
            "modelRun": {"mode": "llm", "modelCalls": 9, "fallbackCount": 0},
            "finalReportMarkdown": "x" * 500,
            "reviewRounds": [{"round": 1}, {"round": 2}],
            "citationValidation": {"passed": True, "sources": []},
            "executionTrace": [{}] * 9,
        }
        with patch("evaluation.run_live_report_smoke._copy_openai_env_to_deep_research"):
            report = build_report(Namespace(question="test", model_workbench=True, red_blue_rounds=2))
        self.assertTrue(report["passed"])
        self.assertTrue(report["summary"]["model_backed"])
        self.assertEqual(report["summary"]["llm_call_count"], 9)

    def test_finalizer_restores_finding_citation_markers_without_new_claims(self):
        runner = ModelWorkbenchRunner("test question", MockLLMClient())
        markdown = "# Research Report: test\n\n## References（参考来源）\n"
        findings = [
            {
                "citationId": "C1",
                "sourceTitle": "Evaluation source",
                "sourceUrl": "https://example.com/evaluation",
            }
        ]
        finalized = runner._ensure_citation_markers(markdown, findings)
        self.assertIn("[C1]", finalized)
        self.assertIn("Evaluation source", finalized)
        self.assertTrue(runner._validate_citations(finalized, findings)["passed"])

    def test_non_browser_smoke_uses_complete_responses_instead_of_native_streaming(self):
        class StreamBreakingClient(BaseLLMClient):
            supports_streaming = True

            def __init__(self):
                self.stream_calls = 0
                self.generate_calls = 0

            def generate(self, messages: list[LLMMessage], temperature: float = 0.2) -> LLMResponse:
                self.generate_calls += 1
                return LLMResponse(content='{"ok": true}', model="test-model")

            def generate_stream(self, messages: list[LLMMessage], temperature: float = 0.2):
                self.stream_calls += 1
                raise AssertionError("non-browser smoke should not use native streaming")

        client = StreamBreakingClient()
        runner = ModelWorkbenchRunner("test question", client)
        call = runner._call_model(
            runner._task("writer_task"),
            [LLMMessage(role="user", content="test")],
            fallback_factory=lambda: '{"fallback": true}',
            stream_target="initialDraft",
            stream_field="markdown",
        )
        self.assertEqual(client.generate_calls, 1)
        self.assertEqual(client.stream_calls, 0)
        self.assertFalse(call.fallback_used)
