# DeepResearchAgent

[English](#english) | [中文](#中文)

---

## English

DeepResearchAgent is a local multi-agent research workflow that turns a research question into a structured Markdown report.

It demonstrates how a research task can be split across specialized agents:

- `PlannerAgent` creates sub-questions, search queries, and expected report sections.
- `SearcherAgent` gathers candidate search results.
- `ReaderAgent` converts sources into grounded findings with citation IDs.
- `WriterAgent` drafts the initial Markdown report.
- `CriticAgent` checks report structure, references, and citation grounding.
- `RedAgent` turns quality problems into structured review issues.
- `BlueAgent` revises the draft and produces the final report.

The default mode is deterministic and local. It can run without external API keys.

### Features

- Multi-agent research pipeline
- DAG-style task orchestration
- Markdown report generation
- Initial draft vs final report comparison
- Citation grounding and validation
- Red/Blue review and revision flow
- Local tests and evaluation utilities
- Browser-based visual report workbench
- Optional OpenAI-compatible LLM configuration
- Optional web search provider configuration

### Project Structure

```text
agents/          Agent roles: planner, searcher, reader, writer, critic, red, blue
compression/     Context compression helpers
core/            Dataclass schemas and configuration
evaluation/      Local evaluation utilities
examples/        Example inputs
memory/          Shared memory and optional vector memory helpers
orchestrator/    DAG graph, executor, checkpoint, and pipeline runner
prompts/         Prompt templates
search/          Search provider abstractions
tests/           Unit tests
tools/           Citation and fetch/search tools
main.py          CLI demo entry
report_workbench.py  Browser report workbench
```

### Quick Start

```powershell
cd "F:\All projects\deep-research-agent"
python -m unittest tests.test_report_workbench
python report_workbench.py
```

Open:

```text
http://127.0.0.1:18181
```

Enter a research question and click `Run Report`.

### Visual Report Workbench

The browser workbench shows more than a simple test result. It displays:

- Final report
- Initial draft
- Review diff
- Pipeline impact for every agent step
- Findings and citations
- Citation validation output

API endpoints:

```text
GET  /api/health
POST /api/research
```

Example request:

```json
{
  "question": "How should teams evaluate agentic research tools?"
}
```

### CLI Demo

```powershell
python main.py
```

Optional Red/Blue loop:

```powershell
python main.py --red-blue-loop
```

### Tests

Run the focused workbench test:

```powershell
python -m unittest tests.test_report_workbench
```

Run all tests:

```powershell
python -m unittest discover -s tests
```

### Configuration

Copy the example environment file if you want local configuration:

```powershell
Copy-Item .env.example .env
```

Do not commit `.env`.

The default local mode does not require an API key.

Optional LLM mode:

```powershell
$env:DEEP_RESEARCH_USE_LLM="1"
$env:DEEP_RESEARCH_LLM_MODEL="your-model-name"
$env:DEEP_RESEARCH_LLM_API_KEY="your-api-key"
$env:DEEP_RESEARCH_LLM_BASE_URL="https://api.openai.com/v1"
```

### Docker

Build:

```powershell
docker build -t deep-research-agent .
```

Run:

```powershell
docker run --rm -p 18181:18181 deep-research-agent
```

Open:

```text
http://127.0.0.1:18181
```

### Current Scope

This is a local research workflow prototype. It is not a production SaaS system.

Current boundaries:

- No authentication system
- No hosted deployment
- No production monitoring
- Default search/fetch behavior is deterministic and local unless configured otherwise
- Optional LLM and real search integrations require your own environment variables

---

## 中文

DeepResearchAgent 是一个本地多 Agent 研究工作流项目，可以把一个研究问题转换成结构化 Markdown 报告。

它展示了如何把研究任务拆给多个不同职责的 Agent：

- `PlannerAgent`：生成子问题、搜索词和预期报告章节。
- `SearcherAgent`：生成或获取候选搜索结果。
- `ReaderAgent`：把资料来源转换成带 citation ID 的 findings。
- `WriterAgent`：生成第一版 Markdown 报告。
- `CriticAgent`：检查报告结构、References 和 citation grounding。
- `RedAgent`：把质量问题转换成结构化 review issue。
- `BlueAgent`：根据 review issue 修订初稿，生成最终报告。

项目默认是本地确定性模式，不需要外部 API Key 也能运行。

### 功能特点

- 多 Agent 研究工作流
- DAG 风格任务编排
- Markdown 报告生成
- 初稿和最终报告对比
- Citation grounding 和引用校验
- Red/Blue 审查与修订链路
- 本地测试和评测工具
- 浏览器可视化报告工作台
- 可选 OpenAI-compatible LLM 配置
- 可选 Web Search Provider 配置

### 项目结构

```text
agents/          各类 Agent：planner、searcher、reader、writer、critic、red、blue
compression/     上下文压缩工具
core/            dataclass 数据模型和配置
evaluation/      本地评测工具
examples/        示例输入
memory/          共享记忆和可选向量记忆
orchestrator/    DAG、executor、checkpoint、pipeline runner
prompts/         prompt 模板
search/          搜索 provider 抽象
tests/           单元测试
tools/           citation、fetch/search 工具
main.py          CLI demo 入口
report_workbench.py  浏览器报告工作台
```

### 快速开始

```powershell
cd "F:\All projects\deep-research-agent"
python -m unittest tests.test_report_workbench
python report_workbench.py
```

浏览器打开：

```text
http://127.0.0.1:18181
```

输入研究问题，点击 `Run Report`。

### 可视化报告工作台

这个页面不是只显示 `test passed`，而是会展示完整研究链路：

- 最终报告
- Writer 初稿
- 初稿和最终报告 diff
- 每个 Agent 对最终报告的贡献
- Findings 和 citations
- Citation validation 结果

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

### 命令行 Demo

```powershell
python main.py
```

可选 Red/Blue 多轮审查：

```powershell
python main.py --red-blue-loop
```

### 测试

运行报告工作台测试：

```powershell
python -m unittest tests.test_report_workbench
```

运行全部测试：

```powershell
python -m unittest discover -s tests
```

### 配置

如果需要本地配置，可以复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

不要提交 `.env`。

默认本地模式不需要 API Key。

可选 LLM 模式：

```powershell
$env:DEEP_RESEARCH_USE_LLM="1"
$env:DEEP_RESEARCH_LLM_MODEL="your-model-name"
$env:DEEP_RESEARCH_LLM_API_KEY="your-api-key"
$env:DEEP_RESEARCH_LLM_BASE_URL="https://api.openai.com/v1"
```

### Docker

构建：

```powershell
docker build -t deep-research-agent .
```

运行：

```powershell
docker run --rm -p 18181:18181 deep-research-agent
```

浏览器打开：

```text
http://127.0.0.1:18181
```

### 当前边界

这是一个本地研究工作流 prototype，不是生产级 SaaS 系统。

当前边界：

- 没有鉴权系统
- 没有线上托管部署
- 没有生产级监控
- 默认搜索和抓取是本地确定性行为，除非手动配置真实 provider
- 可选 LLM 和真实搜索集成需要你自己的环境变量
