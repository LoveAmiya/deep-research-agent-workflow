from dataclasses import replace
from typing import List

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.llm_client import LLMMessage
from core.prompt_loader import load_prompt
from core.schema import BlueRevisionResult, Finding, RedReviewResult, ResearchReport


class BlueAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="BlueAgent", role="blue_revision")

    def run(self, context: AgentContext) -> AgentResult:
        report = context.inputs["report"]
        red_review = context.inputs["red_review"]
        findings = context.inputs["findings"]
        if not isinstance(report, ResearchReport):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="BlueAgent expected a ResearchReport in context.inputs['report'].",
                metadata={"role": self.role, "handoff": "red_review -> blue_revision"},
            )
        if not isinstance(red_review, RedReviewResult):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="BlueAgent expected a RedReviewResult in context.inputs['red_review'].",
                metadata={"role": self.role, "handoff": "red_review -> blue_revision"},
            )
        if not isinstance(findings, list):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="BlueAgent expected a list of Finding in context.inputs['findings'].",
                metadata={"role": self.role, "handoff": "red_review -> blue_revision"},
            )

        revised_report = self._revise_report(report, findings)
        fixed_issue_ids = []
        remaining_issue_ids = []
        revision_notes = []

        for issue in red_review.issues:
            resolved = self._issue_resolved(issue.message, revised_report)
            if resolved:
                fixed_issue_ids.append(issue.issue_id)
                revision_notes.append(f"Addressed issue {issue.issue_id}: {issue.message}")
            else:
                remaining_issue_ids.append(issue.issue_id)

        llm_error = None
        used_llm = False
        fallback_used = False
        if context.llm_client is not None:
            try:
                response = context.llm_client.generate(
                    [
                        LLMMessage(role="system", content=load_prompt("blue_agent")),
                        LLMMessage(role="user", content=revised_report.markdown),
                    ]
                )
                revision_notes.append(f"LLM revision notes: {response.content}")
                used_llm = True
            except Exception as exc:
                llm_error = str(exc)
                fallback_used = True

        result = BlueRevisionResult(
            revised_report=revised_report,
            fixed_issue_ids=fixed_issue_ids,
            remaining_issue_ids=remaining_issue_ids,
            revision_notes=revision_notes,
        )
        metadata = {
            "role": self.role,
            "handoff": "red_review -> blue_revision",
            "task_id": context.task_id,
            "fixed_issue_count": len(fixed_issue_ids),
            "remaining_issue_count": len(remaining_issue_ids),
            "used_llm": used_llm,
            "llm_error": llm_error,
            "fallback_used": fallback_used,
        }
        self._write_memory(context, result, metadata)
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=result,
            metadata=metadata,
        )

    def _revise_report(self, report: ResearchReport, findings: List[Finding]) -> ResearchReport:
        sections = list(report.sections)
        section_titles = [section["title"] for section in sections]
        citations = list(report.citations) if report.citations else self._collect_citations(findings)
        revision_notes = []

        if "Background" not in section_titles:
            sections.insert(
                0,
                {
                    "title": "Background",
                    "content": "This added background section summarizes the report context in a deterministic way.",
                },
            )
            revision_notes.append("Added missing Background section.")

        if "Key Findings" not in section_titles:
            sections.append(
                {
                    "title": "Key Findings",
                    "content": "\n".join(
                        f"- {finding.claim} ([source]({finding.source_url}))" for finding in findings
                    ),
                }
            )
            revision_notes.append("Added missing Key Findings section.")

        if "Conclusion" not in section_titles:
            sections.append(
                {
                    "title": "Conclusion",
                    "content": "This added conclusion summarizes the report findings at a high level.",
                }
            )
            revision_notes.append("Added missing Conclusion section.")

        if "References" not in section_titles:
            sections.append(
                {
                    "title": "References",
                    "content": "\n".join(f"- {citation}" for citation in citations),
                }
            )
            revision_notes.append("Added missing References section.")

        markdown = self._build_markdown(report, sections, citations)
        return replace(
            report,
            sections=sections,
            citations=citations,
            references=citations,
            markdown=markdown,
            summary=report.summary or "Revised report after BlueAgent pass.",
        )

    @staticmethod
    def _collect_citations(findings: List[Finding]) -> List[str]:
        citations: List[str] = []
        for finding in findings:
            if finding.source_url and finding.source_url not in citations:
                citations.append(finding.source_url)
        return citations

    @staticmethod
    def _build_markdown(report: ResearchReport, sections: List[dict], citations: List[str]) -> str:
        lines = [f"# {report.title}", "", f"Question: {report.question}", ""]
        for section in sections:
            lines.extend([f"## {section['title']}", "", section["content"], ""])
        if "## References" not in "\n".join(lines):
            lines.extend(["## References", ""])
            lines.extend([f"- {citation}" for citation in citations])
        return "\n".join(lines).strip()

    @staticmethod
    def _issue_resolved(message: str, report: ResearchReport) -> bool:
        markdown = report.markdown
        if "Background" in message:
            return "## Background" in markdown
        if "Key Findings" in message:
            return "## Key Findings" in markdown
        if "Conclusion" in message:
            return "## Conclusion" in markdown
        if "References" in message:
            return "## References" in markdown
        if "citations" in message.lower():
            return len(report.citations) > 0
        return False

    def _write_memory(self, context: AgentContext, result: BlueRevisionResult, metadata: dict) -> None:
        if context.memory is None:
            return
        try:
            context.memory.add_record(
                item_type="blue_revision",
                content=result,
                source_agent=self.name,
                task_id=context.task_id,
                metadata=metadata,
            )
        except Exception as exc:
            metadata["memory_error"] = str(exc)
