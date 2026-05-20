from dataclasses import dataclass, field
from typing import Any


TRIGGER_NODE_FAILED = "node_failed"
TRIGGER_NODE_TIMEOUT = "node_timeout"
TRIGGER_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
TRIGGER_CITATION_VALIDATION_FAILED = "citation_validation_failed"
TRIGGER_FETCH_FAILED = "fetch_failed"
TRIGGER_BATCH_FAILURE = "batch_failure"

ACTION_RETRY_NODE = "retry_node"
ACTION_ADD_FOLLOWUP_SEARCH = "add_followup_search"
ACTION_ADD_ALTERNATIVE_READER = "add_alternative_reader"
ACTION_SKIP_OPTIONAL_NODE = "skip_optional_node"
ACTION_FORCE_SYNTHESIS = "force_synthesis"
ACTION_ABORT = "abort"


@dataclass
class ReplanTrigger:
    run_id: str
    node_id: str
    trigger_type: str
    reason: str
    failed_agent: str | None = None
    failed_node_type: str | None = None
    error: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ReplanDecision:
    should_replan: bool
    action: str
    new_nodes: list[dict] = field(default_factory=list)
    new_edges: list[dict] = field(default_factory=list)
    reason: str = ""
    metadata: dict = field(default_factory=dict)


class ReplanPolicy:
    def decide(self, trigger: ReplanTrigger, dag, run_state: dict) -> ReplanDecision:
        raise NotImplementedError("ReplanPolicy implementations must implement decide().")


class RuleBasedReplanPolicy(ReplanPolicy):
    def __init__(
        self,
        max_replan_attempts: int = 2,
        max_failed_nodes_before_force_synthesis: int = 3,
        force_synthesis_on_replan_exhausted: bool = True,
    ) -> None:
        self.max_replan_attempts = max(0, max_replan_attempts)
        self.max_failed_nodes_before_force_synthesis = max(1, max_failed_nodes_before_force_synthesis)
        self.force_synthesis_on_replan_exhausted = force_synthesis_on_replan_exhausted

    def decide(self, trigger: ReplanTrigger, dag, run_state: dict) -> ReplanDecision:
        current_attempts = int(run_state.get("replan_attempts", 0))
        failed_node_count = int(run_state.get("failed_node_count", 0))
        base_metadata = {
            "policy": self.__class__.__name__,
            "deterministic": True,
            "replan_attempt": current_attempts + 1,
            "max_replan_attempts": self.max_replan_attempts,
            "trigger_type": trigger.trigger_type,
        }
        if current_attempts >= self.max_replan_attempts:
            return self._limit_decision(trigger, base_metadata, "max replan attempts reached")
        if failed_node_count >= self.max_failed_nodes_before_force_synthesis:
            return self._limit_decision(trigger, base_metadata, "too many failed nodes")

        node_type = self._node_type(trigger)
        if trigger.trigger_type == TRIGGER_CITATION_VALIDATION_FAILED:
            return self._decision_with_node(
                trigger=trigger,
                dag=dag,
                action=ACTION_ADD_FOLLOWUP_SEARCH,
                suffix="citation_repair",
                agent_name="CitationRepairAgent",
                output_kind="citation_repair",
                reason="Citation validation failed; add a deterministic citation repair node.",
                metadata={**base_metadata, "rule": "citation_validation_failed"},
            )
        if trigger.trigger_type == TRIGGER_INSUFFICIENT_EVIDENCE:
            return self._decision_with_node(
                trigger=trigger,
                dag=dag,
                action=ACTION_ADD_FOLLOWUP_SEARCH,
                suffix="followup_search",
                agent_name="FollowupSearchAgent",
                output_kind="search_results",
                reason="Evidence is insufficient; add a follow-up mock search node.",
                metadata={**base_metadata, "rule": "insufficient_evidence"},
            )
        if "search" in node_type:
            return self._decision_with_node(
                trigger=trigger,
                dag=dag,
                action=ACTION_ADD_FOLLOWUP_SEARCH,
                suffix="alternative_search",
                agent_name="AlternativeSearchAgent",
                output_kind="search_results",
                reason="Search node failed; add an alternative deterministic search node.",
                metadata={**base_metadata, "rule": "search_failure"},
            )
        if "reader" in node_type or "fetch" in node_type or trigger.trigger_type == TRIGGER_FETCH_FAILED:
            return self._decision_with_node(
                trigger=trigger,
                dag=dag,
                action=ACTION_ADD_ALTERNATIVE_READER,
                suffix="alternative_reader",
                agent_name="AlternativeReaderAgent",
                output_kind="findings",
                reason="Reader/fetch node failed; add a snippet-based alternative reader node.",
                metadata={**base_metadata, "rule": "reader_fetch_failure"},
            )
        if "writer" in node_type:
            return ReplanDecision(
                should_replan=True,
                action=ACTION_FORCE_SYNTHESIS,
                reason="Writer failed; use force synthesis fallback.",
                metadata={**base_metadata, "rule": "writer_force_synthesis"},
            )
        return ReplanDecision(
            should_replan=True,
            action=ACTION_RETRY_NODE,
            new_nodes=[],
            new_edges=[],
            reason="Generic node failure; retrying is the safest deterministic replan.",
            metadata={**base_metadata, "rule": "generic_retry"},
        )

    def _limit_decision(self, trigger: ReplanTrigger, metadata: dict, reason: str) -> ReplanDecision:
        if self.force_synthesis_on_replan_exhausted:
            return ReplanDecision(
                should_replan=True,
                action=ACTION_FORCE_SYNTHESIS,
                reason=f"{reason}; using force synthesis fallback.",
                metadata={**metadata, "replan_exhausted": True},
            )
        return ReplanDecision(
            should_replan=False,
            action=ACTION_ABORT,
            reason=f"{reason}; aborting by policy.",
            metadata={**metadata, "replan_exhausted": True},
        )

    def _decision_with_node(
        self,
        trigger: ReplanTrigger,
        dag,
        action: str,
        suffix: str,
        agent_name: str,
        output_kind: str,
        reason: str,
        metadata: dict,
    ) -> ReplanDecision:
        failed_node = dag.nodes.get(trigger.node_id)
        depends_on = list(failed_node.depends_on) if failed_node is not None else []
        node_id = f"{trigger.node_id}_replan_{metadata['replan_attempt']}_{suffix}"
        new_node = {
            "task_id": node_id,
            "name": f"Replan {suffix.replace('_', ' ').title()}",
            "agent_name": agent_name,
            "depends_on": depends_on,
            "metadata": {
                "output_kind": output_kind,
                "replaces_node_id": trigger.node_id,
                "parent_failed_node_id": trigger.node_id,
                "as_agent_result": True,
            },
        }
        return ReplanDecision(
            should_replan=True,
            action=action,
            new_nodes=[new_node],
            new_edges=[],
            reason=reason,
            metadata=metadata,
        )

    @staticmethod
    def _node_type(trigger: ReplanTrigger) -> str:
        return " ".join(
            str(value or "")
            for value in [trigger.failed_node_type, trigger.node_id, trigger.failed_agent]
        ).lower()
