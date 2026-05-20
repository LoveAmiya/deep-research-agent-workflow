import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from agents.base_agent import AgentResult
from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.state import TaskState
from orchestrator.trace import TraceRecorder

AsyncTaskHandler = Callable[[Dict[str, Any], TaskNode], Any]


@dataclass
class AsyncExecutionResult:
    success: bool
    outputs: Dict[str, Any] = field(default_factory=dict)
    states: Dict[str, TaskState] = field(default_factory=dict)
    traces: list[dict] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)


class AsyncDAGExecutor:
    def __init__(
        self,
        graph: TaskGraph,
        handlers: Dict[str, AsyncTaskHandler],
        max_concurrency: int = 3,
        task_timeout_seconds: Optional[float] = None,
        trace_recorder: Optional[TraceRecorder] = None,
    ) -> None:
        self.graph = graph
        self.handlers = handlers
        self.max_concurrency = max(1, max_concurrency)
        self.task_timeout_seconds = task_timeout_seconds
        self.trace_recorder = trace_recorder or TraceRecorder()

    async def execute(self) -> AsyncExecutionResult:
        self.graph.validate()
        self._validate_handlers()

        states: Dict[str, TaskState] = {
            task_id: TaskState.PENDING for task_id in self.graph.nodes
        }
        outputs: Dict[str, Any] = {}
        errors: Dict[str, str] = {}
        completed: set[str] = set()
        running: Dict[str, asyncio.Task] = {}
        semaphore = asyncio.Semaphore(self.max_concurrency)

        while len(completed) < len(self.graph.nodes):
            self._skip_blocked_tasks(states, completed)
            ready_nodes = self._ready_nodes(states, completed, running)
            for node in ready_nodes:
                running[node.task_id] = asyncio.create_task(
                    self._run_node(node, outputs, states, errors, semaphore)
                )

            if not running:
                break

            done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                finished_task_id = self._task_id_for_async_task(running, task)
                if finished_task_id is not None:
                    completed.add(finished_task_id)
                    del running[finished_task_id]

        self._skip_blocked_tasks(states, completed)
        success = all(state == TaskState.SUCCESS for state in states.values())
        return AsyncExecutionResult(
            success=success,
            outputs=outputs,
            states=states,
            traces=self.trace_recorder.to_dict_list(),
            errors=errors,
        )

    async def _run_node(
        self,
        node: TaskNode,
        outputs: Dict[str, Any],
        states: Dict[str, TaskState],
        errors: Dict[str, str],
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            states[node.task_id] = TaskState.RUNNING
            self.trace_recorder.record(
                task_id=node.task_id,
                task_name=node.name,
                state=TaskState.RUNNING,
                metadata={"agent_name": node.agent_name},
            )
            try:
                coroutine = self._call_handler(node, outputs)
                if self.task_timeout_seconds is None:
                    result = await coroutine
                else:
                    result = await asyncio.wait_for(coroutine, timeout=self.task_timeout_seconds)
                if isinstance(result, AgentResult) and not result.success:
                    raise RuntimeError(result.error or "Agent returned unsuccessful result.")
                outputs[node.task_id] = result
                states[node.task_id] = TaskState.SUCCESS
                self.trace_recorder.record(
                    task_id=node.task_id,
                    task_name=node.name,
                    state=TaskState.SUCCESS,
                    metadata={"agent_name": node.agent_name},
                )
            except asyncio.TimeoutError:
                error = f"Task timed out after {self.task_timeout_seconds} seconds."
                errors[node.task_id] = error
                states[node.task_id] = TaskState.FAILED
                self.trace_recorder.record(
                    task_id=node.task_id,
                    task_name=node.name,
                    state=TaskState.FAILED,
                    error=error,
                    metadata={"agent_name": node.agent_name},
                )
            except Exception as exc:
                errors[node.task_id] = str(exc)
                states[node.task_id] = TaskState.FAILED
                self.trace_recorder.record(
                    task_id=node.task_id,
                    task_name=node.name,
                    state=TaskState.FAILED,
                    error=str(exc),
                    metadata={"agent_name": node.agent_name},
                )

    async def _call_handler(self, node: TaskNode, outputs: Dict[str, Any]) -> Any:
        handler = self.handlers[node.task_id]
        if inspect.iscoroutinefunction(handler):
            return await handler(outputs, node)
        return await asyncio.to_thread(handler, outputs, node)

    def _ready_nodes(
        self,
        states: Dict[str, TaskState],
        completed: set[str],
        running: Dict[str, asyncio.Task],
    ) -> list[TaskNode]:
        ready = []
        for node in self.graph.topological_sort():
            if node.task_id in completed or node.task_id in running:
                continue
            if states[node.task_id] != TaskState.PENDING:
                continue
            if all(states[dependency_id] == TaskState.SUCCESS for dependency_id in node.depends_on):
                ready.append(node)
        return ready

    def _skip_blocked_tasks(self, states: Dict[str, TaskState], completed: set[str]) -> None:
        changed = True
        while changed:
            changed = False
            for node in self.graph.topological_sort():
                if states[node.task_id] != TaskState.PENDING:
                    continue
                if any(
                    states[dependency_id] in {TaskState.FAILED, TaskState.SKIPPED}
                    for dependency_id in node.depends_on
                ):
                    states[node.task_id] = TaskState.SKIPPED
                    completed.add(node.task_id)
                    self.trace_recorder.record(
                        task_id=node.task_id,
                        task_name=node.name,
                        state=TaskState.SKIPPED,
                        metadata={"depends_on": list(node.depends_on)},
                    )
                    changed = True

    @staticmethod
    def _task_id_for_async_task(
        running: Dict[str, asyncio.Task],
        task: asyncio.Task,
    ) -> Optional[str]:
        for task_id, candidate in running.items():
            if candidate is task:
                return task_id
        return None

    def _validate_handlers(self) -> None:
        missing_handlers = [
            task_id for task_id in self.graph.nodes if task_id not in self.handlers
        ]
        if missing_handlers:
            missing = ", ".join(missing_handlers)
            raise ValueError(f"Missing handlers for task ids: {missing}")
