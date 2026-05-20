import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from agents.base_agent import AgentResult
from orchestrator.checkpoint import (
    CheckpointStore,
    NodeCheckpoint,
    RunCheckpoint,
    deserialize_checkpoint_output,
    serialize_checkpoint_output,
    utc_now_iso,
)
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
    metadata: Dict[str, Any] = field(default_factory=dict)


class AsyncDAGExecutor:
    def __init__(
        self,
        graph: TaskGraph,
        handlers: Dict[str, AsyncTaskHandler],
        max_concurrency: int = 3,
        task_timeout_seconds: Optional[float] = None,
        trace_recorder: Optional[TraceRecorder] = None,
        checkpoint_store: Optional[CheckpointStore] = None,
        checkpoint: Optional[RunCheckpoint] = None,
        checkpoint_enabled: bool = False,
        resume: bool = False,
    ) -> None:
        self.graph = graph
        self.handlers = handlers
        self.max_concurrency = max(1, max_concurrency)
        self.task_timeout_seconds = task_timeout_seconds
        self.trace_recorder = trace_recorder or TraceRecorder()
        self.checkpoint_store = checkpoint_store
        self.checkpoint = checkpoint
        self.checkpoint_enabled = checkpoint_enabled and checkpoint_store is not None and checkpoint is not None
        self.resume = resume
        self.checkpoint_save_count = 0
        self.skipped_node_count = 0
        self.reexecuted_node_count = 0

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

        for node in self.graph.topological_sort():
            if self._can_resume_node(node):
                outputs[node.task_id] = deserialize_checkpoint_output(
                    self.checkpoint.node_checkpoints[node.task_id].output
                )
                states[node.task_id] = TaskState.SUCCESS
                completed.add(node.task_id)
                self.skipped_node_count += 1
                self.trace_recorder.record(
                    task_id=node.task_id,
                    task_name=node.name,
                    state=TaskState.SUCCESS,
                    metadata={
                        "agent_name": node.agent_name,
                        "checkpoint_resumed": True,
                        "skipped_execution": True,
                    },
                )

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
        self._finalize_checkpoint(success=success)
        return AsyncExecutionResult(
            success=success,
            outputs=outputs,
            states=states,
            traces=self.trace_recorder.to_dict_list(),
            errors=errors,
            metadata=self._execution_metadata(),
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
            self.reexecuted_node_count += 1
            states[node.task_id] = TaskState.RUNNING
            self.trace_recorder.record(
                task_id=node.task_id,
                task_name=node.name,
                state=TaskState.RUNNING,
                metadata={"agent_name": node.agent_name},
            )
            self._record_node_checkpoint(node=node, status=TaskState.RUNNING)
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
                self._record_node_checkpoint(
                    node=node,
                    status=TaskState.SUCCESS,
                    output=result,
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
                self._record_node_checkpoint(
                    node=node,
                    status=TaskState.FAILED,
                    error=error,
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
                self._record_node_checkpoint(
                    node=node,
                    status=TaskState.FAILED,
                    error=str(exc),
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
                    self._record_node_checkpoint(
                        node=node,
                        status=TaskState.SKIPPED,
                        error="dependency failed or skipped",
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

    def _can_resume_node(self, node: TaskNode) -> bool:
        if not self.resume or self.checkpoint is None:
            return False
        node_checkpoint = self.checkpoint.node_checkpoints.get(node.task_id)
        return bool(
            node_checkpoint
            and node_checkpoint.status == TaskState.SUCCESS.value
            and node_checkpoint.output is not None
        )

    def _record_node_checkpoint(
        self,
        node: TaskNode,
        status: TaskState,
        output: Any = None,
        error: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        if not self.checkpoint_enabled:
            return
        now = utc_now_iso()
        existing = self.checkpoint.node_checkpoints.get(node.task_id)
        started_at = existing.started_at if existing else None
        if status == TaskState.RUNNING:
            started_at = now
        self.checkpoint.node_checkpoints[node.task_id] = NodeCheckpoint(
            node_id=node.task_id,
            status=status.value,
            agent_name=node.agent_name,
            input_hash=None,
            output=serialize_checkpoint_output(output) if output is not None else None,
            error=error,
            started_at=started_at,
            finished_at=now if status in {TaskState.SUCCESS, TaskState.FAILED, TaskState.SKIPPED} else None,
            metadata=metadata or {"agent_name": node.agent_name},
        )
        self.checkpoint.refresh_node_lists(list(self.graph.nodes.keys()))
        self._save_checkpoint()

    def _save_checkpoint(self) -> None:
        if not self.checkpoint_enabled:
            return
        self.checkpoint_store.save_checkpoint(self.checkpoint)
        self.checkpoint_save_count += 1

    def _finalize_checkpoint(self, success: bool) -> None:
        if not self.checkpoint_enabled:
            return
        self.checkpoint.status = "SUCCESS" if success else "FAILED"
        self.checkpoint.refresh_node_lists(list(self.graph.nodes.keys()))
        self._save_checkpoint()

    def _execution_metadata(self) -> Dict[str, Any]:
        checkpoint_path = None
        if self.checkpoint_enabled and hasattr(self.checkpoint_store, "checkpoint_path"):
            checkpoint_path = str(self.checkpoint_store.checkpoint_path(self.checkpoint.run_id))
        failed_nodes = (
            list(self.checkpoint.failed_node_ids)
            if self.checkpoint_enabled and self.checkpoint is not None
            else []
        )
        return {
            "checkpoint_enabled": self.checkpoint_enabled,
            "checkpoint_saved": self.checkpoint_save_count > 0,
            "checkpoint_path": checkpoint_path,
            "checkpoint_save_count": self.checkpoint_save_count,
            "resumed": self.resume,
            "resumed_from_run_id": self.checkpoint.run_id if self.resume and self.checkpoint else None,
            "skipped_node_count": self.skipped_node_count,
            "reexecuted_node_count": self.reexecuted_node_count,
            "skipped_nodes": self.skipped_node_count,
            "reexecuted_nodes": self.reexecuted_node_count,
            "failed_nodes_after_resume": failed_nodes,
        }
