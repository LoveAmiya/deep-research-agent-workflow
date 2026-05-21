import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


STATUS_CONVERGED = "CONVERGED"
STATUS_MAX_ROUNDS_REACHED = "MAX_ROUNDS_REACHED"
STATUS_NO_IMPROVEMENT = "NO_IMPROVEMENT"
STATUS_OSCILLATION_DETECTED = "OSCILLATION_DETECTED"
STATUS_BLUE_UNABLE_TO_FIX = "BLUE_UNABLE_TO_FIX"
STATUS_ERROR = "ERROR"
STATUS_CONTINUE = "CONTINUE"


@dataclass
class IssueFingerprint:
    issue_type: str
    severity: str | None
    normalized_message: str
    citation_id: str | None
    evidence_id: str | None
    fingerprint: str


@dataclass
class RedBlueRoundSnapshot:
    round_index: int
    issue_count: int
    issue_fingerprints: list[str]
    report_hash: str
    blue_action_count: int
    fixed_issue_count: int
    remaining_issue_count: int
    passed: bool
    metadata: dict = field(default_factory=dict)


@dataclass
class RedBlueConvergenceDecision:
    should_stop: bool
    status: str
    reason: str
    convergence_score: float
    oscillation_detected: bool
    repeated_fingerprints: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class RedBlueLoopSummary:
    total_rounds: int
    final_status: str
    stop_reason: str
    issue_count_history: list[int]
    convergence_score_history: list[float]
    oscillation_detected: bool
    repeated_fingerprints: list[str]
    final_issue_count: int
    metadata: dict = field(default_factory=dict)


def normalize_issue_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
    normalized = re.sub(r"\b\d+\b", "<num>", normalized)
    return normalized


def fingerprint_issue(issue) -> IssueFingerprint:
    issue_type = _get_issue_field(issue, "category") or _get_issue_field(issue, "issue_type") or "unknown"
    severity = _get_issue_field(issue, "severity")
    message = (
        _get_issue_field(issue, "message")
        or _get_issue_field(issue, "summary")
        or _get_issue_field(issue, "issue")
        or ""
    )
    citation_id = _get_issue_field(issue, "citation_id") or _metadata_value(issue, "citation_id")
    evidence_id = _get_issue_field(issue, "evidence_id") or _metadata_value(issue, "evidence_id")
    normalized_message = normalize_issue_text(message)
    payload = {
        "issue_type": str(issue_type or "unknown").lower(),
        "severity": str(severity).lower() if severity is not None else None,
        "normalized_message": normalized_message,
        "citation_id": citation_id,
        "evidence_id": evidence_id,
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return IssueFingerprint(
        issue_type=payload["issue_type"],
        severity=payload["severity"],
        normalized_message=normalized_message,
        citation_id=citation_id,
        evidence_id=evidence_id,
        fingerprint=fingerprint,
    )


def hash_report(report_text: str) -> str:
    normalized = normalize_issue_text(report_text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalized_report_hash(report) -> str:
    if hasattr(report, "markdown"):
        return hash_report(getattr(report, "markdown", ""))
    return hash_report(str(report or ""))


def compute_issue_delta(previous, current) -> dict:
    previous_set = set(_snapshot_fingerprints(previous))
    current_set = set(_snapshot_fingerprints(current))
    return {
        "added": sorted(current_set - previous_set),
        "removed": sorted(previous_set - current_set),
        "persisted": sorted(previous_set & current_set),
        "previous_count": len(previous_set),
        "current_count": len(current_set),
        "count_delta": len(current_set) - len(previous_set),
    }


def compute_convergence_score(snapshot_history: list[RedBlueRoundSnapshot]) -> float:
    if not snapshot_history:
        return 0.0
    first_count = max(0, snapshot_history[0].issue_count)
    latest_count = max(0, snapshot_history[-1].remaining_issue_count)
    if latest_count == 0:
        return 1.0
    if first_count == 0:
        return 1.0
    score = 1.0 - (latest_count / max(1, first_count))
    return max(0.0, min(1.0, score))


def convergence_score_history(snapshot_history: list[RedBlueRoundSnapshot]) -> list[float]:
    return [
        compute_convergence_score(snapshot_history[: index + 1])
        for index in range(len(snapshot_history))
    ]


def detect_no_improvement(
    snapshot_history: list[RedBlueRoundSnapshot],
    patience: int = 2,
) -> bool:
    if patience <= 0:
        return False
    if len(snapshot_history) < patience + 1:
        return False
    tail = snapshot_history[-(patience + 1) :]
    counts = [snapshot.remaining_issue_count for snapshot in tail]
    return all(current >= previous for previous, current in zip(counts, counts[1:]))


def detect_oscillation(
    snapshot_history: list[RedBlueRoundSnapshot],
    window: int = 4,
) -> tuple[bool, dict]:
    if len(snapshot_history) < 2:
        return False, {"reason": "not_enough_snapshots"}
    tail = snapshot_history[-max(2, window) :]
    issue_signatures = [tuple(sorted(snapshot.issue_fingerprints)) for snapshot in tail]
    report_hashes = [snapshot.report_hash for snapshot in tail]
    repeated_issue_signature = _first_repeated(issue_signatures)
    repeated_report_hash = _first_repeated(report_hashes)
    alternating_report = len(report_hashes) >= 4 and report_hashes[-4] == report_hashes[-2] and report_hashes[-3] == report_hashes[-1] and report_hashes[-1] != report_hashes[-2]
    alternating_issues = len(issue_signatures) >= 4 and issue_signatures[-4] == issue_signatures[-2] and issue_signatures[-3] == issue_signatures[-1] and issue_signatures[-1] != issue_signatures[-2]
    oscillation_detected = bool(
        repeated_issue_signature is not None
        or repeated_report_hash is not None
        or alternating_report
        or alternating_issues
    )
    repeated_fingerprints = []
    if repeated_issue_signature:
        repeated_fingerprints = list(repeated_issue_signature)
    return oscillation_detected, {
        "repeated_issue_signature": repeated_issue_signature,
        "repeated_report_hash": repeated_report_hash,
        "alternating_report_hash": alternating_report,
        "alternating_issue_signature": alternating_issues,
        "repeated_fingerprints": repeated_fingerprints,
    }


def decide_convergence(
    snapshot_history: list[RedBlueRoundSnapshot],
    max_rounds: int,
    no_improvement_patience: int = 2,
    oscillation_window: int = 4,
    enable_oscillation_detection: bool = True,
) -> RedBlueConvergenceDecision:
    score = compute_convergence_score(snapshot_history)
    if not snapshot_history:
        return RedBlueConvergenceDecision(
            should_stop=False,
            status=STATUS_CONTINUE,
            reason="No rounds have completed.",
            convergence_score=score,
            oscillation_detected=False,
        )
    latest = snapshot_history[-1]
    if latest.passed or latest.issue_count == 0:
        return RedBlueConvergenceDecision(
            should_stop=True,
            status=STATUS_CONVERGED,
            reason="RedAgent found no remaining issues.",
            convergence_score=1.0,
            oscillation_detected=False,
            metadata={"round_index": latest.round_index},
        )
    if latest.metadata.get("blue_unable_to_fix"):
        return RedBlueConvergenceDecision(
            should_stop=True,
            status=STATUS_BLUE_UNABLE_TO_FIX,
            reason="BlueAgent could not continue fixing issues.",
            convergence_score=score,
            oscillation_detected=False,
            repeated_fingerprints=list(latest.issue_fingerprints),
            metadata={"round_index": latest.round_index},
        )
    if latest.remaining_issue_count == 0:
        if latest.round_index >= max(1, max_rounds):
            return RedBlueConvergenceDecision(
                should_stop=True,
                status=STATUS_MAX_ROUNDS_REACHED,
                reason="Maximum Red-Blue loop rounds reached before RedAgent revalidation.",
                convergence_score=score,
                oscillation_detected=False,
                repeated_fingerprints=list(latest.issue_fingerprints),
                metadata={"max_rounds": max_rounds},
            )
        return RedBlueConvergenceDecision(
            should_stop=False,
            status=STATUS_CONTINUE,
            reason="BlueAgent cleared remaining issues; continue for RedAgent revalidation.",
            convergence_score=score,
            oscillation_detected=False,
            metadata={"round_index": latest.round_index, "awaiting_red_revalidation": True},
        )
    if enable_oscillation_detection:
        oscillation_detected, oscillation_metadata = detect_oscillation(
            snapshot_history,
            window=oscillation_window,
        )
        if oscillation_detected:
            return RedBlueConvergenceDecision(
                should_stop=True,
                status=STATUS_OSCILLATION_DETECTED,
                reason="Issue fingerprints or report hashes repeated across recent rounds.",
                convergence_score=score,
                oscillation_detected=True,
                repeated_fingerprints=list(oscillation_metadata.get("repeated_fingerprints", [])),
                metadata=oscillation_metadata,
            )
    if detect_no_improvement(snapshot_history, patience=no_improvement_patience):
        return RedBlueConvergenceDecision(
            should_stop=True,
            status=STATUS_NO_IMPROVEMENT,
            reason="Remaining issue count did not improve within patience.",
            convergence_score=score,
            oscillation_detected=False,
            repeated_fingerprints=list(latest.issue_fingerprints),
            metadata={"patience": no_improvement_patience},
        )
    if latest.round_index >= max(1, max_rounds):
        return RedBlueConvergenceDecision(
            should_stop=True,
            status=STATUS_MAX_ROUNDS_REACHED,
            reason="Maximum Red-Blue loop rounds reached.",
            convergence_score=score,
            oscillation_detected=False,
            repeated_fingerprints=list(latest.issue_fingerprints),
            metadata={"max_rounds": max_rounds},
        )
    return RedBlueConvergenceDecision(
        should_stop=False,
        status=STATUS_CONTINUE,
        reason="Continue Red-Blue loop.",
        convergence_score=score,
        oscillation_detected=False,
        metadata={"round_index": latest.round_index},
    )


def build_round_snapshot(
    round_index: int,
    red_review,
    report,
    blue_revision=None,
    metadata: dict | None = None,
) -> RedBlueRoundSnapshot:
    issues = _issues_from_review(red_review)
    issue_fingerprints = [fingerprint_issue(issue).fingerprint for issue in issues]
    fixed_ids = list(getattr(blue_revision, "fixed_issue_ids", []) or []) if blue_revision is not None else []
    remaining_ids = list(getattr(blue_revision, "remaining_issue_ids", []) or []) if blue_revision is not None else []
    revision_notes = list(getattr(blue_revision, "revision_notes", []) or []) if blue_revision is not None else []
    passed = bool(getattr(red_review, "passed", False)) and not issues
    return RedBlueRoundSnapshot(
        round_index=round_index,
        issue_count=len(issues),
        issue_fingerprints=issue_fingerprints,
        report_hash=normalized_report_hash(report),
        blue_action_count=len(fixed_ids) + len(revision_notes),
        fixed_issue_count=len(fixed_ids),
        remaining_issue_count=len(remaining_ids) if blue_revision is not None else len(issues),
        passed=passed,
        metadata=metadata or {},
    )


def build_loop_summary(
    snapshot_history: list[RedBlueRoundSnapshot],
    decision: RedBlueConvergenceDecision,
    stop_reason: str | None = None,
    metadata: dict | None = None,
) -> RedBlueLoopSummary:
    issue_history = [snapshot.issue_count for snapshot in snapshot_history]
    final_issue_count = snapshot_history[-1].remaining_issue_count if snapshot_history else 0
    return RedBlueLoopSummary(
        total_rounds=len(snapshot_history),
        final_status=decision.status,
        stop_reason=stop_reason or decision.reason,
        issue_count_history=issue_history,
        convergence_score_history=convergence_score_history(snapshot_history),
        oscillation_detected=decision.oscillation_detected,
        repeated_fingerprints=list(decision.repeated_fingerprints),
        final_issue_count=final_issue_count,
        metadata=metadata or {},
    )


def to_dict(value) -> dict:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return {"value": value}


def _issues_from_review(red_review) -> list:
    if red_review is None:
        return []
    if isinstance(red_review, dict):
        return list(red_review.get("issues", []) or [])
    return list(getattr(red_review, "issues", []) or [])


def _get_issue_field(issue, field_name: str):
    if isinstance(issue, dict):
        return issue.get(field_name)
    return getattr(issue, field_name, None)


def _metadata_value(issue, key: str):
    metadata = _get_issue_field(issue, "metadata")
    if isinstance(metadata, dict):
        return metadata.get(key)
    return None


def _snapshot_fingerprints(snapshot) -> list[str]:
    if snapshot is None:
        return []
    if isinstance(snapshot, dict):
        return list(snapshot.get("issue_fingerprints", []) or [])
    return list(getattr(snapshot, "issue_fingerprints", []) or [])


def _first_repeated(values: list):
    seen = set()
    for value in values:
        if not value:
            continue
        if value in seen:
            return value
        seen.add(value)
    return None
