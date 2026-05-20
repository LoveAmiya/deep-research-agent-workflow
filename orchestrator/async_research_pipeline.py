from orchestrator.async_executor import AsyncDAGExecutor
from orchestrator.research_pipeline import (
    build_research_pipeline_components,
    build_research_pipeline_result,
)


async def async_run_research_pipeline(
    question_text: str,
    llm_client=None,
    search_tool=None,
    fetch_tool=None,
    citation_registry=None,
    max_concurrency: int = 3,
    task_timeout_seconds=None,
    use_red_blue_loop: bool = False,
    red_blue_loop_config=None,
) -> dict:
    components = build_research_pipeline_components(
        question_text=question_text,
        llm_client=llm_client,
        search_tool=search_tool,
        fetch_tool=fetch_tool,
        citation_registry=citation_registry,
    )
    execution = await AsyncDAGExecutor(
        graph=components["graph"],
        handlers=components["handlers"],
        max_concurrency=max_concurrency,
        task_timeout_seconds=task_timeout_seconds,
    ).execute()
    return build_research_pipeline_result(
        question=components["question"],
        memory=components["memory"],
        citation_registry=components["citation_registry"],
        execution=execution,
        use_red_blue_loop=use_red_blue_loop,
        red_blue_loop_config=red_blue_loop_config,
    )
