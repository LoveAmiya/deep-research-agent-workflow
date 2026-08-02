# DeepResearch 启动手册

本手册对应远程 `main` 当前版本。系统展示真实的运行内 Agent 工件交接、多轮 Red/Blue 审查和 SSE 工作台；它没有内置或公开真实语料数据源。

## 最短启动路径

在仓库根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\test-local.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_workbench.ps1
```

浏览器打开 <http://127.0.0.1:18181/>。默认确定性模式不需要 API Key；它用于演示协作流程，不应把生成内容当作已核验研究结论。

## 1. 确认当前版本

```powershell
git switch main
git pull --ff-only
git status --short --branch
```

应看到当前分支为 `main`，并且工作区没有意外修改。

## 2. 检查 Python

```powershell
python --version
```

建议使用 Python 3.11 或更高版本。当前项目没有必须安装的第三方依赖。

## 3. 先运行测试

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_tests.ps1
```

也可以分别运行：

```powershell
python -m unittest tests.test_report_workbench
python -m unittest discover -s tests -p "test_*.py"
```

测试验证协作账本、Agent 工件依赖、Red/Blue 轮次、SSE 顺序、报告结构、mock 隔离，以及网页抓取的 SSRF、重定向和响应大小边界。截至 2026-08-02，完整测试集为 `328/328` 通过。测试通过不代表外部网站一定可访问。

## 4. 启动浏览器工作台

默认端口：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_workbench.ps1
```

浏览器打开：<http://127.0.0.1:18181/>

指定端口：

```powershell
$env:DEEP_RESEARCH_WEB_PORT="18183"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_workbench.ps1
```

浏览器打开：<http://127.0.0.1:18183/>

如果端口已被占用：

```powershell
Get-NetTCPConnection -LocalPort 18183 -State Listen
```

换一个未占用端口启动即可，不要随意结束来源不明的进程。

## 5. 可选：配置模型

```powershell
Copy-Item .env.example .env
```

在 `.env` 中至少填写：

```dotenv
DEEP_RESEARCH_USE_LLM=1
DEEP_RESEARCH_LLM_MODEL=<your-model-name>
DEEP_RESEARCH_LLM_API_KEY=<your-api-key>
DEEP_RESEARCH_LLM_BASE_URL=https://api.openai.com/v1
```

模型配置由工作台在收到研究请求时加载，所以修改 `.env` 后通常应重启服务再测试。不要把 `.env`、API Key 或服务日志提交到 Git。

远程仓库和 Docker 镜像只发布源码、测试、文档与空值配置模板。抓取语料、`data/`、`runs/`、
SQLite、评测输出和日志全部留在本机。

模型只负责规划、写作和审查。配置 API Key 不会自动提供真实网页证据。

## 6. 页面正确表现

点击“生成报告”后，页面应依次出现：

1. Planner、Searcher、Reader 等 Agent 的实时状态。
2. Writer 初始草稿逐段显示。
3. Critic 审查状态。
4. 第一轮、第二轮以及可能的第三轮 Red/Blue 审查内容。
5. 模型超时时，对应节点显示“已用本地规则完成”，而不是一直停在“运行中”或“等待”。
6. 页面最终提示任务已经完成，并说明需要重点复核哪些降级步骤；不会展示原始异常、密钥或本机路径。
7. Red 的具体问题、依据与建议。
8. Blue 的修改原因、修改前内容和修改后内容。
9. Agent 交接卡片中的工件名称、摘要、接收动作和状态。
10. 校验后的最终报告。
11. 有真实 Evidence 时显示来源、摘录、链接和字符位置。

后端仍使用 JSON/SSE 作为机器协议，但普通页面不显示原始 Agent JSON。

## 7. 关于 mock 和真实引用

当前浏览器工作台的数据源升级不在本分支范围内：

- 默认确定性来源用于演示 Agent 协作。
- `mock://` 不会进入正式 References。
- 没有真实来源时，引用校验必须显示“需复查”。
- 页面可能展示“不可引用的本地分析线索”，但不能把它当成真实研究结论。
- 配置 LLM 不能替代来源采集，也不能把模型生成文字变成 Evidence。

因此，当前分支适合展示多 Agent 协作和报告审查，不应宣传为已经具备生产级真实数据覆盖。

## 8. API 检查

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18181/api/health
```

接口：

```text
GET  /api/health
POST /api/research
POST /api/research/stream
```

浏览器默认使用 `/api/research/stream`。如果页面点击后没有反应，优先检查浏览器控制台、服务终端和 health 接口。

## 9. 常见问题

### 点击后没有反应

1. 确认 health 接口返回 `ok: true`。
2. 确认浏览器地址与实际启动端口一致。
3. 查看启动终端是否出现模型认证、超时或连接错误。
4. 运行 `python -m unittest tests.test_report_workbench` 排除前后端契约回归。

### 报告一下全部出现

模型或确定性路径可能很快，但前端仍会按 SSE 队列显示 Writer、Red/Blue 和最终报告。若完全没有中间状态，检查请求是否确实访问 `/api/research/stream`，并检查浏览器控制台错误。

### 没有 References

这通常表示没有获得真实可验证来源。系统会剔除 mock 引用，这是预期的可信降级，不应通过伪造 References 解决。

### API 额度消耗过快

一次研究可能调用多个 Agent，并包含至少两轮 Red/Blue。测试真实模型前先运行确定性测试；不要为了观察 UI 连续重复提交同一个真实模型任务。

完整说明见 [`README.md`](README.md)。
