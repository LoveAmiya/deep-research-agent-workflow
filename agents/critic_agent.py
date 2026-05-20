from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.llm_client import LLMMessage
from core.prompt_loader import load_prompt
from core.schema import ResearchReport
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
        checks = {
            "has_title": markdown.startswith("# "),
            "has_key_findings": "## Key Findings" in markdown,
            "has_references": "## References" in markdown,
            "citation_count": len(report.citations),
        }
        issues = []
        if not checks["has_title"]:
            issues.append("Report is missing a markdown title.")
        if not checks["has_key_findings"]:
            issues.append("Report is missing the Key Findings section.")
        if not checks["has_references"]:
            issues.append("Report is missing the References section.")
        if checks["citation_count"] == 0:
            issues.append("Report does not contain any citations.")

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
                        LLMMessage(role="user", content=report.markdown),
                    ]
                )
                review["llm_notes"] = response.content
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
