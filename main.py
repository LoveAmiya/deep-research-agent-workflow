import asyncio

from core.config import (
    load_dag_execution_config_from_env,
    load_llm_config_from_env,
    load_red_blue_loop_config_from_env,
    load_run_store_config_from_env,
    load_search_config_from_env,
)
from core.llm_client import MockLLMClient, create_llm_client
from agents.red_blue_loop import RedBlueLoopConfig
from memory.persistent_store import SQLiteRunStore
from orchestrator.async_research_pipeline import async_run_research_pipeline
from orchestrator.research_pipeline import run_research_pipeline
from search.providers import MockSearchProvider
from search.registry import create_search_provider_registry
from tools.fetch_tool import MockFetchTool, create_fetch_tool
from tools.search_tool import MockSearchTool, create_search_tool


DEMO_QUESTION = "What are the main factors that affect open-source LLM adoption in enterprises?"


def build_demo_execution(load_dotenv: bool = False) -> dict:
    llm_config = load_llm_config_from_env(load_dotenv=load_dotenv)
    search_config = load_search_config_from_env(load_dotenv=load_dotenv)
    dag_config = load_dag_execution_config_from_env(load_dotenv=load_dotenv)
    red_blue_loop_execution_config = load_red_blue_loop_config_from_env(load_dotenv=load_dotenv)
    run_store_config = load_run_store_config_from_env(load_dotenv=load_dotenv)
    red_blue_loop_config = RedBlueLoopConfig(
        max_rounds=red_blue_loop_execution_config.max_rounds,
        stop_if_no_improvement_rounds=red_blue_loop_execution_config.stop_if_no_improvement_rounds,
        enable_oscillation_detection=red_blue_loop_execution_config.enable_oscillation_detection,
    )
    llm_client = create_llm_client(llm_config)
    search_tool = create_search_tool(search_config)
    search_provider_registry = create_search_provider_registry(search_config)
    fetch_tool = create_fetch_tool(search_config)
    if dag_config.use_async:
        result = asyncio.run(
            async_run_research_pipeline(
                DEMO_QUESTION,
                llm_client=llm_client,
                search_tool=search_tool,
                search_provider_registry=search_provider_registry,
                search_provider_order=search_config.provider_order,
                real_search_enabled=search_config.real_search_enabled,
                fetch_tool=fetch_tool,
                max_concurrency=dag_config.max_concurrency,
                task_timeout_seconds=dag_config.task_timeout_seconds,
                use_red_blue_loop=red_blue_loop_execution_config.enabled,
                red_blue_loop_config=red_blue_loop_config,
            )
        )
    else:
        result = run_research_pipeline(
            DEMO_QUESTION,
            llm_client=llm_client,
            search_tool=search_tool,
            search_provider_registry=search_provider_registry,
            search_provider_order=search_config.provider_order,
            real_search_enabled=search_config.real_search_enabled,
            fetch_tool=fetch_tool,
            use_red_blue_loop=red_blue_loop_execution_config.enabled,
            red_blue_loop_config=red_blue_loop_config,
        )
    result["llm_config"] = llm_config
    result["llm_client"] = llm_client
    result["search_config"] = search_config
    result["search_tool"] = search_tool
    result["search_provider_registry"] = search_provider_registry
    result["fetch_tool"] = fetch_tool
    result["dag_config"] = dag_config
    result["red_blue_loop_execution_config"] = red_blue_loop_execution_config
    result["run_store_config"] = run_store_config
    return result


def build_demo_report() -> str:
    execution = build_demo_execution()
    return execution["report"].markdown


def build_demo_review() -> dict:
    execution = build_demo_execution()
    return execution["critic_review"]


def main() -> None:
    execution = build_demo_execution(load_dotenv=True)
    critic_review = execution["critic_review"]
    red_review = execution["red_review"]
    blue_revision = execution["blue_revision"]
    memory = execution["memory"]
    final_report = execution["report"]
    citation_validation = execution["citation_validation"]
    llm_config = execution["llm_config"]
    llm_client = execution["llm_client"]
    search_config = execution["search_config"]
    search_tool = execution["search_tool"]
    search_provider_registry = execution["search_provider_registry"]
    fetch_tool = execution["fetch_tool"]
    dag_config = execution["dag_config"]
    red_blue_loop_execution_config = execution["red_blue_loop_execution_config"]
    run_store_config = execution["run_store_config"]
    red_blue_loop_result = execution.get("red_blue_loop_result")
    dag_outputs = execution["execution"].outputs
    search_metadata = dag_outputs["search_task"].metadata
    reader_metadata = dag_outputs["reader_task"].metadata

    print(f"LLM enabled: {llm_config.enabled}")
    print(f"LLM provider/model: {llm_config.provider}/{llm_config.model or 'not-configured'}")
    if isinstance(llm_client, MockLLMClient):
        print("LLM mode: mock")
    print(f"DAG mode: {'async' if dag_config.use_async else 'sync'}")
    if dag_config.use_async:
        print(f"DAG max_concurrency: {dag_config.max_concurrency}")
        print(f"DAG task_timeout_seconds: {dag_config.task_timeout_seconds}")
    print(f"Web search enabled: {search_config.enabled}")
    print(f"Search provider order: {search_config.provider_order}")
    print(f"Search provider selected: {search_metadata.get('search_provider')}")
    print(f"Search mode: {'mock' if isinstance(search_tool, MockSearchTool) else search_tool.provider}")
    if isinstance(search_provider_registry.get(search_metadata.get("search_provider", "mock")), MockSearchProvider):
        print("Search provider mode: mock")
    print(f"Fetch mode: {'mock' if isinstance(fetch_tool, MockFetchTool) else fetch_tool.provider}")
    if search_metadata.get("fallback_used") or reader_metadata.get("fallback_used"):
        print(
            "Fallback summary: "
            f"search_fallback={search_metadata.get('fallback_used')}, "
            f"fetch_fallback={reader_metadata.get('fallback_used')}"
        )
    print(f"Citation count: {citation_validation['citation_count']}")
    print(f"Grounded citation count: {citation_validation['grounded_citation_count']}")
    print(f"Citation validation passed: {citation_validation['passed']}")
    print(f"Red-Blue loop enabled: {red_blue_loop_execution_config.enabled}")
    if red_blue_loop_execution_config.enabled and red_blue_loop_result is not None:
        print(f"Red-Blue max_rounds: {red_blue_loop_execution_config.max_rounds}")
        print(f"Red-Blue loop rounds: {len(red_blue_loop_result.rounds)}")
        print(f"Red-Blue loop stop_reason: {red_blue_loop_result.stop_reason}")
        print(f"Red-Blue loop total_fixed_issues: {red_blue_loop_result.total_fixed_issues}")
        print(f"Red-Blue loop remaining_issue_count: {red_blue_loop_result.remaining_issue_count}")
    if run_store_config.enabled:
        try:
            saved_record = SQLiteRunStore(run_store_config.db_path).save_run_result(execution)
            print("Run saved: true")
            print(f"run_id: {saved_record.run_id}")
            print(f"run_store_path: {run_store_config.db_path}")
        except Exception as exc:
            print("Run saved: false")
            print(f"run_store_error: {exc}")
    print()
    print(final_report.markdown)
    print()
    print(f"Critic review passed: {critic_review['passed']}")
    print(f"Critic issues: {critic_review['issues']}")
    print(f"Red review passed: {red_review.passed}")
    print(f"Red issues: {len(red_review.issues)}")
    print(f"Blue fixed issues: {blue_revision.fixed_issue_ids}")
    print(f"Blue remaining issues: {blue_revision.remaining_issue_ids}")
    print()
    print("Shared memory items:")
    for item_type in [
        "plan",
        "search_results",
        "findings",
        "report",
        "review",
        "red_review",
        "blue_revision",
    ]:
        print(f"- {item_type}: {len(memory.list_by_type(item_type))}")


if __name__ == "__main__":
    main()
