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
        replan_enabled: bool = False,
        replan_policy: Optional[ReplanPolicy] = None,
        max_replan_attempts: int = 2,
        max_failed_nodes_before_force_synthesis: int = 3,
        force_synthesis_on_replan_exhausted: bool = True,
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
        self.replan_enabled = replan_enabled
        self.replan_policy = replan_policy or RuleBasedReplanPolicy(
            max_replan_attempts=max_replan_attempts,
            max_failed_nodes_before_force_synthesis=max_failed_nodes_before_force_synthesis,
            force_synthesis_on_replan_exhausted=force_synthesis_on_replan_exhausted,
        )
        self.dag_replanner = DAGReplanner()
        self.max_replan_attempts = max_replan_attempts
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

    def execute(self) -> ExecutionResult:
        self.graph.validate()
        self._validate_handlers()

        outputs: Dict[str, Any] = {}
        states: Dict[str, TaskState] = {
            task_id: TaskState.PENDING for task_id in self.graph.nodes
        }
        completed_node_ids: set[str] = set()

        while len(completed_node_ids) < len(self.graph.nodes):
            progress_made = False
            ordered_nodes = self.graph.topological_sort()
            for node in ordered_nodes:
                if node.task_id in completed_node_ids:
                    continue
                progress_made = True
                self._execute_node(node, outputs, states, completed_node_ids)
                break
            if not progress_made:
                break

        success = self.force_synthesis_used or (
            not self.aborted_by_replan_policy
            and all(
                state == TaskState.SUCCESS
                or (task_id in self.replaced_node_ids and state == TaskState.SKIPPED)
                for task_id, state in states.items()
            )
        )
        self._finalize_checkpoint(success=success)
        return ExecutionResult(
            success=success,
            outputs=outputs,
            states=states,
            traces=self.trace_recorder.to_dict_list(),
            metadata=self._execution_metadata(),
        )

    def _execute_node(
        self,
        node: TaskNode,
        outputs: Dict[str, Any],
        states: Dict[str, TaskState],
        completed_node_ids: set[str],
    ) -> None:
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
                completed_node_ids.add(node.task_id)
                return

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
                completed_node_ids.add(node.task_id)
                return

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
                if self._handle_replan_for_failure(node=node, outputs=outputs, states=states, error=str(exc)):
                    completed_node_ids.add(node.task_id)
                return

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
            completed_node_ids.add(node.task_id)

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
    ) -> bool:
        if not self.replan_enabled:
            return True
        if self.force_synthesis_used:
            self._apply_force_synthesis(node=node, outputs=outputs, states=states, error=error)
            return True
        trigger = ReplanTrigger(
            run_id=self.checkpoint.run_id if self.checkpoint is not None else "",
            node_id=node.task_id,
            trigger_type="node_failed",
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
            return True

        self.replan_attempts += 1
        run_state = self._replan_run_state(states)
        apply_result = self.dag_replanner.apply_decision(self.graph, decision, run_state)
        self.replanned_node_ids.extend(apply_result.inserted_node_ids)
        self.force_synthesis_used = self.force_synthesis_used or apply_result.force_synthesis
        self.aborted_by_replan_policy = self.aborted_by_replan_policy or apply_result.aborted
        self.replan_exhausted = self.replan_exhausted or bool(decision.metadata.get("replan_exhausted"))
        if apply_result.inserted_node_ids:
            self._wire_replan_nodes(
                failed_node_id=node.task_id,
                inserted_node_ids=apply_result.inserted_node_ids,
                states=states,
            )
            self._register_default_replan_handlers(
                inserted_node_ids=apply_result.inserted_node_ids,
                failed_node=node,
                decision_action=decision.action,
                error=error,
            )
        if self.force_synthesis_used:
            self._apply_force_synthesis(node=node, outputs=outputs, states=states, error=error)
        self._update_checkpoint_replan_metadata()
        self._save_checkpoint()
        return True

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

    def _default_replan_handler(self, failed_node: TaskNode, decision_action: str, error: str) -> TaskHandler:
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
