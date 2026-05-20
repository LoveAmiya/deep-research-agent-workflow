from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class TaskNode:
    task_id: str
    name: str
    agent_name: str
    depends_on: List[str] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class TaskGraph:
    nodes: Dict[str, TaskNode] = field(default_factory=dict)

    def add_node(self, node: TaskNode) -> None:
        if node.task_id in self.nodes:
            raise ValueError(f"Duplicate task_id detected: {node.task_id}")
        self.nodes[node.task_id] = node

    def get_node(self, task_id: str) -> TaskNode:
        return self.nodes[task_id]

    def validate(self) -> None:
        for node in self.nodes.values():
            for dependency_id in node.depends_on:
                if dependency_id not in self.nodes:
                    raise ValueError(
                        f"Task '{node.task_id}' depends on missing task '{dependency_id}'."
                    )
        self._detect_cycles()

    def topological_sort(self) -> List[TaskNode]:
        self.validate()
        indegree_map = {task_id: 0 for task_id in self.nodes}
        adjacency: Dict[str, List[str]] = {task_id: [] for task_id in self.nodes}

        for node in self.nodes.values():
            for dependency_id in node.depends_on:
                indegree_map[node.task_id] += 1
                adjacency[dependency_id].append(node.task_id)

        ready_queue = deque(
            [task_id for task_id, indegree in indegree_map.items() if indegree == 0]
        )
        ordered_nodes: List[TaskNode] = []

        while ready_queue:
            task_id = ready_queue.popleft()
            ordered_nodes.append(self.nodes[task_id])
            for downstream_task_id in adjacency[task_id]:
                indegree_map[downstream_task_id] -= 1
                if indegree_map[downstream_task_id] == 0:
                    ready_queue.append(downstream_task_id)

        if len(ordered_nodes) != len(self.nodes):
            raise ValueError("Cycle detected while computing topological order.")

        return ordered_nodes

    def _detect_cycles(self) -> None:
        visited = set()
        active = set()

        def visit(task_id: str) -> None:
            if task_id in active:
                raise ValueError(f"Cycle detected involving task '{task_id}'.")
            if task_id in visited:
                return

            active.add(task_id)
            for dependency_id in self.nodes[task_id].depends_on:
                visit(dependency_id)
            active.remove(task_id)
            visited.add(task_id)

        for task_id in self.nodes:
            visit(task_id)
