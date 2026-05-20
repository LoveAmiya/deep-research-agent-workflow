import json
import unittest

from agents.base_agent import AgentContext
from agents.critic_agent import CriticAgent
from agents.planner_agent import PlannerAgent
from agents.reader_agent import ReaderAgent
from agents.searcher_agent import SearcherAgent
from agents.writer_agent import WriterAgent
from core.schema import Finding, ResearchQuestion
from memory.compression import compress_findings
from memory.store import MemoryItem, SharedMemory
from orchestrator.executor import DAGExecutor
from orchestrator.research_pipeline import build_minimal_research_graph


class TestSharedMemory(unittest.TestCase):
    def test_shared_memory_can_add_item(self) -> None:
        memory = SharedMemory()
        item = MemoryItem(
            item_id="item-1",
            item_type="plan",
            content={"value": 1},
            source_agent="PlannerAgent",
        )

        stored = memory.add(item)

        self.assertIs(stored, item)
        self.assertEqual(len(memory.all_items()), 1)

    def test_shared_memory_can_query_by_type(self) -> None:
        memory = SharedMemory()
        memory.add_record("plan", {"a": 1}, "PlannerAgent")
        memory.add_record("report", {"b": 2}, "WriterAgent")

        items = memory.list_by_type("plan")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item_type, "plan")

    def test_shared_memory_can_query_by_agent(self) -> None:
        memory = SharedMemory()
        memory.add_record("findings", {"a": 1}, "ReaderAgent")
        memory.add_record("report", {"b": 2}, "WriterAgent")

        items = memory.list_by_agent("ReaderAgent")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_agent, "ReaderAgent")

    def test_add_record_creates_memory_item(self) -> None:
        memory = SharedMemory()

        item = memory.add_record("review", {"passed": True}, "CriticAgent")

        self.assertIsInstance(item, MemoryItem)
        self.assertEqual(item.item_type, "review")

    def test_duplicate_item_is_not_added_twice(self) -> None:
        memory = SharedMemory()

        first = memory.add_record("plan", {"value": 1}, "PlannerAgent")
        second = memory.add_record("plan", {"value": 1}, "PlannerAgent")

        self.assertEqual(first.item_id, second.item_id)
        self.assertEqual(len(memory.all_items()), 1)

    def test_to_dict_list_is_json_friendly(self) -> None:
        memory = SharedMemory()
        memory.add_record("plan", {"steps": ["a", "b"]}, "PlannerAgent")

        payload = memory.to_dict_list()
        serialized = json.dumps(payload)

        self.assertTrue(serialized)
        self.assertEqual(payload[0]["item_type"], "plan")

    def test_compress_findings_can_truncate(self) -> None:
        findings = [
            Finding(claim=f"claim-{index}", evidence="evidence", source_url=f"mock://{index}")
            for index in range(7)
        ]

        compressed = compress_findings(findings, max_items=5)

        self.assertEqual(len(compressed), 5)
        self.assertEqual(compressed[0].claim, "claim-0")

    def test_agent_context_can_carry_memory(self) -> None:
        memory = SharedMemory()
        context = AgentContext(task_id="task-1", memory=memory)

        self.assertIs(context.memory, memory)

    def test_planner_writes_plan_memory(self) -> None:
        memory = SharedMemory()
        planner = PlannerAgent()
        question = ResearchQuestion(question="How should teams evaluate open-source LLMs?")

        result = planner.run(
            AgentContext(
                task_id="planner_task",
                inputs={"question": question},
                memory=memory,
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(len(memory.list_by_type("plan")), 1)

    def test_reader_writes_findings_memory(self) -> None:
        memory = SharedMemory()
        planner = PlannerAgent()
        searcher = SearcherAgent()
        reader = ReaderAgent()
        question = ResearchQuestion(question="How should teams evaluate open-source LLMs?")

        plan = planner.run(
            AgentContext(task_id="planner_task", inputs={"question": question}, memory=memory)
        ).output
        search_results = searcher.run(
            AgentContext(task_id="search_task", inputs={"plan": plan}, memory=memory)
        ).output
        result = reader.run(
            AgentContext(
                task_id="reader_task",
                inputs={"search_results": search_results},
                memory=memory,
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(len(memory.list_by_type("findings")), 1)

    def test_full_pipeline_populates_memory(self) -> None:
        memory = SharedMemory()
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
                AgentContext(task_id=node.task_id, inputs={"question": question}, memory=memory)
            ),
            "search_task": lambda outputs, node: searcher.run(
                AgentContext(
                    task_id=node.task_id,
                    inputs={"plan": outputs["planner_task"].output},
                    memory=memory,
                )
            ),
            "reader_task": lambda outputs, node: reader.run(
                AgentContext(
                    task_id=node.task_id,
                    inputs={"search_results": outputs["search_task"].output},
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
                    memory=memory,
                )
            ),
        }

        result = DAGExecutor(graph=graph, handlers=handlers).execute()

        self.assertTrue(result.success)
        self.assertEqual(len(memory.list_by_type("plan")), 1)
        self.assertEqual(len(memory.list_by_type("search_results")), 1)
        self.assertEqual(len(memory.list_by_type("findings")), 1)
        self.assertEqual(len(memory.list_by_type("report")), 1)
        self.assertEqual(len(memory.list_by_type("review")), 1)


if __name__ == "__main__":
    unittest.main()
