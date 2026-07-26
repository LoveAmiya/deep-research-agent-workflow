import http.client
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from http.server import ThreadingHTTPServer

from report_workbench import (
    INDEX_HTML,
    TASK_ORDER,
    ReportWorkbenchHandler,
    build_report_workbench_payload,
)
from agents.base_agent import AgentContext
from agents.writer_agent import WriterAgent
from agents.blue_agent import BlueAgent
from agents.critic_agent import CriticAgent
from core.schema import Finding, RedReviewResult, ResearchPlan, ResearchQuestion, ResearchReport, ReviewIssue
from tools.citation_tool import CitationRegistry


class ScriptedChineseLLMClient:
    def __init__(self) -> None:
        self.calls = []

    def generate(self, messages, temperature=0.2):
        self.calls.append(messages[-1].content)
        responses = [
            '{"objective":"研究 Agent 工具评估方法。","subQuestions":["如何定义质量？","如何评估可追踪性？"],"searchQueries":["agentic research tools evaluation","RAG evaluation"],"expectedSections":["摘要","Key Findings（关键发现）","行动建议","References（参考来源）"]}',
            '{"results":[{"title":"Agent 评估资料","url":"https://example.com/agent-eval","snippet":"评估需要覆盖任务成功率、证据质量和过程可追踪性。","whyUseful":"提供评估维度。"}]}',
            '{"findings":[{"claim":"Agentic research tools 需要同时评估结果质量和过程可追踪性。","evidence":"评估需要覆盖任务成功率、证据质量和过程可追踪性。","sourceTitle":"Agent 评估资料","sourceUrl":"https://example.com/agent-eval","confidence":0.85}]}',
            '{"markdown":"# Research Report: 如何评估 Agentic Research Tools\\n\\n## 摘要\\n\\n这是一份中文初稿。\\n\\n## Key Findings（关键发现）\\n\\n- 需要同时评估结果质量和过程可追踪性。[C1]\\n\\n## 深入分析\\n\\nAgent（智能体）不仅要回答正确，还要展示计划、证据和修改过程。\\n\\n## 行动建议\\n\\n- 建立人工样例集。\\n\\n## References（参考来源）\\n\\n- [C1] Agent 评估资料 https://example.com/agent-eval"}',
            '{"passed":false,"summary":"初稿可用，但建议补充评估指标。","checks":{"has_title":true,"has_references":true},"issues":["行动建议还可以更具体。"]}',
            '{"passed":false,"summary":"发现 1 个可修订问题。","reviewText":"问题：行动建议缺少可执行指标。\\n依据：行动建议仅要求建立样例集。\\n建议：在行动建议章节加入成功率、引用准确率和过程覆盖率。","issues":[{"issueId":"R1-1","severity":"medium","message":"行动建议缺少可执行指标。","evidence":"只说建立样例集。","suggestion":"补充 success rate、citation accuracy 和 trace coverage。"}]}',
            '{"revisedReportMarkdown":"# Research Report: 如何评估 Agentic Research Tools\\n\\n## 摘要\\n\\n这是一份中文最终版报告，覆盖结果质量、证据质量和过程可追踪性。\\n\\n## Key Findings（关键发现）\\n\\n- 需要同时评估结果质量和过程可追踪性。[C1]\\n\\n## 深入分析\\n\\nAgent（智能体）评估不能只看最终答案，还要看 Planner、Reader、Writer、Red/Blue 修改链路是否可解释。\\n\\n## 行动建议\\n\\n- 建立人工样例集。\\n- 记录 success rate（任务成功率）、citation accuracy（引用准确率）和 trace coverage（过程覆盖率）。\\n\\n## References（参考来源）\\n\\n- [C1] Agent 评估资料 https://example.com/agent-eval","fixedIssueIds":["R1-1"],"remainingIssueIds":[],"revisionNotes":["补充了可执行指标。"],"revisionText":"已在行动建议章节新增 success rate、citation accuracy 与 trace coverage 三项可执行指标，直接回应 R1-1。"}',
            '{"passed":true,"summary":"Second review passed.","reviewText":"本轮未发现新的阻断问题；引用标记与报告结构保持完整。","issues":[]}',
            '{"revisedReportMarkdown":"# Research Report: Agentic Research Tools\\n\\n## Key Findings\\n\\n- Evaluate results and traceability. [C1]\\n\\n## References\\n\\n- [C1] Agent evaluation source https://example.com/agent-eval\\n\\n\\u4e2d\\u6587\\u6700\\u7ec8\\u7248\\u62a5\\u544a","fixedIssueIds":[],"remainingIssueIds":[],"revisionNotes":["Second independent review completed."],"revisionText":"第二轮保持结论与引用不变，确认没有新的修订项。"}',
        ]
        return SimpleNamespace(
            content=responses[len(self.calls) - 1],
            model="scripted-chinese-llm",
            usage={"prompt_messages": len(messages), "temperature": temperature},
        )


class StreamingScriptedChineseLLMClient(ScriptedChineseLLMClient):
    supports_streaming = True

    def generate_stream(self, messages, temperature=0.2):
        response = self.generate(messages, temperature=temperature)
        for index in range(0, len(response.content), 17):
            yield response.content[index : index + 17]


class TestReportWorkbench(unittest.TestCase):
    def test_public_workbench_never_presents_mock_sources_as_verified_references(self) -> None:
        payload = build_report_workbench_payload("What affects enterprise LLM adoption?")

        self.assertNotIn("mock://", payload["finalReportMarkdown"])
        self.assertFalse(payload["citationValidation"]["passed"])
        self.assertTrue(any("模拟" in reason for reason in payload["degradationReasons"]))

    def test_fallback_writer_builds_a_complete_research_structure(self) -> None:
        registry = CitationRegistry()
        findings = []
        dimensions = ["成本", "治理", "集成", "模型能力", "人才", "安全"]
        for index, dimension in enumerate(dimensions, start=1):
            evidence = registry.add_evidence(
                f"https://example.com/{index}",
                f"{dimension}会影响企业采用决策。",
                source_title=f"来源 {index}",
            )
            citation = registry.add_citation(
                f"https://example.com/{index}",
                evidence_id=evidence.evidence_id,
                source_title=f"来源 {index}",
            )
            findings.append(Finding(
                claim=f"{dimension}是企业评估开源大语言模型时需要单独衡量的因素。",
                evidence=evidence.text,
                source_url=evidence.source_url,
                source_title=evidence.source_title,
                evidence_id=evidence.evidence_id,
                citation_id=citation.citation_id,
            ))

        result = WriterAgent().run(AgentContext(
            task_id="writer_task",
            inputs={
                "question": ResearchQuestion(question="企业为什么采用开源大语言模型？"),
                "plan": ResearchPlan(question="企业为什么采用开源大语言模型？"),
                "findings": findings,
                "citation_registry": registry,
            },
        ))

        markdown = result.output.markdown
        for heading in ["Background", "Key Findings", "Analysis and Discussion", "Limitations", "Recommendations", "Conclusion", "References"]:
            self.assertIn(f"## {heading}", markdown)
        self.assertGreaterEqual(markdown.count("- "), 6)
        self.assertNotIn("mock evidence", markdown.lower())

    def test_handoffs_explain_artifact_action_and_content_in_chinese(self) -> None:
        payload = build_report_workbench_payload("What affects enterprise LLM adoption?")

        first = payload["handoffs"][0]
        self.assertEqual(first["actionLabel"], "接收并用于下一步")
        self.assertIn("研究任务书", first["artifactLabel"])
        self.assertTrue(first["contentSummary"])
        self.assertNotIn("research_brief", first["displayText"])

    def test_browser_defers_final_payload_until_stream_queues_are_drained(self) -> None:
        self.assertIn("enqueueStreamDelta(data.target", INDEX_HTML)
        self.assertIn("pendingCompletedPayload", INDEX_HTML)
        self.assertIn("flushCompletedPayloadWhenReady", INDEX_HTML)
        self.assertNotIn('if (event === "run_completed") {\n        renderPayload(data.payload);', INDEX_HTML)

    def test_default_analysis_has_six_distinct_points_and_a_real_discussion(self) -> None:
        payload = build_report_workbench_payload("影响企业采用开源大语言模型的主要因素有哪些？")
        markdown = payload["finalReportMarkdown"]
        key_body = markdown.split("## Key Findings", 1)[1].split("\n## ", 1)[0]
        discussion = markdown.split("## Analysis and Discussion", 1)[1].split("\n## ", 1)[0]
        conclusion = markdown.split("## Conclusion", 1)[1].split("\n## ", 1)[0]

        self.assertGreaterEqual(len([line for line in key_body.splitlines() if line.startswith("- ")]), 5)
        self.assertGreaterEqual(len(set(line for line in key_body.splitlines() if line.startswith("- "))), 5)
        self.assertGreater(len(discussion.strip()), 240)
        self.assertGreater(len(conclusion.strip()), 120)

    def test_review_rounds_expose_actual_before_and_after_content(self) -> None:
        payload = build_report_workbench_payload("影响企业采用开源大语言模型的主要因素有哪些？")
        changes = [
            change
            for review in payload["reviewRounds"]
            for change in review["blueRevision"]["changes"]
        ]

        self.assertTrue(changes)
        self.assertTrue(any(change.get("before") or change.get("after") for change in changes))
        self.assertTrue(all(change.get("change") for change in changes))

    def test_quality_gate_and_blue_revision_require_full_argument_structure(self) -> None:
        report = ResearchReport(
            title="研究报告",
            question="问题",
            sections=[],
            citations=[],
            markdown="# 研究报告\n\n## Background\n\n背景。\n\n## Key Findings\n\n暂无。\n\n## Conclusion\n\n结论。\n\n## References\n\n暂无。",
        )
        critic = CriticAgent().run(AgentContext(
            task_id="critic_task",
            inputs={"report": report, "findings": []},
        )).output

        self.assertFalse(critic["passed"])
        self.assertTrue(any("Analysis and Discussion" in issue for issue in critic["issues"]))

        red = RedReviewResult(
            passed=False,
            issues=[ReviewIssue("R1", "structure", "high", issue) for issue in critic["issues"]],
            summary="结构不完整",
        )
        blue = BlueAgent().run(AgentContext(
            task_id="blue_task",
            inputs={"report": report, "red_review": red, "findings": []},
        )).output.revised_report.markdown

        self.assertIn("## Analysis and Discussion", blue)
        self.assertIn("## Limitations", blue)
        self.assertIn("## Recommendations", blue)

    def test_user_workbench_does_not_render_raw_agent_or_validation_json(self) -> None:
        self.assertNotIn("JSON.stringify(payload.citationValidation", INDEX_HTML)
        self.assertNotIn("step.outputPreview", INDEX_HTML)
        self.assertNotIn('window.addEventListener("load", runResearch)', INDEX_HTML)
        self.assertIn('enqueueStreamDelta(data.target, "\\n--- 审查流开始 ---\\n")', INDEX_HTML)

    def test_user_workbench_renders_review_round_handoffs(self) -> None:
        self.assertIn('id="reviewRounds"', INDEX_HTML)
        self.assertIn("renderReviewRounds(currentReviewRounds)", INDEX_HTML)
        self.assertIn('event === "review_round_completed"', INDEX_HTML)
        self.assertIn("item.evidence", INDEX_HTML)
        self.assertIn("revision.changes", INDEX_HTML)
        self.assertIn("validation.sources", INDEX_HTML)

    def test_stream_endpoint_closes_after_emitting_final_payload(self) -> None:
        """浏览器读完最终事件后必须能结束读取循环并恢复运行按钮。"""

        def fake_build_report_workbench_payload(question, **kwargs):
            kwargs["event_sink"]("run_completed", {"payload": {"ok": True, "question": question}})
            return {"ok": True}

        server = ThreadingHTTPServer(("127.0.0.1", 0), ReportWorkbenchHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)

        try:
            with patch("report_workbench.build_report_workbench_payload", fake_build_report_workbench_payload):
                connection.request(
                    "POST",
                    "/api/research/stream",
                    body=json.dumps({"question": "测试问题"}),
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Connection"), "close")
        finally:
            connection.close()
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_payload_contains_final_report_and_pipeline_impacts(self) -> None:
        payload = build_report_workbench_payload(
            "What are the main factors that affect open-source LLM adoption in enterprises?"
        )

        self.assertTrue(payload["success"])
        self.assertIn("# Research Report:", payload["finalReportMarkdown"])
        self.assertIn("## Key Findings", payload["finalReportMarkdown"])
        self.assertIn("## References", payload["finalReportMarkdown"])
        self.assertGreater(len(payload["findings"]), 0)

        task_ids = [step["taskId"] for step in payload["stepImpacts"]]
        self.assertEqual(task_ids, [task_id for task_id, _, _ in TASK_ORDER])
        self.assertTrue(all(step["impactOnFinalReport"] for step in payload["stepImpacts"]))
        self.assertTrue(all("metrics" in step for step in payload["stepImpacts"]))

    def test_payload_explains_writer_and_blue_outputs(self) -> None:
        payload = build_report_workbench_payload("How should teams evaluate agentic research tools?")
        steps = {step["taskId"]: step for step in payload["stepImpacts"]}

        self.assertGreater(steps["writer_task"]["metrics"]["Characters"], 0)
        self.assertIn("第一版", steps["writer_task"]["impactOnFinalReport"])
        self.assertIn("最终报告", steps["blue_revision_task"]["impactOnFinalReport"])
        self.assertIn("summary", payload["reportDiffSummary"])
        self.assertIn("passed", payload["citationValidation"])

    def test_payload_uses_llm_first_and_streams_status_events(self) -> None:
        client = ScriptedChineseLLMClient()
        events = []

        payload = build_report_workbench_payload(
            "如何评估 Agentic Research Tools？",
            llm_client=client,
            red_blue_rounds=2,
            event_sink=lambda event_type, data: events.append((event_type, data)),
            model_workbench=True,
        )

        self.assertEqual(len(client.calls), len(TASK_ORDER) + 2)
        self.assertEqual(payload["modelRun"]["fallbackCount"], 0)
        self.assertIn("中文最终版报告", payload["finalReportMarkdown"])
        self.assertTrue(all(step["status"] == "done" for step in payload["stepImpacts"]))
        self.assertTrue(all(step["mode"] == "llm" for step in payload["stepImpacts"]))

        event_types = [event_type for event_type, _ in events]
        self.assertIn("run_started", event_types)
        self.assertIn("agent_started", event_types)
        self.assertIn("review_round_started", event_types)
        self.assertIn("agent_done", event_types)
        self.assertIn("report_delta", event_types)
        stream_starts = [
            (index, data.get("target"))
            for index, (event_type, data) in enumerate(events)
            if event_type == "report_stream_start"
        ]
        initial_stream = next(index for index, target in stream_starts if target == "initialDraft")
        final_stream = next(index for index, target in stream_starts if target == "finalReport")
        writer_done = next(
            index
            for index, (event_type, data) in enumerate(events)
            if event_type == "agent_done" and data["step"]["taskId"] == "writer_task"
        )
        first_review = next(index for index, (event_type, _) in enumerate(events) if event_type == "review_round_started")
        review_streams = [index for index, target in stream_starts if target == "reviewTranscript"]
        final_stream_done = next(
            index
            for index, (event_type, data) in enumerate(events)
            if event_type == "report_stream_done" and data.get("target") == "finalReport"
        )
        self.assertGreater(initial_stream, writer_done)
        self.assertLess(initial_stream, first_review)
        self.assertGreaterEqual(len(review_streams), 4)
        self.assertLess(review_streams[0], event_types.index("report_validated"))
        self.assertLess(event_types.index("report_validated"), final_stream)
        self.assertLess(final_stream_done, event_types.index("report_completed"))
        self.assertLess(event_types.index("report_completed"), event_types.index("run_completed"))
        self.assertEqual(event_types[-1], "run_completed")

        first_round = payload["reviewRounds"][0]
        self.assertTrue(first_round["blueRevision"]["changes"])
        self.assertIn("新增：", first_round["blueRevision"]["changes"][0]["change"])
        self.assertIn("sourceUrl", payload["citationValidation"]["sources"][0])

    def test_native_llm_stream_reaches_readable_workbench_fields_before_task_completion(self) -> None:
        client = StreamingScriptedChineseLLMClient()
        events = []

        build_report_workbench_payload(
            "如何评估 Agentic Research Tools？",
            llm_client=client,
            red_blue_rounds=2,
            event_sink=lambda event_type, data: events.append((event_type, data)),
            model_workbench=True,
        )

        writer_done = next(
            index
            for index, (event_type, data) in enumerate(events)
            if event_type == "agent_done" and data["step"]["taskId"] == "writer_task"
        )
        initial_delta = next(
            index
            for index, (event_type, data) in enumerate(events)
            if event_type == "report_delta" and data.get("target") == "initialDraft"
        )
        review_delta = next(
            data["delta"]
            for event_type, data in events
            if event_type == "report_delta" and data.get("target") == "reviewTranscript"
        )
        streamed_deltas = [
            data["delta"]
            for event_type, data in events
            if event_type == "report_delta" and data.get("target") in {"initialDraft", "reviewTranscript"}
        ]

        self.assertLess(initial_delta, writer_done)
        self.assertIn("Red Review", review_delta)
        self.assertTrue(any("行动建议" in delta for delta in streamed_deltas))
        self.assertFalse(any(delta.lstrip().startswith("{") for delta in streamed_deltas))

    def test_default_workbench_completes_at_least_two_review_rounds(self) -> None:
        events = []

        payload = build_report_workbench_payload(
            "How should teams evaluate agentic research tools?",
            event_sink=lambda event_type, data: events.append((event_type, data)),
        )

        self.assertEqual(len(payload["reviewRounds"]), 2)
        self.assertEqual([item["round"] for item in payload["reviewRounds"]], [1, 2])
        live_rounds = [data["round"] for event_type, data in events if event_type == "review_round_started"]
        self.assertEqual(live_rounds, [1, 2])
        review_streams = [
            data
            for event_type, data in events
            if event_type == "report_stream_start" and data.get("target") == "reviewTranscript"
        ]
        self.assertGreaterEqual(len(review_streams), 4)

    def test_default_workbench_uses_collaborative_dag_and_emits_readable_handoffs(self) -> None:
        events = []

        payload = build_report_workbench_payload(
            "What affects enterprise LLM adoption?",
            event_sink=lambda event_type, data: events.append((event_type, data)),
        )

        event_types = [event_type for event_type, _ in events]
        self.assertEqual(payload["modelRun"]["mode"], "collaborative_dag_deterministic")
        self.assertGreaterEqual(payload["ledgerSummary"]["artifactCount"], len(TASK_ORDER))
        self.assertGreaterEqual(len(payload["handoffs"]), len(TASK_ORDER) - 1)
        self.assertGreaterEqual(len(payload["reviewRounds"]), 2)
        self.assertIn("handoff_updated", event_types)
        self.assertIn("initialDraft", [
            data.get("target") for event_type, data in events if event_type == "report_stream_start"
        ])
        self.assertLess(event_types.index("agent_started"), event_types.index("handoff_updated"))
        self.assertLess(event_types.index("handoff_updated"), event_types.index("report_completed"))
        self.assertEqual(event_types[-1], "run_completed")

    def test_collaboration_workbench_html_renders_handoffs_without_raw_ledger_json(self) -> None:
        self.assertIn('id="handoffs"', INDEX_HTML)
        self.assertIn("renderHandoffs(currentHandoffs)", INDEX_HTML)
        self.assertNotIn("JSON.stringify(payload.ledger", INDEX_HTML)
        self.assertNotIn("executionTrace", INDEX_HTML)

    def test_deterministic_collaboration_is_explicitly_marked_as_degraded(self) -> None:
        payload = build_report_workbench_payload("What affects enterprise LLM adoption?")

        self.assertEqual(payload["modelRun"]["mode"], "collaborative_dag_deterministic")
        self.assertIn("本次运行没有成功消费任何模型输出。", payload["degradationReasons"])
        self.assertTrue(any("模拟/确定性来源" in reason for reason in payload["degradationReasons"]))

    def test_public_payload_exposes_agent_summaries_but_not_raw_output_previews(self) -> None:
        payload = build_report_workbench_payload("How should teams evaluate agentic research tools?")

        self.assertTrue(all("outputPreview" not in step for step in payload["stepImpacts"]))
        self.assertTrue(all("bullets" in step and "highlights" in step for step in payload["stepImpacts"]))


if __name__ == "__main__":
    unittest.main()
