from dataclasses import dataclass, field

from orchestrator.dag import TaskGraph, TaskNode
from orchestrator.replan import ACTION_ABORT, ACTION_FORCE_SYNTHESIS, ReplanDecision


@dataclass
class DAGReplanApplyResult:
    inserted_node_ids: list[str] = field(default_factory=list)
    force_synthesis: bool = False
    aborted: bool = False
    metadata: dict = field(default_factory=dict)


class DAGReplanner:
    def apply_decision(
        self,
        dag: TaskGraph,
        decision: ReplanDecision,
        run_state: dict,
    ) -> DAGReplanApplyResult:
        if decision.action == ACTION_FORCE_SYNTHESIS:
            return DAGReplanApplyResult(
                force_synthesis=True,
                metadata={
                    "decision_action": decision.action,
                    "decision_reason": decision.reason,
                    **decision.metadata,
                },
            )
        if decision.action == ACTION_ABORT:
            return DAGReplanApplyResult(
                aborted=True,
                metadata={
                    "decision_action": decision.action,
                    "decision_reason": decision.reason,
                    **decision.metadata,
                },
            )

        inserted_node_ids: list[str] = []
        id_mapping: dict[str, str] = {}
        for node_data in decision.new_nodes:
            requested_id = node_data["task_id"]
            task_id = self._unique_task_id(dag, requested_id)
            id_mapping[requested_id] = task_id
            metadata = dict(node_data.get("metadata", {}))
            metadata.update(
                {
                    "generated_by_replan": True,
                    "replan_attempt": run_state.get("replan_attempts", 0),
                    "replan_reason": decision.reason,
                    "replan_action": decision.action,
                }
            )
            if "parent_failed_node_id" not in metadata:
                metadata["parent_failed_node_id"] = metadata.get("replaces_node_id")
            dag.add_node(
                TaskNode(
                    task_id=task_id,
                    name=node_data.get("name", f"Replan Node {task_id}"),
                    agent_name=node_data.get("agent_name", "ReplanAgent"),
                    depends_on=[
                        id_mapping.get(dependency_id, dependency_id)
                        for dependency_id in node_data.get("depends_on", [])
                    ],
                    metadata=metadata,
                )
            )
            inserted_node_ids.append(task_id)

        for edge in decision.new_edges:
            from_node = id_mapping.get(edge.get("from"), edge.get("from"))
            to_node = id_mapping.get(edge.get("to"), edge.get("to"))
            if to_node not in dag.nodes or from_node not in dag.nodes:
                continue
            replace_dependency = edge.get("replace_dependency")
            if replace_dependency and replace_dependency in dag.nodes[to_node].depends_on:
                dag.nodes[to_node].depends_on = [
                    dependency
                    for dependency in dag.nodes[to_node].depends_on
                    if dependency != replace_dependency
                ]
            if from_node not in dag.nodes[to_node].depends_on:
                dag.nodes[to_node].depends_on.append(from_node)

        return DAGReplanApplyResult(
            inserted_node_ids=inserted_node_ids,
            metadata={
                "decision_action": decision.action,
                "decision_reason": decision.reason,
                "id_mapping": id_mapping,
            },
        )

    @staticmethod
    def _unique_task_id(dag: TaskGraph, requested_id: str) -> str:
        if requested_id not in dag.nodes:
            return requested_id
        index = 2
        while f"{requested_id}_{index}" in dag.nodes:
            index += 1
        return f"{requested_id}_{index}"
