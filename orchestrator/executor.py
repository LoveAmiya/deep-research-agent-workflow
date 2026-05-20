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

TaskHandler = Callable[[Dict[str, Any], TaskNode], Any]


@dataclass
class ExecutionResult:
    success: bool
    outputs: Dict[str, Any] = field(default_factory=dict)
    states: Dict[str, TaskState] = field(default_factory=dict)
    traces: list[dict] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class DAGExecutor:
    def __init__(
        self,
        graph: TaskGraph,
        handlers: Dict[str, TaskHandler],
        trace_recorder: Optional[TraceRecorder] = None,
        checkpoint_store: Optional[CheckpointStore] = None,
        checkpoint: Optional[RunCheckpoint] = None,
        checkpoint_enabled: bool = False,
        resume: bool = False,
    ) -> None:
        self.graph = graph
        self.handlers = handlers
        self.trace_recorder = trace_recorder or TraceRecorder()
        self.checkpoint_store = checkpoint_store
        self.checkpoint = checkpoint
        self.checkpoint_enabled = checkpoint_enabled and checkpoint_store is not None and checkpoint is not None
        self.resume = resume
        self.checkpoint_save_count = 0
        self.skipped_node_count = 0
        self.reexecuted_node_count = 0

    def execute(self) -> ExecutionResult:
        self.graph.validate()
        self._validate_handlers()

        ordered_nodes = self.graph.topological_sort()
        outputs: Dict[str, Any] = {}
        states: Dict[str, TaskState] = {
            task_id: TaskState.PENDING for task_id in self.graph.nodes
        }

        for node in ordered_nodes:
            if self._can_resume_node(node):
                outputs[node.task_id] = deserialize_checkpoint_output(
                    self.checkpoint.node_checkpoints[node.task_id].output
                )
                states[node.task_id] = TaskState.SUCCESS
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
                continue

            if self._should_skip(node, states):
                states[node.task_id] = TaskState.SKIPPED
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
                continue

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
                self._record_node_checkpoint(
                    node=node,
                    status=TaskState.FAILED,
                    error=str(exc),
                )
                continue

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
                output=outputs[node.task_id],
            )

        success = all(state == TaskState.SUCCESS for state in states.values())
        self._finalize_checkpoint(success=success)
        return ExecutionResult(
            success=success,
            outputs=outputs,
            states=states,
            traces=self.trace_recorder.to_dict_list(),
            metadata=self._execution_metadata(),
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
