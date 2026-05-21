# DeepResearchAgent 接口与入口说明

本文只根据当前仓库真实代码整理。当前项目功能终点是 Phase 24，没有发现 Phase 25；当前仓库没有 FastAPI、Flask、HTTP server、OpenAPI route 或独立后台服务入口。

## 一、接口总览

| 入口名称 | 文件路径 | 调用方式 | 所属链路 | 作用 | 输入 | 输出 | 是否主链路必需 | 面试一句话讲法 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Demo CLI 主入口 | `main.py` | `python main.py` | 主研究链路 | 运行内置 demo question，加载 `.env`，选择同步或异步 DAG，打印报告和运行元数据 | 内置 `DEMO_QUESTION`、环境变量 | 控制台输出 run id、checkpoint/search/citation/Red-Blue 状态和 markdown report | 可选；Python API 可替代 | `main.py` 是演示入口，把配置、pipeline 和报告输出串起来。 |
| Demo Resume 入口 | `main.py` | `python main.py --resume <run_id>` | 主研究链路 | 从 `runs/checkpoints` 读取 JSON checkpoint，跳过已成功节点 | checkpoint run id | 恢复后的报告、resume metadata、跳过和重跑节点数 | 否 | resume 入口展示 DAG 节点级断点恢复，不是重新规划系统。 |
| Demo Red-Blue Loop 入口 | `main.py` | `python main.py --red-blue-loop` | Red-Blue 对抗修复链路 | 在 demo 中强制启用多轮 Red/Blue 修复 loop | CLI flag、内置问题 | loop round 数、stop reason、convergence status、final report | 否 | 这个 flag 用来演示 bounded Red-Blue 修复，而不是默认每次都多轮对抗。 |
| Demo Async DAG 入口 | `main.py` | 设置 `DEEP_RESEARCH_USE_ASYNC_DAG=1` 后运行 `python main.py` | 主研究链路 | 使用 `AsyncDAGExecutor` 跑同一套研究组件 | 环境变量、内置问题 | 与同步 demo 兼容的报告和元数据 | 否；同步 executor 是默认 | 异步入口复用主链路，只替换调度器。 |
| Demo 构建函数 | `main.py::build_demo_execution` | `from main import build_demo_execution` | Demo / Debug 链路 | 供测试或调试直接构造一次 demo execution | `load_dotenv`、`resume_from_run_id`、`red_blue_loop_enabled` | 包含 report、memory、execution、config 的 dict | 否 | 这是 demo 的 Python helper，方便绕过控制台直接拿结果对象。 |
| Demo 报告 helper | `main.py::build_demo_report` | `from main import build_demo_report` | Demo / Debug 链路 | 返回 demo 最终报告 markdown | 无显式参数 | `str` markdown | 否 | 这是轻量调试入口，只拿最终报告文本。 |
| 同步研究 Pipeline API | `orchestrator/research_pipeline.py::run_research_pipeline` | `run_research_pipeline(question_text, ...)` | 主研究链路 | 创建 ResearchQuestion、构建 DAG、执行 Agent、校验 citation、返回完整结果 | 研究问题文本，可选 LLM/search/fetch/checkpoint/replan/vector memory 参数 | result dict，含 `ResearchReport`、findings、memory、traces、citation validation | 是；这是核心主链路 API | 主链路的核心入口是 `run_research_pipeline(...)`，所有 Agent 都通过它进入 DAG。 |
| 异步研究 Pipeline API | `orchestrator/async_research_pipeline.py::async_run_research_pipeline` | `await async_run_research_pipeline(question_text, ...)` | 主研究链路 | 使用 async executor 执行同一套 pipeline components | 研究问题文本、并发数、timeout 和可选组件 | 与同步 pipeline 兼容的 result dict | 否；是替代执行路径 | 异步 API 是主链路的调度增强版，不改变 Agent 职责。 |
| DAG 构图入口 | `orchestrator/research_pipeline.py::build_minimal_research_graph` | `build_minimal_research_graph()` | 主研究链路 | 创建固定任务图：Planner -> Searcher -> Reader -> Writer -> Critic -> Red -> Blue | 无 | `TaskGraph` | 是；由 pipeline 内部调用 | 项目里的 DAG 是显式 TaskGraph，不是隐式函数调用链。 |
| Pipeline 组件构建入口 | `orchestrator/research_pipeline.py::build_research_pipeline_components` | `build_research_pipeline_components(question_text, ...)` | 主研究链路 | 实例化 Agent、SharedMemory、CitationRegistry，并生成 DAG handlers | 研究问题和可选工具 | question、memory、citation_registry、graph、handlers | 是；由 pipeline 内部调用 | 这个函数把 Agent 和 DAG node handler 绑定起来。 |
| Pipeline 结果组装入口 | `orchestrator/research_pipeline.py::build_research_pipeline_result` | `build_research_pipeline_result(...)` | 主研究链路 | 从 executor outputs 组装 final report、Red-Blue loop、citation validation、checkpoint metadata | question、memory、citation registry、execution | 完整 result dict | 是；由 pipeline 内部调用 | 执行结束后，这里把节点输出整理成对外结果。 |
| Writer 报告生成入口 | `agents/writer_agent.py::WriterAgent.run` | 由 DAG handler 调用 | 主研究链路 | 把 question、plan、findings 合成为 markdown `ResearchReport` | `ResearchQuestion`、`ResearchPlan`、`list[Finding]`、可选 `CitationRegistry` | `AgentResult(output=ResearchReport)` | 是 | 真正写初稿报告的是 WriterAgent。 |
| Blue 修订报告入口 | `agents/blue_agent.py::BlueAgent.run` | 由 DAG handler 或 loop 调用 | Red-Blue 对抗修复链路 | 根据 RedReviewResult 修复章节、引用和 citation marker | report、red_review、findings、citation_registry | `BlueRevisionResult`，含 revised report、fixed/remaining issue ids | 是；单轮 Blue 是当前主 DAG 的一部分 | BlueAgent 负责把规则可修的问题落回报告文本。 |
| Red 审查入口 | `agents/red_agent.py::RedAgent.run` | 由 DAG handler 或 loop 调用 | Red-Blue 对抗修复链路 | 检查结构、引用、证据数量、critic issue 等 | report、findings、critic_review、citation_registry | `RedReviewResult`，含 `ReviewIssue` 列表 | 是；单轮 Red 是当前主 DAG 的一部分 | RedAgent 是对抗审查角色，输出结构化问题而不是直接改报告。 |
| Red-Blue 多轮 loop 入口 | `agents/red_blue_loop.py::RedBlueLoopRunner.run` | `RedBlueLoopRunner(...).run(context, report, findings, critic_review)` | Red-Blue 对抗修复链路 | 多轮执行 Red/Blue，并记录 stop reason、summary、convergence metadata | 初稿 report、findings、critic review、loop config | `RedBlueLoopResult` | 否；需显式启用 | 多轮 loop 是可选增强，用于 bounded repair 和可审计停止。 |
| Red-Blue 收敛判断入口 | `agents/red_blue_convergence.py::decide_convergence` | `decide_convergence(snapshot_history, max_rounds, ...)` | Red-Blue 对抗修复链路 | 根据 issue 数、fingerprint、report hash、无改进和震荡检测决定是否停止 | round snapshots、max_rounds、patience、oscillation flag | `RedBlueConvergenceDecision` | 否；loop 内部使用 | 收敛模块让 Red-Blue 停止条件可测试，而不是靠口头描述。 |
| SharedMemory 写入/读取入口 | `memory/store.py::SharedMemory` | `add_record(...)`、`get(...)`、`list_by_type(...)`、`all_items()` | Memory / Context 链路 | 保存一次运行内的 plan、search results、findings、report、review 等中间产物 | item_type、content、source_agent、task_id、metadata | `MemoryItem` 或 item 列表 | 是；主 DAG Agent 默认写入 | SharedMemory 是单次运行内的共享状态和审计记录。 |
| Vector memory 持久化入口 | `memory/integration.py::persist_pipeline_result_to_vector_memory` | `persist_pipeline_result_to_vector_memory(result, store, run_id)` | Memory / Context 链路 | 将 pipeline result 转成 evidence/citation/summary/node_output/failure memory items 并写入 vector store | pipeline result、`SQLiteVectorMemoryStore` | memory id 列表 | 否；需传入 store | vector memory 是可选持久化，不是默认主链路必经步骤。 |
| SQLite vector memory 入口 | `memory/vector_store.py::SQLiteVectorMemoryStore` | `add_item`、`add_items`、`search`、`get_item`、`list_items`、`delete_run_memory` | Memory / Context 链路 | 用 SQLite 存 JSON 向量并做本地 cosine 检索 | `MemoryItem` 或 query text | memory id、`MemorySearchResult`、MemoryItem 列表 | 否 | 这是本地 SQLite 向量记忆，不是外部向量数据库。 |
| Run-level SQLite 持久化入口 | `memory/persistent_store.py::SQLiteRunStore` | `save_run_result`、`load_run`、`list_runs`、`export_run_summary`、`delete_run` | Demo / Debug 链路 | 保存整次运行的报告、summary 和 payload，供调试回放 | pipeline result 或 run id | `RunRecord` 或 summary dict | 否 | RunStore 存的是运行记录，不是语义长期记忆。 |
| Context Compressor 入口 | `compression/compressor.py::ContextCompressor` | `compress`、`compress_from_memory`、`merge_contexts` | Memory / Context 链路 | 对 evidence/memory 做 L1/L2/L3 风格的离线上下文压缩 | query、`list[EvidenceUnit]` 或 memory items、config | `CompressedContext` | 否；当前主链路未默认启用 | 压缩模块是独立可选 API，保留 citation、quote 和 source。 |
| Writer/Reviewer 压缩 helper | `compression/integration.py` | `compress_for_writer(...)`、`compress_for_reviewer(...)` | Memory / Context 链路 | 从 evidence units 或 memory items 生成面向 writer/reviewer 的压缩上下文 | query、evidence_units、memory_items、config | `CompressedContext` | 否 | 这是把压缩模块接到写作/审查场景的适配层。 |
| Mini Evaluation CLI | `evaluation/run_eval.py` | `python -m evaluation.run_eval` | Evaluation 链路 | 加载 `evaluation/cases.jsonl`，运行 pipeline，计算规则指标均值 | mini JSONL cases | 控制台 Eval Summary 和 case results | 否 | 默认评测是本地 deterministic smoke benchmark。 |
| Plus Benchmark CLI | `evaluation/run_eval.py` | `python -m evaluation.run_eval --bench plus` | Evaluation 链路 | 运行 `ResearchBench-mini Plus` 内置 20 个 case | `evaluation/research_bench_plus.py::PLUS_CASES` | Plus summary、domain summary、composite score | 否 | Plus benchmark 扩大了本地评测覆盖面，但不是外部 ResearchBench。 |
| Evaluation report 输出入口 | `evaluation/run_eval.py`、`evaluation/reporting.py` | `python -m evaluation.run_eval --bench plus --output-json ... --output-md ...` | Evaluation 链路 | 将评测结果写成 JSON 和 Markdown | eval result、输出路径 | report 文件 | 否 | 报告输出入口只生成评测报告，不生成研究答案。 |
| Evaluation comparison CLI | `evaluation/run_eval.py` | `python -m evaluation.run_eval --compare baseline.json candidate.json` | Evaluation 链路 | 对齐 case_id，比较 baseline/candidate deltas | 两个 eval result JSON | comparison JSON 到控制台，可选 report 文件 | 否 | comparison 是离线 before/after 对比，不影响 pipeline 运行。 |
| LLM-as-Judge 评测入口 | `evaluation/run_eval.py`、`evaluation/llm_judge.py` | `--enable-judge` 或 `DEEP_RESEARCH_USE_LLM_JUDGE=1` | Evaluation 链路 | 对报告做可选 judge 打分，失败时 fallback | question、report、findings、citation validation、LLM client | `JudgeResult`、judge score summary | 否 | Judge 是可选质量视角，默认不会调用真实 LLM。 |
| Red-Blue comparison CLI | `evaluation/run_eval.py` | `python -m evaluation.run_eval --bench plus --compare-red-blue` | Evaluation 链路 | Plus cases 跑两遍：Red-Blue disabled vs enabled，然后比较 | Plus cases、可选 judge | baseline/candidate/comparison dict | 否 | 这是评测 Red-Blue 开关效果的离线实验入口。 |
| Statistical comparison CLI | `evaluation/run_eval.py` | `python -m evaluation.run_eval --compare baseline.json candidate.json --stats` | Statistical Evaluation 链路 | 在 comparison 上增加 bootstrap CI 和 paired Cohen's d | 两个 eval result JSON、metric、bootstrap 参数 | comparison JSON，含 `statistical_summary` | 否 | Phase 24 统计评测是离线增强，不影响报告生成。 |
| Red-Blue statistical comparison CLI | `evaluation/run_eval.py` | `python -m evaluation.run_eval --bench plus --compare-red-blue --stats` | Statistical Evaluation 链路 | 自动跑 Red-Blue disabled/enabled Plus 对比并加统计摘要 | Plus cases、stats 参数 | comparison、statistical_summary | 否 | 这是用统计摘要解释 Red-Blue 策略差异是否稳定。 |
| Mini evaluation Python API | `evaluation/run_eval.py::run_eval` | `run_eval(cases_path="evaluation/cases.jsonl")` | Evaluation 链路 | 以函数方式运行 mini cases | cases JSONL 路径 | `{"summary": ..., "results": ...}` | 否 | 评测 CLI 底层就是这个 API。 |
| Plus evaluation Python API | `evaluation/run_eval.py::run_plus_eval` | `run_plus_eval(judge_evaluator=None, use_red_blue_loop=False)` | Evaluation 链路 | 以函数方式运行 Plus benchmark | judge evaluator、Red-Blue loop flag | run id、benchmark summary、case results | 否 | Plus API 支持在代码里做本地 benchmark。 |
| Evaluation comparison API | `evaluation/comparison.py::compare_evaluation_results` | `compare_evaluation_results(baseline, candidate, include_statistics=...)` | Evaluation 链路 | 比较两个评测结果，可选调用统计模块 | 两个 eval result dict | `EvaluationComparison` | 否 | 对比模块负责 case 对齐和 delta 汇总。 |
| Statistical API | `evaluation/statistics.py` | `bootstrap_mean_ci`、`paired_bootstrap_delta_ci`、`paired_cohens_d`、`build_statistical_comparison` | Statistical Evaluation 链路 | 计算均值 CI、配对 delta CI、配对 Cohen's dz 和综合统计比较 | 数值列表或两个 eval result dict | `BootstrapCI`、`EffectSizeSummary`、`StatisticalComparison` | 否 | Phase 24 的核心 API 在 `statistics.py`，完全离线、无依赖。 |
| ResearchBench-mini loader | `evaluation/run_eval.py::load_cases` | `load_cases("evaluation/cases.jsonl")` | Evaluation 链路 | 从 JSONL 加载 mini cases | JSONL 路径 | list[dict] | 否 | mini benchmark 是本地 JSONL 数据集。 |
| ResearchBench-mini Plus loader | `evaluation/research_bench_plus.py::load_plus_cases` | `load_plus_cases()` | Evaluation 链路 | 返回内置 Plus cases | 无 | `list[ResearchBenchCase]` | 否 | Plus cases 是代码内置的本地 benchmark，不下载外部数据。 |
| Evaluation report API | `evaluation/reporting.py` | `write_json_report`、`write_markdown_report`、`build_markdown_report` | Evaluation 链路 | 将 eval result 序列化为文件或 markdown 文本 | eval result dict、输出路径 | JSON/Markdown 文件或字符串 | 否 | 评测报告生成和研究报告生成是两套入口。 |
| Demo 数据文件 | `examples/demo_questions.jsonl` | 当前代码未自动读取；可人工读取 | Demo / Debug 链路 | 保存示例问题数据 | JSONL 行 | question_id、query、context | 否 | 示例问题文件存在，但当前 `main.py` 没把它作为 CLI 输入。 |
| 测试发现入口 | `tests/` | `python -m unittest discover -s tests` | Test 链路 | 运行项目推荐的全部 unittest 测试 | `tests/test_*.py` | unittest pass/fail summary | 否 | 项目测试入口是标准库 unittest discovery。 |
| 单测试文件入口 | `tests/test_*.py` | `python -m unittest tests.test_statistical_evaluation` 或直接运行含 `unittest.main()` 的测试文件 | Test 链路 | 单独验证某个模块 | 指定测试模块 | unittest pass/fail | 否 | 每个测试文件可以独立定位某一阶段能力。 |

## 二、主研究链路接口

用户提交研究问题后，真实主链路从 `orchestrator.research_pipeline.run_research_pipeline(question_text, ...)` 开始。`python main.py` 只是 demo CLI，它把内置 `DEMO_QUESTION` 传给这个 API；如果启用了 `DEEP_RESEARCH_USE_ASYNC_DAG=1`，则走 `async_run_research_pipeline(...)`，但组件和输出结构基本一致。

主链路的输入是 `question_text: str`。pipeline 先创建 `ResearchQuestion`，再由 `build_research_pipeline_components(...)` 实例化 `PlannerAgent`、`SearcherAgent`、`ReaderAgent`、`WriterAgent`、`CriticAgent`、`RedAgent`、`BlueAgent`、`SharedMemory` 和 `CitationRegistry`。`build_minimal_research_graph()` 构建固定 DAG，节点顺序是真实存在的 `planner_task -> search_task -> reader_task -> writer_task -> critic_task -> red_review_task -> blue_revision_task`。

`PlannerAgent` 输出 `ResearchPlan` 和 search queries。当前仓库没有名为 `DAGBuilder` 的单独类，DAG 构建函数就是 `build_minimal_research_graph()`，底层数据结构是 `TaskGraph` / `TaskNode`。`DAGExecutor` 默认同步执行；异步模式使用 `AsyncDAGExecutor`。执行器调用每个 node 对应的 handler，handler 再调用具体 Agent 的 `run(context)`。

当前仓库没有名为 `ResearchAgent` 的类。研究收集职责由 `SearcherAgent` 和 `ReaderAgent` 分担：`SearcherAgent` 调用 `SearchProviderRegistry` 或 `SearchTool` 产生 `SearchResult`，`ReaderAgent` 调用 `WebFetcher` 或 `FetchTool` 把搜索结果变成 `Finding`，并通过 `CitationRegistry` 写入 evidence/citation。`WriterAgent` 根据 question、plan、findings 和 citation registry 生成 `ResearchReport` 初稿。之后 `CriticAgent` 做规则检查，`RedAgent` 输出结构化问题，`BlueAgent` 输出 revised report。最终 `build_research_pipeline_result(...)` 用 `CitationValidator` 校验最终 report 的 citation marker 和 registry 是否匹配。

```mermaid
flowchart TD
    User[User]
    CLI[CLI: python main.py]
    PyAPI[Python API: run_research_pipeline(question_text)]
    AsyncAPI[Python API: async_run_research_pipeline(question_text)]
    RQ[ResearchQuestion]
    Components[build_research_pipeline_components]
    Planner[PlannerAgent]
    Graph[build_minimal_research_graph<br/>TaskGraph / TaskNode]
    Executor{Executor}
    Sync[DAGExecutor]
    Async[AsyncDAGExecutor]
    Searcher[SearcherAgent]
    SearchTools[SearchProviderRegistry / SearchTool]
    Reader[ReaderAgent]
    Fetchers[WebFetcher / FetchTool]
    Citation[CitationRegistry]
    Writer[WriterAgent]
    Critic[CriticAgent]
    Red[RedAgent]
    Blue[BlueAgent]
    Validate[CitationValidator]
    Final[Final ResearchReport]
    Memory[SharedMemory]
    Result[build_research_pipeline_result]

    User --> CLI
    User --> PyAPI
    User --> AsyncAPI
    CLI --> PyAPI
    PyAPI --> RQ
    AsyncAPI --> RQ
    RQ --> Components
    Components --> Planner
    Components --> Graph
    Graph --> Executor
    Executor --> Sync
    Executor --> Async
    Planner --> Searcher
    Searcher --> SearchTools
    Searcher --> Reader
    Reader --> Fetchers
    Reader --> Citation
    Reader --> Writer
    Citation --> Writer
    Writer --> Critic
    Critic --> Red
    Red --> Blue
    Blue --> Result
    Result --> Validate
    Validate --> Final
    Planner --> Memory
    Searcher --> Memory
    Reader --> Memory
    Writer --> Memory
    Critic --> Memory
    Red --> Memory
    Blue --> Memory
```

主链路输出是一个 dict，常用字段包括 `report` / `final_report`、`initial_report`、`findings`、`critic_review`、`red_review`、`blue_revision`、`memory_items`、`citation_validation`、`traces`、`execution`、`success`、`checkpoint_metadata`。`main.py` 会把其中的 metadata 和 `final_report.markdown` 打印到控制台。

## 三、Red-Blue 对抗修复接口

当前主 DAG 默认包含单轮 `RedAgent` 和 `BlueAgent`：`red_review_task` 在 `critic_task` 后执行，输入是 writer 初稿、reader findings、critic review 和 citation registry；输出是 `RedReviewResult`，里面包含 `passed`、`issues` 和 `summary`。每个 issue 是 `ReviewIssue`，字段包括 `issue_id`、`category`、`severity`、`message`、`evidence`、`suggestion`。

`BlueAgent` 在 `blue_revision_task` 执行，输入是 report、`RedReviewResult`、findings 和 citation registry，输出是 `BlueRevisionResult`。它会补缺失的 `Background`、`Key Findings`、`Conclusion`、`References`，替换或生成 references，并尽量补 citation marker。输出里有 `fixed_issue_ids`、`remaining_issue_ids`、`revision_notes` 和 `revised_report`。

多轮对抗入口是 `RedBlueLoopRunner.run(...)`。它不会默认总是启用，只有 `run_research_pipeline(..., use_red_blue_loop=True)`、`python main.py --red-blue-loop` 或环境变量 `DEEP_RESEARCH_USE_RED_BLUE_LOOP=1` 这类路径会触发。loop 每轮先 Red 再 Blue，并记录 `RedBlueRoundResult`、`RedBlueRoundSnapshot` 和 `RedBlueLoopSummary`。

当前代码中存在评分收敛和震荡检测：`agents/red_blue_convergence.py` 里有 `compute_convergence_score(...)`、`detect_no_improvement(...)`、`detect_oscillation(...)`、`decide_convergence(...)`。震荡检测基于 issue fingerprint 集合和 report hash 的重复或交替；收敛状态包括 `CONVERGED`、`MAX_ROUNDS_REACHED`、`NO_IMPROVEMENT`、`OSCILLATION_DETECTED`、`BLUE_UNABLE_TO_FIX`、`ERROR`、`CONTINUE`。停止原因会映射为 `red_passed`、`max_rounds_reached`、`no_improvement`、`oscillation_detected`、`blue_agent_failed` 或 `error`。

当前代码中没有发现正式的 `ADD / DELETE / MODIFY / VERIFY` 操作枚举或通用 edit action 协议。`BlueAgent` 真实做过的事情主要是“补充缺失章节、生成或替换 References、补 citation marker”，可以说是规则化修复，但不能在简历里写成“实现了完整 ADD/DELETE/MODIFY/VERIFY 编辑系统”。`RedAgent` 会验证结构、引用、证据和 critic concerns，但这也不是一个名为 `VERIFY` 的显式动作类型。

如果面试中讲 Red-Blue，准确说法是：当前实现是 deterministic rule-based Red/Blue review and revision，支持可选多轮 loop、收敛分数、无改进停止和震荡检测；它不是多智能体自由博弈，不是 LLM 自动修复全类型问题，也不是统计显著性驱动的在线优化。

## 四、Memory / Context Compression 接口

当前仓库有两类 memory：一次运行内的 `SharedMemory`，以及可选 SQLite vector memory。`SharedMemory` 在 `memory/store.py`，每个 Agent 的 `_write_memory(...)` 会通过 `add_record(...)` 写入中间产物。读取入口是 `get(...)`、`list_by_type(...)`、`list_by_agent(...)`、`all_items()` 和 `to_dict_list()`。`main.py` 最后用 `list_by_type(...)` 打印各类 memory item 数量。

`SharedMemory` 的去重逻辑真实存在：`SharedMemory.add(...)` 调用 `_find_duplicate(...)`，比较 `item_type`、`source_agent` 和 JSON-friendly content key。`CitationRegistry` 也会按 `(source_url, text)` 去重 evidence，按 `(source_url, evidence_id)` 去重 citation。vector memory 的去重入口是 `memory/dedup.py::build_memory_fingerprint(...)`，`SQLiteVectorMemoryStore.add_item(...)` 会先查 fingerprint，重复时返回已有 id。

SQLite vector memory 真实存在，入口是 `SQLiteVectorMemoryStore`。写入用 `add_item(...)` / `add_items(...)`，读取用 `get_item(...)` / `list_items(...)`，检索用 `search(query_text, top_k, memory_type, run_id)`，删除用 `delete_run_memory(run_id)`。它用标准库 `sqlite3`，embedding 来自 `HashEmbeddingProvider`，向量以 JSON 存在 SQLite 表里，检索时逐行计算 cosine similarity。当前未使用 numpy、FAISS、Chroma、Milvus、Qdrant 或真实 embedding API。

把主链路结果写入 vector memory 的入口是 `persist_pipeline_result_to_vector_memory(result, vector_memory_store, run_id)`。它会从 pipeline result 提取 evidence、citation、summary、node_output、failure 这些类型。注意：`run_research_pipeline(...)` 只有在调用方显式传入 `vector_memory_store` 时才会写入；`python main.py` 默认没有把 vector memory 强制接入。

上下文压缩真实存在于 `compression/` 包，但当前不是 `main.py` 默认主链路必经步骤。核心入口是 `ContextCompressor.compress(query, evidence_units, config)`、`compress_from_memory(...)` 和 `merge_contexts(...)`；适配入口是 `compress_for_writer(...)`、`compress_for_reviewer(...)`、`build_evidence_units_from_node_outputs(...)`、`build_evidence_units_from_memory_items(...)`。

L1 / L2 / L3 压缩在代码中是真实存在的分层逻辑，但不是三个独立类。L1 是 `ContextCompressor._l1_select(...)`，使用 `HashEmbeddingProvider` 和 lexical overlap 粗筛 evidence；L2 是 `compression/text_rank.py::rank_sentences(...)`，用轻量 TextRank 风格句子排序；L3 是 `_assemble_context(...)` / `_fallback_context(...)`，组装保留 citation、source URL、title 和 raw quote 的 `CompressedContext`。输出字段包括 `compressed_text`、`selected_evidence`、`preserved_quotes`、`citations`、token estimate、compression ratio 和 warnings。

当前代码中未发现完整的矛盾检测实现。可以说有去重、fingerprint、citation grounding、压缩筛选和本地向量检索；不能说已经实现了复杂 semantic contradiction detection、长期用户记忆、外部向量数据库或生产级语义记忆系统。

## 五、Evaluation 接口

默认评测入口是 `python -m evaluation.run_eval`，它调用 `run_eval()`，用 `load_cases("evaluation/cases.jsonl")` 加载本地 mini cases。每个 case 通过 `run_case(...)` 调用 `run_research_pipeline(...)`，然后在 `evaluation/metrics.py` 里计算 section coverage、citation coverage、citation grounding、finding coverage、keyword coverage、red-blue improvement 和 memory completeness。

ResearchBench-mini Plus 入口是 `python -m evaluation.run_eval --bench plus` 或 `run_plus_eval(...)`。Plus cases 来自 `evaluation/research_bench_plus.py::PLUS_CASES`，通过 `load_plus_cases()` 返回。Plus scoring 在 `evaluation/scoring_plus.py`，规则分数包含 section、keyword、evidence count、citation count、citation grounding、finding coverage 和 red-blue improvement；`composite_score` 默认等于 rule score，如果启用 judge，则按 `0.7 * rule_score + 0.3 * judge_score` 合成。

LLM-as-Judge 入口是真实存在的，但默认关闭。CLI 可用 `--enable-judge`，环境变量可用 `DEEP_RESEARCH_USE_LLM_JUDGE=1`；`DEEP_RESEARCH_LLM_JUDGE_USE_MOCK=1` 可强制 mock judge。实际调用在 `LLMJudgeEvaluator.judge(...)`，输入是 question、report、findings、citations 和 citation validation，输出是 `JudgeResult`。如果没有 LLM client 或解析失败，会走 deterministic fallback judge。

规则指标和 judge 是评测链路，不是主研究报告生成链路。主链路可以生成报告而不跑 evaluation；evaluation 会反过来调用主 pipeline 多次。当前没有实现多模型 benchmark 矩阵，也没有外部 ResearchBench 下载。可以说支持一个 OpenAI-compatible LLM client 配置和 mock fallback，但不能说支持“多模型后端自动横评平台”。

评测报告输出入口是真实存在的：`--output-json` 调用 `write_json_report(...)`，`--output-md` 调用 `write_markdown_report(...)`，Markdown 内容由 `build_markdown_report(...)` 生成。输出格式是 JSON 文件、Markdown 文件和控制台 summary。comparison 入口 `--compare baseline.json candidate.json` 会输出 case-level deltas、domain deltas、improved/regressed/unchanged cases。

一键实验脚本的真实程度要谨慎表述：仓库没有独立 `scripts/` 目录或复杂实验 runner，但 `evaluation.run_eval` CLI 提供了可重复的命令入口，例如 `--bench plus --compare-red-blue` 和 `--stats`。这可以称为本地 CLI 实验入口，不应说成完整实验平台。

## 六、Phase 24 Statistical Evaluation 接口

Phase 24 的统计评测实现集中在 `evaluation/statistics.py`，CLI 接在 `evaluation/run_eval.py` 的 `--stats` 参数上。它属于离线评测链路，不属于主研究链路；它不会改变 `WriterAgent`、`BlueAgent` 或最终报告内容。

Bootstrap 95% CI 的入口是 `bootstrap_mean_ci(values, metric_name, confidence_level=0.95, num_bootstrap=1000, seed=42)`。输入是一组数值分数，例如各 case 的 `composite_score`；输出是 `BootstrapCI`，包含 mean、lower、upper、confidence_level、num_bootstrap、sample_size、seed 和 metadata。

配对 delta CI 的入口是 `paired_bootstrap_delta_ci(baseline_values, candidate_values, metric_name, ...)`。输入是 baseline 和 candidate 按同一 case 对齐后的分数列表，输出也是 `BootstrapCI`，其中 mean 表示平均 candidate-minus-baseline delta。

Cohen's d 的入口是 `paired_cohens_d(baseline_values, candidate_values, metric_name)`。它实现的是 paired Cohen's dz：先算每个 case 的 delta，再用 mean_delta / sample_std_delta 得到 effect size。输出是 `EffectSizeSummary`，包含 `effect_size_type="cohens_dz"`、value、interpretation、sample_size、mean_delta、std_delta 和 metadata。

综合统计比较入口是 `build_statistical_comparison(baseline_result, candidate_result, metric_name="composite_score", ...)`。它按 `case_id` 对齐两个 eval result，跳过缺失指标的 case，然后输出 `StatisticalComparison`，包括 baseline/candidate mean、mean_delta、baseline_ci、candidate_ci、delta_ci、effect_size、improved、summary 和 skipped_cases。

CLI 使用方式：

```bash
python -m evaluation.run_eval --compare evaluation/results/baseline.json evaluation/results/candidate.json --stats
python -m evaluation.run_eval --compare evaluation/results/baseline.json evaluation/results/candidate.json --stats --stats-metric composite_score --num-bootstrap 1000 --confidence-level 0.95 --seed 42
python -m evaluation.run_eval --bench plus --compare-red-blue --stats
```

面试时可以这样解释：Phase 24 不直接影响报告生成结果，它是离线评测增强，用来判断不同策略的效果差异是否稳定，而不是只看单次平均分。它提供的是 bootstrap confidence interval 和 paired effect size，不提供 p-value、t-test 或严格统计显著性结论。

## 七、测试入口

已检查当前仓库：`README.md` 和 `AGENTS.md` 都推荐 `python -m unittest discover -s tests`；`requirements.txt` 写明当前阶段不需要外部依赖；未发现 `pyproject.toml`、`setup.cfg`、`setup.py`、`pytest.ini` 或 `tox.ini`。因此项目推荐测试命令是：

```bash
python -m unittest discover -s tests
```

`pytest` 没有在项目文档或配置中作为推荐入口出现；当前测试文件使用标准库 `unittest`，并且多数测试文件可通过 `python -m unittest tests.test_xxx` 单独运行。

测试覆盖大致分为：

| 测试范围 | 代表文件 | 所属链路 |
| --- | --- | --- |
| schema、minimal pipeline、多 Agent role | `test_schema.py`、`test_minimal_pipeline.py`、`test_multi_agent_roles.py` | 主研究链路 |
| DAG、async executor、checkpoint、resume、replan | `test_dag_orchestrator.py`、`test_async_dag_executor.py`、`test_checkpoint_store.py`、`test_dag_resume.py`、`test_executor_replan.py`、`test_replan_policy.py`、`test_dag_replanner.py` | 主研究链路 |
| search、fetch、reader、citation grounding | `test_search_fetch_tools.py`、`test_search_providers.py`、`test_searcher_agent.py`、`test_reader_agent.py`、`test_web_fetchers.py`、`test_content_extraction.py`、`test_citation_grounding.py` | 主研究链路 |
| SharedMemory、run store、vector memory、context compression | `test_memory.py`、`test_persistent_run_store.py`、`test_vector_memory.py`、`test_context_compression.py` | Memory / Context 链路 |
| Red-Blue 单轮、多轮、收敛 | `test_red_blue_review.py`、`test_iterative_red_blue.py`、`test_red_blue_convergence.py` | Red-Blue 对抗修复链路 |
| evaluation、judge、Plus、comparison、statistics | `test_evaluation.py`、`test_llm_judge.py`、`test_researchbench_plus.py`、`test_eval_scoring_plus.py`、`test_eval_comparison.py`、`test_statistical_evaluation.py` | Evaluation / Statistical Evaluation 链路 |
| CLI helper | `test_main_resume.py` | Demo / Debug 链路 |

当前测试缺口也要诚实说：默认测试不验证真实外部网络搜索质量，不验证真实 LLM 质量，不覆盖 HTTP API 因为仓库没有 HTTP API，不验证外部大规模 ResearchBench，也没有把 context compression 作为默认主链路强制集成测试。

## 八、面试版接口讲解

我会先把项目入口分成两类：主研究链路和评测链路。主研究链路负责把一个问题变成报告，从 `run_research_pipeline(question_text)` 进入；评测链路负责反复调用主链路，然后用规则指标、可选 judge、comparison 和统计摘要评估效果。这样拆开以后，用户使用系统和开发者评估系统不会混在一起。

主链路里，`main.py` 只是 demo CLI，真正核心是 `orchestrator/research_pipeline.py`。它会创建 `ResearchQuestion`，让 `PlannerAgent` 产出计划和搜索 query，然后通过 `TaskGraph` 把 Planner、Searcher、Reader、Writer、Critic、Red、Blue 串成 DAG。执行器默认是 `DAGExecutor`，也可以通过环境变量切到 `AsyncDAGExecutor`。

Red-Blue 没有直接硬写在 `main.py` 里，是因为它本质上是报告质量修复模块，而不是 CLI 行为。单轮 Red/Blue 是主 DAG 的一部分，多轮 loop 是可选增强；这样 demo、pipeline API、evaluation 都能复用同一套 RedAgent、BlueAgent 和 convergence 逻辑。面试时我会强调它是 bounded deterministic repair，不是无限多智能体争论。

Memory 和 Context Compression 也是独立模块，因为它们服务的是跨 Agent 共享、持久化和上下文裁剪，不应该和 Writer 或 Reader 强耦合。`SharedMemory` 是单次运行内的共享记录，`SQLiteVectorMemoryStore` 是可选本地持久化，`ContextCompressor` 是可选上下文压缩 API。当前 `main.py` 默认不强制启用 vector memory 或 compression，所以不能把它讲成主链路必经能力。

Evaluation 链路从 `python -m evaluation.run_eval` 进入，默认跑 mini cases；`--bench plus` 跑本地 Plus benchmark；`--compare` 做 baseline/candidate 对比；`--enable-judge` 或环境变量启用可选 LLM-as-Judge。它们都是离线评测入口，不会改变一次正常研究任务的报告内容。

Phase 24 是收尾功能，因为到 Phase 23 已经能比较平均分和 case delta，但平均分本身不说明差异是否稳定。Phase 24 加了 bootstrap CI 和 paired Cohen's d，用来描述不确定性和效果量。它的价值是让策略对比更有可信度，但它不做 p-value、t-test，也不宣称严格统计显著。

用户真正会用的入口主要是 `python main.py`、`python main.py --resume <run_id>`、`run_research_pipeline(...)`，以及评测时的 `python -m evaluation.run_eval`。开发和实验会更多用 `--bench plus`、`--compare`、`--compare-red-blue`、`--stats`、`ContextCompressor`、`SQLiteVectorMemoryStore` 和单元测试入口。

简历里不能吹过头的地方也要讲清楚：当前没有 HTTP API，没有完整外部 ResearchBench，没有生产级真实搜索排序，没有多模型自动横评平台，没有 numpy/FAISS 向量索引，没有完整 ADD/DELETE/MODIFY/VERIFY 编辑协议，也没有复杂语义矛盾检测。准确的表达是：这是一个 deterministic local multi-agent research prototype，具备清晰的主链路、可选 LLM/search/fetch 增强、本地评测闭环和 Phase 24 统计摘要。
