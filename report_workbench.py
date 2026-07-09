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
from orchestrator.research_pipeline import run_research_pipeline


DEFAULT_QUESTION = "What are the main factors that affect open-source LLM adoption in enterprises?"

TASK_ORDER = [
    ("planner_task", "PlannerAgent", "Research plan"),
    ("search_task", "SearcherAgent", "Search results"),
    ("reader_task", "ReaderAgent", "Evidence findings"),
    ("writer_task", "WriterAgent", "Initial report"),
    ("critic_task", "CriticAgent", "Quality checks"),
    ("red_review_task", "RedAgent", "Review issues"),
    ("blue_revision_task", "BlueAgent", "Final revision"),
]


def build_report_workbench_payload(question_text: str = DEFAULT_QUESTION, **pipeline_kwargs: Any) -> dict:
    """Run the research pipeline and return a JSON-friendly visual explanation."""

    question = (question_text or DEFAULT_QUESTION).strip() or DEFAULT_QUESTION
    result = run_research_pipeline(question, **pipeline_kwargs)
    return summarize_pipeline_result(result)


def summarize_pipeline_result(result: dict) -> dict:
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
            {"label": "Search queries", "items": output.search_queries},
            {"label": "Expected sections", "items": output.expected_sections},
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
                "label": "Evidence samples",
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
        step["highlights"] = [{"label": "Checks", "items": [f"{key}: {value}" for key, value in checks.items()]}]
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
                "label": "Suggestions",
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
            "Review passed without structural changes; final report keeps the verified draft."
        ]
        step["highlights"] = [
            {"label": "Fixed issue ids", "items": output.fixed_issue_ids},
            {"label": "Remaining issue ids", "items": output.remaining_issue_ids},
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
        summary = f"Final report changed {len(added)} added line(s) and {len(removed)} removed line(s) after review."
    else:
        summary = "Final report matches the initial draft after Critic/Red/Blue verification."
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
  <title>DeepResearch Report Workbench</title>
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
    .badge.warn { background: #fff4e5; color: var(--accent-2); }
    .impact { color: var(--ink); margin: 8px 0 10px; line-height: 1.45; }
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
    <h1>DeepResearch Report Workbench</h1>
  </header>
  <main>
    <section class="toolbar">
      <div>
        <label for="question">Research Question</label>
        <textarea id="question">What are the main factors that affect open-source LLM adoption in enterprises?</textarea>
      </div>
      <button id="runButton">Run Report</button>
    </section>
    <div id="status" class="status"></div>
    <section id="metrics" class="metrics"></section>
    <section class="layout">
      <div>
        <section class="panel">
          <h2>Final Report</h2>
          <article id="finalReport" class="report"></article>
        </section>
        <section class="panel split">
          <div>
            <h2>Initial Draft</h2>
            <pre id="initialDraft"></pre>
          </div>
          <div>
            <h2>Review Diff</h2>
            <pre id="reportDiff"></pre>
          </div>
        </section>
        <section class="panel">
          <h2>Findings & Citations</h2>
          <div id="findings"></div>
        </section>
      </div>
      <aside>
        <section class="panel">
          <h2>Pipeline Impact</h2>
          <div id="steps" class="timeline"></div>
        </section>
        <section class="panel">
          <h2>Citation Validation</h2>
          <pre id="citationValidation"></pre>
        </section>
      </aside>
    </section>
  </main>
  <script>
    const questionEl = document.getElementById("question");
    const runButton = document.getElementById("runButton");
    const statusEl = document.getElementById("status");

    runButton.addEventListener("click", runResearch);
    window.addEventListener("load", runResearch);

    async function runResearch() {
      runButton.disabled = true;
      statusEl.textContent = "Running Planner -> Searcher -> Reader -> Writer -> Critic -> Red -> Blue...";
      try {
        const response = await fetch("/api/research", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: questionEl.value })
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Request failed");
        renderPayload(payload);
        statusEl.textContent = payload.success ? "Report ready." : "Pipeline completed with warnings.";
      } catch (error) {
        statusEl.innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      } finally {
        runButton.disabled = false;
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
      document.getElementById("steps").innerHTML = (payload.stepImpacts || []).map(renderStep).join("");
      document.getElementById("citationValidation").textContent =
        JSON.stringify(payload.citationValidation || {}, null, 2);
      document.getElementById("findings").innerHTML = renderFindings(payload.findings || []);
    }

    function renderMetrics(metrics) {
      document.getElementById("metrics").innerHTML = Object.entries(metrics).map(([key, value]) => `
        <div class="metric"><span>${escapeHtml(key)}</span><strong>${escapeHtml(String(value))}</strong></div>
      `).join("");
    }

    function renderStep(step) {
      const metricChips = Object.entries(step.metrics || {}).map(([key, value]) =>
        `<span class="chip">${escapeHtml(key)}: ${escapeHtml(String(value))}</span>`
      ).join("");
      const bullets = (step.bullets || []).slice(0, 6).map(item => `<li>${escapeHtml(item)}</li>`).join("");
      const highlights = (step.highlights || []).filter(group => (group.items || []).length).map(group => `
        <details>
          <summary>${escapeHtml(group.label)}</summary>
          <ul class="list">${group.items.map(item => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>
        </details>
      `).join("");
      const preview = step.outputPreview
        ? `<details><summary>Output preview</summary><pre>${escapeHtml(step.outputPreview)}</pre></details>`
        : "";
      return `
        <article class="step">
          <div class="step-head">
            <div>
              <h3>${escapeHtml(step.title)}</h3>
              <small>${escapeHtml(step.taskId)} / ${escapeHtml(step.agent)}</small>
            </div>
            <span class="badge ${step.success ? "" : "warn"}">${step.success ? "DONE" : "CHECK"}</span>
          </div>
          <p class="impact">${escapeHtml(step.impactOnFinalReport)}</p>
          <div class="chips">${metricChips}</div>
          ${bullets ? `<ul class="list">${bullets}</ul>` : ""}
          ${highlights}
          ${preview}
        </article>
      `;
    }

    function renderFindings(findings) {
      if (!findings.length) return "<p>No findings returned.</p>";
      return findings.map((finding, index) => `
        <article class="step">
          <div class="step-head">
            <h3>Finding ${index + 1}</h3>
            <span class="badge">${escapeHtml(finding.citationId || "source")}</span>
          </div>
          <p><strong>Claim:</strong> ${escapeHtml(finding.claim || "")}</p>
          <p><strong>Evidence:</strong> ${escapeHtml(finding.evidence || "")}</p>
          <small>${escapeHtml(finding.sourceUrl || "")}</small>
        </article>
      `).join("");
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
        if path != "/api/research":
            self.send_error(404, "Not found")
            return
        try:
            body = self._read_json_body()
            payload = build_report_workbench_payload(body.get("question", DEFAULT_QUESTION))
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

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_server(host: str = "127.0.0.1", port: int | None = None) -> None:
    selected_port = port or int(os.environ.get("DEEP_RESEARCH_WEB_PORT", "18181"))
    server = ThreadingHTTPServer((host, selected_port), ReportWorkbenchHandler)
    print(f"DeepResearch Report Workbench started at http://{host}:{selected_port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
