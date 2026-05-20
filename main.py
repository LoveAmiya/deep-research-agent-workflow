import asyncio
import sys

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
from search.fetchers import MockWebFetcher, create_web_fetcher
from tools.fetch_tool import MockFetchTool, create_fetch_tool
from tools.search_tool import MockSearchTool, create_search_tool


DEMO_QUESTION = "What are the main factors that affect open-source LLM adoption in enterprises?"
DEFAULT_CHECKPOINT_DIR = "runs/checkpoints"


def build_demo_execution(load_dotenv: bool = False, resume_from_run_id: str | None = None) -> dict:
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
    web_fetcher = create_web_fetcher(search_config)
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
                web_fetcher=web_fetcher,
                max_concurrency=dag_config.max_concurrency,
                task_timeout_seconds=dag_config.task_timeout_seconds,
                use_red_blue_loop=red_blue_loop_execution_config.enabled,
                red_blue_loop_config=red_blue_loop_config,
                checkpoint_enabled=True,
                resume_from_run_id=resume_from_run_id,
                checkpoint_dir=DEFAULT_CHECKPOINT_DIR,
                replan_enabled=True,
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
            web_fetcher=web_fetcher,
            use_red_blue_loop=red_blue_loop_execution_config.enabled,
            red_blue_loop_config=red_blue_loop_config,
            checkpoint_enabled=True,
            resume_from_run_id=resume_from_run_id,
            checkpoint_dir=DEFAULT_CHECKPOINT_DIR,
            replan_enabled=True,
        )
    result["llm_config"] = llm_config
    result["llm_client"] = llm_client
    result["search_config"] = search_config
    result["search_tool"] = search_tool
    result["search_provider_registry"] = search_provider_registry
    result["fetch_tool"] = fetch_tool
    result["web_fetcher"] = web_fetcher
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
    resume_from_run_id = _parse_resume_arg(sys.argv[1:])
    execution = build_demo_execution(load_dotenv=True, resume_from_run_id=resume_from_run_id)
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
    web_fetcher = execution["web_fetcher"]
    dag_config = execution["dag_config"]
    red_blue_loop_execution_config = execution["red_blue_loop_execution_config"]
    run_store_config = execution["run_store_config"]
    red_blue_loop_result = execution.get("red_blue_loop_result")
    dag_outputs = execution["execution"].outputs
    search_metadata = dag_outputs["search_task"].metadata
    reader_metadata = dag_outputs["reader_task"].metadata
    checkpoint_metadata = execution.get("checkpoint_metadata", {})

    print(f"Run ID: {execution.get('run_id')}")
    print(f"Checkpoint enabled: {checkpoint_metadata.get('checkpoint_enabled')}")
    print(f"Checkpoint path: {checkpoint_metadata.get('checkpoint_path')}")
    print(f"Checkpoint save count: {checkpoint_metadata.get('checkpoint_save_count')}")
    print(f"Resumed: {checkpoint_metadata.get('resumed')}")
    print(f"Resumed from run_id: {checkpoint_metadata.get('resumed_from_run_id')}")
    print(f"Skipped node count: {checkpoint_metadata.get('skipped_node_count')}")
    print(f"Reexecuted node count: {checkpoint_metadata.get('reexecuted_node_count')}")
    print(f"Replan enabled: {checkpoint_metadata.get('replan_enabled')}")
    print(f"Replan attempts: {checkpoint_metadata.get('replan_attempts')}")
    print(f"Replan actions: {checkpoint_metadata.get('replan_actions')}")
    print(f"Force synthesis used: {checkpoint_metadata.get('force_synthesis_used')}")
    if checkpoint_metadata.get("resume_checkpoint_missing"):
        print(f"Resume checkpoint missing; started a new run for requested id: {resume_from_run_id}")
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
    print(f"Web fetcher: {reader_metadata.get('fetcher_name')}")
    if isinstance(web_fetcher, MockWebFetcher):
        print("Web fetcher mode: mock")
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


def _parse_resume_arg(args: list[str]) -> str | None:
    if not args:
        return None
    if args[0] == "--resume" and len(args) >= 2:
        return args[1]
    return None


if __name__ == "__main__":
    main()
