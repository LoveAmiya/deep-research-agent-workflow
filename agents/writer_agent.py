import re
from typing import List

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from core.llm_client import LLMMessage
from core.prompt_loader import load_prompt
from core.schema import Finding, ResearchPlan, ResearchQuestion, ResearchReport
from core.structured_output import extract_json_object


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

        report_findings = self._unique_findings(findings)[:8]
        references = self._unique_references(report_findings)
        citation_registry = context.inputs.get("citation_registry")
        citation_ids = self._citation_ids(report_findings)
        metadata = {
            "role": self.role,
            "handoff": "findings -> report",
            "task_id": context.task_id,
            "citation_count": len(references),
            "used_llm": False,
            "llm_error": None,
            "fallback_used": False,
            "citation_markers_added": 0,
            "references_generated_from_registry": False,
        }
        if citation_registry is not None and citation_ids:
            references = citation_ids
            metadata["citation_count"] = len(references)
        markdown = None
        if context.llm_client is not None:
            try:
                prompt = load_prompt("writer")
                response = context.llm_client.generate(
                    [
                        LLMMessage(role="system", content=prompt),
                        LLMMessage(
                            role="user",
                            content=self._build_writer_user_message(question, report_findings, references),
                        ),
                    ]
                )
                candidate = response.content.strip()
                metadata["llm_output_shape"] = self._model_output_shape(candidate)
                validation_diagnostics = {}
                accepted = self._normalize_model_markdown(
                    candidate,
                    report_findings,
                    citation_registry,
                    validation_diagnostics,
                )
                metadata["llm_output_shape"].update(validation_diagnostics)
                if accepted is not None:
                    markdown, sections = accepted
                    metadata["used_llm"] = True
                else:
                    metadata["used_llm"] = True
                    metadata["fallback_used"] = True
                    metadata["llm_error"] = "LLM output was not a usable report or contained unsupported citations."
            except Exception as exc:
                metadata["llm_error"] = str(exc)
                metadata["fallback_used"] = True

        if markdown is None:
            sections = self._build_sections(question, report_findings, use_citation_markers=citation_registry is not None)
        if markdown is None:
            markdown = self._build_markdown(question, sections, references, citation_registry)
            if context.llm_client is not None:
                metadata["fallback_used"] = True
        if citation_registry is not None:
            markdown, added_count = self._ensure_citation_markers(markdown, report_findings)
            metadata["citation_markers_added"] = added_count
            metadata["references_generated_from_registry"] = True
        report = ResearchReport(
            title=f"Research Report: {question.question}",
            question=question.question,
            sections=sections,
            citations=references,
            markdown=markdown,
            question_id=question.question_id,
            findings=report_findings,
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
    def _build_sections(
        question: ResearchQuestion,
        findings: List[Finding],
        use_citation_markers: bool = False,
    ) -> List[dict]:
        unique_findings = WriterAgent._unique_findings(findings)[:8]
        background = (
            f"本报告围绕“{question.question}”展开。分析重点不是单一模型参数，而是把已经获得的"
            "证据放回企业决策场景，考察业务目标、实施条件、治理责任与持续运营之间的关系。"
        )
        key_findings_lines = [
            f"- {finding.claim}{WriterAgent._citation_suffix(finding, use_citation_markers)}"
            for finding in unique_findings
        ]
        if not key_findings_lines:
            key_findings_lines = ["当前没有足够的可引用证据形成事实性发现。"]
        analysis_lines = [
            f"{index}. **{finding.claim}** 该判断直接对应已批准证据，报告不在证据范围之外扩展新的事实断言。"
            for index, finding in enumerate(unique_findings, start=1)
        ] or ["现有材料不足以支持展开事实性讨论，应先补齐来源后再比较各影响因素。"]
        limitations = (
            f"本次共形成 {len(unique_findings)} 条互不重复的批准发现。"
            + ("发现数量少于五条，不能据此声称已经完整覆盖该问题。" if len(unique_findings) < 5 else "结论仍受当前来源范围和证据时点限制。")
        )
        recommendations = (
            "优先复核每条发现对应的原文切片与来源；对证据覆盖较弱的维度补充独立材料；"
            "在形成采购、部署或治理决策前，将结论转换为可测量的验证问题。"
        )
        conclusion_claims = "；".join(finding.claim.rstrip("。") for finding in unique_findings[:5])
        conclusion = (
            f"综合现有证据，对“{question.question}”的回答不能被压缩为单一因素。"
            + (f"当前最明确的结论包括：{conclusion_claims}。" if conclusion_claims else "当前证据不足，尚不能形成可靠结论。")
            + "这些发现需要结合企业自身约束进行优先级排序，并通过后续验证形成可执行决策。"
        )
        return [
            {"title": "Background", "content": background},
            {"title": "Key Findings", "content": "\n".join(key_findings_lines)},
            {"title": "Analysis and Discussion", "content": "\n\n".join(analysis_lines)},
            {"title": "Limitations", "content": limitations},
            {"title": "Recommendations", "content": recommendations},
            {"title": "Conclusion", "content": conclusion},
        ]

    @staticmethod
    def _unique_findings(findings: List[Finding]) -> List[Finding]:
        unique = []
        seen = set()
        for finding in findings:
            normalized = " ".join((finding.claim or "").lower().split())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(finding)
        return unique

    @classmethod
    def _accept_model_markdown(
        cls,
        markdown: str,
        findings: List[Finding],
        citation_registry=None,
        diagnostics: dict | None = None,
    ):
        diagnostics = diagnostics if diagnostics is not None else {}
        required_sections = ["Background", "Key Findings", "Conclusion", "References"]
        if not markdown.startswith("# ") or any(f"## {section}" not in markdown for section in required_sections):
            diagnostics["validation_error"] = "missing_required_sections"
            return None
        allowed = {finding.citation_id for finding in findings if finding.citation_id}
        markers = set(re.findall(r"\[(C[^\]]+)\]", markdown))
        if not markers.issubset(allowed):
            diagnostics["validation_error"] = "unknown_citation_marker"
            return None
        key_findings = cls._extract_section(markdown, "Key Findings")
        bullets = [line.strip() for line in key_findings.splitlines() if line.strip().startswith("-")]
        distinct_claim_count = len({finding.claim.strip().lower() for finding in findings if finding.claim.strip()})
        if len(bullets) < distinct_claim_count:
            diagnostics["validation_error"] = "too_few_key_finding_bullets"
            return None
        allowed_markers = {f"[{citation_id}]" for citation_id in allowed}
        if findings and any(not any(marker in bullet for marker in allowed_markers) for bullet in bullets):
            diagnostics["validation_error"] = "uncited_key_finding_bullet"
            return None
        sections = [
            {"title": section, "content": cls._extract_section(markdown, section).strip()}
            for section in required_sections
        ]
        return markdown.strip(), sections

    @classmethod
    def _normalize_model_markdown(
        cls,
        markdown: str,
        findings: List[Finding],
        citation_registry=None,
        diagnostics: dict | None = None,
    ):
        """Keep model prose, but deterministically rebuild factual finding and reference blocks."""
        markdown = cls._canonicalize_model_markdown(markdown)
        required_sections = ["Background", "Key Findings", "Conclusion"]
        if not markdown.startswith("# ") or any(f"## {section}" not in markdown for section in required_sections):
            if diagnostics is not None:
                diagnostics["validation_error"] = "unrecognized_report_structure"
            return None
        allowed = {finding.citation_id for finding in findings if finding.citation_id}
        markers = set(re.findall(r"\[(C[^\]]+)\]", markdown))
        if not markers.issubset(allowed):
            if diagnostics is not None:
                diagnostics["validation_error"] = "unknown_citation_marker_before_normalization"
            return None

        key_start = markdown.find("## Key Findings")
        next_heading = markdown.find("\n## ", key_start + len("## Key Findings"))
        key_end = len(markdown) if next_heading < 0 else next_heading
        key_body = markdown[key_start + len("## Key Findings") : key_end].strip()
        model_bullets = [line.strip() for line in key_body.splitlines() if line.strip().startswith("-")]
        rebuilt_bullets = []
        for line in model_bullets:
            matching = next((finding for finding in findings if finding.claim.lower() in line.lower()), None)
            if matching is None:
                continue
            marker = f"[{matching.citation_id}]" if matching.citation_id else ""
            if marker and marker not in line:
                line = f"{line.rstrip('.')} {marker}"
            rebuilt_bullets.append(line)
        for finding in findings:
            if not any(finding.claim.lower() in line.lower() for line in rebuilt_bullets):
                marker = f" [{finding.citation_id}]" if finding.citation_id else ""
                rebuilt_bullets.append(f"- {finding.claim}{marker}")
        if findings and not rebuilt_bullets:
            if diagnostics is not None:
                diagnostics["validation_error"] = "no_rebuildable_key_findings"
            return None
        normalized = markdown[:key_start] + "## Key Findings\n\n" + "\n".join(rebuilt_bullets) + markdown[key_end:]
        references = citation_registry.to_references_markdown(sorted(allowed)) if citation_registry is not None else ""
        if not references:
            references = "\n".join(
                f"[{finding.citation_id}] {finding.source_url}"
                for finding in findings if finding.citation_id
            )
        if "## References" not in normalized:
            normalized = normalized.rstrip() + "\n\n## References\n\n" + references
        elif references:
            reference_start = normalized.find("## References")
            reference_body = normalized[reference_start:]
            missing_lines = [line for line in references.splitlines() if line not in reference_body]
            if missing_lines:
                normalized = normalized.rstrip() + "\n" + "\n".join(missing_lines)
        return cls._accept_model_markdown(normalized, findings, citation_registry, diagnostics)

    @staticmethod
    def _canonicalize_model_markdown(markdown: str) -> str:
        normalized = str(markdown or "").strip()
        json_envelope = extract_json_object(normalized)
        if isinstance(json_envelope, dict):
            normalized = str(
                json_envelope.get("markdown")
                or json_envelope.get("report_markdown")
                or json_envelope.get("revised_markdown")
                or normalized
            ).strip()
        if normalized.startswith("```"):
            normalized = normalized.split("\n", 1)[1] if "\n" in normalized else ""
            if normalized.rstrip().endswith("```"):
                normalized = normalized.rstrip()[:-3].rstrip()
        normalized = normalized.replace("【", "[").replace("】", "]")
        aliases = {
            "Background": ["background", "背景", "研究背景", "概述", "摘要"],
            "Key Findings": ["key findings", "findings", "关键发现", "主要发现", "核心发现", "研究发现"],
            "Conclusion": ["conclusion", "总结", "结论", "建议", "行动建议"],
            "References": ["references", "reference", "参考文献", "参考来源", "来源"],
        }
        lines = []
        for raw_line in normalized.splitlines():
            heading = re.match(r"^#{1,6}\s*(.+?)\s*$", raw_line)
            bold_heading = re.match(r"^\*\*(.+?)\*\*\s*$", raw_line)
            title = (heading or bold_heading).group(1).strip() if heading or bold_heading else ""
            if title:
                comparison = title.lower()
                canonical = next(
                    (
                        section for section, values in aliases.items()
                        if any(value.lower() in comparison for value in values)
                    ),
                    None,
                )
                if canonical:
                    lines.append(f"## {canonical}")
                    continue
            lines.append(raw_line)
        normalized = "\n".join(lines).strip()
        if not normalized.startswith("# ") and any(f"## {section}" in normalized for section in aliases):
            normalized = "# Research Report\n\n" + normalized
        return normalized

    @classmethod
    def _model_output_shape(cls, value: str) -> dict:
        canonical = cls._canonicalize_model_markdown(value)
        envelope = extract_json_object(value)
        return {
            "length": len(value),
            "json_envelope": isinstance(envelope, dict),
            "canonical_title": canonical.startswith("# "),
            "canonical_sections": [
                section for section in ["Background", "Key Findings", "Conclusion", "References"]
                if f"## {section}" in canonical
            ],
            "citation_ids": sorted(set(re.findall(r"\[(C[^\]]+)\]", canonical))),
        }

    @staticmethod
    def _extract_section(markdown: str, title: str) -> str:
        heading = f"## {title}"
        start = markdown.find(heading)
        if start < 0:
            return ""
        content_start = start + len(heading)
        next_heading = markdown.find("\n## ", content_start)
        return markdown[content_start:] if next_heading < 0 else markdown[content_start:next_heading]

    @staticmethod
    def _unique_references(findings: List[Finding]) -> List[str]:
        unique_refs: List[str] = []
        for finding in findings:
            if finding.source_url not in unique_refs:
                unique_refs.append(finding.source_url)
        return unique_refs

    @staticmethod
    def _citation_ids(findings: List[Finding]) -> List[str]:
        citation_ids: List[str] = []
        for finding in findings:
            if finding.citation_id and finding.citation_id not in citation_ids:
                citation_ids.append(finding.citation_id)
        return citation_ids

    @staticmethod
    def _build_markdown(
        question: ResearchQuestion,
        sections: List[dict],
        references: List[str],
        citation_registry=None,
    ) -> str:
        lines = [f"# Research Report: {question.question}", "", f"Question: {question.question}", ""]
        for section in sections:
            lines.extend([f"## {section['title']}", "", section["content"], ""])
        lines.extend(["## References", ""])
        if citation_registry is not None:
            references_markdown = citation_registry.to_references_markdown(references)
            if references_markdown:
                lines.extend(references_markdown.splitlines())
        else:
            lines.extend([f"- {reference}" for reference in references])
        return "\n".join(lines).strip()

    @staticmethod
    def _citation_suffix(finding: Finding, use_citation_markers: bool) -> str:
        if use_citation_markers and finding.citation_id:
            return f" [{finding.citation_id}]"
        return f" ([source]({finding.source_url}))"

    @staticmethod
    def _ensure_citation_markers(markdown: str, findings: List[Finding]) -> tuple[str, int]:
        updated_markdown = markdown
        added_count = 0
        for finding in findings:
            if not finding.citation_id:
                continue
            marker = f"[{finding.citation_id}]"
            if marker in updated_markdown:
                continue
            source_link = f"([source]({finding.source_url}))"
            if source_link in updated_markdown:
                updated_markdown = updated_markdown.replace(source_link, marker, 1)
                added_count += 1
        return updated_markdown, added_count

    @staticmethod
    def _build_writer_user_message(
        question: ResearchQuestion,
        findings: List[Finding],
        references: List[str],
    ) -> str:
        finding_lines = "\n".join(
            f"- Claim: {finding.claim}\n  Evidence: {finding.evidence}\n"
            f"  Citation: [{finding.citation_id or finding.source_url}]\n  Source: {finding.source_url}"
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
