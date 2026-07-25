import json
import unittest
from types import SimpleNamespace

from agents.base_agent import AgentContext
from agents.blue_agent import BlueAgent
from agents.critic_agent import CriticAgent
from agents.planner_agent import PlannerAgent
from agents.red_agent import RedAgent
from agents.writer_agent import WriterAgent
from core.schema import Finding, RedReviewResult, ResearchPlan, ResearchQuestion, ResearchReport
from tools.citation_tool import CitationRegistry
from orchestrator.research_pipeline import run_research_pipeline


class ScriptedAgentLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, messages, temperature=0.2):
        self.calls.append(messages)
        return SimpleNamespace(content=self.responses.pop(0), model="scripted", usage={})


class FailingLLM:
    def generate(self, messages, temperature=0.2):
        raise RuntimeError("model endpoint unavailable")


class TestAgentCollaborationLogic(unittest.TestCase):
    def test_planner_consumes_structured_model_plan(self) -> None:
        client = ScriptedAgentLLM([
            json.dumps({
                "sub_questions": ["Which controls matter?"],
                "search_queries": ["enterprise open source LLM governance"],
                "expected_sections": ["Background", "Findings", "Conclusion"],
            })
        ])

        result = PlannerAgent().run(AgentContext(
            task_id="planner_task",
            inputs={"question": ResearchQuestion(question="What affects adoption?")},
            llm_client=client,
        ))

        self.assertTrue(result.success)
        self.assertEqual(result.output.sub_questions, ["Which controls matter?"])
        self.assertFalse(result.metadata["fallback_used"])
        self.assertTrue(result.metadata["used_llm"])

    def test_critic_and_red_use_model_issues_in_review(self) -> None:
        report = ResearchReport(
            title="Research Report",
            question="Q",
            sections=[{"title": "Key Findings", "content": "- Finding [C1]"}],
            citations=["C1"],
            markdown="# Research Report\n\n## Key Findings\n\n- Finding [C1]\n\n## References\n\n[C1]",
        )
        finding = Finding(claim="Finding", evidence="Evidence", source_url="https://example.com", citation_id="C1")
        critic = CriticAgent().run(AgentContext(
            task_id="critic_task",
            inputs={"report": report, "findings": [finding]},
            llm_client=ScriptedAgentLLM([json.dumps({
                "passed": False,
                "issues": ["The conclusion is missing."],
                "checks": {"scope": "incomplete"},
            })]),
        ))
        red = RedAgent().run(AgentContext(
            task_id="red_task",
            inputs={"report": report, "findings": [finding], "critic_review": critic.output},
            llm_client=ScriptedAgentLLM([json.dumps({
                "passed": False,
                "summary": "需要补充结论。",
                "issues": [{
                    "issue_id": "red-model-1",
                    "category": "completeness",
                    "severity": "high",
                    "message": "Conclusion is missing.",
                    "evidence": "No Conclusion heading",
                    "suggestion": "Add a conclusion grounded in the findings.",
                }],
            })]),
        ))

        self.assertFalse(critic.output["passed"])
        self.assertIn("The conclusion is missing.", critic.output["issues"])
        self.assertFalse(red.output.passed)
        self.assertIn("red-model-1", [issue.issue_id for issue in red.output.issues])
        self.assertFalse(red.metadata["fallback_used"])

    def test_blue_consumes_structured_revision_and_rejects_unknown_citations(self) -> None:
        report = ResearchReport(
            title="Research Report",
            question="Q",
            sections=[
                {"title": "Key Findings", "content": "- Supported finding [C1]"},
                {"title": "References", "content": "[C1]"},
            ],
            citations=["C1"],
            markdown="# Research Report\n\n## Key Findings\n\n- Supported finding [C1]\n\n## References\n\n[C1]",
        )
        finding = Finding(claim="Supported finding", evidence="Evidence", source_url="https://example.com", citation_id="C1")
        review = RedReviewResult(passed=False, issues=[])
        client = ScriptedAgentLLM([json.dumps({
            "revised_markdown": "# Research Report\n\n## Key Findings\n\n- Supported finding [C1]\n- Invented claim [C999]\n\n## References\n\n[C1]",
            "fixed_issue_ids": [],
            "remaining_issue_ids": [],
            "revision_notes": ["整理发现段落。"],
        })])
        registry = CitationRegistry()
        evidence = registry.add_evidence(source_url="https://example.com", text="Evidence")
        registry.add_citation(source_url="https://example.com", evidence_id=evidence.evidence_id, quote="Evidence")

        result = BlueAgent().run(AgentContext(
            task_id="blue_task",
            inputs={"report": report, "red_review": review, "findings": [finding], "citation_registry": registry},
            llm_client=client,
        ))

        self.assertTrue(result.success)
        self.assertNotIn("C999", result.output.revised_report.markdown)
        self.assertIn("C1", result.output.revised_report.markdown)
        self.assertIn("整理发现段落。", result.output.revision_notes)
        self.assertFalse(result.metadata["fallback_used"])

    def test_blue_rebuilds_reference_urls_after_accepting_model_revision(self) -> None:
        report = ResearchReport(
            title="Research Report",
            question="Q",
            sections=[
                {"title": "Background", "content": "Background"},
                {"title": "Key Findings", "content": "- Supported finding [C1]"},
                {"title": "Conclusion", "content": "Conclusion"},
                {"title": "References", "content": "[C1] https://example.com"},
            ],
            citations=["C1"],
            markdown="# Research Report\n\n## Background\n\nBackground\n\n## Key Findings\n\n- Supported finding [C1]\n\n## Conclusion\n\nConclusion\n\n## References\n\n[C1] https://example.com",
        )
        finding = Finding(claim="Supported finding", evidence="Evidence", source_url="https://example.com", citation_id="C1")
        registry = CitationRegistry()
        evidence = registry.add_evidence(source_url="https://example.com", text="Evidence", source_title="Example source")
        registry.add_citation(source_url="https://example.com", evidence_id=evidence.evidence_id, source_title="Example source", quote="Evidence")
        client = ScriptedAgentLLM([json.dumps({
            "revised_markdown": "# Research Report\n\n## Background\n\nBackground\n\n## Key Findings\n\n- Supported finding [C1]\n\n## Conclusion\n\nConclusion\n\n## References\n\n[C1]",
            "fixed_issue_ids": [],
            "remaining_issue_ids": [],
            "revision_notes": ["保留引用。"],
        })])

        result = BlueAgent().run(AgentContext(
            task_id="blue_task",
            inputs={"report": report, "red_review": RedReviewResult(passed=True), "findings": [finding], "citation_registry": registry},
            llm_client=client,
        ))

        self.assertIn("https://example.com", result.output.revised_report.markdown)

    def test_writer_accepts_grounded_model_markdown_and_keeps_sections_consistent(self) -> None:
        question = ResearchQuestion(question="What affects adoption?")
        finding = Finding(
            claim="Governance affects adoption",
            evidence="Governance evidence",
            source_url="https://example.com",
            citation_id="C1",
        )
        client = ScriptedAgentLLM(["""# Research Report: What affects adoption?

Question: What affects adoption?

## Background

Governance context.

## Key Findings

- Governance affects adoption [C1]

## Conclusion

Governance should be assessed.

## References

[C1] https://example.com
"""])
        registry = CitationRegistry()
        evidence = registry.add_evidence(source_url="https://example.com", text="Governance evidence")
        registry.add_citation(source_url="https://example.com", evidence_id=evidence.evidence_id, quote="Governance evidence")

        result = WriterAgent().run(AgentContext(
            task_id="writer_task",
            inputs={"question": question, "plan": ResearchPlan(question=question.question), "findings": [finding], "citation_registry": registry},
            llm_client=client,
        ))

        self.assertFalse(result.metadata["fallback_used"])
        self.assertEqual(result.output.sections[1]["content"], "- Governance affects adoption [C1]")
        self.assertIn("Governance context.", result.output.markdown)

    def test_writer_repairs_missing_citations_with_approved_findings(self) -> None:
        question = ResearchQuestion(question="What affects adoption?")
        finding = Finding(
            claim="Governance affects adoption",
            evidence="Governance evidence",
            source_url="https://example.com",
            citation_id="C1",
        )
        client = ScriptedAgentLLM(["""# Research Report: What affects adoption?

## Background

Governance context.

## Key Findings

- Governance affects adoption.

## Conclusion

Governance should be assessed.
"""])
        registry = CitationRegistry()
        evidence = registry.add_evidence(source_url="https://example.com", text="Governance evidence")
        registry.add_citation(source_url="https://example.com", evidence_id=evidence.evidence_id, quote="Governance evidence")

        result = WriterAgent().run(AgentContext(
            task_id="writer_task",
            inputs={"question": question, "plan": ResearchPlan(question=question.question), "findings": [finding], "citation_registry": registry},
            llm_client=client,
        ))

        self.assertFalse(result.metadata["fallback_used"])
        self.assertIn("Governance affects adoption [C1]", result.output.markdown)
        self.assertIn("https://example.com", result.output.markdown)

    def test_writer_normalizes_chinese_headings_and_full_width_citations(self) -> None:
        question = ResearchQuestion(question="What affects adoption?")
        finding = Finding(claim="Governance affects adoption", evidence="Evidence", source_url="https://example.com", citation_id="C1")
        registry = CitationRegistry()
        evidence = registry.add_evidence(source_url="https://example.com", text="Evidence")
        registry.add_citation(source_url="https://example.com", evidence_id=evidence.evidence_id, quote="Evidence")
        client = ScriptedAgentLLM(["""# 研究报告

## 背景

治理背景。

## 关键发现

- Governance affects adoption【C1】

## 结论

应评估治理。

## 参考来源

[C1] https://example.com
"""])

        result = WriterAgent().run(AgentContext(
            task_id="writer_task",
            inputs={"question": question, "plan": ResearchPlan(question=question.question), "findings": [finding], "citation_registry": registry},
            llm_client=client,
        ))

        self.assertFalse(result.metadata["fallback_used"])
        self.assertIn("## Key Findings", result.output.markdown)
        self.assertIn("[C1]", result.output.markdown)

    def test_writer_extracts_markdown_from_json_envelope_and_mixed_headings(self) -> None:
        question = ResearchQuestion(question="What affects adoption?")
        finding = Finding(claim="Governance affects adoption", evidence="Evidence", source_url="https://example.com", citation_id="C1")
        registry = CitationRegistry()
        evidence = registry.add_evidence(source_url="https://example.com", text="Evidence")
        registry.add_citation(source_url="https://example.com", evidence_id=evidence.evidence_id, quote="Evidence")
        content = """### 背景（Background）

治理背景。

### 关键发现（Key Findings）

- Governance affects adoption [C1]

### 总结（Conclusion）

应评估治理。
"""
        client = ScriptedAgentLLM([json.dumps({"markdown": content})])

        result = WriterAgent().run(AgentContext(
            task_id="writer_task",
            inputs={"question": question, "plan": ResearchPlan(question=question.question), "findings": [finding], "citation_registry": registry},
            llm_client=client,
        ))

        self.assertFalse(result.metadata["fallback_used"])
        self.assertIn("## Background", result.output.markdown)
        self.assertIn("## References", result.output.markdown)

    def test_pipeline_uses_model_artifacts_across_two_review_rounds(self) -> None:
        client = ScriptedAgentLLM([
            json.dumps({
                "sub_questions": ["Which governance controls affect adoption?"],
                "search_queries": ["enterprise LLM governance"],
                "expected_sections": ["Background", "Key Findings", "Conclusion"],
            }),
            """# Research Report: What affects adoption?

Question: What affects adoption?

## Background

The reviewed evidence focuses on governance readiness.

## Key Findings

- Enterprise adoption depends on cost control, governance readiness, integration effort, and measurable business value [C1]

## Conclusion

Teams should evaluate governance before deployment.

## References

[C1] Mock Source 1 for What affects adoption? - mock://source/1
""",
            json.dumps({"passed": False, "issues": ["The report needs a clearer scope statement."], "checks": {"scope": "needs clarification"}}),
            json.dumps({"passed": False, "summary": "范围说明不足。", "issues": [{"issue_id": "red-model-1", "category": "scope", "severity": "medium", "message": "Clarify the report scope.", "evidence": "Scope statement is brief.", "suggestion": "State that findings are limited to the available sources."}]}),
            json.dumps({"revised_markdown": "# Research Report: What affects adoption?\n\n## Background\n\nThe reviewed evidence focuses on governance readiness and the available sources only.\n\n## Key Findings\n\n- Enterprise adoption depends on cost control, governance readiness, integration effort, and measurable business value [C1]\n\n## Conclusion\n\nTeams should evaluate governance before deployment.\n\n## References\n\n[C1] Mock Source 1 for What affects adoption? - mock://source/1", "fixed_issue_ids": ["red-model-1"], "remaining_issue_ids": [], "revision_notes": ["已补充来源范围限制。"]}),
            json.dumps({"passed": True, "summary": "第二轮未发现阻断问题。", "issues": []}),
        ])

        result = run_research_pipeline(
            "What affects adoption?",
            llm_client=client,
            use_red_blue_loop=True,
        )

        self.assertEqual(
            result["initial_report"].sections[0]["content"],
            "The reviewed evidence focuses on governance readiness.",
            result["execution"].outputs["writer_task"].metadata,
        )
        self.assertIn("available sources only", result["final_report"].markdown)
        self.assertEqual(result["red_blue_loop_result"].rounds[0].red_review.summary, "第二轮未发现阻断问题。")
        self.assertEqual(len(client.calls), 6)

    def test_pipeline_returns_explicit_degraded_report_when_model_failure_stops_dag(self) -> None:
        result = run_research_pipeline(
            "What affects adoption?",
            llm_client=FailingLLM(),
            require_llm=True,
        )

        self.assertFalse(result["success"])
        self.assertIn("未能完成真实报告生成", result["final_report"].markdown)
        self.assertEqual(result["findings"], [])
        self.assertIsNone(result["blue_revision"])


if __name__ == "__main__":
    unittest.main()
