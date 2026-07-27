from dataclasses import dataclass, field
from typing import List, Optional

from agents.base_agent import AgentContext
from agents.blue_agent import BlueAgent
from agents.red_agent import RedAgent
from agents.red_blue_convergence import (
    STATUS_BLUE_UNABLE_TO_FIX,
    STATUS_CONVERGED,
    STATUS_ERROR,
    STATUS_MAX_ROUNDS_REACHED,
    STATUS_NO_IMPROVEMENT,
    STATUS_OSCILLATION_DETECTED,
    RedBlueLoopSummary,
    RedBlueRoundSnapshot,
    build_loop_summary,
    build_round_snapshot,
    decide_convergence,
)
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
    round_snapshots: List[RedBlueRoundSnapshot] = field(default_factory=list)
    loop_summary: Optional[RedBlueLoopSummary] = None
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
        snapshots: List[RedBlueRoundSnapshot] = []
        total_fixed_issue_ids: set[str] = set()
        stop_reason = "max_rounds_reached"
        passed = False
        latest_decision = None
        event_sink = context.metadata.get("event_sink")
        round_offset = int(context.metadata.get("round_offset", 0) or 0)
        max_display_rounds = int(
            context.metadata.get("max_display_rounds", self.config.max_rounds + round_offset)
        )

        for round_index in range(1, max(1, self.config.max_rounds) + 1):
            display_round = round_index + round_offset
            self._emit_event(
                event_sink,
                "review_round_started",
                {"round": display_round, "maxRounds": max_display_rounds},
            )
            self._emit_event(
                event_sink,
                "review_agent_started",
                {
                    "round": display_round,
                    "maxRounds": max_display_rounds,
                    "agent": "RedAgent",
                    "phase": "review",
                    "modelBacked": context.llm_client is not None,
                },
            )
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
                    llm_client=context.llm_client,
                )
            )
            self._emit_event(
                event_sink,
                "review_agent_completed",
                {
                    "round": display_round,
                    "maxRounds": max_display_rounds,
                    "agent": "RedAgent",
                    "success": red_result.success,
                },
            )
            if not red_result.success:
                stop_reason = "red_agent_failed"
                loop_result = self._build_result(
                    final_report=current_report,
                    rounds=rounds,
                    snapshots=snapshots,
                    passed=False,
                    stop_reason=stop_reason,
                    convergence_status=STATUS_ERROR,
                    total_fixed_issue_ids=total_fixed_issue_ids,
                )
                self._write_memory(context, loop_result)
                return loop_result

            red_review = red_result.output
            issue_count_before = len(red_review.issues)
            self._emit_review_stream(
                event_sink,
                "Red 审查",
                [
                    red_review.summary,
                    *[
                        f"- {issue.issue_id} [{issue.severity}] {issue.message}\n"
                        f"  依据：{issue.evidence or '未提供'}\n"
                        f"  建议：{issue.suggestion or '未提供'}"
                        for issue in red_review.issues
                    ],
                ],
            )

            if red_review.passed and self.config.stop_on_pass:
                self._emit_review_stream(
                    event_sink,
                    "Blue 复核",
                    ["Red 本轮未提出新的阻断问题，Blue 保留当前报告版本，不新增事实或引用。"],
                )
                self._emit_event(
                    event_sink,
                    "review_round_completed",
                    {
                        "round": display_round,
                        "review": self._live_review_payload(display_round, red_review, None),
                    },
                )
                passed = True
                stop_reason = "red_passed"
                snapshot = build_round_snapshot(
                    round_index=round_index,
                    red_review=red_review,
                    report=current_report,
                    blue_revision=None,
                    metadata={"stop_on_pass": True},
                )
                snapshots.append(snapshot)
                latest_decision = decide_convergence(
                    snapshots,
                    max_rounds=self.config.max_rounds,
                    no_improvement_patience=self.config.stop_if_no_improvement_rounds,
                    enable_oscillation_detection=self.config.enable_oscillation_detection,
                )
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

            self._emit_event(
                event_sink,
                "review_agent_started",
                {
                    "round": display_round,
                    "maxRounds": max_display_rounds,
                    "agent": "BlueAgent",
                    "phase": "revision",
                    "modelBacked": context.llm_client is not None,
                },
            )
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
                    llm_client=context.llm_client,
                )
            )
            self._emit_event(
                event_sink,
                "review_agent_completed",
                {
                    "round": display_round,
                    "maxRounds": max_display_rounds,
                    "agent": "BlueAgent",
                    "success": blue_result.success,
                },
            )
            if not blue_result.success:
                stop_reason = "blue_agent_failed"
                snapshot = build_round_snapshot(
                    round_index=round_index,
                    red_review=red_review,
                    report=current_report,
                    blue_revision=None,
                    metadata={"blue_unable_to_fix": True, "blue_error": blue_result.error},
                )
                snapshots.append(snapshot)
                latest_decision = decide_convergence(
                    snapshots,
                    max_rounds=self.config.max_rounds,
                    no_improvement_patience=self.config.stop_if_no_improvement_rounds,
                    enable_oscillation_detection=self.config.enable_oscillation_detection,
                )
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
            self._emit_review_stream(
                event_sink,
                "Blue 修订",
                [
                    *blue_revision.revision_notes,
                    *[f"已修复：{issue_id}" for issue_id in blue_revision.fixed_issue_ids],
                    *[f"仍待复核：{issue_id}" for issue_id in blue_revision.remaining_issue_ids],
                ] or ["本轮未产生正文修改。"],
            )
            self._emit_event(
                event_sink,
                "review_round_completed",
                {
                    "round": display_round,
                    "review": self._live_review_payload(display_round, red_review, blue_revision),
                },
            )
            current_report = blue_revision.revised_report
            total_fixed_issue_ids.update(blue_revision.fixed_issue_ids)
            issue_count_after = len(blue_revision.remaining_issue_ids)
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

            snapshot_metadata = {
                "remaining_signature": tuple(sorted(blue_revision.remaining_issue_ids)),
            }
            if (
                issue_count_before > 0
                and issue_count_after >= issue_count_before
                and not blue_revision.fixed_issue_ids
            ):
                snapshot_metadata["blue_unable_to_fix"] = True
            snapshot = build_round_snapshot(
                round_index=round_index,
                red_review=red_review,
                report=current_report,
                blue_revision=blue_revision,
                metadata=snapshot_metadata,
            )
            snapshots.append(snapshot)
            latest_decision = decide_convergence(
                snapshots,
                max_rounds=self.config.max_rounds,
                no_improvement_patience=self.config.stop_if_no_improvement_rounds,
                enable_oscillation_detection=self.config.enable_oscillation_detection,
            )
            if latest_decision.should_stop:
                stop_reason = self._legacy_stop_reason(latest_decision.status)
                round_result.stopped = True
                round_result.stop_reason = stop_reason
                break

        if latest_decision is None:
            latest_decision = decide_convergence(
                snapshots,
                max_rounds=self.config.max_rounds,
                no_improvement_patience=self.config.stop_if_no_improvement_rounds,
                enable_oscillation_detection=self.config.enable_oscillation_detection,
            )
        remaining_issue_count = self._remaining_issue_count(rounds)
        if passed:
            remaining_issue_count = 0
        loop_summary = build_loop_summary(
            snapshots,
            latest_decision,
            stop_reason=stop_reason,
            metadata={
                "max_rounds": self.config.max_rounds,
                "stop_on_pass": self.config.stop_on_pass,
            },
        )
        loop_result = RedBlueLoopResult(
            final_report=current_report,
            rounds=rounds,
            round_snapshots=snapshots,
            loop_summary=loop_summary,
            passed=passed,
            total_fixed_issues=len(total_fixed_issue_ids),
            remaining_issue_count=remaining_issue_count,
            stop_reason=stop_reason,
            metadata=self._metadata(loop_summary, latest_decision.status, stop_reason),
        )
        self._write_memory(context, loop_result)
        return loop_result

    @staticmethod
    def _emit_event(event_sink, event_type: str, data: dict) -> None:
        if event_sink is not None:
            event_sink(event_type, data)

    @classmethod
    def _emit_review_stream(cls, event_sink, title: str, lines: List[str]) -> None:
        if event_sink is None:
            return
        text = "\n".join([f"{title}：", *[line for line in lines if line]]).strip()
        cls._emit_event(event_sink, "report_stream_start", {"target": "reviewTranscript"})
        for index in range(0, len(text), 80):
            cls._emit_event(
                event_sink,
                "report_delta",
                {"target": "reviewTranscript", "delta": text[index : index + 80]},
            )
        cls._emit_event(
            event_sink,
            "report_stream_done",
            {"target": "reviewTranscript", "text": text},
        )

    @staticmethod
    def _live_review_payload(round_index, red_review, blue_revision) -> dict:
        return {
            "round": round_index,
            "redSummary": red_review.summary,
            "redIssues": [
                {
                    "issueId": issue.issue_id,
                    "severity": issue.severity,
                    "message": issue.message,
                    "evidence": issue.evidence or "",
                    "suggestion": issue.suggestion or "",
                }
                for issue in red_review.issues
            ],
            "blueRevision": {
                "fixedIssueIds": list(getattr(blue_revision, "fixed_issue_ids", []) or []),
                "remainingIssueIds": list(getattr(blue_revision, "remaining_issue_ids", []) or []),
                "revisionNotes": list(getattr(blue_revision, "revision_notes", []) or [])
                or (["本轮复核通过，无需修改正文。"] if blue_revision is None else []),
                "changes": [],
            },
            "status": "PASSED" if red_review.passed else "REVISED",
        }

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
        snapshots: List[RedBlueRoundSnapshot],
        passed: bool,
        stop_reason: str,
        convergence_status: str,
        total_fixed_issue_ids: set[str],
    ) -> RedBlueLoopResult:
        decision = decide_convergence(snapshots, max_rounds=len(rounds) or 1)
        decision.status = convergence_status
        loop_summary = build_loop_summary(
            snapshots,
            decision,
            stop_reason=stop_reason,
            metadata={"error_stop": stop_reason},
        )
        return RedBlueLoopResult(
            final_report=final_report,
            rounds=rounds,
            round_snapshots=snapshots,
            loop_summary=loop_summary,
            passed=passed,
            total_fixed_issues=len(total_fixed_issue_ids),
            remaining_issue_count=RedBlueLoopRunner._remaining_issue_count(rounds),
            stop_reason=stop_reason,
            metadata=RedBlueLoopRunner._metadata(loop_summary, convergence_status, stop_reason),
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
        if result.loop_summary is not None:
            context.memory.add_record(
                item_type="red_blue_loop_summary",
                content=result.loop_summary,
                source_agent=self.name,
                task_id=context.task_id,
                metadata=result.metadata,
            )

    @staticmethod
    def _metadata(
        loop_summary: RedBlueLoopSummary,
        convergence_status: str,
        stop_reason: str,
    ) -> dict:
        final_score = (
            loop_summary.convergence_score_history[-1]
            if loop_summary.convergence_score_history
            else 0.0
        )
        return {
            "max_rounds": loop_summary.metadata.get("max_rounds"),
            "round_count": loop_summary.total_rounds,
            "stop_on_pass": loop_summary.metadata.get("stop_on_pass"),
            "convergence_status": convergence_status,
            "red_blue_convergence_status": convergence_status,
            "red_blue_stop_reason": stop_reason,
            "red_blue_round_count": loop_summary.total_rounds,
            "red_blue_issue_count_history": loop_summary.issue_count_history,
            "red_blue_oscillation_detected": loop_summary.oscillation_detected,
            "red_blue_repeated_fingerprints": loop_summary.repeated_fingerprints,
            "red_blue_final_convergence_score": final_score,
        }

    @staticmethod
    def _legacy_stop_reason(status: str) -> str:
        mapping = {
            STATUS_CONVERGED: "red_passed",
            STATUS_MAX_ROUNDS_REACHED: "max_rounds_reached",
            STATUS_NO_IMPROVEMENT: "no_improvement",
            STATUS_OSCILLATION_DETECTED: "oscillation_detected",
            STATUS_BLUE_UNABLE_TO_FIX: "blue_agent_failed",
            STATUS_ERROR: "error",
        }
        return mapping.get(status, "max_rounds_reached")
