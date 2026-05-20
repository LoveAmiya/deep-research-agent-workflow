from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from agents.base_agent import AgentResult
from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.state import TaskState
from orchestrator.trace import TraceRecorder

TaskHandler = Callable[[Dict[str, Any], TaskNode], Any]


@dataclass
class ExecutionResult:
    success: bool
    outputs: Dict[str, Any] = field(default_factory=dict)
    states: Dict[str, TaskState] = field(default_factory=dict)
    traces: list[dict] = field(default_factory=list)


class DAGExecutor:
    def __init__(
        self,
        graph: TaskGraph,
        handlers: Dict[str, TaskHandler],
        trace_recorder: Optional[TraceRecorder] = None,
    ) -> None:
        self.graph = graph
        self.handlers = handlers
        self.trace_recorder = trace_recorder or TraceRecorder()

    def execute(self) -> ExecutionResult:
        self.graph.validate()
        self._validate_handlers()

        ordered_nodes = self.graph.topological_sort()
        outputs: Dict[str, Any] = {}
        states: Dict[str, TaskState] = {
            task_id: TaskState.PENDING for task_id in self.graph.nodes
        }

        for node in ordered_nodes:
            if self._should_skip(node, states):
                states[node.task_id] = TaskState.SKIPPED
                self.trace_recorder.record(
                    task_id=node.task_id,
                    task_name=node.name,
                    state=TaskState.SKIPPED,
                    metadata={"depends_on": list(node.depends_on)},
                )
                continue

            states[node.task_id] = TaskState.RUNNING
            self.trace_recorder.record(
                task_id=node.task_id,
                task_name=node.name,
                state=TaskState.RUNNING,
                metadata={"agent_name": node.agent_name},
            )

            try:
                handler = self.handlers[node.task_id]
                outputs[node.task_id] = handler(outputs, node)
                if isinstance(outputs[node.task_id], AgentResult) and not outputs[node.task_id].success:
                    raise RuntimeError(outputs[node.task_id].error or "Agent returned unsuccessful result.")
            except Exception as exc:
                states[node.task_id] = TaskState.FAILED
                self.trace_recorder.record(
                    task_id=node.task_id,
                    task_name=node.name,
                    state=TaskState.FAILED,
                    error=str(exc),
                    metadata={"agent_name": node.agent_name},
                )
                continue

            states[node.task_id] = TaskState.SUCCESS
            self.trace_recorder.record(
                task_id=node.task_id,
                task_name=node.name,
                state=TaskState.SUCCESS,
                metadata={"agent_name": node.agent_name},
            )

        success = all(state == TaskState.SUCCESS for state in states.values())
        return ExecutionResult(
            success=success,
            outputs=outputs,
            states=states,
            traces=self.trace_recorder.to_dict_list(),
        )

    def _should_skip(self, node: TaskNode, states: Dict[str, TaskState]) -> bool:
        return any(
            states[dependency_id] in {TaskState.FAILED, TaskState.SKIPPED}
            for dependency_id in node.depends_on
        )

    def _validate_handlers(self) -> None:
        missing_handlers = [
            task_id for task_id in self.graph.nodes if task_id not in self.handlers
        ]
        if missing_handlers:
            missing = ", ".join(missing_handlers)
            raise ValueError(f"Missing handlers for task ids: {missing}")
