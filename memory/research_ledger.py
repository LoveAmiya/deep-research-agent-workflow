"""Run-scoped, append-only collaboration records for research agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from uuid import uuid4


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class LedgerArtifact:
    artifact_id: str
    artifact_type: str
    producer_agent: str
    task_id: str
    version: int
    status: str
    dependencies: list[str]
    content: Any
    summary: str
    created_at: str


@dataclass(frozen=True)
class LedgerHandoff:
    handoff_id: str
    sender_agent: str
    recipient_agent: str
    artifact_ids: list[str]
    action: str
    status: str
    reason: str
    created_at: str


@dataclass
class ResearchLedger:
    """Append-only artifacts and handoffs for one research run."""

    run_id: Optional[str] = None
    artifacts: list[LedgerArtifact] = field(default_factory=list)
    handoffs: list[LedgerHandoff] = field(default_factory=list)

    def publish(
        self,
        *,
        artifact_type: str,
        producer_agent: str,
        task_id: str,
        content: Any,
        summary: str,
        dependencies: Optional[Iterable[str]] = None,
        status: str = "PUBLISHED",
    ) -> LedgerArtifact:
        version = 1 + sum(
            artifact.artifact_type == artifact_type
            and artifact.producer_agent == producer_agent
            and artifact.task_id == task_id
            for artifact in self.artifacts
        )
        artifact = LedgerArtifact(
            artifact_id=f"artifact-{uuid4().hex}",
            artifact_type=artifact_type,
            producer_agent=producer_agent,
            task_id=task_id,
            version=version,
            status=status,
            dependencies=list(dependencies or []),
            content=content,
            summary=summary,
            created_at=_timestamp(),
        )
        self.artifacts.append(artifact)
        return artifact

    def read(self, artifact_id: str) -> LedgerArtifact:
        for artifact in self.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        raise KeyError(f"Unknown ledger artifact: {artifact_id}")

    def latest(self, artifact_type: str, status: Optional[str] = None) -> Optional[LedgerArtifact]:
        for artifact in reversed(self.artifacts):
            if artifact.artifact_type == artifact_type and (status is None or artifact.status == status):
                return artifact
        return None

    def list_artifacts(self, artifact_type: Optional[str] = None) -> list[LedgerArtifact]:
        if artifact_type is None:
            return list(self.artifacts)
        return [artifact for artifact in self.artifacts if artifact.artifact_type == artifact_type]

    def acknowledge(
        self,
        *,
        sender_agent: str,
        recipient_agent: str,
        artifact_ids: Iterable[str],
        action: str = "consume",
        reason: str = "",
        status: str = "ACKNOWLEDGED",
    ) -> LedgerHandoff:
        artifact_ids = list(artifact_ids)
        for artifact_id in artifact_ids:
            self.read(artifact_id)
        handoff = LedgerHandoff(
            handoff_id=f"handoff-{uuid4().hex}",
            sender_agent=sender_agent,
            recipient_agent=recipient_agent,
            artifact_ids=artifact_ids,
            action=action,
            status=status,
            reason=reason,
            created_at=_timestamp(),
        )
        self.handoffs.append(handoff)
        return handoff

    def request_revision(
        self,
        *,
        sender_agent: str,
        recipient_agent: str,
        artifact_ids: Iterable[str],
        reason: str,
    ) -> LedgerHandoff:
        return self.acknowledge(
            sender_agent=sender_agent,
            recipient_agent=recipient_agent,
            artifact_ids=artifact_ids,
            action="request_revision",
            reason=reason,
            status="REVISION_REQUESTED",
        )

    def list_handoffs(self, status: Optional[str] = None) -> list[LedgerHandoff]:
        if status is None:
            return list(self.handoffs)
        return [handoff for handoff in self.handoffs if handoff.status == status]

    def summary(self) -> dict[str, int]:
        return {
            "artifactCount": len(self.artifacts),
            "handoffCount": len(self.handoffs),
            "revisionRequestCount": len(self.list_handoffs("REVISION_REQUESTED")),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifacts": [asdict(artifact) for artifact in self.artifacts],
            "handoffs": [asdict(handoff) for handoff in self.handoffs],
        }

    @classmethod
    def from_dict(cls, value: Optional[dict[str, Any]]) -> "ResearchLedger":
        value = value or {}
        return cls(
            run_id=value.get("run_id"),
            artifacts=[LedgerArtifact(**artifact) for artifact in value.get("artifacts", [])],
            handoffs=[LedgerHandoff(**handoff) for handoff in value.get("handoffs", [])],
        )
