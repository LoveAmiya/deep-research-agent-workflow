from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.llm_client import LLMMessage
from core.prompt_loader import load_prompt
from core.schema import Finding, RedReviewResult, ResearchReport, ReviewIssue


class RedAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="RedAgent", role="red_review")

    def run(self, context: AgentContext) -> AgentResult:
        report = context.inputs["report"]
        findings = context.inputs["findings"]
        critic_review = context.inputs.get("critic_review")
        if not isinstance(report, ResearchReport):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="RedAgent expected a ResearchReport in context.inputs['report'].",
                metadata={"role": self.role, "handoff": "report -> red_review"},
            )
        if not isinstance(findings, list):
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="RedAgent expected a list of Finding in context.inputs['findings'].",
                metadata={"role": self.role, "handoff": "report -> red_review"},
            )

        issues = []
        markdown = report.markdown or ""
        issue_index = 1

        for section in ["Background", "Key Findings", "Conclusion", "References"]:
            if f"## {section}" not in markdown:
                issues.append(
                    ReviewIssue(
                        issue_id=f"red-{issue_index}",
                        category="structure" if section != "References" else "citation",
                        severity="high" if section in {"Key Findings", "References"} else "medium",
                        message=f"Report is missing the {section} section.",
                        evidence=section,
                        suggestion=f"Add a {section} section to the report.",
                    )
                )
                issue_index += 1

        if not report.citations:
            issues.append(
                ReviewIssue(
                    issue_id=f"red-{issue_index}",
                    category="citation",
                    severity="high",
                    message="Report does not contain any citations.",
                    evidence="citations=[]",
                    suggestion="Populate citations from finding source URLs.",
                )
            )
            issue_index += 1
        else:
            for citation in report.citations:
                if citation not in markdown:
                    issues.append(
                        ReviewIssue(
                            issue_id=f"red-{issue_index}",
                            category="citation",
                            severity="medium",
                            message="A citation is missing from the References section text.",
                            evidence=citation,
                            suggestion="Ensure each citation URL appears in References.",
                        )
                    )
                    issue_index += 1
                    break

        if not findings:
            issues.append(
                ReviewIssue(
                    issue_id=f"red-{issue_index}",
                    category="evidence",
                    severity="high",
                    message="No findings were available to support the report.",
                    suggestion="Generate findings before report writing.",
                )
            )
            issue_index += 1
        else:
            key_findings_section = self._extract_key_findings(markdown)
            bullet_count = key_findings_section.count("\n- ") + (
                1 if key_findings_section.startswith("- ") else 0
            )
            if bullet_count < len(findings):
                issues.append(
                    ReviewIssue(
                        issue_id=f"red-{issue_index}",
                        category="evidence",
                        severity="low" if bullet_count > 0 else "medium",
                        message="Key Findings appears to summarize fewer items than the findings list.",
                        evidence=f"key_findings_bullets={bullet_count}, findings={len(findings)}",
                        suggestion="Expand Key Findings to reflect the available findings.",
                    )
                )
                issue_index += 1

        if len(markdown.strip()) < 120:
            issues.append(
                ReviewIssue(
                    issue_id=f"red-{issue_index}",
                    category="completeness",
                    severity="medium",
                    message="Report markdown is very short.",
                    evidence=f"length={len(markdown.strip())}",
                    suggestion="Expand the report content with the expected sections.",
                )
            )
            issue_index += 1

        if critic_review and isinstance(critic_review, dict) and critic_review.get("issues"):
            issues.append(
                ReviewIssue(
                    issue_id=f"red-{issue_index}",
                    category="logic",
                    severity="low",
                    message="Critic review reported additional concerns.",
                    evidence=", ".join(critic_review["issues"]),
                    suggestion="Address the critic review concerns in the revision pass.",
                )
            )

        if issues:
            result = RedReviewResult(
                passed=False,
                issues=issues,
                summary=f"Found {len(issues)} issue(s) in the report review.",
            )
        else:
            result = RedReviewResult(
                passed=True,
                issues=[],
                summary="No major issues found.",
            )

        metadata = {
            "role": self.role,
            "handoff": "report -> red_review",
            "task_id": context.task_id,
            "issue_count": len(result.issues),
            "used_llm": False,
            "llm_error": None,
            "fallback_used": False,
        }
        if context.llm_client is not None:
            try:
                response = context.llm_client.generate(
                    [
                        LLMMessage(role="system", content=load_prompt("red_agent")),
                        LLMMessage(role="user", content=report.markdown),
                    ]
                )
                metadata["llm_review_notes"] = response.content
                metadata["used_llm"] = True
            except Exception as exc:
                metadata["llm_error"] = str(exc)
                metadata["fallback_used"] = True
        self._write_memory(context, result, metadata)
        return AgentResult(
            agent_name=self.name,
            success=True,
            output=result,
            metadata=metadata,
        )

    @staticmethod
    def _extract_key_findings(markdown: str) -> str:
        if "## Key Findings" not in markdown:
            return ""
        start = markdown.index("## Key Findings")
        section_text = markdown[start:]
        next_heading_index = section_text.find("\n## ", len("## Key Findings"))
        if next_heading_index == -1:
            return section_text
        return section_text[:next_heading_index]

    def _write_memory(self, context: AgentContext, review: RedReviewResult, metadata: dict) -> None:
        if context.memory is None:
            return
        try:
            context.memory.add_record(
                item_type="red_review",
                content=review,
                source_agent=self.name,
                task_id=context.task_id,
                metadata=metadata,
            )
        except Exception as exc:
            metadata["memory_error"] = str(exc)
