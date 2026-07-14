"""Browser workbench for showing how DeepResearch builds a final report."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from difflib import unified_diff
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from agents.base_agent import AgentResult
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
    red_blue_rounds: int = 1,
    **pipeline_kwargs: Any,
) -> dict:
    """运行流水线，并把内部产物转换为浏览器可用的数据。

    工作台不是第二套研究实现，而是适配层：它以 JSON 友好的结构暴露每个 Agent 的
    贡献、报告差异、引用和 Trace，让审阅者检查最终报告的来源链路。
    """

    question = (question_text or DEFAULT_QUESTION).strip() or DEFAULT_QUESTION
    if not legacy_pipeline:
        return build_model_workbench_payload(
            question,
            llm_client=pipeline_kwargs.pop("llm_client", None),
            use_env_llm=use_env_llm,
            event_sink=event_sink,
            red_blue_rounds=red_blue_rounds,
        )
    result = run_research_pipeline(question, **pipeline_kwargs)
    return summarize_pipeline_result(result)


def summarize_pipeline_result(result: dict) -> dict:
    """将带类型的流水线输出转换为稳定的前端 Payload。

    单独保留这一层投影，避免 HTTP/UI 格式化逻辑反向侵入 Agent 与编排代码。
    """
    execution = result["execution"]
    outputs = execution.outputs
    initial_report = result.get("initial_report")
    final_report = result.get("final_report") or result.get("report")
    initial_markdown = _report_markdown(initial_report)
    final_markdown = _report_markdown(final_report)
    diff_summary = _build_report_diff_summary(initial_markdown, final_markdown)

    return {
        "success": bool(result.get("success")),
        "runId": result.get("run_id"),
        "question": getattr(result.get("question"), "question", str(result.get("question", ""))),
        "finalReportMarkdown": final_markdown,
        "initialReportMarkdown": initial_markdown,
        "reportDiffSummary": diff_summary,
        "reportMetrics": _report_metrics(final_report, initial_report, result),
        "stepImpacts": [
            _summarize_step(task_id, agent_name, title, outputs, result, diff_summary)
            for task_id, agent_name, title in TASK_ORDER
        ],
        "findings": [_summarize_finding(finding) for finding in result.get("findings", [])],
        "citationValidation": _to_jsonable(result.get("citation_validation", {})),
        "memoryTimeline": [_summarize_memory_item(item) for item in result.get("memory_items", [])],
        "executionTrace": _to_jsonable(result.get("traces", [])),
    }


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
          <h2>最终报告 Final Report（最终生成的 Markdown 报告）</h2>
          <article id="finalReport" class="report"></article>
        </section>
        <section class="panel split">
          <div>
            <h2>初始草稿 Initial Draft（Writer 写出的第一版）</h2>
            <pre id="initialDraft"></pre>
          </div>
          <div>
            <h2>修订差异 Review Diff（初稿到终稿的变化）</h2>
            <pre id="reportDiff"></pre>
          </div>
        </section>
        <section class="panel">
          <h2>证据结论与引用 Findings & Citations（事实结论和来源标记）</h2>
          <div id="findings"></div>
        </section>
      </div>
      <aside>
        <section class="panel">
          <h2>Pipeline 影响链路（每个 Agent 对报告的作用）</h2>
          <div id="steps" class="timeline"></div>
        </section>
        <section class="panel">
          <h2>Citation Validation（引用校验）</h2>
          <pre id="citationValidation"></pre>
        </section>
      </aside>
    </section>
  </main>
  <script>
    const questionEl = document.getElementById("question");
    const runButton = document.getElementById("runButton");
    const statusEl = document.getElementById("status");
    let currentSteps = [];
    let streamBuffers = {};

    runButton.addEventListener("click", runResearch);
    window.addEventListener("load", runResearch);

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
      } catch (error) {
        statusEl.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      } finally {
        runButton.disabled = false;
      }
    }

    function clearDashboard() {
      currentSteps = [];
      streamBuffers = {};
      document.getElementById("metrics").innerHTML = "";
      document.getElementById("finalReport").innerHTML = "<p>等待模型生成最终报告...</p>";
      document.getElementById("initialDraft").textContent = "";
      document.getElementById("reportDiff").textContent = "";
      document.getElementById("steps").innerHTML = "";
      document.getElementById("citationValidation").textContent = "";
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
      if (event === "agent_started" || event === "agent_done" || event === "agent_fallback") {
        upsertStep(data.step);
        const label = data.step?.agent || "Agent";
        const state = statusLabel(data.step?.status || "");
        statusEl.textContent = `${label}：${state}`;
        return;
      }
      if (event === "report_stream_start") {
        streamBuffers[data.target] = "";
        updateStreamTarget(data.target, "");
        return;
      }
      if (event === "report_delta") {
        streamBuffers[data.target] = (streamBuffers[data.target] || "") + (data.delta || "");
        updateStreamTarget(data.target, streamBuffers[data.target]);
        return;
      }
      if (event === "report_stream_done") {
        const value = data.markdown || data.text || streamBuffers[data.target] || "";
        updateStreamTarget(data.target, value);
        return;
      }
      if (event === "run_completed") {
        renderPayload(data.payload);
        const fallbackCount = data.payload?.modelRun?.fallbackCount || 0;
        if (fallbackCount) {
          const firstError = firstStepError(data.payload?.stepImpacts || []);
          statusEl.textContent = firstError
            ? `报告已生成，但有 ${fallbackCount} 个 Agent 使用了本地兜底。首个失败原因：${firstError}`
            : `报告已生成，但有 ${fallbackCount} 个 Agent 使用了本地兜底。`;
        } else {
          statusEl.textContent = "报告已生成：全部 Agent 均完成模型调用。";
        }
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
        document.getElementById("initialDraft").textContent = value;
      } else if (target === "finalReport") {
        document.getElementById("finalReport").innerHTML = renderMarkdown(value);
      } else if (target === "redReview") {
        document.getElementById("reportDiff").textContent = value;
      }
    }

    function renderPayload(payload) {
      renderMetrics(payload.reportMetrics || {});
      document.getElementById("finalReport").innerHTML = renderMarkdown(payload.finalReportMarkdown || "");
      document.getElementById("initialDraft").textContent = payload.initialReportMarkdown || "";
      document.getElementById("reportDiff").textContent = [
        payload.reportDiffSummary?.summary || "",
        ...(payload.reportDiffSummary?.diffPreview || [])
      ].join("\\n");
      currentSteps = payload.stepImpacts || [];
      renderSteps(currentSteps);
      document.getElementById("citationValidation").textContent =
        JSON.stringify(payload.citationValidation || {}, null, 2);
      document.getElementById("findings").innerHTML = renderFindings(payload.findings || []);
    }

    function renderSteps(steps) {
      document.getElementById("steps").innerHTML = (steps || []).map(renderStep).join("");
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
      const preview = step.outputPreview
        ? `<details><summary>输出预览 Output preview</summary><pre>${escapeHtml(step.outputPreview)}</pre></details>`
        : "";
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
          ${preview}
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
            <h3>Finding ${index + 1}（证据结论）</h3>
            <span class="badge">${escapeHtml(finding.citationId || "source（来源）")}</span>
          </div>
          <p><strong>Claim（结论）:</strong> ${escapeHtml(finding.claim || "")}</p>
          <p><strong>Evidence（证据）:</strong> ${escapeHtml(finding.evidence || "")}</p>
          <small>${escapeHtml(finding.sourceUrl || "")}</small>
        </article>
      `).join("");
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
          html += `<h1>${escapeHtml(line.slice(2))}</h1>`;
        } else if (line.startsWith("## ")) {
          if (inList) { html += "</ul>"; inList = false; }
          html += `<h2>${escapeHtml(line.slice(3))}</h2>`;
        } else if (line.startsWith("- ")) {
          if (!inList) { html += "<ul>"; inList = true; }
          html += `<li>${escapeHtml(line.slice(2))}</li>`;
        } else {
          if (inList) { html += "</ul>"; inList = false; }
          html += `<p>${escapeHtml(line)}</p>`;
        }
      }
      if (inList) html += "</ul>";
      return html;
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
        self.send_header("Cache-Control", "no-cache")
        # 浏览器前端在读取到流结束后才会恢复“生成报告”按钮。这个端点不是
        # 永久订阅，而是一轮任务对应一条有限事件流，因此完成后必须关闭连接。
        self.send_header("Connection", "close")
        self.end_headers()

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
