from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.schema import ResearchReport


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
        }
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
