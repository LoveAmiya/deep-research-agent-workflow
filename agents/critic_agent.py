from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.llm_client import LLMMessage
from core.prompt_loader import load_prompt
from core.schema import ResearchReport
from core.structured_output import extract_json_object, string_list
from tools.citation_tool import CitationValidator


class CriticAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="CriticAgent", role="critic")

    def run(self, context: AgentContext) -> AgentResult:
        report = context.inputs["report"]
        findings = context.inputs["findings"]
        if not isinstance(report, ResearchReport):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="CriticAgent expected a ResearchReport in context.inputs['report'].",
                metadata={"role": self.role, "handoff": "report -> review"},
            )
        if not isinstance(findings, list):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="CriticAgent expected a list of Finding in context.inputs['findings'].",
                metadata={"role": self.role, "handoff": "report -> review"},
            )

        markdown = report.markdown or ""
        citation_registry = context.inputs.get("citation_registry")
        required_sections = [
            "Background",
            "Key Findings",
            "Analysis and Discussion",
            "Limitations",
            "Recommendations",
            "Conclusion",
            "References",
        ]
        checks = {
            "has_title": markdown.startswith("# "),
            **{f"has_{section.lower().replace(' ', '_')}": f"## {section}" in markdown for section in required_sections},
            "citation_count": len(report.citations),
        }
        issues = []
        if not checks["has_title"]:
            issues.append("Report is missing a markdown title.")
        for section in required_sections:
            if f"## {section}" not in markdown:
                issues.append(f"Report is missing the {section} section.")
        if checks["citation_count"] == 0:
            issues.append("Report does not contain any citations.")

        key_findings = self._extract_section(markdown, "Key Findings")
        checks["key_finding_bullet_count"] = len(
            [line for line in key_findings.splitlines() if line.strip().startswith("- ")]
        )
        discussion = self._extract_section(markdown, "Analysis and Discussion")
        conclusion = self._extract_section(markdown, "Conclusion")
        checks["discussion_character_count"] = len(discussion.strip())
        checks["conclusion_character_count"] = len(conclusion.strip())
        if "## Analysis and Discussion" in markdown and len(discussion.strip()) < 120:
            issues.append("Analysis and Discussion is too short to explain relationships or trade-offs.")
        if "## Conclusion" in markdown and len(conclusion.strip()) < 60:
            issues.append("Conclusion is too short to synthesize the research answer.")

        if citation_registry is not None:
            citation_validation = CitationValidator().validate_report_citations(report, citation_registry)
            checks["citation_markers_present"] = "[C" in markdown
            checks["references_grounded"] = citation_validation["passed"]
            checks["grounded_citation_count"] = citation_validation["grounded_citation_count"]
            issues.extend(citation_validation["issues"])

        review = {
            "passed": len(issues) == 0,
            "issues": issues,
            "checks": checks,
            "finding_count": len(findings),
        }
        metadata = {
            "role": self.role,
            "handoff": "report -> review",
            "task_id": context.task_id,
            "used_llm": False,
            "llm_error": None,
            "fallback_used": False,
        }
        if context.llm_client is not None:
            try:
                response = context.llm_client.generate(
                    [
                        LLMMessage(role="system", content=load_prompt("critic")),
                        LLMMessage(
                            role="user",
                            content=(
                                f"Report:\n{report.markdown}\n\n"
                                f"Approved finding count: {len(findings)}"
                            ),
                        ),
                    ]
                )
                parsed = extract_json_object(response.content)
                if parsed is None:
                    raise ValueError("Critic LLM output was not a JSON object.")
                model_issues = string_list(parsed.get("issues"))
                review["issues"] = list(dict.fromkeys([*review["issues"], *model_issues]))
                model_checks = parsed.get("checks")
                if isinstance(model_checks, dict):
                    review["checks"].update(model_checks)
                if model_issues or parsed.get("passed") is False:
                    review["passed"] = False
                review["llm_notes"] = str(parsed.get("summary") or "")
                metadata["used_llm"] = True
            except Exception as exc:
                metadata["llm_error"] = str(exc)
                metadata["fallback_used"] = True
        self._write_memory(context, review, metadata)
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=review,
            metadata=metadata,
        )

    @staticmethod
    def _extract_section(markdown: str, title: str) -> str:
        marker = f"## {title}"
        start = markdown.find(marker)
        if start < 0:
            return ""
        body_start = start + len(marker)
        next_heading = markdown.find("\n## ", body_start)
        return markdown[body_start:] if next_heading < 0 else markdown[body_start:next_heading]

    def _write_memory(self, context: AgentContext, review: dict, metadata: dict) -> None:
        if context.memory is None:
            return
        try:
            context.memory.add_record(
                item_type="review",
                content=review,
                source_agent=self.name,
                task_id=context.task_id,
                metadata=metadata,
            )
        except Exception as exc:
            metadata["memory_error"] = str(exc)
