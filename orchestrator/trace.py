import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from orchestrator.state import TaskState


@dataclass
class TraceEvent:
    task_id: str
    task_name: str
    state: TaskState
    timestamp_ms: int
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceRecorder:
    events: List[TraceEvent] = field(default_factory=list)

    def record(
        self,
        task_id: str,
        task_name: str,
        state: TaskState,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TraceEvent:
        event = TraceEvent(
            task_id=task_id,
            task_name=task_name,
            state=state,
            timestamp_ms=int(time.time() * 1000),
            error=error,
            metadata=metadata or {},
        )
        self.events.append(event)
        return event

    def to_dict_list(self) -> List[Dict[str, Any]]:
        return [
            {
                "task_id": event.task_id,
                "task_name": event.task_name,
                "state": event.state.value,
                "timestamp_ms": event.timestamp_ms,
                "error": event.error,
                "metadata": event.metadata,
            }
            for event in self.events
        ]
