from core.config import load_llm_config_from_env
from core.llm_client import MockLLMClient, create_llm_client
from orchestrator.research_pipeline import run_research_pipeline


DEMO_QUESTION = "What are the main factors that affect open-source LLM adoption in enterprises?"


def build_demo_execution() -> dict:
    config = load_llm_config_from_env()
    llm_client = create_llm_client(config)
    result = run_research_pipeline(DEMO_QUESTION, llm_client=llm_client)
    result["llm_config"] = config
    result["llm_client"] = llm_client
    return result


def build_demo_report() -> str:
    execution = build_demo_execution()
    return execution["report"].markdown


def build_demo_review() -> dict:
    execution = build_demo_execution()
    return execution["critic_review"]


def main() -> None:
    execution = build_demo_execution()
    critic_review = execution["critic_review"]
    red_review = execution["red_review"]
    blue_revision = execution["blue_revision"]
    memory = execution["memory"]
    final_report = execution["report"]
    llm_config = execution["llm_config"]
    llm_client = execution["llm_client"]

    print(f"LLM enabled: {llm_config.enabled}")
    print(f"LLM provider/model: {llm_config.provider}/{llm_config.model or 'not-configured'}")
    if isinstance(llm_client, MockLLMClient):
        print("LLM mode: mock")
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
