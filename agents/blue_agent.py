import re
from dataclasses import replace
from typing import List

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.llm_client import LLMMessage
from core.prompt_loader import load_prompt
from core.schema import BlueRevisionResult, Finding, RedReviewResult, ResearchReport
from core.structured_output import extract_json_object, string_list


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

        citation_registry = context.inputs.get("citation_registry")
        revised_report = self._revise_report(report, findings, citation_registry)
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
                        LLMMessage(
                            role="user",
                            content=self._build_revision_request(revised_report, red_review, findings),
                        ),
                    ]
                )
                parsed = extract_json_object(response.content)
                if parsed is None:
                    raise ValueError("Blue LLM output was not a JSON object.")
                candidate = str(
                    parsed.get("revised_markdown") or parsed.get("revisedReportMarkdown") or ""
                ).strip()
                if candidate:
                    revised_report = self._accept_model_revision(
                        candidate,
                        revised_report,
                        findings,
                        citation_registry,
                    )
                model_fixed = string_list(parsed.get("fixed_issue_ids") or parsed.get("fixedIssueIds"))
                model_remaining = string_list(parsed.get("remaining_issue_ids") or parsed.get("remainingIssueIds"))
                allowed_issue_ids = {issue.issue_id for issue in red_review.issues}
                fixed_issue_ids = [issue_id for issue_id in model_fixed if issue_id in allowed_issue_ids]
                remaining_issue_ids = [issue_id for issue_id in model_remaining if issue_id in allowed_issue_ids]
                revision_notes.extend(string_list(parsed.get("revision_notes") or parsed.get("revisionNotes")))
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

    @staticmethod
    def _build_revision_request(
        report: ResearchReport,
        red_review: RedReviewResult,
        findings: List[Finding],
    ) -> str:
        issues = "\n".join(
            f"- {issue.issue_id}: {issue.message}; suggestion: {issue.suggestion or ''}"
            for issue in red_review.issues
        ) or "- No blocking issues; improve clarity only."
        approved = "\n".join(
            f"- {finding.claim} [{finding.citation_id or finding.source_url}]"
            for finding in findings
        )
        return (
            "Return one JSON object with revised_markdown, fixed_issue_ids, remaining_issue_ids, and revision_notes. "
            "Use only these approved findings and citation markers. Do not introduce a new citation marker.\n\n"
            f"Approved findings:\n{approved}\n\nRed issues:\n{issues}\n\nCurrent report:\n{report.markdown}"
        )

    @classmethod
    def _accept_model_revision(
        cls,
        markdown: str,
        fallback_report: ResearchReport,
        findings: List[Finding],
        citation_registry=None,
    ) -> ResearchReport:
        allowed_citations = {
            finding.citation_id for finding in findings if finding.citation_id
        }
        if citation_registry is not None:
            allowed_citations.update(
                citation.citation_id for citation in citation_registry.list_citations()
            )
        sanitized_lines = [
            line for line in markdown.splitlines()
            if not any(marker not in allowed_citations for marker in re.findall(r"\[([^\]]+)\]", line) if marker.startswith("C"))
        ]
        sanitized = "\n".join(sanitized_lines).strip()
        required_sections = {"Background", "Key Findings", "Conclusion", "References"}
        if not sanitized.startswith("# ") or any(f"## {section}" not in sanitized for section in required_sections):
            return fallback_report
        key_findings = cls._extract_section(sanitized, "Key Findings")
        approved_markers = {f"[{citation_id}]" for citation_id in allowed_citations}
        for line in key_findings.splitlines():
            if not line.lstrip().startswith("-"):
                continue
            if not any(marker in line for marker in approved_markers):
                return fallback_report
        sections = [
            {"title": section, "content": cls._extract_section(sanitized, section).strip()}
            for section in ["Background", "Key Findings", "Conclusion", "References"]
        ]
        revised = replace(fallback_report, sections=sections, markdown=sanitized)
        return cls._restore_registry_references(revised, citation_registry)

    @staticmethod
    def _restore_registry_references(report: ResearchReport, citation_registry=None) -> ResearchReport:
        if citation_registry is None:
            return report
        references = citation_registry.to_references_markdown()
        if not references:
            return report
        marker = "## References"
        start = report.markdown.find(marker)
        if start < 0:
            markdown = report.markdown.rstrip() + f"\n\n{marker}\n\n{references}"
        else:
            markdown = report.markdown[:start].rstrip() + f"\n\n{marker}\n\n{references}"
        sections = [
            {"title": section["title"], "content": references if section["title"] == "References" else section["content"]}
            for section in report.sections
        ]
        if not any(section["title"] == "References" for section in sections):
            sections.append({"title": "References", "content": references})
        return replace(report, sections=sections, markdown=markdown)

    @staticmethod
    def _extract_section(markdown: str, title: str) -> str:
        heading = f"## {title}"
        start = markdown.find(heading)
        if start < 0:
            return ""
        content_start = start + len(heading)
        next_heading = markdown.find("\n## ", content_start)
        return markdown[content_start:] if next_heading < 0 else markdown[content_start:next_heading]

    def _revise_report(
        self,
        report: ResearchReport,
        findings: List[Finding],
        citation_registry=None,
    ) -> ResearchReport:
        sections = list(report.sections)
        section_titles = [section["title"] for section in sections]
        citations = (
            self._collect_citation_ids(findings)
            if citation_registry is not None
            else list(report.citations) if report.citations else self._collect_citations(findings)
        )
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
                        f"- {finding.claim}{self._citation_suffix(finding, citation_registry is not None)}"
                        for finding in findings
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
                    "content": self._references_content(citations, citation_registry),
                }
            )
            revision_notes.append("Added missing References section.")
        else:
            sections = self._replace_references_if_registry_available(sections, citations, citation_registry)

        markdown = self._build_markdown(report, sections, citations, citation_registry)
        markdown = self._ensure_key_finding_markers(markdown, findings)
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
    def _collect_citation_ids(findings: List[Finding]) -> List[str]:
        citations: List[str] = []
        for finding in findings:
            if finding.citation_id and finding.citation_id not in citations:
                citations.append(finding.citation_id)
        return citations

    @staticmethod
    def _citation_suffix(finding: Finding, use_citation_markers: bool) -> str:
        if use_citation_markers and finding.citation_id:
            return f" [{finding.citation_id}]"
        return f" ([source]({finding.source_url}))"

    @staticmethod
    def _references_content(citations: List[str], citation_registry=None) -> str:
        if citation_registry is not None:
            references = citation_registry.to_references_markdown()
            if references:
                return references
        return "\n".join(f"- {citation}" for citation in citations)

    @classmethod
    def _replace_references_if_registry_available(
        cls,
        sections: List[dict],
        citations: List[str],
        citation_registry=None,
    ) -> List[dict]:
        if citation_registry is None:
            return sections
        updated_sections = []
        for section in sections:
            if section["title"] == "References":
                updated_sections.append(
                    {"title": "References", "content": cls._references_content(citations, citation_registry)}
                )
            else:
                updated_sections.append(section)
        return updated_sections

    @staticmethod
    def _build_markdown(
        report: ResearchReport,
        sections: List[dict],
        citations: List[str],
        citation_registry=None,
    ) -> str:
        lines = [f"# {report.title}", "", f"Question: {report.question}", ""]
        for section in sections:
            lines.extend([f"## {section['title']}", "", section["content"], ""])
        if "## References" not in "\n".join(lines):
            lines.extend(["## References", ""])
            references = BlueAgent._references_content(citations, citation_registry)
            if references:
                lines.extend(references.splitlines())
        return "\n".join(lines).strip()

    @staticmethod
    def _ensure_key_finding_markers(markdown: str, findings: List[Finding]) -> str:
        updated = markdown
        for finding in findings:
            if not finding.citation_id:
                continue
            marker = f"[{finding.citation_id}]"
            if marker in updated:
                continue
            source_link = f"([source]({finding.source_url}))"
            if source_link in updated:
                updated = updated.replace(source_link, marker, 1)
            elif finding.claim in updated:
                updated = updated.replace(finding.claim, f"{finding.claim} {marker}", 1)
        return updated

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
