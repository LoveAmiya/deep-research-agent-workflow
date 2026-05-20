from agents.base_agent import AgentContext
from agents.blue_agent import BlueAgent
from agents.critic_agent import CriticAgent
from agents.planner_agent import PlannerAgent
from agents.reader_agent import ReaderAgent
from agents.red_agent import RedAgent
from agents.searcher_agent import SearcherAgent
from agents.writer_agent import WriterAgent
from core.schema import ResearchQuestion
from memory.store import SharedMemory
from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.executor import DAGExecutor
from tools.citation_tool import CitationRegistry, CitationValidator


def build_minimal_research_graph() -> TaskGraph:
    graph = TaskGraph()
    graph.add_node(
        TaskNode(
            task_id="planner_task",
            name="Planner Task",
            agent_name="PlannerAgent",
        )
    )
    graph.add_node(
        TaskNode(
            task_id="search_task",
            name="Search Task",
            agent_name="SearcherAgent",
            depends_on=["planner_task"],
        )
    )
    graph.add_node(
        TaskNode(
            task_id="reader_task",
            name="Reader Task",
            agent_name="ReaderAgent",
            depends_on=["search_task"],
        )
    )
    graph.add_node(
        TaskNode(
            task_id="writer_task",
            name="Writer Task",
            agent_name="WriterAgent",
            depends_on=["reader_task"],
        )
    )
    graph.add_node(
        TaskNode(
            task_id="critic_task",
            name="Critic Task",
            agent_name="CriticAgent",
            depends_on=["writer_task"],
        )
    )
    graph.add_node(
        TaskNode(
            task_id="red_review_task",
            name="Red Review Task",
            agent_name="RedAgent",
            depends_on=["critic_task"],
        )
    )
    graph.add_node(
        TaskNode(
            task_id="blue_revision_task",
            name="Blue Revision Task",
            agent_name="BlueAgent",
            depends_on=["red_review_task"],
        )
    )
    return graph


def run_research_pipeline(
    question_text: str,
    llm_client=None,
    search_tool=None,
    fetch_tool=None,
    citation_registry=None,
) -> dict:
    question = ResearchQuestion(question=question_text)
    planner = PlannerAgent()
    searcher = SearcherAgent()
    reader = ReaderAgent()
    writer = WriterAgent()
    critic = CriticAgent()
    red = RedAgent()
    blue = BlueAgent()
    memory = SharedMemory()
    if citation_registry is None:
        citation_registry = CitationRegistry()

    graph = build_minimal_research_graph()
    handlers = {
        "planner_task": lambda outputs, node: planner.run(
            AgentContext(
                task_id=node.task_id,
                inputs={"question": question},
                metadata={"agent_name": planner.name},
                memory=memory,
                llm_client=llm_client,
            )
        ),
        "search_task": lambda outputs, node: searcher.run(
            AgentContext(
                task_id=node.task_id,
                inputs={"plan": outputs["planner_task"].output, "search_tool": search_tool},
                metadata={"agent_name": searcher.name},
                memory=memory,
                llm_client=llm_client,
            )
        ),
        "reader_task": lambda outputs, node: reader.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "search_results": outputs["search_task"].output,
                    "fetch_tool": fetch_tool,
                    "citation_registry": citation_registry,
                },
                metadata={"agent_name": reader.name},
                memory=memory,
                llm_client=llm_client,
            )
        ),
        "writer_task": lambda outputs, node: writer.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "question": question,
                    "plan": outputs["planner_task"].output,
                    "findings": outputs["reader_task"].output,
                    "citation_registry": citation_registry,
                },
                metadata={"agent_name": writer.name},
                memory=memory,
                llm_client=llm_client,
            )
        ),
        "critic_task": lambda outputs, node: critic.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "report": outputs["writer_task"].output,
                    "findings": outputs["reader_task"].output,
                    "citation_registry": citation_registry,
                },
                metadata={"agent_name": critic.name},
                memory=memory,
                llm_client=llm_client,
            )
        ),
        "red_review_task": lambda outputs, node: red.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "report": outputs["writer_task"].output,
                    "findings": outputs["reader_task"].output,
                    "critic_review": outputs["critic_task"].output,
                    "citation_registry": citation_registry,
                },
                metadata={"agent_name": red.name},
                memory=memory,
                llm_client=llm_client,
            )
        ),
        "blue_revision_task": lambda outputs, node: blue.run(
            AgentContext(
                task_id=node.task_id,
                inputs={
                    "report": outputs["writer_task"].output,
                    "red_review": outputs["red_review_task"].output,
                    "findings": outputs["reader_task"].output,
                    "citation_registry": citation_registry,
                },
                metadata={"agent_name": blue.name},
                memory=memory,
                llm_client=llm_client,
            )
        ),
    }
    execution = DAGExecutor(graph=graph, handlers=handlers).execute()
    outputs = execution.outputs
    blue_revision = outputs["blue_revision_task"].output
    citation_validation = CitationValidator().validate_report_citations(
        blue_revision.revised_report,
        citation_registry,
    )
    return {
        "question": question,
        "report": blue_revision.revised_report,
        "initial_report": outputs["writer_task"].output,
        "findings": outputs["reader_task"].output,
        "critic_review": outputs["critic_task"].output,
        "red_review": outputs["red_review_task"].output,
        "blue_revision": blue_revision,
        "memory_items": memory.to_dict_list(),
        "memory": memory,
        "citation_registry": citation_registry,
        "citation_validation": citation_validation,
        "traces": execution.traces,
        "success": execution.success,
        "execution": execution,
    }
