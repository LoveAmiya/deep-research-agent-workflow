"""DeepResearch 完整演示的命令行入口。

本模块只负责读取配置、创建 LLM/搜索/抓取工具并交给编排层执行。
把依赖装配集中在入口处，可以让流水线模块在测试中替换为 Mock 依赖。
"""

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


def build_demo_execution(
    load_dotenv: bool = False,
    resume_from_run_id: str | None = None,
    red_blue_loop_enabled: bool | None = None,
) -> dict:
    """创建依赖并运行同步或异步 DAG。

    返回值同时保留最终产物、运行时依赖和元数据，因此命令行与浏览器工作台
    不只展示报告本身，还能展示报告是如何一步步生成的。
    """
    llm_config = load_llm_config_from_env(load_dotenv=load_dotenv)
    search_config = load_search_config_from_env(load_dotenv=load_dotenv)
    dag_config = load_dag_execution_config_from_env(load_dotenv=load_dotenv)
    red_blue_loop_execution_config = load_red_blue_loop_config_from_env(load_dotenv=load_dotenv)
    if red_blue_loop_enabled is not None:
        red_blue_loop_execution_config.enabled = red_blue_loop_enabled
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
    # 两条路径使用相同依赖，方便在不修改 Agent 的前提下比较同步和异步执行。
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
    """运行演示，并输出报告质量、Trace 和恢复执行信息。"""
    cli_args = _parse_cli_args(sys.argv[1:])
    resume_from_run_id = cli_args["resume_from_run_id"]
    execution = build_demo_execution(
        load_dotenv=True,
        resume_from_run_id=resume_from_run_id,
        red_blue_loop_enabled=cli_args["red_blue_loop_enabled"],
    )
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
        print(
            "Red-Blue convergence status: "
            f"{red_blue_loop_result.metadata.get('red_blue_convergence_status')}"
        )
        print(
            "Red-Blue convergence stop reason: "
            f"{red_blue_loop_result.metadata.get('red_blue_stop_reason')}"
        )
        print(
            "Red-Blue oscillation detected: "
            f"{red_blue_loop_result.metadata.get('red_blue_oscillation_detected')}"
        )
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


def _parse_cli_args(args: list[str]) -> dict:
    """解析两个命令行参数，避免为演示项目额外引入 CLI 依赖。

    ``--resume <run_id>`` 复用已经成功的 Checkpoint 节点；
    ``--red-blue-loop`` 开启额外的审查与修订循环。
    """
    parsed = {
        "resume_from_run_id": None,
        "red_blue_loop_enabled": None,
    }
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--resume":
            if index + 1 < len(args) and not args[index + 1].startswith("--"):
                parsed["resume_from_run_id"] = args[index + 1]
                index += 2
                continue
        elif arg == "--red-blue-loop":
            parsed["red_blue_loop_enabled"] = True
        index += 1
    return parsed


def _parse_resume_arg(args: list[str]) -> str | None:
    return _parse_cli_args(args)["resume_from_run_id"]


if __name__ == "__main__":
    main()
