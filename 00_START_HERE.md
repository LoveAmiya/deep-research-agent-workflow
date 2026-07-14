# DeepResearch 启动手册

## 项目做什么

这是一个多 Agent 研究报告系统。它把问题依次交给 Planner、Searcher、Reader、Writer、Critic、Red、Blue 等节点，最终输出带引用的 Markdown 报告。

本地浏览器工作台不仅显示“测试通过”，还会显示初稿、终稿、差异、每一步对报告的影响、findings、引用校验与执行 Trace。

## 先测试

```powershell
cd "F:\All projects\deep-research-agent"
python -m unittest tests.test_report_workbench
```

这证明工作台相关的 Payload 构建与报告产物可以正常生成。

## 启动与前端可视化

```powershell
cd "F:\All projects\deep-research-agent"
python report_workbench.py
```

浏览器打开：`http://127.0.0.1:18181`

页面演示顺序：

```text
1. 输入一个研究问题。
2. 点击运行报告。
3. 先看最终报告，再切换初稿与终稿差异。
4. 展开 Agent 步骤，说明每个节点给最终报告提供了什么。
5. 展示 findings、引用与 Citation Validation。
6. 最后展示 Trace，说明失败时可以定位到哪一个节点。
```

可用接口：

```text
GET  /api/health
POST /api/research
```

## 失败先查

```text
1. 当前目录是否为 F:\All projects\deep-research-agent。
2. python --version 是否可用。
3. 终端是否出现缺少模块或依赖的错误。
4. 18181 是否已被其他程序占用。
5. 先跑 focused test，再看浏览器服务。
```

正式介绍见：`README.md`
