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

    graph = build_minimal_research_graph()
    handlers = {
        "planner_task": lambda outputs, node: planner.run(question),
        "search_task": lambda outputs, node: searcher.run(outputs["planner_task"]),
        "reader_task": lambda outputs, node: reader.run(outputs["search_task"]),
        "writer_task": lambda outputs, node: writer.run(
            question,
            outputs["planner_task"],
            outputs["reader_task"],
        ),
    }
    executor = DAGExecutor(graph=graph, handlers=handlers)
    return executor.execute()


def build_demo_report() -> str:
    execution = build_demo_execution()
    report = execution.outputs["writer_task"]
    return report.markdown


def main() -> None:
    print(build_demo_report())


if __name__ == "__main__":
    main()
