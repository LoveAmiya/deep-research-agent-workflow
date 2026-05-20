from orchestrator.async_executor import AsyncDAGExecutor
from orchestrator.checkpoint import JSONCheckpointStore, RunCheckpoint
from orchestrator.research_pipeline import (
    build_research_pipeline_components,
    build_research_pipeline_result,
)


async def async_run_research_pipeline(
    question_text: str,
    llm_client=None,
    search_tool=None,
    search_provider_registry=None,
    search_provider_order=None,
    real_search_enabled: bool = False,
    fetch_tool=None,
    web_fetcher=None,
    citation_registry=None,
    max_concurrency: int = 3,
    task_timeout_seconds=None,
    use_red_blue_loop: bool = False,
    red_blue_loop_config=None,
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
    execution = await AsyncDAGExecutor(
        graph=components["graph"],
        handlers=components["handlers"],
        max_concurrency=max_concurrency,
        task_timeout_seconds=task_timeout_seconds,
        checkpoint_store=checkpoint_store,
        checkpoint=checkpoint,
        checkpoint_enabled=checkpoint is not None and checkpoint_store is not None,
        resume=resumed,
    ).execute()
    return build_research_pipeline_result(
        question=components["question"],
        memory=components["memory"],
        citation_registry=components["citation_registry"],
        execution=execution,
        use_red_blue_loop=use_red_blue_loop,
        red_blue_loop_config=red_blue_loop_config,
        checkpoint=checkpoint,
        resume_missing=resume_missing,
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
