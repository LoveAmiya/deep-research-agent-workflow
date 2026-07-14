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
from orchestrator.dag_replanner import DAGReplanner
from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.replan import ReplanPolicy, ReplanTrigger, RuleBasedReplanPolicy
from orchestrator.state import TaskState
from orchestrator.trace import TraceRecorder

AsyncTaskHandler = Callable[[Dict[str, Any], TaskNode], Any]


@dataclass
class AsyncExecutionResult:
    """暴露给调用方、测试和可视化工作台的最终执行状态。"""
    success: bool
    outputs: Dict[str, Any] = field(default_factory=dict)
    states: Dict[str, TaskState] = field(default_factory=dict)
    traces: list[dict] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AsyncDAGExecutor:
    """执行具备并发上限、Trace、Checkpoint 与重规划能力的任务 DAG。

    执行器只负责调度，不承载 Agent 业务逻辑。一个 handler 仅在所有声明依赖
    成功后才能调用，这使数据流明确，也让失败节点能被独立恢复。
    """
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
        replan_enabled: bool = False,
        replan_policy: Optional[ReplanPolicy] = None,
        max_replan_attempts: int = 2,
        max_failed_nodes_before_force_synthesis: int = 3,
        force_synthesis_on_replan_exhausted: bool = True,
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
        self.replan_enabled = replan_enabled
        self.replan_policy = replan_policy or RuleBasedReplanPolicy(
            max_replan_attempts=max_replan_attempts,
            max_failed_nodes_before_force_synthesis=max_failed_nodes_before_force_synthesis,
            force_synthesis_on_replan_exhausted=force_synthesis_on_replan_exhausted,
        )
        self.dag_replanner = DAGReplanner()
        self.replan_attempts = 0
        self.replan_trigger_count = 0
        self.replan_actions: list[str] = []
        self.replanned_node_ids: list[str] = []
        self.replan_reasons: list[str] = []
        self.replan_history: list[dict] = []
        self.replaced_node_ids: list[str] = []
        self.force_synthesis_used = False
        self.aborted_by_replan_policy = False
        self.replan_exhausted = False

    async def execute(self) -> AsyncExecutionResult:
        """持续调度就绪节点，直到所有节点都进入终态。

        先从兼容 Checkpoint 恢复成功节点；随后同时启动新就绪节点，但通过信号量
        限制外部 API 压力和 Token 成本。
        """
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

        # 只恢复已确认成功的节点；失败或缺失的 Checkpoint 必须重新执行，不能让过期的
        # 部分结果进入最终输出。
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

        # 每轮启动所有依赖已满足的节点，再等待至少一个完成，从而发现新解锁的下游节点。
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
                    if states.get(finished_task_id) == TaskState.FAILED:
                        self._handle_replan_for_failure(
                            node=self.graph.get_node(finished_task_id),
                            outputs=outputs,
                            states=states,
                            error=errors.get(finished_task_id, "task failed"),
                        )

        self._skip_blocked_tasks(states, completed)
        success = self.force_synthesis_used or (
            not self.aborted_by_replan_policy
            and all(
                state == TaskState.SUCCESS
                or (task_id in self.replaced_node_ids and state == TaskState.SKIPPED)
                for task_id, state in states.items()
            )
        )
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
        """执行单个节点，并持久化完整的状态迁移。

        每一种终态都会写入相同的可观测面：内存状态、Trace 记录和可选 Checkpoint。
        因此前端可以区分成功、超时和普通 handler 失败。
        """
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
                # _call_handler 会把同步 handler 放进工作线程，避免一个遗留的阻塞调用
                # 卡住无关的异步节点。
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
            "replan_enabled": self.replan_enabled,
            "replan_attempts": self.replan_attempts,
            "replan_trigger_count": self.replan_trigger_count,
            "replan_actions": list(self.replan_actions),
            "replanned_node_ids": list(self.replanned_node_ids),
            "force_synthesis_used": self.force_synthesis_used,
            "aborted_by_replan_policy": self.aborted_by_replan_policy,
            "replan_reasons": list(self.replan_reasons),
            "replan_history": list(self.replan_history),
            "generated_replan_nodes": list(self.replanned_node_ids),
            "replan_exhausted": self.replan_exhausted,
        }

    def _handle_replan_for_failure(
        self,
        node: TaskNode,
        outputs: Dict[str, Any],
        states: Dict[str, TaskState],
        error: str,
    ) -> None:
        if not self.replan_enabled:
            return
        if self.force_synthesis_used:
            self._apply_force_synthesis(node=node, outputs=outputs, states=states, error=error)
            return
        trigger_type = "node_timeout" if "timed out" in error.lower() else "node_failed"
        trigger = ReplanTrigger(
            run_id=self.checkpoint.run_id if self.checkpoint is not None else "",
            node_id=node.task_id,
            trigger_type=trigger_type,
            reason=f"Node {node.task_id} failed.",
            failed_agent=node.agent_name,
            failed_node_type=node.task_id,
            error=error,
            metadata={"node_metadata": dict(node.metadata)},
        )
        self.replan_trigger_count += 1
        decision = self.replan_policy.decide(trigger, self.graph, self._replan_run_state(states))
        self.replan_actions.append(decision.action)
        self.replan_reasons.append(decision.reason)
        self.replan_history.append(
            {
                "trigger": trigger.__dict__,
                "decision": {
                    "should_replan": decision.should_replan,
                    "action": decision.action,
                    "reason": decision.reason,
                    "metadata": decision.metadata,
                },
            }
        )
        if not decision.should_replan and decision.action == "abort":
            self.aborted_by_replan_policy = True
            self.replan_exhausted = bool(decision.metadata.get("replan_exhausted"))
            self._update_checkpoint_replan_metadata()
            self._save_checkpoint()
            return

        self.replan_attempts += 1
        apply_result = self.dag_replanner.apply_decision(
            self.graph,
            decision,
            self._replan_run_state(states),
        )
        self.replanned_node_ids.extend(apply_result.inserted_node_ids)
        self.force_synthesis_used = self.force_synthesis_used or apply_result.force_synthesis
        self.aborted_by_replan_policy = self.aborted_by_replan_policy or apply_result.aborted
        self.replan_exhausted = self.replan_exhausted or bool(decision.metadata.get("replan_exhausted"))
        if apply_result.inserted_node_ids:
            self._wire_replan_nodes(node.task_id, apply_result.inserted_node_ids, states)
            self._register_default_replan_handlers(apply_result.inserted_node_ids, node, decision.action, error)
        if self.force_synthesis_used:
            self._apply_force_synthesis(node=node, outputs=outputs, states=states, error=error)
        self._update_checkpoint_replan_metadata()
        self._save_checkpoint()

    def _wire_replan_nodes(
        self,
        failed_node_id: str,
        inserted_node_ids: list[str],
        states: Dict[str, TaskState],
    ) -> None:
        replacement_node_id = inserted_node_ids[-1]
        if failed_node_id not in self.replaced_node_ids:
            self.replaced_node_ids.append(failed_node_id)
        for node in self.graph.nodes.values():
            if node.task_id in inserted_node_ids:
                states[node.task_id] = TaskState.PENDING
                continue
            if failed_node_id in node.depends_on:
                node.depends_on = [
                    replacement_node_id if dependency_id == failed_node_id else dependency_id
                    for dependency_id in node.depends_on
                ]
        states[failed_node_id] = TaskState.SKIPPED

    def _register_default_replan_handlers(
        self,
        inserted_node_ids: list[str],
        failed_node: TaskNode,
        decision_action: str,
        error: str,
    ) -> None:
        for node_id in inserted_node_ids:
            if node_id in self.handlers:
                continue
            self.handlers[node_id] = self._default_replan_handler(failed_node, decision_action, error)

    def _default_replan_handler(self, failed_node: TaskNode, decision_action: str, error: str):
        def handler(outputs, node):
            output_kind = node.metadata.get("output_kind", "generic")
            content = {
                "replanned": True,
                "output_kind": output_kind,
                "action": decision_action,
                "parent_failed_node_id": failed_node.task_id,
                "reason": node.metadata.get("replan_reason", ""),
                "error": error,
            }
            if node.metadata.get("as_agent_result", False):
                return AgentResult(
                    agent_name=node.agent_name,
                    success=True,
                    output=content,
                    metadata={
                        "generated_by_replan": True,
                        "replan_action": decision_action,
                        "parent_failed_node_id": failed_node.task_id,
                    },
                )
            return content

        return handler

    def _apply_force_synthesis(
        self,
        node: TaskNode,
        outputs: Dict[str, Any],
        states: Dict[str, TaskState],
        error: str,
    ) -> None:
        outputs[node.task_id] = AgentResult(
            agent_name=node.agent_name,
            success=True,
            output={
                "partial_report": True,
                "force_synthesis_used": True,
                "missing_sections": [],
                "failed_nodes": [node.task_id],
                "evidence_limitations": [error],
            },
            metadata={
                "partial_report": True,
                "force_synthesis_used": True,
                "failed_nodes": [node.task_id],
                "evidence_limitations": [error],
            },
        )
        states[node.task_id] = TaskState.SUCCESS

    def _replan_run_state(self, states: Dict[str, TaskState]) -> Dict[str, Any]:
        return {
            "replan_attempts": self.replan_attempts,
            "failed_node_count": sum(1 for state in states.values() if state == TaskState.FAILED),
            "replan_history": list(self.replan_history),
        }

    def _update_checkpoint_replan_metadata(self) -> None:
        if self.checkpoint is None:
            return
        self.checkpoint.metadata.update(
            {
                "replan_enabled": self.replan_enabled,
                "replan_attempts": self.replan_attempts,
                "replan_history": list(self.replan_history),
                "generated_replan_nodes": list(self.replanned_node_ids),
                "force_synthesis_used": self.force_synthesis_used,
                "replan_exhausted": self.replan_exhausted,
            }
        )
