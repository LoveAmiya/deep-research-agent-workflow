from dataclasses import dataclass, field
from typing import List, Optional

from agents.base_agent import AgentContext
from agents.blue_agent import BlueAgent
from agents.red_agent import RedAgent
from core.schema import (
    BlueRevisionResult,
    Finding,
    RedReviewResult,
    ResearchReport,
)


@dataclass
class RedBlueLoopConfig:
    max_rounds: int = 3
    stop_on_pass: bool = True
    stop_if_no_improvement_rounds: int = 2
    enable_oscillation_detection: bool = True


@dataclass
class RedBlueRoundResult:
    round_index: int
    red_review: RedReviewResult
    blue_revision: Optional[BlueRevisionResult]
    issue_count_before: int
    issue_count_after: Optional[int]
    fixed_issue_ids: List[str] = field(default_factory=list)
    remaining_issue_ids: List[str] = field(default_factory=list)
    stopped: bool = False
    stop_reason: Optional[str] = None


@dataclass
class RedBlueLoopResult:
    final_report: ResearchReport
    rounds: List[RedBlueRoundResult] = field(default_factory=list)
    passed: bool = False
    total_fixed_issues: int = 0
    remaining_issue_count: int = 0
    stop_reason: str = ""
    metadata: dict = field(default_factory=dict)


class RedBlueLoopRunner:
    name = "RedBlueLoopRunner"

    def __init__(
        self,
        red_agent: RedAgent,
        blue_agent: BlueAgent,
        config: Optional[RedBlueLoopConfig] = None,
    ) -> None:
        self.red_agent = red_agent
        self.blue_agent = blue_agent
        self.config = config or RedBlueLoopConfig()

    def run(
        self,
        context: AgentContext,
        report: ResearchReport,
        findings: List[Finding],
        critic_review: Optional[dict] = None,
    ) -> RedBlueLoopResult:
        current_report = report
        rounds: List[RedBlueRoundResult] = []
        no_improvement_count = 0
        previous_issue_count: Optional[int] = None
        seen_remaining_signatures: set[tuple[str, ...]] = set()
        total_fixed_issue_ids: set[str] = set()
        stop_reason = "max_rounds_reached"
        passed = False

        for round_index in range(1, max(1, self.config.max_rounds) + 1):
            red_result = self.red_agent.run(
                AgentContext(
                    task_id=f"{context.task_id}_red_round_{round_index}",
                    inputs={
                        "report": current_report,
                        "findings": findings,
                        "critic_review": critic_review,
                        "citation_registry": context.inputs.get("citation_registry"),
                    },
                    metadata={"round_index": round_index},
                    memory=context.memory,
                    llm_client=None,
                )
            )
            if not red_result.success:
                stop_reason = "red_agent_failed"
                loop_result = self._build_result(
                    final_report=current_report,
                    rounds=rounds,
                    passed=False,
                    stop_reason=stop_reason,
                    total_fixed_issue_ids=total_fixed_issue_ids,
                )
                self._write_memory(context, loop_result)
                return loop_result

            red_review = red_result.output
            issue_count_before = len(red_review.issues)

            if red_review.passed and self.config.stop_on_pass:
                passed = True
                stop_reason = "red_passed"
                rounds.append(
                    RedBlueRoundResult(
                        round_index=round_index,
                        red_review=red_review,
                        blue_revision=None,
                        issue_count_before=issue_count_before,
                        issue_count_after=issue_count_before,
                        fixed_issue_ids=[],
                        remaining_issue_ids=[],
                        stopped=True,
                        stop_reason=stop_reason,
                    )
                )
                break

            blue_result = self.blue_agent.run(
                AgentContext(
                    task_id=f"{context.task_id}_blue_round_{round_index}",
                    inputs={
                        "report": current_report,
                        "red_review": red_review,
                        "findings": findings,
                        "citation_registry": context.inputs.get("citation_registry"),
                    },
                    metadata={"round_index": round_index},
                    memory=context.memory,
                    llm_client=None,
                )
            )
            if not blue_result.success:
                stop_reason = "blue_agent_failed"
                rounds.append(
                    RedBlueRoundResult(
                        round_index=round_index,
                        red_review=red_review,
                        blue_revision=None,
                        issue_count_before=issue_count_before,
                        issue_count_after=None,
                        stopped=True,
                        stop_reason=stop_reason,
                    )
                )
                break

            blue_revision = blue_result.output
            current_report = blue_revision.revised_report
            total_fixed_issue_ids.update(blue_revision.fixed_issue_ids)
            issue_count_after = len(blue_revision.remaining_issue_ids)
            remaining_signature = tuple(sorted(blue_revision.remaining_issue_ids))
            round_result = RedBlueRoundResult(
                round_index=round_index,
                red_review=red_review,
                blue_revision=blue_revision,
                issue_count_before=issue_count_before,
                issue_count_after=issue_count_after,
                fixed_issue_ids=list(blue_revision.fixed_issue_ids),
                remaining_issue_ids=list(blue_revision.remaining_issue_ids),
            )
            rounds.append(round_result)

            if previous_issue_count is not None and issue_count_after >= previous_issue_count:
                no_improvement_count += 1
            else:
                no_improvement_count = 0
            previous_issue_count = issue_count_after

            if self._should_stop_for_oscillation(remaining_signature, seen_remaining_signatures):
                stop_reason = "oscillation_detected"
                round_result.stopped = True
                round_result.stop_reason = stop_reason
                break
            seen_remaining_signatures.add(remaining_signature)

            if no_improvement_count >= self.config.stop_if_no_improvement_rounds:
                stop_reason = "no_improvement"
                round_result.stopped = True
                round_result.stop_reason = stop_reason
                break

        remaining_issue_count = self._remaining_issue_count(rounds)
        if passed:
            remaining_issue_count = 0
        loop_result = RedBlueLoopResult(
            final_report=current_report,
            rounds=rounds,
            passed=passed,
            total_fixed_issues=len(total_fixed_issue_ids),
            remaining_issue_count=remaining_issue_count,
            stop_reason=stop_reason,
            metadata={
                "max_rounds": self.config.max_rounds,
                "round_count": len(rounds),
                "stop_on_pass": self.config.stop_on_pass,
            },
        )
        self._write_memory(context, loop_result)
        return loop_result

    def _should_stop_for_oscillation(
        self,
        remaining_signature: tuple[str, ...],
        seen_remaining_signatures: set[tuple[str, ...]],
    ) -> bool:
        return (
            self.config.enable_oscillation_detection
            and bool(remaining_signature)
            and remaining_signature in seen_remaining_signatures
        )

    @staticmethod
    def _remaining_issue_count(rounds: List[RedBlueRoundResult]) -> int:
        if not rounds:
            return 0
        latest = rounds[-1]
        if latest.issue_count_after is not None:
            return latest.issue_count_after
        return latest.issue_count_before

    @staticmethod
    def _build_result(
        final_report: ResearchReport,
        rounds: List[RedBlueRoundResult],
        passed: bool,
        stop_reason: str,
        total_fixed_issue_ids: set[str],
    ) -> RedBlueLoopResult:
        return RedBlueLoopResult(
            final_report=final_report,
            rounds=rounds,
            passed=passed,
            total_fixed_issues=len(total_fixed_issue_ids),
            remaining_issue_count=RedBlueLoopRunner._remaining_issue_count(rounds),
            stop_reason=stop_reason,
            metadata={"round_count": len(rounds)},
        )

    def _write_memory(self, context: AgentContext, result: RedBlueLoopResult) -> None:
        if context.memory is None:
            return
        context.memory.add_record(
            item_type="red_blue_loop",
            content=result,
            source_agent=self.name,
            task_id=context.task_id,
            metadata=result.metadata,
        )
