"""Model-first workbench runner for the browser research demo."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
import json
import re
import time
import uuid
from typing import Any, Callable

from core.config import load_llm_config_from_env
from core.llm_client import BaseLLMClient, LLMMessage, MockLLMClient, create_llm_client


EventSink = Callable[[str, dict], None]


@dataclass(frozen=True)
class WorkbenchTask:
    task_id: str
    agent: str
    title: str
    impact: str


@dataclass
class StepCall:
    content: str
    model: str | None = None
    usage: dict | None = None
    fallback_used: bool = False
    error: str | None = None
    duration_ms: int = 0
    native_stream_used: bool = False
    visible_streamed: bool = False


MODEL_TASKS = [
    WorkbenchTask(
        "planner_task",
        "PlannerAgent",
        "研究计划 Research Plan（拆解问题和章节）",
        "用模型把问题拆成目标、子问题、检索词和报告结构，后续 Agent 都按这份计划推进。",
    ),
    WorkbenchTask(
        "search_task",
        "SearcherAgent",
        "资料搜索 Search Brief（生成候选资料方向）",
        "用模型根据计划列出候选资料、检索方向和为什么这些来源值得看，Reader 会基于它提炼证据。",
    ),
    WorkbenchTask(
        "reader_task",
        "ReaderAgent",
        "证据结论 Findings（提炼可写入报告的事实）",
        "用模型把候选资料压缩成 claim/evidence/citation，Writer 的正文和引用都从这里来。",
    ),
    WorkbenchTask(
        "writer_task",
        "WriterAgent",
        "初始报告 Initial Draft（第一版中文报告）",
        "用模型把计划和 findings 合成为第一版中文 Markdown 报告，后续 Critic/Red/Blue 都在它上面修改。",
    ),
    WorkbenchTask(
        "critic_task",
        "CriticAgent",
        "质量检查 Quality Checks（结构、引用、完整性）",
        "用模型检查初稿是否回答问题、是否有引用、是否结构完整，并把风险交给 RedAgent 深挖。",
    ),
    WorkbenchTask(
        "red_review_task",
        "RedAgent",
        "红队审查 Red Review（找问题和反例）",
        "用模型扮演挑错方，持续指出逻辑、证据、遗漏和表达问题，生成可追踪的修改项。",
    ),
    WorkbenchTask(
        "blue_revision_task",
        "BlueAgent",
        "蓝队修订 Blue Revision（逐轮改写终稿）",
        "用模型根据红队问题改写报告，记录修复项，并产出最终报告（中文 Markdown）。",
    ),
]


class ModelWorkbenchRunner:
    def __init__(
        self,
        question: str,
        llm_client: BaseLLMClient,
        event_sink: EventSink | None = None,
        red_blue_rounds: int = 2,
    ) -> None:
        self.question = question
        self.llm_client = llm_client
        self.event_sink = event_sink
        self.red_blue_rounds = max(2, min(3, int(red_blue_rounds)))
        self.run_id = f"workbench-{uuid.uuid4().hex[:12]}"
        self.steps = {task.task_id: self._initial_step(task) for task in MODEL_TASKS}
        self.execution_trace: list[dict] = []
        self.report_versions: list[dict] = []
        self.model_call_count = 0
        self.fallback_count = 0
        self.initial_report_markdown = ""
        self.final_report_markdown = ""
        self.findings: list[dict] = []
        self.citation_validation: dict = {"passed": False, "issues": ["run_not_started"]}
        self.review_rounds: list[dict] = []
        # The provider client is request/response today. Small chunks keep SSE visibly alive
        # without exposing its JSON contract to the browser.
        self._stream_delay_seconds = 0.012 if event_sink is not None else 0.0

    def run(self) -> dict:
        self._emit(
            "run_started",
            {
                "runId": self.run_id,
                "question": self.question,
                "steps": self._step_list(),
                "modelRun": self._model_run_metadata(),
            },
        )

        plan = self._run_planner()
        search_results = self._run_searcher(plan)
        self.findings = self._run_reader(plan, search_results)
        self.initial_report_markdown = self._run_writer(plan, self.findings)
        self.report_versions.append(
            {"label": "初稿 Initial Draft", "round": 0, "markdown": self.initial_report_markdown}
        )

        critic_review = self._run_critic(self.initial_report_markdown, self.findings)
        current_report = self.initial_report_markdown
        red_review: dict = {"passed": True, "issues": [], "summary": "未发现需要修订的问题。"}

        for round_index in range(1, self.red_blue_rounds + 1):
            self._emit("review_round_started", {"round": round_index, "maxRounds": self.red_blue_rounds})
            red_review = self._run_red(round_index, current_report, critic_review)
            current_report, blue_revision = self._run_blue(
                round_index,
                current_report,
                red_review,
                self.findings,
            )
            self.report_versions.append(
                {"label": f"第 {round_index} 轮修订", "round": round_index, "markdown": current_report}
            )
            self.review_rounds.append(
                {
                    "round": round_index,
                    "redIssues": list(red_review.get("issues", [])),
                    "redSummary": red_review.get("summary", ""),
                    "blueRevision": blue_revision,
                    "status": "PASSED" if red_review.get("passed") and not red_review.get("issues") else "REVISED",
                }
            )
            self._emit("review_round_completed", {"round": round_index, "review": self.review_rounds[-1]})
            if round_index >= 2 and red_review.get("passed") and not red_review.get("issues"):
                break

        self.final_report_markdown = self._ensure_chinese_report_shape(current_report)
        self.citation_validation = self._validate_citations(self.final_report_markdown, self.findings)
        payload = self._build_payload(critic_review, red_review)
        self._emit("report_validated", {"citationValidation": self.citation_validation})
        self._emit_markdown_stream("finalReport", self.final_report_markdown)
        self._emit("report_completed", {"finalReportMarkdown": self.final_report_markdown})
        self._emit("run_completed", {"payload": payload})
        return payload

    def _run_planner(self) -> dict:
        task = self._task("planner_task")
        call = self._call_model(
            task,
            [
                LLMMessage(role="system", content=self._system_prompt(task.agent)),
                LLMMessage(
                    role="user",
                    content=(
                        "请为下面的研究问题制定中文研究计划。只返回 JSON，字段为 "
                        "objective, subQuestions, searchQueries, expectedSections。"
                        "subQuestions 最多 4 条，searchQueries 最多 5 条，expectedSections 最多 5 条。\n\n"
                        f"研究问题：{self.question}"
                    ),
                ),
            ],
            fallback_factory=lambda: json.dumps(self._fallback_plan(), ensure_ascii=False),
        )
        parsed = _extract_json_object(call.content) or {}
        plan = {
            "objective": str(parsed.get("objective") or f"回答研究问题：{self.question}"),
            "subQuestions": _string_list(parsed.get("subQuestions")) or [
                f"{self.question} 的背景和边界是什么？",
                f"{self.question} 的关键影响因素有哪些？",
                f"{self.question} 对团队落地有什么建议？",
            ],
            "searchQueries": _string_list(parsed.get("searchQueries")) or [
                self.question,
                f"{self.question} 实践 案例 风险",
                f"{self.question} 评估 指标",
            ],
            "expectedSections": _string_list(parsed.get("expectedSections")) or [
                "摘要",
                "Key Findings（关键发现）",
                "深入分析",
                "行动建议",
                "References（参考来源）",
            ],
        }
        self._finish_step(
            task,
            call,
            metrics={
                "Sub questions": len(plan["subQuestions"]),
                "Search queries": len(plan["searchQueries"]),
                "Expected sections": len(plan["expectedSections"]),
            },
            bullets=plan["subQuestions"],
            highlights=[
                {"label": "检索词 Search queries", "items": plan["searchQueries"]},
                {"label": "预期章节 Expected sections", "items": plan["expectedSections"]},
            ],
        )
        return plan

    def _run_searcher(self, plan: dict) -> list[dict]:
        task = self._task("search_task")
        call = self._call_model(
            task,
            [
                LLMMessage(role="system", content=self._system_prompt(task.agent)),
                LLMMessage(
                    role="user",
                    content=(
                        "根据研究计划生成 3 到 4 个候选资料方向。只返回 JSON，字段为 "
                        "results，数组元素包含 title, url, snippet, whyUseful。不要编造不存在的精确论文编号；"
                        "如果无法确定具体页面，使用机构或项目主页。\n\n"
                        f"研究问题：{self.question}\n研究计划：{json.dumps(plan, ensure_ascii=False)}"
                    ),
                ),
            ],
            fallback_factory=lambda: json.dumps(self._fallback_search_results(plan), ensure_ascii=False),
        )
        parsed = _extract_json_object(call.content) or {}
        results = _dict_list(parsed.get("results")) or self._search_results_from_text(call.content)
        self._finish_step(
            task,
            call,
            metrics={"Search results": len(results), "Model calls": 0 if call.fallback_used else 1},
            bullets=[f"{item.get('title', '未命名来源')} -> {item.get('url', '')}" for item in results[:6]],
            highlights=[
                {
                    "label": "资料价值 Why useful",
                    "items": [item.get("whyUseful") or item.get("snippet", "") for item in results[:4]],
                }
            ],
        )
        return results

    def _run_reader(self, plan: dict, search_results: list[dict]) -> list[dict]:
        task = self._task("reader_task")
        call = self._call_model(
            task,
            [
                LLMMessage(role="system", content=self._system_prompt(task.agent)),
                LLMMessage(
                    role="user",
                    content=(
                        "请从候选资料里提炼 3 到 4 条可写入报告的中文 findings。只返回 JSON，字段为 "
                        "findings，数组元素包含 claim, evidence, sourceTitle, sourceUrl, confidence。"
                        "每条 finding 都要能解释它会怎样影响最终报告。\n\n"
                        f"研究问题：{self.question}\n研究计划：{json.dumps(plan, ensure_ascii=False)}\n"
                        f"候选资料：{json.dumps(search_results, ensure_ascii=False)}"
                    ),
                ),
            ],
            fallback_factory=lambda: json.dumps(self._fallback_findings(search_results), ensure_ascii=False),
        )
        parsed = _extract_json_object(call.content) or {}
        findings = _dict_list(parsed.get("findings")) or self._findings_from_text(call.content, search_results)
        for index, finding in enumerate(findings, start=1):
            finding.setdefault("citationId", f"C{index}")
            finding.setdefault("sourceUrl", search_results[min(index - 1, len(search_results) - 1)].get("url", ""))
            finding.setdefault("sourceTitle", search_results[min(index - 1, len(search_results) - 1)].get("title", ""))
            finding.setdefault("confidence", 0.7)
        self._finish_step(
            task,
            call,
            metrics={
                "Findings": len(findings),
                "Grounded citations": len([item for item in findings if item.get("sourceUrl")]),
            },
            bullets=[f"{item.get('claim', '')} [{item.get('citationId', '')}]" for item in findings[:6]],
            highlights=[
                {"label": "证据样例 Evidence samples", "items": [item.get("evidence", "") for item in findings[:4]]}
            ],
        )
        return findings

    def _run_writer(self, plan: dict, findings: list[dict]) -> str:
        task = self._task("writer_task")
        call = self._call_model(
            task,
            [
                LLMMessage(role="system", content=self._system_prompt(task.agent)),
                LLMMessage(
                    role="user",
                    content=(
                        "请写第一版中文 Markdown 研究报告。只返回 JSON，字段 markdown。"
                        "markdown 必须包含这些标题：# Research Report:、## 摘要、## Key Findings（关键发现）、"
                        "## 深入分析、## 行动建议、## References（参考来源）。"
                        "正文使用中文，关键术语可以保留英文但要用中文解释。每条关键发现尽量带 [C1] 这类引用标记。"
                        "总长度控制在 900 到 1300 个汉字。\n\n"
                        f"研究问题：{self.question}\n研究计划：{json.dumps(plan, ensure_ascii=False)}\n"
                        f"Findings：{json.dumps(findings, ensure_ascii=False)}"
                    ),
                ),
            ],
            fallback_factory=lambda: json.dumps(
                {"markdown": self._fallback_report_markdown(plan, findings)},
                ensure_ascii=False,
            ),
            stream_target="initialDraft",
            stream_field="markdown",
        )
        parsed = _extract_json_object(call.content) or {}
        markdown = str(parsed.get("markdown") or "").strip() or self._markdown_from_model_text(call.content, findings)
        markdown = self._ensure_chinese_report_shape(markdown)
        self._finish_step(
            task,
            call,
            metrics=_markdown_metrics(markdown, findings),
            bullets=_headings(markdown),
            highlights=[{"label": "报告版本 Report version", "items": ["第一版初稿 Initial Draft"]}],
        )
        self._complete_markdown_stream("initialDraft", markdown, call)
        return markdown

    def _run_critic(self, report_markdown: str, findings: list[dict]) -> dict:
        task = self._task("critic_task")
        call = self._call_model(
            task,
            [
                LLMMessage(role="system", content=self._system_prompt(task.agent)),
                LLMMessage(
                    role="user",
                    content=(
                        "请检查这份中文研究报告。只返回 JSON，字段为 passed, summary, checks, issues。"
                        "issues 是字符串数组，最多 3 条，重点检查是否回答问题、是否有证据、是否引用清楚、是否过于空泛。\n\n"
                        f"研究问题：{self.question}\nFindings：{json.dumps(findings, ensure_ascii=False)}\n"
                        f"报告：\n{report_markdown}"
                    ),
                ),
            ],
            fallback_factory=lambda: json.dumps(self._fallback_critic(report_markdown, findings), ensure_ascii=False),
        )
        parsed = _extract_json_object(call.content) or {}
        review = {
            "passed": bool(parsed.get("passed", False)),
            "summary": str(parsed.get("summary") or "模型完成了结构和证据检查。"),
            "checks": parsed.get("checks") if isinstance(parsed.get("checks"), dict) else {},
            "issues": _string_list(parsed.get("issues")),
            "llmNotes": call.content,
        }
        if not review["checks"]:
            review["checks"] = {
                "has_title": report_markdown.startswith("# "),
                "has_key_findings": "## Key Findings" in report_markdown,
                "has_references": "## References" in report_markdown,
                "finding_count": len(findings),
            }
        self._finish_step(
            task,
            call,
            metrics={
                "Issues": len(review["issues"]),
                "Finding count": len(findings),
                "Passed": review["passed"],
            },
            bullets=review["issues"] or [review["summary"]],
            highlights=[
                {"label": "检查项 Checks", "items": [f"{key}: {value}" for key, value in review["checks"].items()]}
            ],
        )
        return review

    def _run_red(self, round_index: int, report_markdown: str, critic_review: dict) -> dict:
        task = self._task("red_review_task")
        call = self._call_model(
            task,
            [
                LLMMessage(role="system", content=self._system_prompt(task.agent)),
                LLMMessage(
                    role="user",
                    content=(
                        f"这是第 {round_index} 轮 Red Review。请扮演严格审查者，找出报告仍然存在的问题。"
                        "只返回 JSON，字段为 passed, summary, reviewText, issues。reviewText 必须用中文逐条写出"
                        "问题、依据和建议，供用户阅读。issues 数组元素包含 "
                        "issueId, severity, message, evidence, suggestion。issues 最多 3 条。\n\n"
                        "每条 evidence 必须指出报告中的具体句子、章节或缺失项；每条 suggestion 必须说明要改哪一段、"
                        "应补充或删除什么。不要输出泛化的“加强论证”“补充细节”一类建议。\n\n"
                        f"研究问题：{self.question}\nCritic 检查：{json.dumps(critic_review, ensure_ascii=False)}\n"
                        f"当前报告：\n{report_markdown}"
                    ),
                ),
            ],
            fallback_factory=lambda: json.dumps(
                self._fallback_red_review(round_index, report_markdown, critic_review),
                ensure_ascii=False,
            ),
            temperature=0.25,
            stream_target="reviewTranscript",
            stream_field="reviewText",
            stream_prefix=f"第 {round_index} 轮 Red Review\n\n",
        )
        parsed = _extract_json_object(call.content) or {}
        issues = _dict_list(parsed.get("issues"))
        review = {
            "passed": bool(parsed.get("passed", not issues)),
            "summary": str(parsed.get("summary") or f"第 {round_index} 轮审查完成。"),
            "issues": issues,
            "round": round_index,
            "reviewText": str(parsed.get("reviewText") or ""),
        }
        self._finish_step(
            task,
            call,
            metrics={
                "Issues": len(issues),
                "Passed": review["passed"],
                "Review rounds": round_index,
            },
            bullets=[
                f"{item.get('issueId', f'R{round_index}-{idx}')} [{item.get('severity', 'medium')}] {item.get('message', '')}"
                for idx, item in enumerate(issues, start=1)
            ] or [review["summary"]],
            highlights=[
                {
                    "label": "修订建议 Suggestions",
                    "items": [item.get("suggestion", "") for item in issues if item.get("suggestion")],
                }
            ],
        )
        self._complete_text_stream("reviewTranscript", self._red_review_text(review, round_index), call)
        return review

    def _run_blue(
        self,
        round_index: int,
        report_markdown: str,
        red_review: dict,
        findings: list[dict],
    ) -> tuple[str, dict]:
        task = self._task("blue_revision_task")
        call = self._call_model(
            task,
            [
                LLMMessage(role="system", content=self._system_prompt(task.agent)),
                LLMMessage(
                    role="user",
                    content=(
                        f"这是第 {round_index} 轮 Blue Revision。请根据 Red Review 修改报告。只返回 JSON，字段为 "
                        "revisedReportMarkdown, fixedIssueIds, remainingIssueIds, revisionNotes, revisionText, changes。"
                        "revisionText 必须用中文逐条说明每个问题的具体修改和原因，供用户阅读。"
                        "changes 是数组，每项必须包含 issueId、change、reason；具体说明修改了报告的哪一段、改成了什么，"
                        "不能只返回 issue ID。"
                        "最终报告必须是中文 Markdown，保留 # Research Report: 和 References 标题，"
                        "关键英文术语后面要给中文解释。总长度控制在 1000 到 1500 个汉字。\n\n"
                        f"研究问题：{self.question}\nFindings：{json.dumps(findings, ensure_ascii=False)}\n"
                        f"Red Review：{json.dumps(red_review, ensure_ascii=False)}\n当前报告：\n{report_markdown}"
                    ),
                ),
            ],
            fallback_factory=lambda: json.dumps(
                self._fallback_blue_revision(round_index, report_markdown, red_review),
                ensure_ascii=False,
            ),
            temperature=0.2,
            stream_target="reviewTranscript",
            stream_field="revisionText",
            stream_prefix=f"第 {round_index} 轮 Blue Revision\n\n",
        )
        parsed = _extract_json_object(call.content) or {}
        revised = str(parsed.get("revisedReportMarkdown") or "").strip()
        if not revised:
            revised = self._markdown_from_model_text(call.content, findings)
        revised = self._ensure_chinese_report_shape(revised)
        fixed = _string_list(parsed.get("fixedIssueIds"))
        remaining = _string_list(parsed.get("remainingIssueIds"))
        notes = _string_list(parsed.get("revisionNotes")) or [f"第 {round_index} 轮模型修订完成。"]
        revision_text = str(parsed.get("revisionText") or "")
        changes = _dict_list(parsed.get("changes"))
        if not changes:
            issues_by_id = {
                str(item.get("issueId")): item
                for item in red_review.get("issues", [])
                if item.get("issueId")
            }
            applicable_issue_ids = fixed or [
                issue_id
                for issue_id in issues_by_id
                if issue_id not in remaining
            ]
            applied_change = _revision_change_summary(report_markdown, revised)
            changes = [
                {
                    "issueId": issue_id,
                    "change": applied_change or (
                        notes[index] if index < len(notes) else "已根据 Red 审查建议修订相关段落。"
                    ),
                    "reason": str(issues_by_id.get(issue_id, {}).get("suggestion") or "回应对应审查问题。"),
                }
                for index, issue_id in enumerate(applicable_issue_ids)
            ]
        self._finish_step(
            task,
            call,
            metrics={
                "Fixed issues": len(fixed),
                "Remaining issues": len(remaining),
                "Revision rounds": round_index,
                "Characters": len(revised),
            },
            bullets=notes,
            highlights=[
                {"label": "已修复 issue id", "items": fixed},
                {"label": "剩余 issue id", "items": remaining},
                {
                    "label": "具体修改",
                    "items": [
                        f"{item.get('issueId', '未关联问题')}：{item.get('change', '')}"
                        for item in changes
                    ],
                },
            ],
        )
        blue_revision = {
            "fixedIssueIds": fixed,
            "remainingIssueIds": remaining,
            "revisionNotes": notes,
            "revisionText": revision_text,
            "changes": changes,
        }
        self._complete_text_stream("reviewTranscript", self._blue_revision_text(blue_revision, round_index), call)
        return revised, blue_revision

    def _call_model(
        self,
        task: WorkbenchTask,
        messages: list[LLMMessage],
        fallback_factory: Callable[[], str],
        temperature: float = 0.2,
        stream_target: str | None = None,
        stream_field: str | None = None,
        stream_prefix: str = "",
    ) -> StepCall:
        self._mark_step_running(task)
        started = time.perf_counter()
        try:
            if stream_target and stream_field and getattr(self.llm_client, "supports_streaming", False):
                streamed_chunks: list[str] = []
                visible_streamed = False
                stream_started = False
                extractor = _IncrementalJSONTextField(stream_field)
                try:
                    for chunk in self.llm_client.generate_stream(messages, temperature=temperature):
                        streamed_chunks.append(chunk)
                        if not stream_started:
                            self._emit("report_stream_start", {"target": stream_target})
                            if stream_prefix:
                                self._emit("report_delta", {"target": stream_target, "delta": stream_prefix})
                            stream_started = True
                        visible = extractor.feed(chunk)
                        if visible:
                            self._emit("report_delta", {"target": stream_target, "delta": visible})
                            visible_streamed = True
                    self.model_call_count += 1
                    return StepCall(
                        content="".join(streamed_chunks).strip(),
                        model=getattr(self.llm_client, "config", None) and self.llm_client.config.model,
                        duration_ms=int((time.perf_counter() - started) * 1000),
                        native_stream_used=stream_started,
                        visible_streamed=visible_streamed,
                    )
                except Exception as stream_exc:
                    if stream_started:
                        self._emit(
                            "agent_progress",
                            {
                                "taskId": task.task_id,
                                "message": f"{task.agent} 的原生流中断，正在使用完整响应降级。",
                            },
                        )
                    if streamed_chunks:
                        raise stream_exc

            response = self.llm_client.generate(messages, temperature=temperature)
            self.model_call_count += 1
            return StepCall(
                content=(response.content or "").strip(),
                model=response.model,
                usage=response.usage,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            self.fallback_count += 1
            return StepCall(
                content=fallback_factory(),
                fallback_used=True,
                error=str(exc),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    def _complete_markdown_stream(self, target: str, markdown: str, call: StepCall) -> None:
        if not call.native_stream_used:
            self._emit_markdown_stream(target, markdown)
            return
        if not call.visible_streamed:
            self._emit("report_delta", {"target": target, "delta": markdown})
        self._emit("report_stream_done", {"target": target, "markdown": markdown})

    def _complete_text_stream(self, target: str, text: str, call: StepCall) -> None:
        if not call.native_stream_used:
            self._emit_text_stream(target, text)
            return
        if not call.visible_streamed:
            self._emit("report_delta", {"target": target, "delta": text})
        self._emit("report_stream_done", {"target": target, "text": text})

    def _mark_step_running(self, task: WorkbenchTask) -> None:
        step = self.steps[task.task_id]
        step.update(
            {
                "status": "running",
                "success": False,
                "mode": self._client_mode(),
                "startedAt": _timestamp(),
            }
        )
        self._trace(task, "running", {"mode": step["mode"]})
        self._emit("agent_started", {"step": step})
        self._emit("agent_progress", {"taskId": task.task_id, "message": f"{task.agent} 正在生成可交接产物。"})

    def _finish_step(
        self,
        task: WorkbenchTask,
        call: StepCall,
        metrics: dict,
        bullets: list[str],
        highlights: list[dict],
    ) -> None:
        step = self.steps[task.task_id]
        status = "fallback" if call.fallback_used else "done"
        mode = "local_fallback" if call.fallback_used else self._client_mode()
        metrics = dict(metrics)
        metrics.setdefault("Model calls", 0 if call.fallback_used else 1)
        metrics.setdefault("Fallbacks", 1 if call.fallback_used else 0)
        step.update(
            {
                "status": status,
                "success": True,
                "mode": mode,
                "completedAt": _timestamp(),
                "durationMs": call.duration_ms,
                "llmModel": call.model,
                "llmUsage": call.usage or {},
                "fallbackUsed": call.fallback_used,
                "error": call.error,
                "metrics": metrics,
                "bullets": bullets,
                "highlights": highlights,
            }
        )
        self._trace(task, status, {"durationMs": call.duration_ms, "fallbackUsed": call.fallback_used})
        self._emit("artifact_ready", {"taskId": task.task_id, "summary": bullets[:3], "metrics": metrics})
        self._emit("agent_completed", {"step": step})
        self._emit("agent_done" if not call.fallback_used else "agent_fallback", {"step": step})

    def _build_payload(self, critic_review: dict, red_review: dict) -> dict:
        diff_summary = _build_report_diff_summary(self.initial_report_markdown, self.final_report_markdown)
        return {
            "success": True,
            "runId": self.run_id,
            "question": self.question,
            "modelRun": self._model_run_metadata(),
            "finalReportMarkdown": self.final_report_markdown,
            "initialReportMarkdown": self.initial_report_markdown,
            "reportDiffSummary": diff_summary,
            "reportMetrics": _markdown_metrics(self.final_report_markdown, self.findings)
            | {
                "Initial lines": len(self.initial_report_markdown.splitlines()),
                "Findings": len(self.findings),
                "Model calls": self.model_call_count,
                "Fallbacks": self.fallback_count,
                "Report versions": len(self.report_versions),
                "Citation validation": "passed"
                if self.citation_validation.get("passed")
                else "needs review",
            },
            "stepImpacts": self._step_list(),
            "findings": [self._summarize_finding(item, index) for index, item in enumerate(self.findings, start=1)],
            "citationValidation": self.citation_validation,
            "memoryTimeline": self.report_versions,
            "executionTrace": self.execution_trace,
            "criticReview": critic_review,
            "redReview": red_review,
            "reportVersions": self.report_versions,
            "reviewRounds": self.review_rounds,
        }

    def _initial_step(self, task: WorkbenchTask) -> dict:
        return {
            "taskId": task.task_id,
            "agent": task.agent,
            "title": task.title,
            "success": False,
            "status": "pending",
            "mode": "pending",
            "impactOnFinalReport": task.impact,
            "metrics": {},
            "bullets": [],
            "highlights": [],
            "fallbackUsed": False,
            "error": None,
        }

    def _task(self, task_id: str) -> WorkbenchTask:
        return next(task for task in MODEL_TASKS if task.task_id == task_id)

    def _step_list(self) -> list[dict]:
        return [dict(self.steps[task.task_id]) for task in MODEL_TASKS]

    def _trace(self, task: WorkbenchTask, status: str, metadata: dict) -> None:
        self.execution_trace.append(
            {
                "time": _timestamp(),
                "taskId": task.task_id,
                "agent": task.agent,
                "status": status,
                "metadata": metadata,
            }
        )

    def _emit(self, event_type: str, data: dict) -> None:
        if self.event_sink is None:
            return
        self.event_sink(event_type, data)

    def _emit_markdown_stream(self, target: str, markdown: str) -> None:
        self._emit("report_stream_start", {"target": target})
        for chunk in _chunk_text(markdown):
            self._emit("report_delta", {"target": target, "delta": chunk})
            if self._stream_delay_seconds:
                time.sleep(self._stream_delay_seconds)
        self._emit("report_stream_done", {"target": target, "markdown": markdown})

    def _emit_text_stream(self, target: str, text: str) -> None:
        self._emit("report_stream_start", {"target": target})
        for chunk in _chunk_text(text):
            self._emit("report_delta", {"target": target, "delta": chunk})
            if self._stream_delay_seconds:
                time.sleep(self._stream_delay_seconds)
        self._emit("report_stream_done", {"target": target, "text": text})

    def _model_run_metadata(self) -> dict:
        return {
            "mode": self._client_mode(),
            "client": self.llm_client.__class__.__name__,
            "modelCalls": self.model_call_count,
            "fallbackCount": self.fallback_count,
            "fallbackPolicy": "只有模型调用抛异常时才使用本地兜底。",
            "language": "zh-CN",
        }

    def _client_mode(self) -> str:
        return "mock_llm" if isinstance(self.llm_client, MockLLMClient) else "llm"

    @staticmethod
    def _system_prompt(agent_name: str) -> str:
        return (
            f"你是 DeepResearch 多 Agent 系统中的 {agent_name}。"
            "必须优先使用模型推理完成自己的核心产出；除非模型请求失败，不要退回固定模板。"
            "输出使用中文，关键英文术语第一次出现时用中文解释。回答要紧凑，不要写额外寒暄。"
        )

    def _fallback_plan(self) -> dict:
        return {
            "objective": f"在模型不可用时，本地兜底回答：{self.question}",
            "subQuestions": [
                f"{self.question} 的背景是什么？",
                f"{self.question} 的关键影响因素有哪些？",
                f"{self.question} 可以怎样落地和评估？",
            ],
            "searchQueries": [self.question, f"{self.question} 风险", f"{self.question} 实践"],
            "expectedSections": ["摘要", "Key Findings（关键发现）", "深入分析", "行动建议", "References（参考来源）"],
        }

    def _fallback_search_results(self, plan: dict) -> list[dict]:
        return [
            {
                "title": f"本地兜底资料方向 {index}",
                "url": f"local://fallback-source-{index}",
                "snippet": f"围绕 {query} 搜集权威文档、实践案例和风险说明。",
                "whyUseful": "模型请求失败时的占位资料方向，启动真实模型后会被模型生成的候选资料替代。",
            }
            for index, query in enumerate(plan.get("searchQueries", [self.question])[:4], start=1)
        ]

    def _fallback_findings(self, search_results: list[dict]) -> list[dict]:
        return [
            {
                "claim": f"围绕资料方向 {index}，最终报告需要解释业务价值、风险和落地条件。",
                "evidence": item.get("snippet", ""),
                "sourceTitle": item.get("title", ""),
                "sourceUrl": item.get("url", ""),
                "confidence": 0.5,
                "citationId": f"C{index}",
            }
            for index, item in enumerate(search_results[:4], start=1)
        ]

    def _fallback_report_markdown(self, plan: dict, findings: list[dict]) -> str:
        finding_lines = [
            f"- {item.get('claim', '')} [{item.get('citationId', f'C{index}')}]"
            for index, item in enumerate(findings, start=1)
        ]
        reference_lines = [
            f"- [{item.get('citationId', f'C{index}')}] {item.get('sourceTitle', '本地兜底资料')} {item.get('sourceUrl', '')}"
            for index, item in enumerate(findings, start=1)
        ]
        return "\n".join(
            [
                f"# Research Report: {self.question}",
                "",
                "## 摘要",
                "",
                f"模型调用失败，因此这里使用本地兜底报告。报告目标是：{plan.get('objective', self.question)}",
                "",
                "## Key Findings（关键发现）",
                "",
                *(finding_lines or ["- 暂无可用 finding。"]),
                "",
                "## 深入分析",
                "",
                "当前版本只能提供基础分析；恢复模型后应由 WriterAgent 重新生成完整中文报告。",
                "",
                "## 行动建议",
                "",
                "- 检查 API Key、Base URL、模型名和网络连接。",
                "- 重新运行工作台，确认每个 Agent 状态为 done 而不是 fallback。",
                "",
                "## References（参考来源）",
                "",
                *(reference_lines or ["- local://fallback-source"]),
            ]
        )

    def _fallback_critic(self, report_markdown: str, findings: list[dict]) -> dict:
        issues = []
        if "## Key Findings" not in report_markdown:
            issues.append("缺少 Key Findings（关键发现）章节。")
        if "## References" not in report_markdown:
            issues.append("缺少 References（参考来源）章节。")
        if not findings:
            issues.append("缺少可追踪 findings。")
        return {
            "passed": not issues,
            "summary": "模型请求失败，已使用本地规则完成最低限度检查。",
            "checks": {
                "has_title": report_markdown.startswith("# "),
                "has_key_findings": "## Key Findings" in report_markdown,
                "has_references": "## References" in report_markdown,
                "finding_count": len(findings),
            },
            "issues": issues,
        }

    def _fallback_red_review(self, round_index: int, report_markdown: str, critic_review: dict) -> dict:
        issues = [
            {
                "issueId": f"R{round_index}-1",
                "severity": "medium",
                "message": "模型审查失败，本地兜底只能提示需要人工复查证据和引用。",
                "evidence": _trim(report_markdown, 240),
                "suggestion": "恢复模型后重新运行 RedAgent，让它给出更细的反例和修订建议。",
            }
        ]
        if critic_review.get("issues"):
            issues.extend(
                {
                    "issueId": f"R{round_index}-{index + 1}",
                    "severity": "medium",
                    "message": str(issue),
                    "evidence": "来自 CriticAgent 的检查结果。",
                    "suggestion": "在 BlueAgent 修订时补齐该问题。",
                }
                for index, issue in enumerate(critic_review.get("issues", []), start=1)
            )
        return {"passed": False, "summary": "本地兜底 Red Review 完成。", "issues": issues}

    def _fallback_blue_revision(self, round_index: int, report_markdown: str, red_review: dict) -> dict:
        issue_ids = [
            str(item.get("issueId"))
            for item in red_review.get("issues", [])
            if item.get("issueId")
        ]
        return {
            "revisedReportMarkdown": report_markdown
            + f"\n\n## 第 {round_index} 轮兜底修订说明\n\n"
            + "模型修订失败，当前仅追加本地说明。恢复模型后应重新运行 BlueAgent 完成真正改写。\n",
            "fixedIssueIds": [],
            "remainingIssueIds": issue_ids,
            "revisionNotes": ["模型请求失败，已保留原报告并追加兜底说明。"],
        }

    def _search_results_from_text(self, text: str) -> list[dict]:
        lines = [line.strip("- 0123456789.") for line in text.splitlines() if line.strip()]
        return [
            {
                "title": line[:80],
                "url": f"model-text://search-result-{index}",
                "snippet": line,
                "whyUseful": "由模型自由文本转换成候选资料方向。",
            }
            for index, line in enumerate(lines[:5], start=1)
        ] or self._fallback_search_results({"searchQueries": [self.question]})

    def _findings_from_text(self, text: str, search_results: list[dict]) -> list[dict]:
        lines = [line.strip("- 0123456789.") for line in text.splitlines() if line.strip()]
        findings = []
        for index, line in enumerate(lines[:5], start=1):
            source = search_results[min(index - 1, len(search_results) - 1)] if search_results else {}
            findings.append(
                {
                    "claim": line[:180],
                    "evidence": line,
                    "sourceTitle": source.get("title", "模型文本"),
                    "sourceUrl": source.get("url", f"model-text://finding-{index}"),
                    "confidence": 0.65,
                    "citationId": f"C{index}",
                }
            )
        return findings or self._fallback_findings(search_results)

    def _markdown_from_model_text(self, text: str, findings: list[dict]) -> str:
        if text.lstrip().startswith("# "):
            return text.strip()
        finding_lines = [
            f"- {item.get('claim', '')} [{item.get('citationId', f'C{index}')}]"
            for index, item in enumerate(findings[:5], start=1)
        ]
        references = [
            f"- [{item.get('citationId', f'C{index}')}] {item.get('sourceTitle', '')} {item.get('sourceUrl', '')}"
            for index, item in enumerate(findings[:5], start=1)
        ]
        return "\n".join(
            [
                f"# Research Report: {self.question}",
                "",
                "## 摘要",
                "",
                _trim(text.strip(), 900),
                "",
                "## Key Findings（关键发现）",
                "",
                *(finding_lines or ["- 模型没有返回结构化 finding，需要重新运行。"]),
                "",
                "## 深入分析",
                "",
                "以上内容来自模型自由文本输出，系统已将其整理为报告结构，便于继续审查和修订。",
                "",
                "## 行动建议",
                "",
                "- 继续查看 RedAgent 的问题清单。",
                "- 根据 BlueAgent 的最终版本判断报告是否足够具体。",
                "",
                "## References（参考来源）",
                "",
                *(references or ["- model-text://unstructured-output"]),
            ]
        )

    def _ensure_chinese_report_shape(self, markdown: str) -> str:
        text = markdown.strip()
        if not text.startswith("# "):
            text = f"# Research Report: {self.question}\n\n{text}"
        elif text.splitlines()[0].strip() in {"# Research Report:", "# Research Report"}:
            lines = text.splitlines()
            lines[0] = f"# Research Report: {self.question}"
            text = "\n".join(lines)
        if "## Key Findings" not in text:
            text += "\n\n## Key Findings（关键发现）\n\n- 模型输出没有显式关键发现章节，系统已补齐标题以便后续审查。\n"
        if "## References" not in text:
            text += "\n\n## References（参考来源）\n\n- 模型输出没有显式参考来源，建议重新运行或补充资料。\n"
        return text

    @staticmethod
    def _red_review_text(red_review: dict, round_index: int) -> str:
        if red_review.get("reviewText"):
            return f"第 {round_index} 轮 Red Review\n\n{red_review['reviewText'].strip()}"
        lines = [f"第 {round_index} 轮 Red Review", "", red_review.get("summary", "")]
        for item in red_review.get("issues", []):
            lines.append(
                f"\n- {item.get('issueId', '')} [{item.get('severity', 'medium')}]\n"
                f"  问题：{item.get('message', '')}\n"
                f"  依据：{item.get('evidence', '未提供具体依据')}\n"
                f"  建议：{item.get('suggestion', '请补充具体修订建议')}"
            )
        return "\n".join(lines).strip()

    @staticmethod
    def _blue_revision_text(blue_revision: dict, round_index: int) -> str:
        if blue_revision.get("revisionText"):
            return f"第 {round_index} 轮 Blue Revision\n\n{blue_revision['revisionText'].strip()}"
        lines = [f"第 {round_index} 轮 Blue Revision", ""]
        for item in blue_revision.get("changes", []):
            lines.extend(
                [
                    f"- {item.get('issueId', '未关联问题')}",
                    f"  修改：{item.get('change', '未提供具体修改说明')}",
                    f"  原因：{item.get('reason', '回应 Red 审查意见')}",
                ]
            )
        if not blue_revision.get("changes"):
            lines.extend(f"- 修订说明：{note}" for note in blue_revision.get("revisionNotes", []))
        for issue_id in blue_revision.get("remainingIssueIds", []):
            lines.append(f"- 仍待复核：{issue_id}")
        return "\n".join(lines).strip()

    @staticmethod
    def _validate_citations(markdown: str, findings: list[dict]) -> dict:
        citation_ids = [item.get("citationId") for item in findings if item.get("citationId")]
        missing = [citation_id for citation_id in citation_ids if f"[{citation_id}]" not in markdown]
        sources = [
            {
                "citationId": item.get("citationId") or item.get("citation_id") or f"C{index}",
                "sourceTitle": str(item.get("sourceTitle") or item.get("source_title") or "未命名来源"),
                "sourceUrl": str(item.get("sourceUrl") or item.get("source_url") or ""),
                "status": "missing_marker" if (item.get("citationId") or item.get("citation_id")) in missing else "linked",
            }
            for index, item in enumerate(findings, start=1)
        ]
        return {
            "passed": "## References" in markdown and not missing,
            "grounded_citation_count": len(citation_ids) - len(missing),
            "expected_citation_count": len(citation_ids),
            "missingCitationIds": missing,
            "issues": [f"报告缺少引用标记 [{citation_id}]" for citation_id in missing],
            "sources": sources,
        }

    @staticmethod
    def _summarize_finding(finding: dict, index: int) -> dict:
        return {
            "claim": str(finding.get("claim", "")),
            "evidence": str(finding.get("evidence", "")),
            "sourceUrl": str(finding.get("sourceUrl") or finding.get("source_url") or ""),
            "sourceTitle": finding.get("sourceTitle") or finding.get("source_title"),
            "confidence": finding.get("confidence"),
            "citationId": finding.get("citationId") or finding.get("citation_id") or f"C{index}",
            "evidenceId": finding.get("evidenceId") or finding.get("evidence_id") or f"E{index}",
        }


def build_model_workbench_payload(
    question_text: str,
    llm_client: BaseLLMClient | None = None,
    use_env_llm: bool = False,
    event_sink: EventSink | None = None,
    red_blue_rounds: int = 2,
) -> dict:
    question = question_text.strip()
    client = llm_client or _create_workbench_client(use_env_llm)
    return ModelWorkbenchRunner(
        question=question,
        llm_client=client,
        event_sink=event_sink,
        red_blue_rounds=red_blue_rounds,
    ).run()


def _create_workbench_client(use_env_llm: bool) -> BaseLLMClient:
    if use_env_llm:
        return create_llm_client(load_llm_config_from_env(load_dotenv=True))
    return MockLLMClient()


def _extract_json_object(text: str) -> dict | None:
    cleaned = _strip_code_fence(text.strip())
    candidates = [cleaned]
    first_object = cleaned.find("{")
    last_object = cleaned.rfind("}")
    if first_object != -1 and last_object != -1 and last_object > first_object:
        candidates.append(cleaned[first_object : last_object + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [line.strip("- ") for line in value.splitlines() if line.strip()]
    return []


def _dict_list(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _trim(text: str, limit: int = 1000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _chunk_text(text: str, size: int = 160) -> list[str]:
    if not text:
        return [""]
    chunks = []
    current = []
    current_size = 0
    for line in text.splitlines(keepends=True):
        current.append(line)
        current_size += len(line)
        if current_size >= size:
            chunks.append("".join(current))
            current = []
            current_size = 0
    if current:
        chunks.append("".join(current))
    return chunks or [text]


class _IncrementalJSONTextField:
    """Extract one JSON string property without exposing the JSON envelope to the UI."""

    def __init__(self, field_name: str) -> None:
        self._field_name = field_name
        self._source = ""
        self._cursor: int | None = None
        self._escaped = False
        self._completed = False

    def feed(self, chunk: str) -> str:
        if self._completed or not chunk:
            return ""
        self._source += chunk
        if self._cursor is None:
            match = re.search(
                rf'"{re.escape(self._field_name)}"\s*:\s*"',
                self._source,
            )
            if match is None:
                return ""
            self._cursor = match.end()

        output: list[str] = []
        while self._cursor < len(self._source):
            char = self._source[self._cursor]
            if self._escaped:
                if char == "u":
                    if self._cursor + 5 > len(self._source):
                        break
                    escaped_value = self._source[self._cursor + 1 : self._cursor + 5]
                    try:
                        output.append(chr(int(escaped_value, 16)))
                    except ValueError:
                        output.append("\\u" + escaped_value)
                    self._cursor += 5
                else:
                    output.append(
                        {
                            '"': '"',
                            "\\": "\\",
                            "/": "/",
                            "b": "\b",
                            "f": "\f",
                            "n": "\n",
                            "r": "\r",
                            "t": "\t",
                        }.get(char, char)
                    )
                    self._cursor += 1
                self._escaped = False
                continue
            if char == "\\":
                self._escaped = True
                self._cursor += 1
                continue
            if char == '"':
                self._completed = True
                self._cursor += 1
                break
            output.append(char)
            self._cursor += 1
        return "".join(output)


def _revision_change_summary(before: str, after: str, limit: int = 420) -> str:
    """Turn a Blue markdown diff into a readable handoff when the model omits changes."""
    diff_lines = list(unified_diff(before.splitlines(), after.splitlines(), lineterm=""))
    added = [line[1:].strip() for line in diff_lines if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:].strip() for line in diff_lines if line.startswith("-") and not line.startswith("---")]
    parts = []
    if added:
        parts.append("新增：" + "；".join(item for item in added[:2] if item))
    if removed:
        parts.append("删除或替换：" + "；".join(item for item in removed[:2] if item))
    return _trim(" ".join(parts), limit) if parts else ""


def _headings(markdown: str) -> list[str]:
    return [line.strip("# ").strip() for line in markdown.splitlines() if line.startswith("## ")][:8]


def _markdown_metrics(markdown: str, findings: list[dict]) -> dict:
    return {
        "Sections": len(_headings(markdown)),
        "Citations": markdown.count("[C"),
        "Characters": len(markdown),
        "Lines": len(markdown.splitlines()),
        "Findings": len(findings),
    }


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
        summary = f"最终报告在 Red/Blue 多轮修订后发生变化：新增 {len(added)} 行，删除 {len(removed)} 行。"
    else:
        summary = "Red/Blue 审查后没有产生文本差异，最终报告沿用初稿。"
    return {
        "summary": summary,
        "addedLineCount": len(added),
        "removedLineCount": len(removed),
        "addedLines": added[:20],
        "removedLines": removed[:20],
        "diffPreview": diff_lines[:120],
    }
