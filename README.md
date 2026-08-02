# DeepResearchAgent

[中文](#中文) | [English](#english)

## 中文

DeepResearchAgent 是一个本地优先的多 Agent 研究报告项目。当前版本使用运行级协作账本连接 Planner、Searcher、Reader、Writer、Critic、Red 和 Blue：下游 Agent 消费已发布的工件版本，审查问题经过至少两轮 Red/Blue 修订，浏览器通过 SSE 展示初稿、审查过程与最终报告。

> 当前边界：当前版本升级的是协作、报告和工作台，不包含或公开新的真实数据源。默认确定性来源只用于演示流程，不能作为研究引用；`mock://` 来源会从正式报告和引用校验中移除。没有真实来源时，页面会明确显示“需复查”，不会把模拟内容标成已验证事实。

### 当前能力

- 运行级 `ResearchLedger`，记录版本化工件、依赖、消费回执和 Agent 交接。
- Planner -> Searcher -> Reader -> Writer -> Critic -> Red -> Blue 协作 DAG。
- Writer 初稿、Red/Blue 审查文本和最终报告的可读 SSE 流。
- 至少两轮、最多三轮 Red/Blue 审查；问题、依据、建议和修改前后内容可见。
- 中文优先的完整报告结构：研究背景、关键发现、分析与讨论、研究限制、行动建议、结论、参考来源。
- 证据充分时选择 5-8 条互不重复的关键发现；证据不足时不会凑数或伪造引用。
- 引用校验展示 Citation、Evidence、来源标题、原文链接、摘录和字符位置。
- 后端继续使用结构化对象和 JSON/SSE 协议，普通界面不展示原始 Agent JSON。
- 无 API Key 的确定性演示模式，以及可选的 OpenAI-compatible LLM 模式。
- 模型流在收到 `[DONE]` 或 `response.completed` 后立即结束，避免报告已经生成但 Agent 仍显示运行中。
- 单次任务发生模型传输超时后停止重复调用；Critic、Red、Blue 会用本地规则完成并显示明确的降级状态。
- 网页抓取只允许无凭据的公网 HTTP(S) 地址，拒绝本机/私网/保留地址和所有重定向；响应默认限制为 2 MiB。
- 对外错误只返回稳定的安全提示，内部异常、密钥和本机路径不会出现在浏览器响应中。

### 当前本机演示验收

截至 2026-08-02，当前公开 inventory 发现 `333` 项测试，分为 L0 单元/契约 `74`、L1 Agent 编排 `129`、L2 评测质量 `62`、L3 韧性/安全 `62`、L4 真实模型 smoke `6`。针对“Critic 超时后 Blue 长时间运行”的回归测试会验证：任务仍能结束、后续节点显示“已用本地规则完成”、公开 Payload 不含原始超时异常，并且同一工件交接不会重复展示；抓取测试还覆盖 SSRF、非 HTTP(S) URL、重定向、超大响应拒绝和仓库数据隔离。

### 快速启动

要求：Python 3.11 或更高版本。当前版本没有必须安装的第三方 Python 包。

```powershell
git clone https://github.com/LoveAmiya/deep-research-agent-workflow.git
cd deep-research-agent-workflow
python -m unittest tests.test_report_workbench
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_workbench.ps1
```

浏览器打开：<http://127.0.0.1:18181/>

使用其他端口：

```powershell
$env:DEEP_RESEARCH_WEB_PORT="18183"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_workbench.ps1
```

`DEEP_RESEARCH_WEB_PORT` 必须在启动进程前设置；`.env` 主要由模型和命令行配置加载，不负责修改已经启动的监听端口。

服务默认只监听 `127.0.0.1`，每个问题最多 4,000 字符、请求体最多 16 KiB，默认最多同时运行 2 个研究任务且单任务等待上限为 300 秒。非回环监听必须同时设置 `DEEP_RESEARCH_ACCESS_TOKEN`，页面中的令牌只保存在当前内存，不写入浏览器存储。

### LLM 配置

复制配置模板：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```dotenv
DEEP_RESEARCH_USE_LLM=1
DEEP_RESEARCH_LLM_MODEL=<your-model-name>
DEEP_RESEARCH_LLM_API_KEY=<your-api-key>
DEEP_RESEARCH_LLM_BASE_URL=https://api.openai.com/v1
DEEP_RESEARCH_LLM_WIRE_API=chat_completions
```

工作台收到请求时会加载 `.env`。只有 `enabled`、模型名称和 API Key 均有效时才调用模型；否则进入确定性演示模式。不要提交 `.env`。

### 仓库隐私边界

远程仓库只包含源码、测试、文档和空值配置模板。`.env`、API Key、抓取内容、语料、SQLite、
运行记录、评测输出和日志均由 `.gitignore` 与 `.dockerignore` 排除，不能提交、推送或打进镜像。

### 工作台中会看到什么

1. Agent 实时状态和当前处理动作。
2. Writer 初始草稿流。
3. Red/Blue 第一轮、第二轮以及可能的第三轮审查流。
4. 每轮 Red 问题、证据、建议，以及 Blue 的修改原因和修改前后内容。
5. Agent 之间交接的工件名称、内容摘要、接收动作和处理状态。
6. 通过最终校验后发布的完整报告。
7. 可点击的引用和证据来源详情；没有真实证据时显示明确的降级原因。

SSE 不是把 Agent JSON token 直接输出到黑框。后端发送结构化事件，前端只渲染用户可理解的初稿、审查内容、交接摘要和最终报告。

### API

```text
GET  /api/health
GET  /api/research/status
POST /api/research
POST /api/research/stream
POST /api/research/cancel
```

请求体：

```json
{
  "question": "影响企业采用开源 LLM 的主要因素有哪些？"
}
```

`/api/research` 一次返回完整 JSON；`/api/research/stream` 返回有限时长的 SSE 事件流，并在 `run_completed` 后关闭连接。兼容字段包括 `finalReportMarkdown`、`citationValidation` 等；协作字段包括 `ledgerSummary`、`handoffs` 和 `reviewRounds`。

失败响应统一为 `{"error":{"code":"...","message":"..."}}`。流式响应通过 `X-Research-Request-Id` 返回任务 ID，取消接口接收 `{"requestId":"..."}`。

### 数据来源说明

- 浏览器工作台当前默认使用确定性演示来源，没有接入本期排除的真实语料库或稳定搜索服务。
- 配置 LLM 只会改善规划、写作和审查，不会把模型生成内容变成真实 Evidence。
- CLI 保留可选网页搜索配置；网页搜索可用性和来源质量不属于本分支的验收范围。
- 搜索摘要、mock、抓取失败内容和模型自写内容不得进入公开的正式引用。
- 因此，本分支主要用于展示多 Agent 协作、报告生成、审查闭环和引用边界，而不是宣称已经具备生产级研究数据覆盖。

### CLI

```powershell
python main.py
python main.py --red-blue-loop
```

CLI 会加载 `.env`，并支持搜索、异步 DAG、checkpoint 和运行存储等实验配置。它与浏览器工作台共享 Agent 和编排代码，但输出形式不同。

### 测试

```powershell
# 工作台与 SSE/协作集成测试
python -m unittest tests.test_report_workbench

# 完整测试集
python -m unittest discover -s tests -p "test_*.py"

# 项目脚本
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_tests.ps1
```

测试通过证明协议、协作、报告结构和降级逻辑符合断言，不等价于外部来源可访问或报告事实已被真实世界验证。

### Docker

```powershell
docker build -t deep-research-agent .
docker run --rm -p 127.0.0.1:18181:18181 -e DEEP_RESEARCH_ACCESS_TOKEN=choose-a-local-token deep-research-agent
```

容器内部监听 `0.0.0.0`，因此必须提供访问令牌；宿主端口只映射到 `127.0.0.1`。Docker 默认运行确定性演示模式。启用模型时使用 `--env-file` 注入配置，不要把密钥写入镜像。

### 架构

```text
Research question
  -> Planner publishes research brief
  -> Searcher consumes brief and publishes candidate sources
  -> Reader consumes sources and publishes approved findings
  -> Writer consumes findings and publishes initial report
  -> Critic publishes structural and evidence review
  -> Red publishes locatable review issues
  -> Blue consumes issues and publishes a revised report version
  -> Red/Blue loop repeats when needed
  -> Citation validation
  -> Final report
```

所有交接均写入单次运行的 `ResearchLedger`。账本不跨研究问题提供长期记忆，也不是语料数据库。

### 项目结构

```text
agents/               Agent 角色、Critic 和 Red/Blue 循环
core/                 配置、Schema 和 LLM 客户端
memory/               SharedMemory、ResearchLedger 和持久化工具
orchestrator/         DAG、执行器、checkpoint 和协作 pipeline
prompts/              Agent 提示词
search/               可选搜索 provider 抽象
tests/                单元与集成测试
tools/                引用、抓取和搜索工具
main.py               CLI 入口
report_workbench.py   浏览器工作台与 API/SSE 服务
```

架构决策见 [`docs/decisions/001-run-scoped-collaboration-ledger.md`](docs/decisions/001-run-scoped-collaboration-ledger.md)。

## English

DeepResearchAgent is a local-first multi-agent research report project. Agents exchange versioned artifacts through a run-scoped `ResearchLedger`, Red/Blue review runs for at least two visible rounds, and the browser streams the Writer draft, review transcript, and validated final report through readable SSE events.

This version improves collaboration and report UX; it does not bundle or publish a production-grade evidence source. Deterministic `mock://` sources are demo-only and are removed from public references and successful citation validation.

### Start

```powershell
git clone https://github.com/LoveAmiya/deep-research-agent-workflow.git
cd deep-research-agent-workflow
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_tests.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_workbench.ps1
```

Open <http://127.0.0.1:18181/>. Set `DEEP_RESEARCH_WEB_PORT` in the process environment before startup to use another port.

### Local live-model report smoke

The normal workbench remains deterministic when no LLM configuration is present.
To verify the full local model-backed workbench without saving a key in the
repository, keep `OPENAI_API_KEY` in the Windows user or current-process
environment and run:

```powershell
$env:DEEP_RESEARCH_LLM_API_KEY = $env:OPENAI_API_KEY
$env:DEEP_RESEARCH_LLM_MODEL = $env:OPENAI_MODEL
$env:DEEP_RESEARCH_LLM_BASE_URL = "https://crs.ruinique.com"
$env:DEEP_RESEARCH_LLM_WIRE_API = "responses"
$env:DEEP_RESEARCH_LLM_REASONING_EFFORT = "medium"
python .\evaluation\run_live_report_smoke.py
```

Dedicated `DEEP_RESEARCH_LLM_*` values take precedence. If they are absent,
the smoke script reads the compatible `OPENAI_*` environment values and uses
the configured relay instead of persisting credentials. Its sanitized result is
ignored by Git. The check requires all seven model workbench stages, two
Red/Blue review rounds, a final report, and citation-shape validation. It does
not claim that deterministic or `mock://` source material is externally
verified evidence.

Keep the live smoke at `medium`; it deliberately does not inherit an unrelated
`OPENAI_REASONING_EFFORT` value. Use another reasoning level only as an explicit,
one-off manual override when you have accepted the additional latency.

Verified locally on 2026-08-02: the public inventory discovered `333` tests across five layers. The live local report smoke completed `9` model calls with `0` fallbacks, generated a 2,175-character report, completed `2` review rounds, and passed citation-shape validation.

### Main contracts

```text
GET  /api/health
POST /api/research
POST /api/research/stream
```

The backend keeps structured JSON and SSE contracts. The normal UI renders readable agent status, handoffs, reports, review details, and citation evidence instead of raw model JSON.
Web fetching accepts credential-free public HTTP(S) URLs only, rejects local/private/reserved addresses and redirects, and limits responses to 2 MiB by default through `DEEP_RESEARCH_FETCH_MAX_BYTES`.
The remote repository and container context exclude `.env`, credentials, fetched corpora, databases, run artifacts, evaluation outputs, and logs.

