from core.config import load_llm_config_from_env, load_search_config_from_env
from core.llm_client import MockLLMClient, create_llm_client
from orchestrator.research_pipeline import run_research_pipeline
from tools.fetch_tool import MockFetchTool, create_fetch_tool
from tools.search_tool import MockSearchTool, create_search_tool


DEMO_QUESTION = "What are the main factors that affect open-source LLM adoption in enterprises?"


def build_demo_execution(load_dotenv: bool = False) -> dict:
    llm_config = load_llm_config_from_env(load_dotenv=load_dotenv)
    search_config = load_search_config_from_env(load_dotenv=load_dotenv)
    llm_client = create_llm_client(llm_config)
    search_tool = create_search_tool(search_config)
    fetch_tool = create_fetch_tool(search_config)
    result = run_research_pipeline(
        DEMO_QUESTION,
        llm_client=llm_client,
        search_tool=search_tool,
        fetch_tool=fetch_tool,
    )
    result["llm_config"] = llm_config
    result["llm_client"] = llm_client
    result["search_config"] = search_config
    result["search_tool"] = search_tool
    result["fetch_tool"] = fetch_tool
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
    fetch_tool = execution["fetch_tool"]
    dag_outputs = execution["execution"].outputs
    search_metadata = dag_outputs["search_task"].metadata
    reader_metadata = dag_outputs["reader_task"].metadata

    print(f"LLM enabled: {llm_config.enabled}")
    print(f"LLM provider/model: {llm_config.provider}/{llm_config.model or 'not-configured'}")
    if isinstance(llm_client, MockLLMClient):
        print("LLM mode: mock")
    print(f"Web search enabled: {search_config.enabled}")
    print(f"Search provider: {search_config.provider}")
    print(f"Search mode: {'mock' if isinstance(search_tool, MockSearchTool) else search_tool.provider}")
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
