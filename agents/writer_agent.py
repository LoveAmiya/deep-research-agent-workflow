from typing import List

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.schema import Finding, ResearchPlan, ResearchQuestion, ResearchReport


class WriterAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="WriterAgent", role="writer")

    def run(self, context: AgentContext) -> AgentResult:
        question = context.inputs["question"]
        plan = context.inputs["plan"]
        findings = context.inputs["findings"]
        if not isinstance(question, ResearchQuestion):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="WriterAgent expected a ResearchQuestion in context.inputs['question'].",
                metadata={"role": self.role, "handoff": "findings -> report"},
            )
        if not isinstance(plan, ResearchPlan):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="WriterAgent expected a ResearchPlan in context.inputs['plan'].",
                metadata={"role": self.role, "handoff": "findings -> report"},
            )
        if not isinstance(findings, list):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="WriterAgent expected a list of Finding in context.inputs['findings'].",
                metadata={"role": self.role, "handoff": "findings -> report"},
            )

        background = (
            f"This mock research report examines the question: {question.question}. "
            "The current pipeline is deterministic and uses placeholder evidence rather than real web or model calls."
        )
        key_findings_lines = [
            f"- {finding.claim} ([source]({finding.source_url}))" for finding in findings
        ]
        conclusion = (
            f"Based on the mock evidence, {question.question.lower()} is shaped by recurring factors such as "
            "business value, governance, integration effort, and operational readiness."
        )
        references = self._unique_references(findings)
        sections = [
            {"title": "Background", "content": background},
            {"title": "Key Findings", "content": "\n".join(key_findings_lines)},
            {"title": "Conclusion", "content": conclusion},
        ]
        markdown = self._build_markdown(question, sections, references)
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=ResearchReport(
                title=f"Research Report: {question.question}",
                question=question.question,
                sections=sections,
                citations=references,
                markdown=markdown,
                question_id=question.question_id,
                findings=findings,
                references=references,
                summary=plan.objective,
            ),
            metadata={
                "role": self.role,
                "handoff": "findings -> report",
                "task_id": context.task_id,
                "citation_count": len(references),
            },
        )

    @staticmethod
    def _unique_references(findings: List[Finding]) -> List[str]:
        unique_refs: List[str] = []
        for finding in findings:
            if finding.source_url not in unique_refs:
                unique_refs.append(finding.source_url)
        return unique_refs

    @staticmethod
    def _build_markdown(
        question: ResearchQuestion,
        sections: List[dict],
        references: List[str],
    ) -> str:
        lines = [f"# Research Report: {question.question}", "", f"Question: {question.question}", ""]
        for section in sections:
            lines.extend([f"## {section['title']}", "", section["content"], ""])
        lines.extend(["## References", ""])
        lines.extend([f"- {reference}" for reference in references])
        return "\n".join(lines).strip()
