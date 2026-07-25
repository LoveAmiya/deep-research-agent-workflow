# DeepResearchAgent

[English](#english) | [中文](#中文)

---

## English

DeepResearchAgent is a local-first multi-agent research pipeline that turns open-ended questions into structured Markdown reports with visible planning, evidence extraction, critique, and revision artifacts.

The workflow coordinates specialized agents for planning, retrieval, reading, drafting, review, and refinement. A browser workbench makes the full report-generation process inspectable, including the initial draft, final report, agent contributions, citations, and validation output.

### Highlights

- Multi-agent research workflow
- Planner, searcher, reader, writer, critic, red-team, and blue-team roles
- DAG-style orchestration with checkpoint-friendly execution
- Structured Markdown report generation
- Initial-draft and final-report comparison
- Citation IDs, references, and grounding validation
- Browser report workbench with step-by-step pipeline visibility
- Deterministic local mode that runs without API keys
- Optional OpenAI-compatible LLM configuration
- Optional external search provider configuration
- Docker support

### Repository Layout

```text
agents/               Agent role implementations
compression/          Context compression utilities
core/                 Dataclass schemas and configuration
evaluation/           Local evaluation utilities
examples/             Example research inputs
memory/               Shared memory and optional vector-memory helpers
orchestrator/         DAG graph, executor, checkpoints, and pipeline runner
prompts/              Prompt templates
search/               Search provider abstractions
tests/                Unit tests
tools/                Citation and fetch/search utilities
main.py               CLI entry point
report_workbench.py   Browser report workbench
```

### Getting Started

```powershell
git clone https://github.com/LoveAmiya/deep-research-agent-workflow.git
cd deep-research-agent-workflow
python -m unittest tests.test_report_workbench
python report_workbench.py
```

Open the workbench at:

```text
http://127.0.0.1:18181
```

Enter a research question and run the pipeline from the browser.

### Browser Workbench

The workbench exposes the research process as inspectable artifacts:

- Final report
- Initial draft
- Draft-to-final revision diff
- Per-agent pipeline impact
- At least two visible Red/Blue review handoffs
- Findings and citation IDs
- Citation validation result
- Readable agent summaries, progress events, and a validated final-report stream

The browser workbench does not render raw agent JSON or model output previews.
The JSON API and SSE stream remain the machine-facing contracts; normal payloads
contain agent summaries, metrics, review results, and reports rather than raw
model input/output.

API endpoints:

```text
GET  /api/health
POST /api/research
POST /api/research/stream
```

Example request:

```json
{
  "question": "How should teams evaluate agentic research tools?"
}
```

### CLI Usage

```powershell
python main.py
```

Run with the Red/Blue review loop:

```powershell
python main.py --red-blue-loop
```

### Tests

Run the workbench test:

```powershell
python -m unittest tests.test_report_workbench
```

Run the full test suite:

```powershell
python -m unittest discover -s tests
```

### Configuration

Create a local environment file from the template when external providers are needed:

```powershell
Copy-Item .env.example .env
```

The default local workflow runs without API keys. Optional LLM mode can be enabled with:

```powershell
$env:DEEP_RESEARCH_USE_LLM="1"
$env:DEEP_RESEARCH_LLM_MODEL="your-model-name"
$env:DEEP_RESEARCH_LLM_API_KEY="your-api-key"
$env:DEEP_RESEARCH_LLM_BASE_URL="https://api.openai.com/v1"
```

Keep `.env` out of version control.

### Docker

```powershell
docker build -t deep-research-agent .
docker run --rm -p 18181:18181 deep-research-agent
```

Open:

```text
http://127.0.0.1:18181
```

### Pipeline Overview

```text
Question
  -> PlannerAgent
  -> SearcherAgent
  -> ReaderAgent
  -> WriterAgent
  -> CriticAgent
  -> RedAgent
  -> BlueAgent
  -> Final Markdown Report
```

---

## 中文

DeepResearchAgent 是一个本地优先的多 Agent 研究工作流，可以把开放式研究问题转换成结构化 Markdown 报告，并展示规划、证据提取、审查和修订过程。

工作流由多个专门 Agent 协作完成，包括规划、检索、阅读、撰写、审查和修订。浏览器工作台会展示报告生成过程中的关键中间产物，包括初稿、最终报告、Agent 贡献、引用信息和校验结果。

### 项目亮点

- 多 Agent 研究工作流
- 包含 planner、searcher、reader、writer、critic、red-team、blue-team 等角色
- DAG 风格任务编排，支持 checkpoint 友好的执行方式
- 结构化 Markdown 报告生成
- 初稿与最终报告对比
- Citation ID、References 和引用校验
- 浏览器报告工作台，可查看每一步产物
- 默认本地确定性模式，不需要 API Key
- 可选 OpenAI-compatible LLM 配置
- 可选外部搜索 provider 配置
- 支持 Docker 运行

### 项目结构

```text
agents/               Agent 角色实现
compression/          上下文压缩工具
core/                 Dataclass 数据结构和配置
evaluation/           本地评测工具
examples/             示例研究输入
memory/               共享记忆和可选向量记忆工具
orchestrator/         DAG、执行器、checkpoint 和 pipeline runner
prompts/              Prompt 模板
search/               搜索 provider 抽象
tests/                单元测试
tools/                Citation 和 fetch/search 工具
main.py               命令行入口
report_workbench.py   浏览器报告工作台
```

### 快速开始

```powershell
git clone https://github.com/LoveAmiya/deep-research-agent-workflow.git
cd deep-research-agent-workflow
python -m unittest tests.test_report_workbench
python report_workbench.py
```

浏览器打开：

```text
http://127.0.0.1:18181
```

输入研究问题后，可以直接在页面中运行完整 pipeline。

### 浏览器工作台

工作台会把研究流程拆成可查看的中间产物：

- 最终报告
- 初始草稿
- 初稿到最终稿的修订 diff
- 每个 Agent 对 pipeline 的贡献
- Findings 和 Citation ID
- 引用校验结果
- 便于调试和集成的 API 响应

接口：

```text
GET  /api/health
POST /api/research
```

请求示例：

```json
{
  "question": "How should teams evaluate agentic research tools?"
}
```

### 命令行使用

```powershell
python main.py
```

启用 Red/Blue 审查修订链路：

```powershell
python main.py --red-blue-loop
```

### 测试

运行工作台测试：

```powershell
python -m unittest tests.test_report_workbench
```

运行完整测试：

```powershell
python -m unittest discover -s tests
```

### 配置

如需接入外部 provider，可以从模板创建本地环境变量文件：

```powershell
Copy-Item .env.example .env
```

默认本地工作流不需要 API Key。可选 LLM 模式可以通过以下环境变量启用：

```powershell
$env:DEEP_RESEARCH_USE_LLM="1"
$env:DEEP_RESEARCH_LLM_MODEL="your-model-name"
$env:DEEP_RESEARCH_LLM_API_KEY="your-api-key"
$env:DEEP_RESEARCH_LLM_BASE_URL="https://api.openai.com/v1"
```

不要把 `.env` 提交到版本库。

### Docker

```powershell
docker build -t deep-research-agent .
docker run --rm -p 18181:18181 deep-research-agent
```

浏览器打开：

```text
http://127.0.0.1:18181
```

### Pipeline 概览

```text
Question
  -> PlannerAgent
  -> SearcherAgent
  -> ReaderAgent
  -> WriterAgent
  -> CriticAgent
  -> RedAgent
  -> BlueAgent
  -> Final Markdown Report
```
