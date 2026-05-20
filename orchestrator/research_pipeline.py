from orchestrator.dag import TaskGraph, TaskNode


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
