from agents.base_agent import AgentContext, AgentResult
from agents.critic_agent import CriticAgent
from agents.planner_agent import PlannerAgent
from agents.reader_agent import ReaderAgent
from agents.searcher_agent import SearcherAgent
from agents.writer_agent import WriterAgent
from core.schema import ResearchQuestion
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

    graph = build_minimal_research_graph()
    handlers = {
        "planner_task": lambda outputs, node: planner.run(
            AgentContext(
                task_id=node.task_id,
                inputs={"question": question},
                metadata={"agent_name": planner.name},
            )
        ),
        "search_task": lambda outputs, node: searcher.run(
            AgentContext(
                task_id=node.task_id,
                inputs={"plan": outputs["planner_task"].output},
                metadata={"agent_name": searcher.name},
            )
        ),
        "reader_task": lambda outputs, node: reader.run(
            AgentContext(
                task_id=node.task_id,
                inputs={"search_results": outputs["search_task"].output},
                metadata={"agent_name": reader.name},
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
            )
        ),
    }
    executor = DAGExecutor(graph=graph, handlers=handlers)
    return executor.execute()


def build_demo_report() -> str:
    execution = build_demo_execution()
    report_result = execution.outputs["writer_task"]
    report = report_result.output
    return report.markdown


def build_demo_review() -> dict:
    execution = build_demo_execution()
    critic_result = execution.outputs["critic_task"]
    return critic_result.output


def main() -> None:
    execution = build_demo_execution()
    report_result = execution.outputs["writer_task"]
    critic_result = execution.outputs["critic_task"]
    report = report_result.output
    review = critic_result.output

    print(report.markdown)
    print()
    print(f"Review passed: {review['passed']}")
    print(f"Issues: {review['issues']}")


if __name__ == "__main__":
    main()
