from typing import List

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.llm_client import LLMMessage
from core.prompt_loader import load_prompt
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

        references = self._unique_references(findings)
        metadata = {
            "role": self.role,
            "handoff": "findings -> report",
            "task_id": context.task_id,
            "citation_count": len(references),
            "used_llm": False,
            "llm_error": None,
            "fallback_used": False,
        }
        markdown = None
        if context.llm_client is not None:
            try:
                prompt = load_prompt("writer")
                response = context.llm_client.generate(
                    [
                        LLMMessage(role="system", content=prompt),
                        LLMMessage(
                            role="user",
                            content=self._build_writer_user_message(question, findings, references),
                        ),
                    ]
                )
                candidate = response.content.strip()
                if all(reference in candidate for reference in references) and "## References" in candidate:
                    markdown = candidate
                    metadata["used_llm"] = True
                else:
                    metadata["used_llm"] = True
                    metadata["fallback_used"] = True
                    metadata["llm_error"] = "LLM output omitted required citations or References section."
            except Exception as exc:
                metadata["llm_error"] = str(exc)
                metadata["fallback_used"] = True

        sections = self._build_sections(question, findings)
        if markdown is None:
            markdown = self._build_markdown(question, sections, references)
            if context.llm_client is not None:
                metadata["fallback_used"] = True
        report = ResearchReport(
            title=f"Research Report: {question.question}",
            question=question.question,
            sections=sections,
            citations=references,
            markdown=markdown,
            question_id=question.question_id,
            findings=findings,
            references=references,
            summary=plan.objective,
        )
        self._write_memory(context, report, metadata)
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=report,
            metadata=metadata,
        )

    @staticmethod
    def _build_sections(question: ResearchQuestion, findings: List[Finding]) -> List[dict]:
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
        return [
            {"title": "Background", "content": background},
            {"title": "Key Findings", "content": "\n".join(key_findings_lines)},
            {"title": "Conclusion", "content": conclusion},
        ]

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

    @staticmethod
    def _build_writer_user_message(
        question: ResearchQuestion,
        findings: List[Finding],
        references: List[str],
    ) -> str:
        finding_lines = "\n".join(
            f"- Claim: {finding.claim}\n  Evidence: {finding.evidence}\n  Source: {finding.source_url}"
            for finding in findings
        )
        reference_lines = "\n".join(f"- {reference}" for reference in references)
        return (
            f"Question: {question.question}\n\n"
            f"Findings:\n{finding_lines}\n\n"
            f"Citations:\n{reference_lines}"
        )

    def _write_memory(self, context: AgentContext, report: ResearchReport, metadata: dict) -> None:
        if context.memory is None:
            return
        try:
            context.memory.add_record(
                item_type="report",
                content=report,
                source_agent=self.name,
                task_id=context.task_id,
                metadata=metadata,
            )
        except Exception as exc:
            metadata["memory_error"] = str(exc)
