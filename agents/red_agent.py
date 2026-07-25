from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.llm_client import LLMMessage
from core.prompt_loader import load_prompt
from core.schema import Finding, RedReviewResult, ResearchReport, ReviewIssue
from core.structured_output import extract_json_object
from tools.citation_tool import CitationValidator


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
        citation_registry = context.inputs.get("citation_registry")
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
            citation_marker_count = key_findings_section.count("[C")
            distinct_claim_count = len({
                finding.claim.strip().lower()
                for finding in findings
                if finding.claim.strip()
            })
            if bullet_count < distinct_claim_count:
                issues.append(
                    ReviewIssue(
                        issue_id=f"red-{issue_index}",
                        category="evidence",
                        severity="low" if bullet_count > 0 else "medium",
                        message="Key Findings appears to summarize fewer items than the findings list.",
                        evidence=f"key_findings_bullets={bullet_count}, unique_findings={distinct_claim_count}",
                        suggestion="Expand Key Findings to reflect the available findings.",
                    )
                )
                issue_index += 1
            if citation_registry is not None and citation_marker_count < bullet_count:
                issues.append(
                    ReviewIssue(
                        issue_id=f"red-{issue_index}",
                        category="citation",
                        severity="medium",
                        message="One or more Key Findings bullets are missing citation markers.",
                        evidence=f"citation_markers={citation_marker_count}, bullets={bullet_count}",
                        suggestion="Add [C#] citation markers to each grounded finding.",
                    )
                )
                issue_index += 1

        if citation_registry is not None:
            validation = CitationValidator().validate_report_citations(report, citation_registry)
            for validation_issue in validation["issues"]:
                issues.append(
                    ReviewIssue(
                        issue_id=f"red-{issue_index}",
                        category="citation" if "citation" in validation_issue.lower() else "evidence",
                        severity="high",
                        message=validation_issue,
                        evidence=", ".join(validation.get("missing_citations", [])) or None,
                        suggestion="Regenerate citation markers and References from CitationRegistry.",
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
                        LLMMessage(
                            role="user",
                            content=self._build_review_request(report, findings, critic_review),
                        ),
                    ]
                )
                parsed = extract_json_object(response.content)
                if parsed is None:
                    raise ValueError("Red LLM output was not a JSON object.")
                issues.extend(self._model_issues(parsed.get("issues"), issue_index))
                if parsed.get("summary"):
                    metadata["llm_review_notes"] = str(parsed["summary"])
                if issues:
                    result = RedReviewResult(
                        passed=False,
                        issues=issues,
                        summary=str(parsed.get("summary") or f"Found {len(issues)} issue(s) in the report review."),
                    )
                elif parsed.get("passed") is False:
                    result = RedReviewResult(
                        passed=False,
                        issues=[
                            ReviewIssue(
                                issue_id=f"red-model-{issue_index}",
                                category="logic",
                                severity="medium",
                                message="Model review reported a concern without a concrete issue.",
                                suggestion="Provide a concrete, evidence-backed review issue.",
                            )
                        ],
                        summary=str(parsed.get("summary") or "Model review requires follow-up."),
                    )
                elif parsed.get("summary"):
                    result = RedReviewResult(
                        passed=True,
                        issues=[],
                        summary=str(parsed["summary"]),
                    )
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
    def _model_issues(value, start_index: int) -> list[ReviewIssue]:
        if not isinstance(value, list):
            return []
        parsed_issues = []
        for index, item in enumerate(value, start=start_index):
            if not isinstance(item, dict):
                continue
            message = str(item.get("message") or "").strip()
            if not message:
                continue
            severity = str(item.get("severity") or "medium").lower()
            if severity not in {"low", "medium", "high"}:
                severity = "medium"
            parsed_issues.append(
                ReviewIssue(
                    issue_id=str(item.get("issue_id") or item.get("issueId") or f"red-model-{index}"),
                    category=str(item.get("category") or "logic"),
                    severity=severity,
                    message=message,
                    evidence=str(item.get("evidence") or "") or None,
                    suggestion=str(item.get("suggestion") or "") or None,
                )
            )
        return parsed_issues

    @staticmethod
    def _build_review_request(report, findings, critic_review) -> str:
        approved = "\n".join(
            f"- {finding.claim} [{finding.citation_id or finding.source_url}]"
            for finding in findings
        )
        critic_issues = []
        if isinstance(critic_review, dict):
            critic_issues = critic_review.get("issues", []) or []
        return (
            f"Approved findings:\n{approved}\n\n"
            f"Critic issues:\n{critic_issues}\n\n"
            f"Report:\n{report.markdown}"
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
