"""Browser workbench for showing how DeepResearch builds a final report."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from difflib import unified_diff
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from agents.base_agent import AgentResult
from agents.red_blue_loop import RedBlueLoopConfig
from core.config import load_llm_config_from_env
from core.llm_client import create_llm_client
from core.schema import BlueRevisionResult, Finding, RedReviewResult, ResearchPlan, ResearchReport
from orchestrator.model_workbench import MODEL_TASKS, build_model_workbench_payload
from orchestrator.research_pipeline import run_research_pipeline


DEFAULT_QUESTION = "What are the main factors that affect open-source LLM adoption in enterprises?"

TASK_ORDER = [(task.task_id, task.agent, task.title) for task in MODEL_TASKS]


def build_report_workbench_payload(
    question_text: str = DEFAULT_QUESTION,
    use_env_llm: bool = False,
    event_sink=None,
    legacy_pipeline: bool = False,
    model_workbench: bool = False,
    red_blue_rounds: int = 2,
    **pipeline_kwargs: Any,
) -> dict:
    """运行流水线，并把内部产物转换为浏览器可用的数据。

    工作台不是第二套研究实现，而是适配层：它以 JSON 友好的结构暴露每个 Agent 的
    贡献、报告差异、引用和 Trace，让审阅者检查最终报告的来源链路。
    """

    question = (question_text or DEFAULT_QUESTION).strip() or DEFAULT_QUESTION
    if model_workbench:
        return build_model_workbench_payload(
            question,
            llm_client=pipeline_kwargs.pop("llm_client", None),
            use_env_llm=use_env_llm,
            event_sink=event_sink,
            red_blue_rounds=red_blue_rounds,
        )
    review_rounds = max(2, min(3, int(red_blue_rounds)))
    llm_client = pipeline_kwargs.get("llm_client")
    collaborative_mode = "collaborative_dag"
    if llm_client is None and use_env_llm:
        llm_config = load_llm_config_from_env(load_dotenv=True)
        if llm_config.enabled and llm_config.api_key and llm_config.model:
            llm_client = create_llm_client(llm_config)
            pipeline_kwargs["llm_client"] = llm_client
            collaborative_mode = "collaborative_dag_llm"
    if llm_client is not None:
        pipeline_kwargs["require_llm"] = True
    if event_sink is not None:
        event_sink(
            "run_started",
            {
                "question": question,
                "steps": [
                    {"taskId": task_id, "agent": agent, "title": title, "status": "pending"}
                    for task_id, agent, title in TASK_ORDER
                ],
                "modelRun": {"mode": collaborative_mode, "fallbackCount": 0},
            },
        )
    pipeline_kwargs.setdefault("use_red_blue_loop", True)
    pipeline_kwargs.setdefault(
        "red_blue_loop_config",
        RedBlueLoopConfig(max_rounds=max(1, review_rounds - 1)),
    )
    pipeline_kwargs["event_sink"] = event_sink
    result = run_research_pipeline(question, **pipeline_kwargs)
    payload = summarize_pipeline_result(result)
    payload["modelRun"]["mode"] = collaborative_mode if payload["modelRun"]["llmCallCount"] else "collaborative_dag_deterministic"
    if event_sink is not None:
        event_sink("report_validated", {"citationValidation": payload["citationValidation"]})
        _emit_report_stream(event_sink, "finalReport", payload["finalReportMarkdown"])
        event_sink("report_completed", {"finalReportMarkdown": payload["finalReportMarkdown"]})
        event_sink("run_completed", {"payload": payload})
    return payload


def summarize_pipeline_result(result: dict) -> dict:
    """将带类型的流水线输出转换为稳定的前端 Payload。

    单独保留这一层投影，避免 HTTP/UI 格式化逻辑反向侵入 Agent 与编排代码。
    """
    execution = result["execution"]
    outputs = execution.outputs
    initial_report = result.get("initial_report")
    final_report = result.get("final_report") or result.get("report")
    raw_initial_markdown = _report_markdown(initial_report)
    raw_final_markdown = _report_markdown(final_report)
    public_projection = _build_public_projection(
        raw_initial_markdown,
        raw_final_markdown,
        result.get("findings", []),
        result.get("citation_validation", {}),
    )
    initial_markdown = public_projection["initialMarkdown"]
    final_markdown = public_projection["finalMarkdown"]
    diff_summary = _build_report_diff_summary(initial_markdown, final_markdown)
    report_metrics = _report_metrics(final_report, initial_report, result)
    report_metrics["Citations"] = int(public_projection["citationValidation"].get("citation_count", 0) or 0)
    report_metrics["Findings"] = len(
        [finding for finding in public_projection["findings"] if finding.get("citationStatus") == "已关联证据"]
    )
    report_metrics["Citation validation"] = (
        "passed" if public_projection["citationValidation"].get("passed") else "needs review"
    )

    step_impacts = [
        _summarize_step(task_id, agent_name, title, outputs, result, diff_summary)
        for task_id, agent_name, title in TASK_ORDER
    ]
    for step in step_impacts:
        step.pop("outputPreview", None)
    agent_results = [
        value for value in outputs.values()
        if isinstance(value, AgentResult)
    ]
    fallback_count = sum(bool(value.metadata.get("fallback_used")) for value in agent_results)
    llm_count = sum(bool(value.metadata.get("used_llm")) for value in agent_results)
    degradation_reasons = []
    if fallback_count:
        degradation_reasons.extend(
            f"{value.agent_name}: {value.metadata.get('llm_error') or value.metadata.get('search_error') or value.metadata.get('fetch_error') or '本地规则兜底'}"
            for value in agent_results
            if value.metadata.get("fallback_used")
        )
    search_metadata = outputs.get("search_task")
    if isinstance(search_metadata, AgentResult) and search_metadata.metadata.get("search_provider") in {
        "mock", "deterministic_mock"
    }:
        degradation_reasons.append("来源发现使用了模拟/确定性来源，不能作为真实研究结论。")
    if llm_count == 0:
        degradation_reasons.append("本次运行没有成功消费任何模型输出。")
    return {
        "success": bool(result.get("success")),
        "runId": result.get("run_id"),
        "question": getattr(result.get("question"), "question", str(result.get("question", ""))),
        "finalReportMarkdown": final_markdown,
        "initialReportMarkdown": initial_markdown,
        "reportDiffSummary": diff_summary,
        "reportMetrics": report_metrics,
        "modelRun": {
            "mode": "collaborative_dag_llm" if llm_count else "collaborative_dag_deterministic",
            "fallbackCount": fallback_count,
            "llmCallCount": llm_count,
        },
        "degradationReasons": degradation_reasons,
        "stepImpacts": step_impacts,
        "findings": public_projection["findings"],
        "citationValidation": public_projection["citationValidation"],
        "memoryTimeline": [_summarize_memory_item(item) for item in result.get("memory_items", [])],
        "ledgerSummary": _to_jsonable(result.get("ledger_summary", {})),
        "handoffs": [
            _summarize_handoff(handoff, result.get("ledger"))
            for handoff in result.get("handoffs", [])
        ],
        "reviewRounds": _summarize_review_rounds(result),
    }


def _build_public_projection(
    initial_markdown: str,
    final_markdown: str,
    findings: list,
    citation_validation: dict,
) -> dict:
    validation = _to_jsonable(citation_validation or {})
    sources = list(validation.get("sources", []) or [])
    mock_sources = [source for source in sources if source.get("isMock") or str(source.get("sourceUrl", "")).startswith("mock://")]
    public_sources = [source for source in sources if source not in mock_sources]
    mock_citation_ids = {source.get("citationId") for source in mock_sources if source.get("citationId")}

    public_findings = []
    for finding in findings:
        item = _summarize_finding(finding)
        is_mock = str(item.get("sourceUrl", "")).startswith("mock://")
        if is_mock:
            item.update(
                {
                    "citationId": None,
                    "evidenceId": None,
                    "sourceUrl": "",
                    "sourceTitle": "未验证的本地分析线索",
                    "evidence": "该线索没有可核验的公开原文，因此不会进入正式引用或引用校验。",
                    "citationStatus": "不可引用",
                }
            )
        else:
            item["citationStatus"] = "已关联证据" if item.get("citationId") else "待补证"
        public_findings.append(item)

    if mock_sources:
        validation["passed"] = False
        validation["sources"] = public_sources
        validation["citation_count"] = len(public_sources)
        validation["grounded_citation_count"] = len(
            [source for source in public_sources if source.get("status") == "linked"]
        )
        issues = list(validation.get("issues", []) or [])
        issues.append("检测到模拟来源；它们已从公开报告、正式引用和校验结果中移除。")
        validation["issues"] = list(dict.fromkeys(issues))
        initial_markdown = _remove_unverified_references(initial_markdown, mock_citation_ids, public_sources)
        final_markdown = _remove_unverified_references(final_markdown, mock_citation_ids, public_sources)
    else:
        validation["sources"] = public_sources

    return {
        "initialMarkdown": initial_markdown,
        "finalMarkdown": final_markdown,
        "findings": public_findings,
        "citationValidation": validation,
    }


def _remove_unverified_references(markdown: str, citation_ids: set[str], public_sources: list[dict]) -> str:
    sanitized = str(markdown or "")
    for citation_id in citation_ids:
        sanitized = re.sub(rf"\s*\[{re.escape(citation_id)}\]", "", sanitized)
    sanitized = re.sub(r"(?i)\bmock\s+evidence\b", "现有分析线索", sanitized)
    sanitized = re.sub(r"(?i)\bmock\s+research\s+report\b", "研究报告", sanitized)
    sanitized = re.sub(r"(?i)\bplaceholder\s+evidence\b", "有限材料", sanitized)

    references_match = re.search(r"(?m)^##\s+(References|参考来源|参考文献).*?$", sanitized)
    if references_match:
        sanitized = sanitized[: references_match.start()].rstrip()
    reference_lines = [
        f"[{source.get('citationId')}] {source.get('sourceTitle') or '未命名来源'} - {source.get('sourceUrl')}"
        for source in public_sources
        if source.get("citationId") and source.get("sourceUrl")
    ]
    reference_body = "\n".join(reference_lines) if reference_lines else "暂无可核验的公开参考来源。"
    return f"{sanitized}\n\n## References\n\n{reference_body}".strip()


def _emit_report_stream(event_sink, target: str, text: str) -> None:
    event_sink("report_stream_start", {"target": target})
    for index in range(0, len(text), 80):
        event_sink("report_delta", {"target": target, "delta": text[index : index + 80]})
    event_sink("report_stream_done", {"target": target, "markdown": text})


ARTIFACT_LABELS = {
    "research_brief": "研究任务书（问题拆解、子问题与检索方向）",
    "candidate_sources": "候选资料清单（标题、链接与来源摘要）",
    "approved_findings": "批准发现（可供报告使用的结论与证据）",
    "initial_report": "初始报告（Writer 完成的第一版正文）",
    "critic_review": "质量检查单（结构、论证与引用问题）",
    "red_review": "Red 审查单（具体问题、依据与修订建议）",
    "blue_revision": "Blue 修订稿（问题处理结果与新版报告）",
    "red_review_round": "本轮 Red 审查单",
    "blue_revision_round": "本轮 Blue 修订稿",
}

ACTION_LABELS = {
    "consume": "接收并用于下一步",
    "request_revision": "退回并请求修订",
    "revalidate": "修订后交回复核",
}

STATUS_LABELS = {
    "ACKNOWLEDGED": "已接收",
    "REVISION_REQUESTED": "已退回修订",
    "PUBLISHED": "已发布",
}


def _summarize_handoff(handoff: Any, ledger=None) -> dict:
    data = _to_jsonable(handoff)
    artifact_ids = list(data.get("artifact_ids", data.get("artifactIds", [])) or [])
    artifacts = []
    if ledger is not None:
        for artifact_id in artifact_ids:
            try:
                artifact = ledger.read(artifact_id)
            except (KeyError, AttributeError):
                continue
            artifacts.append(artifact)
    artifact_types = [getattr(artifact, "artifact_type", "") for artifact in artifacts]
    artifact_label = "、".join(
        ARTIFACT_LABELS.get(artifact_type, artifact_type)
        for artifact_type in artifact_types
        if artifact_type
    ) or "协作工件"
    content_summary = "；".join(
        getattr(artifact, "summary", "") for artifact in artifacts if getattr(artifact, "summary", "")
    ) or str(data.get("reason", ""))
    action = data.get("action", "")
    status = data.get("status", "")
    sender = data.get("sender_agent", data.get("senderAgent", ""))
    recipient = data.get("recipient_agent", data.get("recipientAgent", ""))
    return {
        "senderAgent": sender,
        "recipientAgent": recipient,
        "status": status,
        "statusLabel": STATUS_LABELS.get(status, status or "已交接"),
        "action": action,
        "actionLabel": ACTION_LABELS.get(action, action or "接收并用于下一步"),
        "reason": data.get("reason", ""),
        "artifactIds": artifact_ids,
        "artifactTypes": artifact_types,
        "artifactLabel": artifact_label,
        "contentSummary": content_summary,
        "displayText": f"{sender} 将“{artifact_label}”交给 {recipient}，用于{ACTION_LABELS.get(action, '下一步处理')}。",
    }


def _summarize_review_rounds(result: dict) -> list[dict]:
    current_report = result.get("initial_report")
    first_blue = result.get("blue_revision")
    rounds = [_review_round(1, result.get("red_review"), first_blue, current_report)]
    if first_blue is not None:
        current_report = getattr(first_blue, "revised_report", current_report)
    loop_result = result.get("red_blue_loop_result")
    for loop_round in getattr(loop_result, "rounds", []) or []:
        rounds.append(_review_round(
            loop_round.round_index + 1,
            loop_round.red_review,
            loop_round.blue_revision,
            current_report,
        ))
        if loop_round.blue_revision is not None:
            current_report = loop_round.blue_revision.revised_report
    return rounds


def _review_round(round_index: int, red_review: Any, blue_revision: Any, before_report: Any = None) -> dict:
    issues = []
    for issue in getattr(red_review, "issues", []) or []:
        issues.append(
            {
                "issueId": getattr(issue, "issue_id", ""),
                "severity": getattr(issue, "severity", ""),
                "message": _localize_review_text(getattr(issue, "message", "")),
                "evidence": _localize_review_text(getattr(issue, "evidence", "")),
                "suggestion": _localize_review_text(getattr(issue, "suggestion", "")),
            }
        )
    changes = [
        {"issueId": issue_id, "change": note, "reason": "回应 Red 审查意见。"}
        for issue_id, note in zip(
            getattr(blue_revision, "fixed_issue_ids", []) or [],
            [_localize_review_text(note) for note in getattr(blue_revision, "revision_notes", []) or []],
        )
    ]
    before_markdown = _report_markdown(before_report)
    after_markdown = _report_markdown(getattr(blue_revision, "revised_report", None)) or before_markdown
    content_diff = _build_report_diff_summary(before_markdown, after_markdown)
    before_excerpt = "\n".join(content_diff["removedLines"][:4]).strip()
    after_excerpt = "\n".join(content_diff["addedLines"][:4]).strip()
    if before_excerpt or after_excerpt:
        changes.append(
            {
                "issueId": "正文差异",
                "change": f"本轮新增 {content_diff['addedLineCount']} 行、删除 {content_diff['removedLineCount']} 行。",
                "reason": "把 Red 指出的问题落实到新版报告正文。",
                "before": before_excerpt,
                "after": after_excerpt,
            }
        )
    elif blue_revision is not None:
        stable_excerpt = _trim_text(after_markdown, 360)
        changes.append(
            {
                "issueId": "复核结果",
                "change": "本轮完成逐项复核，未改变已经通过证据约束的正文。",
                "reason": "没有发现需要改写的事实性内容，保留当前报告版本。",
                "before": stable_excerpt,
                "after": stable_excerpt,
            }
        )
    return {
        "round": round_index,
        "redIssues": issues,
        "redSummary": _localize_review_text(getattr(red_review, "summary", "")),
        "blueRevision": {
            "fixedIssueIds": list(getattr(blue_revision, "fixed_issue_ids", []) or []),
            "remainingIssueIds": list(getattr(blue_revision, "remaining_issue_ids", []) or []),
            "revisionNotes": [
                _localize_review_text(note)
                for note in getattr(blue_revision, "revision_notes", []) or []
            ],
            "changes": changes,
        },
        "status": "PASSED" if getattr(red_review, "passed", False) and not issues else "REVISED",
    }


def _localize_review_text(value: Any) -> str:
    text = str(value or "")
    section_labels = {
        "Background": "研究背景",
        "Key Findings": "关键发现",
        "Analysis and Discussion": "分析与讨论",
        "Limitations": "研究限制",
        "Recommendations": "行动建议",
        "Conclusion": "结论",
        "References": "参考来源",
    }
    missing = re.fullmatch(r"Report is missing the (.+) section\.", text)
    if missing:
        section = missing.group(1)
        return f"报告缺少“{section_labels.get(section, section)}”章节。"
    replacements = {
        "Report does not contain any citations.": "报告没有任何引用。",
        "No findings were available to support the report.": "没有可用于支撑报告的批准发现。",
        "Report markdown is very short.": "报告正文过短，尚未形成完整论述。",
        "Key Findings appears to summarize fewer items than the findings list.": "关键发现没有完整覆盖已批准发现。",
        "One or more Key Findings bullets are missing citation markers.": "一条或多条关键发现缺少引用标记。",
        "Critic review reported additional concerns.": "Critic 质量检查还发现了需要处理的问题。",
        "No major issues found.": "本轮未发现新的主要问题。",
        "Analysis and Discussion is too short to explain relationships or trade-offs.": "分析与讨论过短，没有解释因素之间的关系或权衡。",
        "Conclusion is too short to synthesize the research answer.": "结论过短，没有综合回答研究问题。",
        "Add a ": "补充“",
        " section to the report.": "”章节。",
        "Address the critic review concerns in the revision pass.": "逐项处理 Critic 提出的质量问题。",
    }
    if text in replacements:
        return replacements[text]
    found = re.fullmatch(r"Found (\d+) issue\(s\) in the report review\.", text)
    if found:
        return f"本轮审查发现 {found.group(1)} 个需要处理的问题。"
    addressed = re.fullmatch(r"Addressed issue ([^:]+): (.+)", text)
    if addressed:
        return f"已处理 {addressed.group(1)}：{_localize_review_text(addressed.group(2))}"
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _summarize_step(
    task_id: str,
    agent_name: str,
    title: str,
    outputs: dict,
    result: dict,
    diff_summary: dict,
) -> dict:
    agent_result = outputs.get(task_id)
    output = _unwrap_output(agent_result)
    step = {
        "taskId": task_id,
        "agent": agent_name,
        "title": title,
        "success": _agent_success(agent_result),
        "impactOnFinalReport": "",
        "metrics": {},
        "bullets": [],
        "highlights": [],
        "outputPreview": "",
    }
    if isinstance(agent_result, AgentResult):
        metadata = agent_result.metadata or {}
        step["mode"] = "llm" if metadata.get("used_llm") and not metadata.get("fallback_used") else (
            "local_fallback" if metadata.get("fallback_used") else "deterministic"
        )
        step["fallbackUsed"] = bool(metadata.get("fallback_used"))
        step["error"] = metadata.get("llm_error") or metadata.get("search_error") or metadata.get("fetch_error")

    if isinstance(output, ResearchPlan):
        step["impactOnFinalReport"] = "确定报告要回答的子问题、检索词和章节骨架，后续 Agent 都沿着这份计划工作。"
        step["metrics"] = {
            "Sub questions": len(output.sub_questions),
            "Search queries": len(output.search_queries),
            "Expected sections": len(output.expected_sections),
        }
        step["bullets"] = output.sub_questions
        step["highlights"] = [
            {"label": "检索词 Search queries", "items": output.search_queries},
            {"label": "预期章节 Expected sections", "items": output.expected_sections},
        ]
        step["outputPreview"] = output.objective
    elif task_id == "search_task":
        search_results = list(output or [])
        step["impactOnFinalReport"] = "把计划里的检索词变成候选资料来源，Reader 的证据和最终 References 都从这里开始。"
        step["metrics"] = {"Search results": len(search_results)}
        step["bullets"] = [
            f"{getattr(item, 'title', 'Untitled')} -> {getattr(item, 'url', '')}"
            for item in search_results[:8]
        ]
        step["outputPreview"] = "\n".join(getattr(item, "snippet", "") for item in search_results[:3])
    elif task_id == "reader_task":
        findings = list(output or [])
        step["impactOnFinalReport"] = "把搜索结果压成可写入报告的 claim/evidence/citation，Writer 的 Key Findings 逐条来自这些 findings。"
        step["metrics"] = {
            "Findings": len(findings),
            "Grounded citations": len([finding for finding in findings if getattr(finding, "citation_id", None)]),
        }
        step["bullets"] = [
            f"{finding.claim} [{finding.citation_id or finding.source_url}]"
            for finding in findings[:8]
            if isinstance(finding, Finding)
        ]
        step["highlights"] = [
            {
                "label": "证据样例 Evidence samples",
                "items": [getattr(finding, "evidence", "") for finding in findings[:3]],
            }
        ]
    elif task_id == "writer_task":
        report = output if isinstance(output, ResearchReport) else result.get("initial_report")
        step["impactOnFinalReport"] = "把计划和 findings 合成为第一版 markdown 报告；最终报告是在这份初稿上继续检查和修订。"
        step["metrics"] = _single_report_metrics(report)
        step["bullets"] = [section.get("title", "") for section in getattr(report, "sections", [])]
        step["outputPreview"] = _trim_text(_report_markdown(report), 1000)
    elif task_id == "critic_task":
        review = output if isinstance(output, dict) else {}
        issues = list(review.get("issues", []))
        checks = review.get("checks", {})
        step["impactOnFinalReport"] = "检查初稿是否有标题、Key Findings、References 和 citation grounding，结果会进入后续审查链路。"
        step["metrics"] = {
            "Issues": len(issues),
            "Finding count": review.get("finding_count", 0),
            "Passed": bool(review.get("passed")),
        }
        step["bullets"] = issues or [f"{key}: {value}" for key, value in checks.items()]
        step["highlights"] = [{"label": "检查项 Checks", "items": [f"{key}: {value}" for key, value in checks.items()]}]
    elif isinstance(output, RedReviewResult):
        step["impactOnFinalReport"] = "把结构、证据和引用问题转成可追踪 issue，Blue 会按 issue id 尝试修复最终报告。"
        step["metrics"] = {
            "Issues": len(output.issues),
            "Passed": output.passed,
        }
        step["bullets"] = [
            f"{issue.issue_id} [{issue.severity}] {issue.message}"
            for issue in output.issues
        ] or [output.summary]
        step["highlights"] = [
            {
                "label": "修订建议 Suggestions",
                "items": [issue.suggestion for issue in output.issues if issue.suggestion],
            }
        ]
    elif isinstance(output, BlueRevisionResult):
        final_report = output.revised_report
        step["impactOnFinalReport"] = "产出最终报告，补齐或确认章节、引用和 citation marker，并记录哪些 review issue 已修复。"
        step["metrics"] = {
            "Fixed issues": len(output.fixed_issue_ids),
            "Remaining issues": len(output.remaining_issue_ids),
            "Added lines": diff_summary["addedLineCount"],
            "Removed lines": diff_summary["removedLineCount"],
        }
        step["bullets"] = output.revision_notes or [
            "审查通过，无需结构性修改；最终报告保留已验证的草稿。"
        ]
        step["highlights"] = [
            {"label": "已修复 issue id", "items": output.fixed_issue_ids},
            {"label": "剩余 issue id", "items": output.remaining_issue_ids},
        ]
        step["outputPreview"] = _trim_text(_report_markdown(final_report), 1000)
    else:
        step["impactOnFinalReport"] = "该节点已执行，输出被保留在执行 trace 中用于复盘。"
        step["outputPreview"] = _trim_text(json.dumps(_to_jsonable(output), ensure_ascii=False, indent=2), 1000)

    return step


def _unwrap_output(value: Any) -> Any:
    if isinstance(value, AgentResult):
        return value.output
    return getattr(value, "output", value)


def _agent_success(value: Any) -> bool:
    if isinstance(value, AgentResult):
        return value.success
    return value is not None


def _report_markdown(report: Any) -> str:
    return getattr(report, "markdown", "") or ""


def _single_report_metrics(report: Any) -> dict:
    markdown = _report_markdown(report)
    return {
        "Sections": len(getattr(report, "sections", []) or []),
        "Citations": len(getattr(report, "citations", []) or []),
        "Characters": len(markdown),
        "Lines": len(markdown.splitlines()),
    }


def _report_metrics(final_report: Any, initial_report: Any, result: dict) -> dict:
    final_metrics = _single_report_metrics(final_report)
    final_metrics.update(
        {
            "Initial lines": len(_report_markdown(initial_report).splitlines()),
            "Findings": len(result.get("findings", []) or []),
            "Memory records": len(result.get("memory_items", []) or []),
            "Citation validation": "passed" if result.get("citation_validation", {}).get("passed") else "needs review",
        }
    )
    return final_metrics


def _build_report_diff_summary(initial_markdown: str, final_markdown: str) -> dict:
    diff_lines = list(
        unified_diff(
            initial_markdown.splitlines(),
            final_markdown.splitlines(),
            fromfile="initial_report",
            tofile="final_report",
            lineterm="",
        )
    )
    added = [line[1:] for line in diff_lines if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:] for line in diff_lines if line.startswith("-") and not line.startswith("---")]
    if added or removed:
        summary = f"最终报告在审查后发生变化：新增 {len(added)} 行，删除 {len(removed)} 行。"
    else:
        summary = "经过 Critic/Red/Blue（检查、审查、修订）验证后，最终报告与初稿一致。"
    return {
        "summary": summary,
        "addedLineCount": len(added),
        "removedLineCount": len(removed),
        "addedLines": added[:20],
        "removedLines": removed[:20],
        "diffPreview": diff_lines[:80],
    }


def _summarize_finding(finding: Any) -> dict:
    return {
        "claim": getattr(finding, "claim", ""),
        "evidence": getattr(finding, "evidence", ""),
        "sourceUrl": getattr(finding, "source_url", ""),
        "sourceTitle": getattr(finding, "source_title", None),
        "confidence": getattr(finding, "confidence", None),
        "citationId": getattr(finding, "citation_id", None),
        "evidenceId": getattr(finding, "evidence_id", None),
    }


def _summarize_memory_item(item: dict) -> dict:
    content = item.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(_to_jsonable(content), ensure_ascii=False)
    return {
        "taskId": item.get("task_id"),
        "sourceAgent": item.get("source_agent"),
        "itemType": item.get("item_type"),
        "summary": _trim_text(content, 240),
        "metadata": _to_jsonable(item.get("metadata", {})),
    }


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, AgentResult):
        return {
            "agentName": value.agent_name,
            "success": value.success,
            "output": _to_jsonable(value.output),
            "error": value.error,
            "metadata": _to_jsonable(value.metadata),
        }
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>DeepResearch 报告工作台</title>
  <style>
    :root {
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #1d232f;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #146c5c;
      --accent-2: #c47f23;
      --danger: #b42318;
      --danger-bg: #fff1f0;
      --code: #111827;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      letter-spacing: 0;
    }
    header {
      background: #202632;
      color: white;
      padding: 18px 28px;
      border-bottom: 4px solid var(--accent);
    }
    h1, h2, h3 { margin: 0; line-height: 1.2; }
    h1 { font-size: 22px; font-weight: 750; }
    h2 { font-size: 18px; margin-bottom: 12px; }
    h3 { font-size: 15px; margin-bottom: 8px; }
    main { max-width: 1440px; margin: 0 auto; padding: 20px 24px 32px; }
    .toolbar {
      display: grid;
      grid-template-columns: minmax(280px, 1fr) auto;
      gap: 12px;
      align-items: end;
      margin-bottom: 16px;
    }
    label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; }
    textarea {
      width: 100%;
      min-height: 72px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      font: inherit;
      background: white;
      color: var(--ink);
    }
    button {
      min-width: 132px;
      height: 42px;
      border: 0;
      border-radius: 8px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      cursor: pointer;
    }
    button:disabled { opacity: .65; cursor: progress; }
    .citation-link {
      min-width: 0;
      height: auto;
      padding: 0;
      border: 0;
      background: transparent;
      color: var(--accent);
      text-decoration: underline;
      font: inherit;
    }
    .status { color: var(--muted); font-size: 13px; min-height: 18px; margin-bottom: 14px; }
    .metrics {
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .metric, .panel, .step {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .metric { padding: 12px; }
    .metric span { display: block; color: var(--muted); font-size: 11px; margin-bottom: 5px; }
    .metric strong { font-size: 18px; }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(360px, .8fr);
      gap: 16px;
      align-items: start;
    }
    .panel { padding: 16px; margin-bottom: 16px; }
    .report {
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      line-height: 1.58;
      min-height: 360px;
    }
    .report h1 { color: #202632; font-size: 24px; margin-bottom: 12px; }
    .report h2 { border-top: 1px solid var(--line); padding-top: 14px; margin-top: 18px; }
    .report ul { padding-left: 22px; }
    .report p { margin: 8px 0; }
    .timeline { display: grid; gap: 10px; }
    .step { padding: 13px; }
    .step-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
    }
    .step small { color: var(--muted); }
    .badge {
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 11px;
      font-weight: 700;
      background: #e7f4ef;
      color: var(--accent);
      white-space: nowrap;
    }
    .badge.run { background: #e9efff; color: #2546a1; }
    .badge.warn { background: #fff4e5; color: var(--accent-2); }
    .impact { color: var(--ink); margin: 8px 0 10px; line-height: 1.45; }
    .failure {
      border: 1px solid #f4b4ae;
      background: var(--danger-bg);
      color: var(--danger);
      border-radius: 8px;
      padding: 9px 10px;
      margin: 8px 0 10px;
      font-size: 12px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .validation-summary { margin: 0; line-height: 1.5; }
    .validation-summary.ok { color: var(--accent); font-weight: 700; }
    .validation-summary.warn { color: var(--accent-2); font-weight: 700; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
    .chip {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 7px;
      color: var(--muted);
      font-size: 11px;
      background: #fafbfc;
    }
    details { border-top: 1px solid var(--line); padding-top: 10px; margin-top: 10px; }
    summary { cursor: pointer; color: var(--accent); font-weight: 700; }
    pre {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      background: var(--code);
      color: #f8fafc;
      border-radius: 8px;
      padding: 12px;
      font-size: 12px;
      line-height: 1.45;
      max-height: 460px;
      overflow: auto;
    }
    .split {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .list { margin: 8px 0 0; padding-left: 18px; color: var(--ink); }
    .list li { margin-bottom: 5px; }
    .change-box, .evidence-source {
      border-left: 3px solid var(--accent);
      background: #f7faf9;
      padding: 10px 12px;
      margin-top: 9px;
      line-height: 1.5;
    }
    .change-box pre, .evidence-source pre {
      background: #eef2f1;
      color: var(--ink);
      max-height: 220px;
      margin: 7px 0;
    }
    .error { color: var(--danger); font-weight: 700; }
    @media (max-width: 980px) {
      main { padding: 16px; }
      .toolbar, .layout, .split { grid-template-columns: 1fr; }
      .metrics { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
      button { width: 100%; }
    }
  </style>
</head>
<body>
  <header>
    <h1>DeepResearch 报告工作台</h1>
  </header>
  <main>
    <section class="toolbar">
      <div>
        <label for="question">研究问题 Research Question（要生成报告的问题）</label>
        <textarea id="question">影响企业采用开源 LLM（大语言模型）的主要因素有哪些？</textarea>
      </div>
      <button id="runButton">生成报告</button>
    </section>
    <div id="status" class="status"></div>
    <section id="metrics" class="metrics"></section>
    <section class="layout">
      <div>
        <section class="panel">
          <h2>最终研究报告 <small>Final Report</small></h2>
          <article id="finalReport" class="report"></article>
        </section>
        <section class="panel split">
          <div>
            <h2>Writer 初始草稿 <small>Initial Draft</small></h2>
            <pre id="initialDraft"></pre>
          </div>
          <div>
            <h2>Red / Blue 审查与修订流 <small>Review Stream</small></h2>
            <pre id="reportDiff"></pre>
          </div>
        </section>
        <section class="panel">
          <h2>逐轮审查结果 <small>Review Rounds</small></h2>
          <div id="reviewRounds" class="timeline"></div>
        </section>
        <section class="panel">
          <h2>Agent 协作交接 <small>Collaboration Handoffs</small></h2>
          <div id="handoffs" class="timeline"></div>
        </section>
        <section class="panel">
          <h2>结论与证据 <small>Findings & Citations</small></h2>
          <div id="findings"></div>
        </section>
      </div>
      <aside>
        <section class="panel">
          <h2>Pipeline 影响链路（每个 Agent 对报告的作用）</h2>
          <div id="steps" class="timeline"></div>
        </section>
        <section class="panel">
          <h2>引用校验与证据来源 <small>Citation Validation</small></h2>
          <div id="citationValidation"></div>
        </section>
      </aside>
    </section>
  </main>
  <script>
    const questionEl = document.getElementById("question");
    const runButton = document.getElementById("runButton");
    const statusEl = document.getElementById("status");
    let currentSteps = [];
    let currentReviewRounds = [];
    let currentHandoffs = [];
    let streamBuffers = {};
    let streamQueues = {};
    let streamRendering = {};
    let streamFinalValues = {};
    let pendingCompletedPayload = null;

    runButton.addEventListener("click", runResearch);
    statusEl.textContent = "请输入研究问题后，点击“生成报告”启动研究。";

    async function runResearch() {
      runButton.disabled = true;
      clearDashboard();
      statusEl.textContent = "正在启动模型优先 Pipeline（流水线）：每个 Agent 会先调用 LLM（大语言模型），失败时才本地兜底。";
      try {
        const response = await fetch("/api/research/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: questionEl.value })
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(payload.error || "请求失败");
        }
        await readSseStream(response, handleStreamEvent);
        await waitForStreamQueues();
      } catch (error) {
        statusEl.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      } finally {
        runButton.disabled = false;
      }
    }

    function clearDashboard() {
      currentSteps = [];
      currentReviewRounds = [];
      currentHandoffs = [];
      streamBuffers = {};
      streamQueues = {};
      streamRendering = {};
      streamFinalValues = {};
      pendingCompletedPayload = null;
      document.getElementById("metrics").innerHTML = "";
      document.getElementById("finalReport").innerHTML = "<p>等待模型生成最终报告...</p>";
      document.getElementById("initialDraft").textContent = "";
      document.getElementById("reportDiff").textContent = "";
      document.getElementById("steps").innerHTML = "";
      document.getElementById("reviewRounds").innerHTML = "";
      document.getElementById("handoffs").innerHTML = "";
      document.getElementById("citationValidation").innerHTML = "";
      document.getElementById("findings").innerHTML = "";
    }

    async function readSseStream(response, onEvent) {
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const parts = buffer.split("\\n\\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const parsed = parseSseEvent(part);
          if (parsed) onEvent(parsed.event, parsed.data);
        }
        if (done) break;
      }
      if (buffer.trim()) {
        const parsed = parseSseEvent(buffer);
        if (parsed) onEvent(parsed.event, parsed.data);
      }
    }

    function parseSseEvent(raw) {
      let event = "message";
      const dataLines = [];
      for (const line of raw.split(/\\r?\\n/)) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      if (!dataLines.length) return null;
      return { event, data: JSON.parse(dataLines.join("\\n")) };
    }

    function handleStreamEvent(event, data) {
      if (event === "run_started") {
        currentSteps = data.steps || [];
        renderSteps(currentSteps);
        statusEl.textContent = `已启动：${modeLabel(data.modelRun?.mode)}，正在调用 PlannerAgent（规划 Agent）...`;
        return;
      }
      if (event === "agent_started" || event === "agent_done" || event === "agent_fallback" || event === "agent_completed") {
        upsertStep(data.step);
        const label = data.step?.agent || "Agent";
        const state = statusLabel(data.step?.status || "");
        statusEl.textContent = `${label}：${state}`;
        return;
      }
      if (event === "agent_progress") {
        statusEl.textContent = data.message || "Agent 正在处理。";
        return;
      }
      if (event === "handoff_updated") {
        upsertHandoff(data.handoff);
        const handoff = data.handoff || {};
        statusEl.textContent = `${handoff.senderAgent || "上游 Agent"} 已将成果交给 ${handoff.recipientAgent || "下游 Agent"}`;
        return;
      }
      if (event === "review_round_started") {
        statusEl.textContent = `正在进行第 ${data.round} / ${data.maxRounds} 轮 Red/Blue 审查...`;
        return;
      }
      if (event === "review_round_completed") {
        upsertReviewRound(data.review);
        return;
      }
      if (event === "report_stream_start") {
        streamBuffers[data.target] = "";
        streamQueues[data.target] = [];
        streamFinalValues[data.target] = null;
        if (data.target === "reviewTranscript") {
          enqueueStreamDelta(data.target, "\\n--- 审查流开始 ---\\n");
        } else {
          updateStreamTarget(data.target, "");
        }
        return;
      }
      if (event === "report_delta") {
        enqueueStreamDelta(data.target, data.delta || "");
        return;
      }
      if (event === "report_stream_done") {
        const value = data.markdown || data.text || streamBuffers[data.target] || "";
        streamFinalValues[data.target] = value;
        if (data.target === "reviewTranscript") {
          enqueueStreamDelta(data.target, "\\n--- 审查流结束 ---\\n");
        }
        flushCompletedPayloadWhenReady();
        return;
      }
      if (event === "run_completed") {
        pendingCompletedPayload = data.payload;
        flushCompletedPayloadWhenReady();
        return;
      }
      if (event === "run_error") {
        statusEl.innerHTML = `<span class="error">${escapeHtml(data.error || "运行失败")}</span>`;
      }
    }

    function upsertStep(step) {
      if (!step) return;
      const index = currentSteps.findIndex(item => item.taskId === step.taskId);
      if (index >= 0) currentSteps[index] = step;
      else currentSteps.push(step);
      renderSteps(currentSteps);
    }

    function updateStreamTarget(target, value) {
      if (target === "initialDraft") {
        document.getElementById("initialDraft").textContent = localizeMarkdownForDisplay(value);
      } else if (target === "finalReport") {
        document.getElementById("finalReport").innerHTML = renderMarkdown(value);
      }
    }

    function enqueueStreamDelta(target, delta) {
      if (!delta) return;
      if (!streamQueues[target]) streamQueues[target] = [];
      streamQueues[target].push(delta);
      if (streamRendering[target]) return;
      streamRendering[target] = true;
      requestAnimationFrame(() => drainStreamQueue(target));
    }

    function drainStreamQueue(target) {
      const queue = streamQueues[target] || [];
      if (!queue.length) {
        streamRendering[target] = false;
        const finalValue = streamFinalValues[target];
        if (finalValue && target !== "reviewTranscript") {
          streamBuffers[target] = finalValue;
          updateStreamTarget(target, finalValue);
        }
        flushCompletedPayloadWhenReady();
        return;
      }
      const value = queue.shift();
      const piece = value.slice(0, 24);
      const remainder = value.slice(24);
      if (remainder) queue.unshift(remainder);
      streamBuffers[target] = (streamBuffers[target] || "") + piece;
      if (target === "reviewTranscript") {
        appendReviewTranscript(piece);
      } else {
        updateStreamTarget(target, streamBuffers[target]);
      }
      window.setTimeout(() => requestAnimationFrame(() => drainStreamQueue(target)), 8);
    }

    function streamsAreBusy() {
      return Object.values(streamRendering).some(Boolean)
        || Object.values(streamQueues).some(queue => (queue || []).length > 0);
    }

    function waitForStreamQueues() {
      return new Promise(resolve => {
        const check = () => streamsAreBusy() ? window.setTimeout(check, 20) : resolve();
        check();
      });
    }

    function flushCompletedPayloadWhenReady() {
      if (!pendingCompletedPayload || streamsAreBusy()) return;
      const payload = pendingCompletedPayload;
      pendingCompletedPayload = null;
      renderPayload(payload);
      const fallbackCount = payload?.modelRun?.fallbackCount || 0;
      const degradationReasons = payload?.degradationReasons || [];
      if (fallbackCount || degradationReasons.length) {
        const firstError = firstStepError(payload?.stepImpacts || []);
        statusEl.textContent = firstError
          ? `报告已生成，但需要复查。首个问题：${firstError}`
          : `报告已生成，但需要复查：${degradationReasons[0] || "部分步骤未使用真实模型或来源"}`;
      } else {
        statusEl.textContent = "报告已生成：全部 Agent 均完成模型调用。";
      }
    }

    function appendReviewTranscript(value) {
      const element = document.getElementById("reportDiff");
      element.textContent += value;
      element.scrollTop = element.scrollHeight;
    }

    function renderPayload(payload) {
      renderMetrics(payload.reportMetrics || {});
      document.getElementById("finalReport").innerHTML = renderMarkdown(payload.finalReportMarkdown || "");
      document.getElementById("initialDraft").textContent = localizeMarkdownForDisplay(payload.initialReportMarkdown || "");
      document.getElementById("reportDiff").textContent = buildReviewTranscript(payload);
      currentSteps = payload.stepImpacts || [];
      renderSteps(currentSteps);
      currentReviewRounds = payload.reviewRounds || [];
      renderReviewRounds(currentReviewRounds);
      currentHandoffs = payload.handoffs || [];
      renderHandoffs(currentHandoffs);
      renderCitationValidation(payload.citationValidation || {});
      document.getElementById("findings").innerHTML = renderFindings(payload.findings || []);
    }

    function renderSteps(steps) {
      document.getElementById("steps").innerHTML = (steps || []).map(renderStep).join("");
    }

    function upsertReviewRound(review) {
      if (!review) return;
      const index = currentReviewRounds.findIndex(item => item.round === review.round);
      if (index >= 0) currentReviewRounds[index] = review;
      else currentReviewRounds.push(review);
      renderReviewRounds(currentReviewRounds);
    }

    function upsertHandoff(handoff) {
      if (!handoff) return;
      const key = `${handoff.senderAgent || ""}-${handoff.recipientAgent || ""}-${handoff.reason || ""}`;
      const index = currentHandoffs.findIndex(item => `${item.senderAgent || ""}-${item.recipientAgent || ""}-${item.reason || ""}` === key);
      if (index >= 0) currentHandoffs[index] = handoff;
      else currentHandoffs.push(handoff);
      renderHandoffs(currentHandoffs);
    }

    function renderHandoffs(handoffs) {
      if (!handoffs.length) {
        document.getElementById("handoffs").innerHTML = "<p>等待 Agent 交接工件。</p>";
        return;
      }
      document.getElementById("handoffs").innerHTML = handoffs.map(handoff => `
        <article class="step">
          <div class="step-head">
            <h3>${escapeHtml(agentLabel(handoff.senderAgent))} → ${escapeHtml(agentLabel(handoff.recipientAgent))}</h3>
            <span class="badge ${handoff.status === "REVISION_REQUESTED" ? "warn" : ""}">${escapeHtml(handoff.statusLabel || handoffStatusLabel(handoff.status))}</span>
          </div>
          <p class="impact"><strong>交接内容：</strong>${escapeHtml(handoff.artifactLabel || "协作工件")}</p>
          <p>${escapeHtml(handoff.contentSummary || handoff.reason || handoff.summary || "已完成成果交接。")}</p>
          <small><strong>接收方动作：</strong>${escapeHtml(handoff.actionLabel || handoffActionLabel(handoff.action))}</small>
        </article>
      `).join("");
    }

    function renderReviewRounds(rounds) {
      if (!rounds.length) {
        document.getElementById("reviewRounds").innerHTML = "<p>等待 Red/Blue 审查开始。</p>";
        return;
      }
      document.getElementById("reviewRounds").innerHTML = rounds.map(review => {
        const issues = review.redIssues || [];
        const revision = review.blueRevision || {};
        const notes = revision.revisionNotes || [];
        const fixed = revision.fixedIssueIds || [];
        const remaining = revision.remainingIssueIds || [];
        const issueList = issues.length
          ? `<ul class="list">${issues.map(item => `<li><strong>${escapeHtml(item.issueId || "问题")}</strong>：${escapeHtml(item.message || "")}<br><small>依据：${escapeHtml(item.evidence || "未提供具体依据")}<br>建议：${escapeHtml(item.suggestion || "未提供具体建议")}</small></li>`).join("")}</ul>`
          : "<p>Red 未发现新的阻断问题。</p>";
        const changes = revision.changes || [];
        const revisionList = [
          ...notes,
          ...fixed.filter(item => !changes.some(change => change.issueId === item)).map(item => `已修复：${item}`),
          ...remaining.map(item => `仍待复核：${item}`)
        ]
          .map(item => `<li>${escapeHtml(item)}</li>`).join("");
        const changeList = changes.map(item => `
          <div class="change-box">
            <strong>${escapeHtml(item.issueId || "正文修订")}</strong>：${escapeHtml(item.change || "未提供具体修改")}
            <p><small>修改原因：${escapeHtml(item.reason || "回应审查意见")}</small></p>
            ${item.before ? `<p><strong>修改前：</strong></p><pre>${escapeHtml(item.before)}</pre>` : ""}
            ${item.after ? `<p><strong>修改后：</strong></p><pre>${escapeHtml(item.after)}</pre>` : ""}
          </div>
        `).join("");
        return `
          <article class="step">
            <div class="step-head">
              <h3>第 ${escapeHtml(review.round)} 轮审查</h3>
              <span class="badge ${review.status === "PASSED" ? "" : "warn"}">${escapeHtml(review.status || "REVIEWED")}</span>
            </div>
            <p class="impact">${escapeHtml(review.redSummary || "Red 提交审查结论，Blue 据此完成受控修订。")}</p>
            <details open><summary>Red 发现的问题</summary>${issueList}</details>
            ${(revisionList || changeList) ? `<details open><summary>Blue 具体修改</summary>${revisionList ? `<ul class="list">${revisionList}</ul>` : ""}${changeList}</details>` : ""}
          </article>
        `;
      }).join("");
    }

    function firstStepError(steps) {
      const failed = steps.find(step => step && step.error);
      return failed ? failed.error : "";
    }

    function renderMetrics(metrics) {
      document.getElementById("metrics").innerHTML = Object.entries(metrics).map(([key, value]) => `
        <div class="metric"><span>${escapeHtml(metricLabel(key))}</span><strong>${escapeHtml(metricValue(key, value))}</strong></div>
      `).join("");
    }

    function renderCitationValidation(validation) {
      const issues = Array.isArray(validation.issues) ? validation.issues : [];
      const passed = validation.passed === true;
      const summary = passed
        ? "引用校验已通过。报告中的引用标记与可用来源一致。"
        : "引用仍需人工复核。最终报告已保留可追踪的校验状态。";
      const issueList = issues.length
        ? `<ul class="list">${issues.map(issue => `<li>${escapeHtml(String(issue))}</li>`).join("")}</ul>`
        : "";
      const sources = Array.isArray(validation.sources) ? validation.sources : [];
      const sourceList = sources.length
        ? `<details open><summary>已校验的证据来源（${sources.length} 条）</summary>${sources.map(source => {
            const label = `${source.citationId || "Citation"}：${source.sourceTitle || "未命名来源"}`;
            const link = externalLink(source.sourceUrl, source.sourceUrl || "无公开链接");
            const status = source.status === "linked" ? "已关联" : "待复核";
            const location = source.startChar == null ? "未记录位置" : `字符 ${source.startChar}–${source.endChar}`;
            return `<article id="citation-${escapeHtml(source.citationId || "unknown")}" class="evidence-source"><strong>${escapeHtml(label)}</strong>（${escapeHtml(status)}）<br>
              <small>原文位置：${escapeHtml(location)} · Evidence ID：${escapeHtml(source.evidenceId || "无")}</small>
              <pre>${escapeHtml(source.evidenceText || source.quote || "未提供证据切片")}</pre>
              ${link}</article>`;
          }).join("")}</details>`
        : "<p>本次报告没有可显示的证据来源。</p>";
      document.getElementById("citationValidation").innerHTML = `
        <p class="validation-summary ${passed ? "ok" : "warn"}">${escapeHtml(summary)}</p>
        ${issueList}
        ${sourceList}
      `;
    }

    function buildReviewTranscript(payload) {
      const summary = [
        payload.reportDiffSummary?.summary || "",
        ...(payload.reportDiffSummary?.diffPreview || [])
      ].filter(Boolean);
      const rounds = (payload.reviewRounds || []).flatMap(review => {
        const red = [`第 ${review.round} 轮 Red Review`, review.redSummary || ""];
        for (const issue of review.redIssues || []) {
          red.push(`- ${issue.issueId || "问题"}：${issue.message || ""}`);
          red.push(`  依据：${issue.evidence || "未提供具体依据"}`);
          red.push(`  建议：${issue.suggestion || "未提供具体建议"}`);
        }
        const blue = [`第 ${review.round} 轮 Blue Revision`];
        for (const change of review.blueRevision?.changes || []) {
          blue.push(`- ${change.issueId || "未关联问题"}：${change.change || "未提供具体修改"}`);
          blue.push(`  原因：${change.reason || "回应审查意见"}`);
          if (change.before) blue.push(`  修改前：${change.before}`);
          if (change.after) blue.push(`  修改后：${change.after}`);
        }
        return [...red, "", ...blue, ""];
      });
      return [...summary, "", ...rounds].join("\\n").trim();
    }

    function externalLink(url, label) {
      try {
        const parsed = new URL(url);
        if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error("unsupported protocol");
        return `<a href="${escapeHtml(parsed.href)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
      } catch (_) {
        return `<small>${escapeHtml(label)}</small>`;
      }
    }

    function renderStep(step) {
      const status = step.status || (step.success ? "done" : "pending");
      const badgeClass = status === "running" ? "run" : (status === "fallback" || !step.success ? "warn" : "");
      const modeChip = step.mode && step.mode !== "pending"
        ? `<span class="chip">执行模式 Mode: ${escapeHtml(modeLabel(step.mode))}</span>`
        : "";
      const metricChips = Object.entries(step.metrics || {}).map(([key, value]) =>
        `<span class="chip">${escapeHtml(metricLabel(key))}: ${escapeHtml(metricValue(key, value))}</span>`
      ).join("");
      const bullets = (step.bullets || []).slice(0, 6).map(item => `<li>${escapeHtml(item)}</li>`).join("");
      const highlights = (step.highlights || []).filter(group => (group.items || []).length).map(group => `
        <details>
          <summary>${escapeHtml(group.label)}</summary>
          <ul class="list">${group.items.map(item => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>
        </details>
      `).join("");
      const errorBox = step.error
        ? `<div class="failure"><strong>失败原因 Failure reason:</strong> ${escapeHtml(step.error)}</div>`
        : "";
      return `
        <article class="step">
          <div class="step-head">
            <div>
              <h3>${escapeHtml(step.title)}</h3>
              <small>${escapeHtml(step.taskId)} / ${escapeHtml(step.agent)}</small>
            </div>
            <span class="badge ${badgeClass}">${escapeHtml(statusLabel(status))}</span>
          </div>
          <p class="impact">${escapeHtml(step.impactOnFinalReport)}</p>
          ${errorBox}
          <div class="chips">${modeChip}${metricChips}</div>
          ${bullets ? `<ul class="list">${bullets}</ul>` : ""}
          ${highlights}
        </article>
      `;
    }

    function statusLabel(status) {
      const labels = {
        pending: "等待 PENDING",
        running: "运行中 RUNNING",
        done: "完成 DONE",
        fallback: "本地兜底 FALLBACK",
        failed: "失败 FAILED"
      };
      return labels[status] || status;
    }

    function modeLabel(mode) {
      const labels = {
        llm: "LLM 模型调用",
        mock_llm: "Mock LLM（测试模型）",
        local_fallback: "Local fallback（本地兜底）",
        pending: "等待"
      };
      return labels[mode] || mode || "";
    }

    function renderFindings(findings) {
      if (!findings.length) return "<p>暂无 Findings（证据结论）。</p>";
      return findings.map((finding, index) => `
        <article class="step">
          <div class="step-head">
            <h3>结论 ${index + 1}</h3>
            <span class="badge ${finding.citationId ? "" : "warn"}">${escapeHtml(finding.citationId || finding.citationStatus || "待补证")}</span>
          </div>
          <p><strong>结论：</strong>${escapeHtml(finding.claim || "")}</p>
          <p><strong>原文证据：</strong>${escapeHtml(finding.evidence || "")}</p>
          <small>${escapeHtml(finding.sourceTitle || "")}${finding.sourceUrl ? ` · ${escapeHtml(finding.sourceUrl)}` : ""}</small>
        </article>
      `).join("");
    }

    function agentLabel(agent) {
      const labels = {
        PlannerAgent: "Planner（研究规划）",
        SearcherAgent: "Searcher（资料发现）",
        ReaderAgent: "Reader（正文取证）",
        WriterAgent: "Writer（报告撰写）",
        CriticAgent: "Critic（质量检查）",
        RedAgent: "Red（质疑审查）",
        BlueAgent: "Blue（修订回应）"
      };
      return labels[agent] || agent || "Agent";
    }

    function handoffActionLabel(action) {
      return ({ consume: "接收并用于下一步", request_revision: "退回并请求修订", revalidate: "修订后交回复核" })[action]
        || action || "接收并用于下一步";
    }

    function handoffStatusLabel(status) {
      return ({ ACKNOWLEDGED: "已接收", REVISION_REQUESTED: "已退回修订", PUBLISHED: "已发布" })[status]
        || status || "已交接";
    }

    function metricLabel(key) {
      const labels = {
        "Sections": "章节 Sections",
        "Citations": "引用 Citations",
        "Characters": "字符数 Characters",
        "Lines": "行数 Lines",
        "Initial lines": "初稿行数 Initial lines",
        "Findings": "证据结论 Findings",
        "Memory records": "记忆记录 Memory records",
        "Citation validation": "引用校验 Citation validation",
        "Sub questions": "子问题 Sub questions",
        "Search queries": "检索词 Search queries",
        "Expected sections": "预期章节 Expected sections",
        "Search results": "搜索结果 Search results",
        "Grounded citations": "有依据的引用 Grounded citations",
        "Issues": "问题数 Issues",
        "Finding count": "证据结论数 Finding count",
        "Passed": "是否通过 Passed",
        "Fixed issues": "已修复问题 Fixed issues",
        "Remaining issues": "剩余问题 Remaining issues",
        "Added lines": "新增行 Added lines",
        "Removed lines": "删除行 Removed lines",
        "Model calls": "模型调用 Model calls",
        "Fallbacks": "本地兜底 Fallbacks",
        "Report versions": "报告版本 Report versions",
        "Review rounds": "审查轮次 Review rounds",
        "Revision rounds": "修订轮次 Revision rounds"
      };
      return labels[key] || key;
    }

    function metricValue(key, value) {
      if (key === "Citation validation") {
        return value === "passed" ? "通过 passed" : "需复查 needs review";
      }
      if (typeof value === "boolean") {
        return value ? "是 true" : "否 false";
      }
      return String(value);
    }

    function renderMarkdown(markdown) {
      markdown = localizeMarkdownForDisplay(markdown);
      const lines = markdown.split(/\\r?\\n/);
      let html = "";
      let inList = false;
      for (const rawLine of lines) {
        const line = rawLine.trimEnd();
        if (!line.trim()) {
          if (inList) { html += "</ul>"; inList = false; }
          continue;
        }
        if (line.startsWith("# ")) {
          if (inList) { html += "</ul>"; inList = false; }
          html += `<h1>${renderInlineMarkdown(line.slice(2))}</h1>`;
        } else if (line.startsWith("## ")) {
          if (inList) { html += "</ul>"; inList = false; }
          html += `<h2>${renderInlineMarkdown(line.slice(3))}</h2>`;
        } else if (line.startsWith("- ")) {
          if (!inList) { html += "<ul>"; inList = true; }
          html += `<li>${renderInlineMarkdown(line.slice(2))}</li>`;
        } else {
          if (inList) { html += "</ul>"; inList = false; }
          html += `<p>${renderInlineMarkdown(line)}</p>`;
        }
      }
      if (inList) html += "</ul>";
      return html;
    }

    function localizeMarkdownForDisplay(markdown) {
      return String(markdown || "")
        .replace(/^# Research Report:/gm, "# 研究报告：")
        .replace(/^Question:/gm, "研究问题：")
        .replace(/^## Background$/gm, "## 研究背景")
        .replace(/^## Key Findings$/gm, "## 关键发现")
        .replace(/^## Analysis and Discussion$/gm, "## 分析与讨论")
        .replace(/^## Limitations$/gm, "## 研究限制")
        .replace(/^## Recommendations$/gm, "## 行动建议")
        .replace(/^## Conclusion$/gm, "## 结论")
        .replace(/^## References$/gm, "## 参考来源");
    }

    function renderInlineMarkdown(value) {
      return escapeHtml(value).replace(/\\[(C\\d+)\\]/g, (_, citationId) =>
        `<button class="citation-link" title="查看 ${citationId} 的原文证据" onclick="scrollToCitation('${citationId}')">[${citationId}]</button>`
      );
    }

    function scrollToCitation(citationId) {
      document.getElementById(`citation-${citationId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }
  </script>
</body>
</html>
"""


class ReportWorkbenchHandler(BaseHTTPRequestHandler):
    """本地报告审阅工作台的最小 HTTP 边界。

    ``GET /`` 返回静态浏览器页面；POST 请求运行研究任务，并返回单个 JSON Payload
    或连续的流水线事件流。
    """
    server_version = "DeepResearchWorkbench/1.0"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._write_html(INDEX_HTML)
            return
        if path == "/api/health":
            self._write_json({"ok": True, "service": "deep-research-report-workbench"})
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/research", "/api/research/stream"}:
            self.send_error(404, "Not found")
            return
        try:
            body = self._read_json_body()
            if path == "/api/research/stream":
                self._write_streaming_payload(body.get("question", DEFAULT_QUESTION))
                return
            payload = build_report_workbench_payload(
                body.get("question", DEFAULT_QUESTION),
                use_env_llm=True,
            )
            self._write_json(payload)
        except Exception as exc:  # pragma: no cover - exercised manually through the browser
            self._write_json({"ok": False, "error": str(exc)}, status=500)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw_body = self.rfile.read(length).decode("utf-8")
        return json.loads(raw_body or "{}")

    def _write_html(self, body: str, status: int = 200) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _write_json(self, body: dict, status: int = 200) -> None:
        encoded = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _write_streaming_payload(self, question: str) -> None:
        """为耗时任务在最终 Payload 前持续推送状态事件。

        event sink 被传入流水线适配层，因此 UI 观察到的是实际执行里程碑，而不是伪造进度条。
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Content-Encoding", "identity")
        # 浏览器前端在读取到流结束后才会恢复“生成报告”按钮。这个端点不是
        # 永久订阅，而是一轮任务对应一条有限事件流，因此完成后必须关闭连接。
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b": stream-connected\n\n")
        self.wfile.flush()

        def emit(event_type: str, data: dict) -> None:
            encoded = (
                f"event: {event_type}\n"
                f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            ).encode("utf-8")
            self.wfile.write(encoded)
            self.wfile.flush()

        try:
            build_report_workbench_payload(
                question,
                use_env_llm=True,
                event_sink=emit,
            )
        except Exception as exc:  # pragma: no cover - exercised manually through the browser
            emit("run_error", {"error": str(exc)})
        finally:
            # 显式结束 HTTP 响应，令 Fetch 的 reader.read() 返回 done=true，
            # 前端 runResearch() 的 finally 才能重新启用按钮。
            self.close_connection = True

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_server(host: str = "127.0.0.1", port: int | None = None) -> None:
    selected_port = port or int(os.environ.get("DEEP_RESEARCH_WEB_PORT", "18181"))
    server = ThreadingHTTPServer((host, selected_port), ReportWorkbenchHandler)
    print(f"DeepResearch Report Workbench started at http://{host}:{selected_port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
