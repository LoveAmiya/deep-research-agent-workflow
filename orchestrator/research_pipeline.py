from agents.base_agent import AgentContext
from agents.base_agent import AgentResult
from agents.blue_agent import BlueAgent
from agents.critic_agent import CriticAgent
from agents.planner_agent import PlannerAgent
from agents.reader_agent import ReaderAgent
from agents.red_agent import RedAgent
from agents.red_blue_loop import RedBlueLoopConfig, RedBlueLoopRunner
from agents.searcher_agent import SearcherAgent
from agents.writer_agent import WriterAgent
from core.schema import ResearchQuestion, ResearchReport
from memory.store import SharedMemory
from memory.research_ledger import ResearchLedger
from memory.integration import persist_pipeline_result_to_vector_memory
from orchestrator.checkpoint import JSONCheckpointStore, RunCheckpoint
from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.executor import DAGExecutor
from tools.citation_tool import CitationRegistry, CitationValidator


def build_minimal_research_graph() -> TaskGraph:
    """将默认研究流程声明为依赖图。

    节点间通过 ``depends_on`` 表示依赖，而不是由一个 Agent 直接调用下一个。
    因此执行器能够校验顺序、并发调度无依赖节点，并从保存的 Checkpoint 恢复单个节点。
    """
    graph = TaskGraph()
    graph.add_node(
        TaskNode(
            task_id="planner_task",
            name="Planner Task",
            agent_name="PlannerAgent",
        )
    )
    graph.add_node(
        TaskNode(
            task_id="search_task",
            name="Search Task",
            agent_name="SearcherAgent",
            depends_on=["planner_task"],
        )
    )
    graph.add_node(
        TaskNode(
            task_id="reader_task",
            name="Reader Task",
            agent_name="ReaderAgent",
            depends_on=["search_task"],
        )
    )
    graph.add_node(
        TaskNode(
            task_id="writer_task",
            name="Writer Task",
            agent_name="WriterAgent",
            depends_on=["reader_task"],
        )
    )
    graph.add_node(
        TaskNode(
            task_id="critic_task",
            name="Critic Task",
            agent_name="CriticAgent",
            depends_on=["writer_task"],
        )
    )
    graph.add_node(
        TaskNode(
            task_id="red_review_task",
            name="Red Review Task",
            agent_name="RedAgent",
            depends_on=["critic_task"],
        )
    )
    graph.add_node(
        TaskNode(
            task_id="blue_revision_task",
            name="Blue Revision Task",
            agent_name="BlueAgent",
            depends_on=["red_review_task"],
        )
    )
    return graph


def run_research_pipeline(
    question_text: str,
    llm_client=None,
    search_tool=None,
    search_provider_registry=None,
    search_provider_order=None,
    real_search_enabled: bool = False,
    fetch_tool=None,
    web_fetcher=None,
    citation_registry=None,
    use_red_blue_loop: bool = False,
    red_blue_loop_config: RedBlueLoopConfig | None = None,
    checkpoint_enabled: bool = False,
    resume_from_run_id: str | None = None,
    checkpoint_dir: str = "runs/checkpoints",
    run_id: str | None = None,
    replan_enabled: bool = False,
    max_replan_attempts: int = 2,
    max_failed_nodes_before_force_synthesis: int = 3,
    force_synthesis_on_replan_exhausted: bool = True,
    vector_memory_store=None,
    event_sink=None,
    require_llm: bool = False,
) -> dict:
    """运行同步端到端流水线，并返回可检查的全部产物。

    此函数分离四件事：准备 Checkpoint、装配依赖、执行 DAG、汇总结果。
    这种边界让测试可以分别替换 Mock LLM、搜索和抓取工具。
    """
    checkpoint, checkpoint_store, resumed, resume_missing = _prepare_checkpoint(
        question_text=question_text,
        checkpoint_enabled=checkpoint_enabled,
        resume_from_run_id=resume_from_run_id,
        checkpoint_dir=checkpoint_dir,
        run_id=run_id,
    )
    components = build_research_pipeline_components(
        question_text=question_text,
        llm_client=llm_client,
        search_tool=search_tool,
        search_provider_registry=search_provider_registry,
        search_provider_order=search_provider_order,
        real_search_enabled=real_search_enabled,
        fetch_tool=fetch_tool,
        web_fetcher=web_fetcher,
        citation_registry=citation_registry,
        ledger=ResearchLedger.from_dict(
            checkpoint.metadata.get("research_ledger")
        ) if checkpoint is not None and checkpoint.metadata.get("research_ledger") else ResearchLedger(
            run_id=checkpoint.run_id if checkpoint is not None else run_id
        ),
        checkpoint=checkpoint,
        event_sink=event_sink,
        require_llm=require_llm,
    )
    graph = components["graph"]
    handlers = components["handlers"]
    citation_registry = components["citation_registry"]
    memory = components["memory"]
    ledger = components["ledger"]
    question = components["question"]
    # 执行器负责顺序与失败状态；Agent 只接收下方 handler 声明的输入，彼此不直接调用。
    execution = DAGExecutor(
        graph=graph,
        handlers=handlers,
        checkpoint_store=checkpoint_store,
        checkpoint=checkpoint,
        checkpoint_enabled=checkpoint is not None and checkpoint_store is not None,
        resume=resumed,
        replan_enabled=replan_enabled,
        max_replan_attempts=max_replan_attempts,
        max_failed_nodes_before_force_synthesis=max_failed_nodes_before_force_synthesis,
        force_synthesis_on_replan_exhausted=force_synthesis_on_replan_exhausted,
    ).execute()
    result = build_research_pipeline_result(
        question=question,
        memory=memory,
        citation_registry=citation_registry,
        execution=execution,
        use_red_blue_loop=use_red_blue_loop,
        red_blue_loop_config=red_blue_loop_config,
        checkpoint=checkpoint,
        resume_missing=resume_missing,
        ledger=ledger,
        event_sink=event_sink,
        llm_client=llm_client,
    )
    if vector_memory_store is not None:
        result["vector_memory_ids"] = persist_pipeline_result_to_vector_memory(
            result,
            vector_memory_store,
            run_id=result.get("run_id"),
        )
    return result


def build_research_pipeline_components(
    question_text: str,
    llm_client=None,
    search_tool=None,
    search_provider_registry=None,
    search_provider_order=None,
    real_search_enabled: bool = False,
    fetch_tool=None,
    web_fetcher=None,
    citation_registry=None,
    ledger: ResearchLedger | None = None,
    checkpoint: RunCheckpoint | None = None,
    event_sink=None,
    require_llm: bool = False,
) -> dict:
    """创建 Agent 与 handler，将 DAG 输出转换为下游输入。

    ``handlers`` 是编排层和 Agent 之间的显式契约：每个 handler 只能读取已完成
    的上游输出，并将它们包装为包含共享记忆和外部客户端的 ``AgentContext``。
    """
    question = ResearchQuestion(question=question_text)
    planner = PlannerAgent()
    searcher = SearcherAgent()
    reader = ReaderAgent()
    writer = WriterAgent()
    critic = CriticAgent()
    red = RedAgent()
    blue = BlueAgent()
    memory = SharedMemory()
    ledger = ledger or ResearchLedger()
    if citation_registry is None:
        citation_registry = CitationRegistry()

    graph = build_minimal_research_graph()
    # handler 使数据依赖可见。例如只有图中的 search_task 成功后，Reader 才能拿到 Searcher 输出。
    def run_and_publish(agent, context, artifact_type, recipient, dependencies=()):
        _emit_pipeline_event(event_sink, "agent_started", context, agent.name, artifact_type, "running")
        dependency_ids = [
            artifact.artifact_id
            for dependency_type in dependencies
            for artifact in [ledger.latest(dependency_type)]
            if artifact is not None
        ]
        for artifact_id in dependency_ids:
            source = ledger.read(artifact_id)
            ledger.acknowledge(
                sender_agent=source.producer_agent,
                recipient_agent=agent.name,
                artifact_ids=[artifact_id],
                reason=f"{agent.name} 消费 {source.artifact_type} v{source.version}。",
            )
        context.ledger = ledger
        result = agent.run(context)
        if require_llm and result.success and result.metadata.get("fallback_used"):
            result = AgentResult(
                agent_name=agent.name,
                success=False,
                output=result.output,
                error=result.metadata.get("llm_error") or "Required LLM output was unavailable or invalid.",
                metadata=result.metadata,
            )
        if result.success:
            artifact = ledger.publish(
                artifact_type=artifact_type,
                producer_agent=agent.name,
                task_id=context.task_id,
                content=result.output,
                summary=_artifact_summary(artifact_type, result.output),
                dependencies=dependency_ids,
            )
            if recipient:
                handoff = ledger.acknowledge(
                    sender_agent=agent.name,
                    recipient_agent=recipient,
                    artifact_ids=[artifact.artifact_id],
                    reason=f"{agent.name} 已将 {artifact_type} 交给 {recipient}。",
                )
                _emit_handoff_event(event_sink, handoff, artifact)
            if checkpoint is not None:
                checkpoint.metadata["research_ledger"] = ledger.to_dict()
            _emit_readable_artifact_stream(event_sink, artifact_type, result.output)
        _emit_pipeline_event(
            event_sink,
            "agent_done" if result.success else "agent_failed",
            context,
            agent.name,
            artifact_type,
            "done" if result.success else "failed",
        )
        return result

    def context(task_id, agent_name, inputs, **extra):
        return AgentContext(
            task_id=task_id,
            inputs=inputs,
            metadata={"agent_name": agent_name, "require_llm": require_llm},
            memory=memory,
            llm_client=llm_client,
            ledger=ledger,
            **extra,
        )

    def planner_handler(outputs, node):
        return run_and_publish(
            planner,
            context(node.task_id, planner.name, {"question": question}),
            "research_brief",
            "SearcherAgent",
        )

    def search_handler(outputs, node):
        return run_and_publish(
            searcher,
            context(
                node.task_id,
                searcher.name,
                {
                    "plan": outputs["planner_task"].output,
                    "search_tool": search_tool,
                    "search_provider_registry": search_provider_registry,
                    "search_provider_order": search_provider_order,
                    "real_search_enabled": real_search_enabled,
                },
                search_provider_registry=search_provider_registry,
            ),
            "candidate_sources",
            "ReaderAgent",
            ("research_brief",),
        )

    def reader_handler(outputs, node):
        return run_and_publish(
            reader,
            context(
                node.task_id,
                reader.name,
                {
                    "search_results": outputs["search_task"].output,
                    "fetch_tool": fetch_tool,
                    "web_fetcher": web_fetcher,
                    "citation_registry": citation_registry,
                },
                web_fetcher=web_fetcher,
            ),
            "approved_findings",
            "WriterAgent",
            ("candidate_sources",),
        )

    def writer_handler(outputs, node):
        return run_and_publish(
            writer,
            context(
                node.task_id,
                writer.name,
                {
                    "question": question,
                    "plan": outputs["planner_task"].output,
                    "findings": outputs["reader_task"].output,
                    "citation_registry": citation_registry,
                },
            ),
            "initial_report",
            "CriticAgent",
            ("approved_findings",),
        )

    def critic_handler(outputs, node):
        return run_and_publish(
            critic,
            context(
                node.task_id,
                critic.name,
                {
                    "report": outputs["writer_task"].output,
                    "findings": outputs["reader_task"].output,
                    "citation_registry": citation_registry,
                },
            ),
            "critic_review",
            "RedAgent",
            ("initial_report",),
        )

    def red_handler(outputs, node):
        return run_and_publish(
            red,
            context(
                node.task_id,
                red.name,
                {
                    "report": outputs["writer_task"].output,
                    "findings": outputs["reader_task"].output,
                    "critic_review": outputs["critic_task"].output,
                    "citation_registry": citation_registry,
                },
            ),
            "red_review",
            "BlueAgent",
            ("initial_report", "critic_review"),
        )

    def blue_handler(outputs, node):
        return run_and_publish(
            blue,
            context(
                node.task_id,
                blue.name,
                {
                    "report": outputs["writer_task"].output,
                    "red_review": outputs["red_review_task"].output,
                    "findings": outputs["reader_task"].output,
                    "citation_registry": citation_registry,
                },
            ),
            "blue_revision",
            None,
            ("red_review",),
        )

    handlers = {
        "planner_task": planner_handler,
        "search_task": search_handler,
        "reader_task": reader_handler,
        "writer_task": writer_handler,
        "critic_task": critic_handler,
        "red_review_task": red_handler,
        "blue_revision_task": blue_handler,
    }
    return {
        "question": question,
        "memory": memory,
        "citation_registry": citation_registry,
        "graph": graph,
        "handlers": handlers,
        "ledger": ledger,
    }


def _artifact_summary(artifact_type: str, output: object) -> str:
    summaries = {
        "research_brief": "研究规划已交给来源发现 Agent。",
        "candidate_sources": "候选来源已交给正文取证 Agent。",
        "approved_findings": "可用发现已交给报告撰写 Agent。",
        "initial_report": "初稿已交给质量审查 Agent。",
        "critic_review": "结构审查已交给 Red 审查 Agent。",
        "red_review": "Red 审查问题已交给 Blue 修订 Agent。",
        "blue_revision": "Blue 修订版本已生成。",
    }
    return summaries.get(artifact_type, f"{artifact_type} 已生成。")


def _emit_pipeline_event(event_sink, event_type, context, agent_name, artifact_type, status) -> None:
    if event_sink is None:
        return
    event_sink(
        event_type,
        {
            "step": {
                "taskId": context.task_id,
                "agent": agent_name,
                "title": agent_name,
                "impactOnFinalReport": _artifact_summary(artifact_type, None),
                "status": status,
                "success": status == "done",
                "metrics": {},
                "bullets": [],
                "highlights": [],
            }
        },
    )


def _emit_handoff_event(event_sink, handoff, artifact) -> None:
    if event_sink is None:
        return
    event_sink(
        "handoff_updated",
        {
            "handoff": {
                "senderAgent": handoff.sender_agent,
                "recipientAgent": handoff.recipient_agent,
                "status": handoff.status,
                "reason": handoff.reason,
                "summary": artifact.summary,
                "artifactIds": list(handoff.artifact_ids),
                "artifactTypes": [artifact.artifact_type],
                "artifactLabel": {
                    "research_brief": "研究任务书（问题拆解、子问题与检索方向）",
                    "candidate_sources": "候选资料清单（标题、链接与来源摘要）",
                    "approved_findings": "批准发现（结论与证据）",
                    "initial_report": "初始报告（Writer 第一版正文）",
                    "critic_review": "质量检查单（结构、论证与引用问题）",
                    "red_review": "Red 审查单（问题、依据与建议）",
                    "blue_revision": "Blue 修订稿（处理结果与新版报告）",
                }.get(artifact.artifact_type, artifact.artifact_type),
                "contentSummary": artifact.summary,
                "action": handoff.action,
                "actionLabel": "接收并用于下一步" if handoff.action == "consume" else handoff.action,
                "statusLabel": "已接收" if handoff.status == "ACKNOWLEDGED" else handoff.status,
            }
        },
    )


def _emit_readable_artifact_stream(event_sink, artifact_type: str, output: object) -> None:
    if event_sink is None:
        return
    if artifact_type == "initial_report":
        target = "initialDraft"
        text = getattr(output, "markdown", "")
    elif artifact_type == "red_review":
        target = "reviewTranscript"
        issues = list(getattr(output, "issues", []) or [])
        lines = ["Red 审查：", getattr(output, "summary", "")]
        lines.extend(
            f"- {getattr(issue, 'issue_id', '问题')}: {getattr(issue, 'message', '')}"
            for issue in issues
        )
        text = "\n".join(line for line in lines if line)
    elif artifact_type == "blue_revision":
        target = "reviewTranscript"
        notes = list(getattr(output, "revision_notes", []) or [])
        fixed = list(getattr(output, "fixed_issue_ids", []) or [])
        remaining = list(getattr(output, "remaining_issue_ids", []) or [])
        text = "\n".join(
            ["Blue 修订：", *notes, *(f"已修复: {item}" for item in fixed), *(f"待复核: {item}" for item in remaining)]
        )
    else:
        return
    if not text:
        return
    event_sink("report_stream_start", {"target": target})
    for index in range(0, len(text), 80):
        event_sink("report_delta", {"target": target, "delta": text[index : index + 80]})
    event_sink("report_stream_done", {"target": target, "text": text})


def build_research_pipeline_result(
    question: ResearchQuestion,
    memory: SharedMemory,
    citation_registry: CitationRegistry,
    execution,
    use_red_blue_loop: bool = False,
    red_blue_loop_config: RedBlueLoopConfig | None = None,
    checkpoint: RunCheckpoint | None = None,
    resume_missing: bool = False,
    ledger: ResearchLedger | None = None,
    event_sink=None,
    llm_client=None,
) -> dict:
    outputs = execution.outputs
    ledger = ledger or ResearchLedger()
    blue_result = outputs.get("blue_revision_task")
    writer_result = outputs.get("writer_task")
    blue_revision = getattr(blue_result, "output", None) if getattr(blue_result, "success", False) else None
    writer_report = getattr(writer_result, "output", None) if getattr(writer_result, "success", False) else None
    red_blue_loop_result = None
    final_report = getattr(blue_revision, "revised_report", None) or writer_report
    if not isinstance(final_report, ResearchReport):
        final_report = _build_degraded_report(question, execution)
    _restore_side_effects_from_outputs(
        outputs=outputs,
        memory=memory,
        citation_registry=citation_registry,
        execution_metadata=getattr(execution, "metadata", {}),
    )
    if use_red_blue_loop and isinstance(writer_report, ResearchReport):
        red_blue_loop_result = RedBlueLoopRunner(
            red_agent=RedAgent(),
            blue_agent=BlueAgent(),
            config=red_blue_loop_config,
        ).run(
            AgentContext(
                task_id="red_blue_loop",
                inputs={"citation_registry": citation_registry},
                metadata={
                    "agent_name": "RedBlueLoopRunner",
                    "event_sink": event_sink,
                    "round_offset": 1,
                    "max_display_rounds": 1 + max(
                        1,
                        getattr(red_blue_loop_config, "max_rounds", 1),
                    ),
                },
                memory=memory,
                llm_client=llm_client,
            ),
            report=final_report,
            findings=outputs["reader_task"].output,
            critic_review=None,
        )
        final_report = red_blue_loop_result.final_report
        _record_red_blue_loop_handoffs(ledger, red_blue_loop_result)
        if checkpoint is not None:
            checkpoint.metadata["research_ledger"] = ledger.to_dict()
    red_blue_loop_metadata = (
        dict(getattr(red_blue_loop_result, "metadata", {}) or {})
        if red_blue_loop_result is not None
        else {}
    )
    citation_validation = CitationValidator().validate_report_citations(
        final_report,
        citation_registry,
    )
    return {
        "run_id": checkpoint.run_id if checkpoint is not None else None,
        "question": question,
        "report": final_report,
        "final_report": final_report,
        "initial_report": writer_report,
        "findings": getattr(outputs.get("reader_task"), "output", []) or [],
        "critic_review": getattr(outputs.get("critic_task"), "output", None),
        "red_review": getattr(outputs.get("red_review_task"), "output", None),
        "blue_revision": blue_revision,
        "red_blue_loop_result": red_blue_loop_result,
        "memory_items": memory.to_dict_list(),
        "memory": memory,
        "ledger": ledger,
        "ledger_summary": ledger.summary(),
        "handoffs": [handoff.__dict__ for handoff in ledger.list_handoffs()],
        "citation_registry": citation_registry,
        "citation_validation": citation_validation,
        "traces": execution.traces,
        "success": execution.success,
        "execution": execution,
        "checkpoint": checkpoint,
        "checkpoint_metadata": {
            **getattr(execution, "metadata", {}),
            **red_blue_loop_metadata,
            "resume_checkpoint_missing": resume_missing,
        },
    }


def _record_red_blue_loop_handoffs(ledger: ResearchLedger, loop_result) -> None:
    latest_report = ledger.latest("initial_report")
    report_dependencies = [latest_report.artifact_id] if latest_report is not None else []
    for round_result in loop_result.rounds:
        red_artifact = ledger.publish(
            artifact_type="red_review_round",
            producer_agent="RedAgent",
            task_id=f"red_blue_loop_red_{round_result.round_index}",
            content=round_result.red_review,
            summary=f"第 {round_result.round_index} 轮 Red 审查已完成。",
            dependencies=report_dependencies,
        )
        if round_result.blue_revision is not None:
            ledger.request_revision(
                sender_agent="RedAgent",
                recipient_agent="BlueAgent",
                artifact_ids=[red_artifact.artifact_id],
                reason=f"第 {round_result.round_index} 轮审查问题需要修订。",
            )
            blue_artifact = ledger.publish(
                artifact_type="blue_revision_round",
                producer_agent="BlueAgent",
                task_id=f"red_blue_loop_blue_{round_result.round_index}",
                content=round_result.blue_revision,
                summary=f"第 {round_result.round_index} 轮 Blue 修订已完成。",
                dependencies=[red_artifact.artifact_id],
            )
            ledger.acknowledge(
                sender_agent="BlueAgent",
                recipient_agent="RedAgent",
                artifact_ids=[blue_artifact.artifact_id],
                action="revalidate",
                reason=f"第 {round_result.round_index} 轮修订等待复核。",
            )
            report_dependencies = [blue_artifact.artifact_id]


def _build_degraded_report(question: ResearchQuestion, execution) -> ResearchReport:
    failed = [
        task_id for task_id, state in execution.states.items()
        if getattr(state, "value", state) == "FAILED"
    ]
    reason = (
        f"上游 Agent 未完成：{', '.join(failed)}。"
        if failed
        else "研究链路未产生足够的报告工件。"
    )
    sections = [
        {"title": "Background", "content": f"本次研究未能完成真实报告生成。{reason}"},
        {"title": "Key Findings", "content": "证据不足，未生成可作为研究结论的事实发现。"},
        {"title": "Conclusion", "content": "请检查模型配置、上游 Agent 错误和可用来源后重新运行。"},
        {"title": "References", "content": "暂无已验证参考来源。"},
    ]
    markdown = "\n\n".join(
        [
            f"# Research Report: {question.question}",
            *[f"## {section['title']}\n\n{section['content']}" for section in sections],
        ]
    )
    return ResearchReport(
        title=f"Research Report: {question.question}",
        question=question.question,
        sections=sections,
        citations=[],
        markdown=markdown,
        question_id=question.question_id,
        summary="降级报告：上游 Agent 未完成。",
        findings=[],
        references=[],
    )


def _restore_side_effects_from_outputs(
    outputs: dict,
    memory: SharedMemory,
    citation_registry: CitationRegistry,
    execution_metadata: dict,
) -> None:
    if not execution_metadata.get("resumed"):
        return
    _restore_citation_registry(outputs.get("reader_task", None), citation_registry)
    _restore_memory_items(outputs, memory)


def _restore_citation_registry(reader_output, citation_registry: CitationRegistry) -> None:
    findings = getattr(reader_output, "output", reader_output)
    if not isinstance(findings, list):
        return
    existing_citation_count = len(citation_registry.list_citations())
    if existing_citation_count:
        return
    for finding in findings:
        source_url = getattr(finding, "source_url", None)
        evidence_text = getattr(finding, "evidence", None)
        if not source_url or not evidence_text:
            continue
        source_title = getattr(finding, "source_title", None)
        evidence = citation_registry.add_evidence(
            source_url=source_url,
            text=evidence_text,
            source_title=source_title,
            metadata={"restored_from_checkpoint": True},
        )
        citation = citation_registry.add_citation(
            source_url=source_url,
            evidence_id=evidence.evidence_id,
            source_title=source_title,
            quote=evidence_text[:240],
            metadata={"restored_from_checkpoint": True},
        )
        finding.evidence_id = evidence.evidence_id
        finding.citation_id = citation.citation_id


def _restore_memory_items(outputs: dict, memory: SharedMemory) -> None:
    item_map = {
        "planner_task": ("plan", "PlannerAgent"),
        "search_task": ("search_results", "SearcherAgent"),
        "reader_task": ("findings", "ReaderAgent"),
        "writer_task": ("report", "WriterAgent"),
        "critic_task": ("review", "CriticAgent"),
        "red_review_task": ("red_review", "RedAgent"),
        "blue_revision_task": ("blue_revision", "BlueAgent"),
    }
    for task_id, (item_type, source_agent) in item_map.items():
        output = outputs.get(task_id)
        content = getattr(output, "output", output)
        if content is None:
            continue
        memory.add_record(
            item_type=item_type,
            content=content,
            source_agent=source_agent,
            task_id=task_id,
            metadata={"restored_from_checkpoint": True},
        )


def _prepare_checkpoint(
    question_text: str,
    checkpoint_enabled: bool,
    resume_from_run_id: str | None,
    checkpoint_dir: str,
    run_id: str | None,
) -> tuple[RunCheckpoint | None, JSONCheckpointStore | None, bool, bool]:
    if not checkpoint_enabled and not resume_from_run_id:
        return None, None, False, False

    store = JSONCheckpointStore(checkpoint_dir)
    if resume_from_run_id:
        checkpoint = store.load_checkpoint(resume_from_run_id)
        if checkpoint is not None:
            checkpoint.metadata["resumed"] = True
            checkpoint.metadata["resumed_from_run_id"] = resume_from_run_id
            return checkpoint, store, True, False
        checkpoint = RunCheckpoint.new(
            task=question_text,
            run_id=run_id,
            metadata={
                "requested_resume_from_run_id": resume_from_run_id,
                "resume_checkpoint_missing": True,
            },
        )
        return checkpoint, store, False, True

    checkpoint = RunCheckpoint.new(task=question_text, run_id=run_id)
    return checkpoint, store, False, False
