from agents.base_agent import AgentContext, AgentResult
from agents.blue_agent import BlueAgent
from agents.critic_agent import CriticAgent
from agents.planner_agent import PlannerAgent
from agents.reader_agent import ReaderAgent
from agents.red_agent import RedAgent
from agents.searcher_agent import SearcherAgent
from agents.writer_agent import WriterAgent
from core.schema import ResearchQuestion
from memory.store import SharedMemory
from orchestrator.executor import DAGExecutor, ExecutionResult
from orchestrator.research_pipeline import build_minimal_research_graph


def build_demo_execution() -> ExecutionResult:
    question = ResearchQuestion(
        question="What are the main factors that affect open-source LLM adoption in enterprises?"
    )
    planner = PlannerAgent()
    searcher = SearcherAgent()
    reader = ReaderAgent()
    writer = WriterAgent()
    critic = CriticAgent()
    red = RedAgent()
    blue = BlueAgent()
    memory = SharedMemory()

    graph = build_minimal_research_graph()
    handlers = {
        "planner_task": lambda outputs, node: planner.run(
            AgentContext(
                task_id=node.task_id,
                inputs={"question": question},
                metadata={"agent_name": planner.name},
                memory=memory,
            )
        ),
        "search_task": lambda outputs, node: searcher.run(
            AgentContext(
                task_id=node.task_id,
                inputs={"plan": outputs["planner_task"].output},
                metadata={"agent_name": searcher.name},
                memory=memory,
            )
        ),
        "reader_task": lambda outputs, node: reader.run(
            AgentContext(
                task_id=node.task_id,
                inputs={"search_results": outputs["search_task"].output},
                metadata={"agent_name": reader.name},
                memory=memory,
            )
        ),
        "writer_task": lambda outputs, node: writer.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "question": question,
                    "plan": outputs["planner_task"].output,
                    "findings": outputs["reader_task"].output,
                },
                metadata={"agent_name": writer.name},
                memory=memory,
            )
        ),
        "critic_task": lambda outputs, node: critic.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "report": outputs["writer_task"].output,
                    "findings": outputs["reader_task"].output,
                },
                metadata={"agent_name": critic.name},
                memory=memory,
            )
        ),
        "red_review_task": lambda outputs, node: red.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "report": outputs["writer_task"].output,
                    "findings": outputs["reader_task"].output,
                    "critic_review": outputs["critic_task"].output,
                },
                metadata={"agent_name": red.name},
                memory=memory,
            )
        ),
        "blue_revision_task": lambda outputs, node: blue.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "report": outputs["writer_task"].output,
                    "red_review": outputs["red_review_task"].output,
                    "findings": outputs["reader_task"].output,
                },
                metadata={"agent_name": blue.name},
                memory=memory,
            )
        ),
    }
    executor = DAGExecutor(graph=graph, handlers=handlers)
    result = executor.execute()
    result.outputs["shared_memory"] = memory
    return result


def build_demo_report() -> str:
    execution = build_demo_execution()
    revision_result = execution.outputs["blue_revision_task"]
    return revision_result.output.revised_report.markdown


def build_demo_review() -> dict:
    execution = build_demo_execution()
    critic_result = execution.outputs["critic_task"]
    return critic_result.output


def main() -> None:
    execution = build_demo_execution()
    writer_result = execution.outputs["writer_task"]
    critic_result = execution.outputs["critic_task"]
    red_result = execution.outputs["red_review_task"]
    blue_result = execution.outputs["blue_revision_task"]
    memory = execution.outputs["shared_memory"]
    initial_report = writer_result.output
    critic_review = critic_result.output
    red_review = red_result.output
    blue_revision = blue_result.output
    final_report = blue_revision.revised_report

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
