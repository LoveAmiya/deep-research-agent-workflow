from agents.base_agent import AgentContext
from agents.blue_agent import BlueAgent
from agents.critic_agent import CriticAgent
from agents.planner_agent import PlannerAgent
from agents.reader_agent import ReaderAgent
from agents.red_agent import RedAgent
from agents.red_blue_loop import RedBlueLoopConfig, RedBlueLoopRunner
from agents.searcher_agent import SearcherAgent
from agents.writer_agent import WriterAgent
from core.schema import ResearchQuestion
from memory.store import SharedMemory
from orchestrator.checkpoint import JSONCheckpointStore, RunCheckpoint
from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.executor import DAGExecutor
from tools.citation_tool import CitationRegistry, CitationValidator


def build_minimal_research_graph() -> TaskGraph:
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
) -> dict:
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
    )
    graph = components["graph"]
    handlers = components["handlers"]
    citation_registry = components["citation_registry"]
    memory = components["memory"]
    question = components["question"]
    execution = DAGExecutor(
        graph=graph,
        handlers=handlers,
        checkpoint_store=checkpoint_store,
        checkpoint=checkpoint,
        checkpoint_enabled=checkpoint is not None and checkpoint_store is not None,
        resume=resumed,
    ).execute()
    return build_research_pipeline_result(
        question=question,
        memory=memory,
        citation_registry=citation_registry,
        execution=execution,
        use_red_blue_loop=use_red_blue_loop,
        red_blue_loop_config=red_blue_loop_config,
        checkpoint=checkpoint,
        resume_missing=resume_missing,
    )


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
) -> dict:
    question = ResearchQuestion(question=question_text)
    planner = PlannerAgent()
    searcher = SearcherAgent()
    reader = ReaderAgent()
    writer = WriterAgent()
    critic = CriticAgent()
    red = RedAgent()
    blue = BlueAgent()
    memory = SharedMemory()
    if citation_registry is None:
        citation_registry = CitationRegistry()

    graph = build_minimal_research_graph()
    handlers = {
        "planner_task": lambda outputs, node: planner.run(
            AgentContext(
                task_id=node.task_id,
                inputs={"question": question},
                metadata={"agent_name": planner.name},
                memory=memory,
                llm_client=llm_client,
            )
        ),
        "search_task": lambda outputs, node: searcher.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "plan": outputs["planner_task"].output,
                    "search_tool": search_tool,
                    "search_provider_registry": search_provider_registry,
                    "search_provider_order": search_provider_order,
                    "real_search_enabled": real_search_enabled,
                },
                metadata={"agent_name": searcher.name},
                memory=memory,
                llm_client=llm_client,
                search_provider_registry=search_provider_registry,
            )
        ),
        "reader_task": lambda outputs, node: reader.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "search_results": outputs["search_task"].output,
                    "fetch_tool": fetch_tool,
                    "web_fetcher": web_fetcher,
                    "citation_registry": citation_registry,
                },
                metadata={"agent_name": reader.name},
                memory=memory,
                llm_client=llm_client,
                web_fetcher=web_fetcher,
            )
        ),
        "writer_task": lambda outputs, node: writer.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "question": question,
                    "plan": outputs["planner_task"].output,
                    "findings": outputs["reader_task"].output,
                    "citation_registry": citation_registry,
                },
                metadata={"agent_name": writer.name},
                memory=memory,
                llm_client=llm_client,
            )
        ),
        "critic_task": lambda outputs, node: critic.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "report": outputs["writer_task"].output,
                    "findings": outputs["reader_task"].output,
                    "citation_registry": citation_registry,
                },
                metadata={"agent_name": critic.name},
                memory=memory,
                llm_client=llm_client,
            )
        ),
        "red_review_task": lambda outputs, node: red.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "report": outputs["writer_task"].output,
                    "findings": outputs["reader_task"].output,
                    "critic_review": outputs["critic_task"].output,
                    "citation_registry": citation_registry,
                },
                metadata={"agent_name": red.name},
                memory=memory,
                llm_client=llm_client,
            )
        ),
        "blue_revision_task": lambda outputs, node: blue.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "report": outputs["writer_task"].output,
                    "red_review": outputs["red_review_task"].output,
                    "findings": outputs["reader_task"].output,
                    "citation_registry": citation_registry,
                },
                metadata={"agent_name": blue.name},
                memory=memory,
                llm_client=llm_client,
            )
        ),
    }
    return {
        "question": question,
        "memory": memory,
        "citation_registry": citation_registry,
        "graph": graph,
        "handlers": handlers,
    }


def build_research_pipeline_result(
    question: ResearchQuestion,
    memory: SharedMemory,
    citation_registry: CitationRegistry,
    execution,
    use_red_blue_loop: bool = False,
    red_blue_loop_config: RedBlueLoopConfig | None = None,
    checkpoint: RunCheckpoint | None = None,
    resume_missing: bool = False,
) -> dict:
    outputs = execution.outputs
    blue_revision = outputs["blue_revision_task"].output
    red_blue_loop_result = None
    final_report = blue_revision.revised_report
    _restore_side_effects_from_outputs(
        outputs=outputs,
        memory=memory,
        citation_registry=citation_registry,
        execution_metadata=getattr(execution, "metadata", {}),
    )
    if use_red_blue_loop:
        red_blue_loop_result = RedBlueLoopRunner(
            red_agent=RedAgent(),
            blue_agent=BlueAgent(),
            config=red_blue_loop_config,
        ).run(
            AgentContext(
                task_id="red_blue_loop",
                inputs={"citation_registry": citation_registry},
                metadata={"agent_name": "RedBlueLoopRunner"},
                memory=memory,
            ),
            report=outputs["writer_task"].output,
            findings=outputs["reader_task"].output,
            critic_review=outputs["critic_task"].output,
        )
        final_report = red_blue_loop_result.final_report
    citation_validation = CitationValidator().validate_report_citations(
        final_report,
        citation_registry,
    )
    return {
        "run_id": checkpoint.run_id if checkpoint is not None else None,
        "question": question,
        "report": final_report,
        "final_report": final_report,
        "initial_report": outputs["writer_task"].output,
        "findings": outputs["reader_task"].output,
        "critic_review": outputs["critic_task"].output,
        "red_review": outputs["red_review_task"].output,
        "blue_revision": blue_revision,
        "red_blue_loop_result": red_blue_loop_result,
        "memory_items": memory.to_dict_list(),
        "memory": memory,
        "citation_registry": citation_registry,
        "citation_validation": citation_validation,
        "traces": execution.traces,
        "success": execution.success,
        "execution": execution,
        "checkpoint": checkpoint,
        "checkpoint_metadata": {
            **getattr(execution, "metadata", {}),
            "resume_checkpoint_missing": resume_missing,
        },
    }


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
