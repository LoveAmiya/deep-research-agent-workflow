from agents.planner_agent import PlannerAgent
from agents.reader_agent import ReaderAgent
from agents.searcher_agent import SearcherAgent
from agents.writer_agent import WriterAgent
from core.schema import ResearchQuestion


def build_demo_report() -> str:
    question = ResearchQuestion(
        question="What are the main factors that affect open-source LLM adoption in enterprises?"
    )
    planner = PlannerAgent()
    searcher = SearcherAgent()
    reader = ReaderAgent()
    writer = WriterAgent()

    plan = planner.run(question)
    results = searcher.run(plan)
    findings = reader.run(results)
    report = writer.run(question, plan, findings)
    return report.markdown


def main() -> None:
    print(build_demo_report())


if __name__ == "__main__":
    main()
