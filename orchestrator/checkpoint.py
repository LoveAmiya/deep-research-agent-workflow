import json
import time
import uuid
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agents.base_agent import AgentResult
from core import schema as core_schema


def utc_now_iso() -> str:
    """返回带时区的时间戳，便于跨机器比较运行记录。"""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class NodeCheckpoint:
    """一个 DAG 节点最新执行状态的持久化快照。

    ``output`` 会序列化，而不是保留为内存中的 Python 对象，因此后续进程可以恢复
    已成功节点，无需重复发起外部 API 调用。
    """
    node_id: str
    status: str
    agent_name: Optional[str] = None
    input_hash: Optional[str] = None
    output: Optional[dict] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class RunCheckpoint:
    """运行级别的持久化索引，用来判断哪些节点可以安全恢复。"""
    run_id: str
    task: str
    status: str
    created_at: str
    updated_at: str
    node_checkpoints: dict[str, NodeCheckpoint] = field(default_factory=dict)
    completed_node_ids: list[str] = field(default_factory=list)
    failed_node_ids: list[str] = field(default_factory=list)
    pending_node_ids: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def new(cls, task: str, run_id: Optional[str] = None, metadata: Optional[dict] = None):
        now = utc_now_iso()
        return cls(
            run_id=run_id or str(uuid.uuid4()),
            task=task,
            status="RUNNING",
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

    def refresh_node_lists(self, all_node_ids: Optional[list[str]] = None) -> None:
        """从节点真实状态推导汇总列表，避免维护重复状态。

        节点 Checkpoint 是唯一事实来源；这些列表用于命令行和 UI 快速查看已保存运行。
        """
        self.completed_node_ids = [
            node_id
            for node_id, checkpoint in self.node_checkpoints.items()
            if checkpoint.status == "SUCCESS" and checkpoint.output is not None
        ]
        self.failed_node_ids = [
            node_id
            for node_id, checkpoint in self.node_checkpoints.items()
            if checkpoint.status == "FAILED"
        ]
        candidate_node_ids = all_node_ids or list(self.node_checkpoints.keys())
        self.pending_node_ids = [
            node_id
            for node_id in candidate_node_ids
            if node_id not in self.completed_node_ids and node_id not in self.failed_node_ids
        ]


class CheckpointStore:
    def save_checkpoint(self, checkpoint: RunCheckpoint) -> None:
        raise NotImplementedError

    def load_checkpoint(self, run_id: str) -> Optional[RunCheckpoint]:
        raise NotImplementedError

    def checkpoint_exists(self, run_id: str) -> bool:
        raise NotImplementedError


class JSONCheckpointStore(CheckpointStore):
    """使用写后替换方式持久化到文件的 Checkpoint 存储。

    写入时先创建临时文件再替换目标文件，降低中断后留下截断 JSON 的概率。
    """
    def __init__(self, checkpoint_dir: str = "runs/checkpoints") -> None:
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(self, checkpoint: RunCheckpoint) -> None:
        checkpoint.updated_at = utc_now_iso()
        path = self.checkpoint_path(checkpoint.run_id)
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        payload = run_checkpoint_to_dict(checkpoint)
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._replace_with_retry(temporary_path, path)

    def load_checkpoint(self, run_id: str) -> Optional[RunCheckpoint]:
        path = self.checkpoint_path(run_id)
        if not path.exists():
            return None
        try:
            return run_checkpoint_from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def checkpoint_exists(self, run_id: str) -> bool:
        return self.checkpoint_path(run_id).exists()

    def checkpoint_path(self, run_id: str) -> Path:
        safe_run_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in run_id)
        return self.checkpoint_dir / f"{safe_run_id}.json"

    @staticmethod
    def _replace_with_retry(
        temporary_path: Path,
        target_path: Path,
        attempts: int = 5,
        delay_seconds: float = 0.02,
    ) -> None:
        for attempt in range(1, attempts + 1):
            try:
                temporary_path.replace(target_path)
                return
            except PermissionError:
                if attempt == attempts:
                    raise
                time.sleep(delay_seconds * attempt)


def run_checkpoint_to_dict(checkpoint: RunCheckpoint) -> dict:
    return {
        "run_id": checkpoint.run_id,
        "task": checkpoint.task,
        "status": checkpoint.status,
        "created_at": checkpoint.created_at,
        "updated_at": checkpoint.updated_at,
        "node_checkpoints": {
            node_id: node_checkpoint_to_dict(node_checkpoint)
            for node_id, node_checkpoint in checkpoint.node_checkpoints.items()
        },
        "completed_node_ids": list(checkpoint.completed_node_ids),
        "failed_node_ids": list(checkpoint.failed_node_ids),
        "pending_node_ids": list(checkpoint.pending_node_ids),
        "metadata": serialize_checkpoint_value(checkpoint.metadata),
    }


def run_checkpoint_from_dict(data: dict) -> RunCheckpoint:
    checkpoint = RunCheckpoint(
        run_id=data["run_id"],
        task=data.get("task", ""),
        status=data.get("status", "PENDING"),
        created_at=data.get("created_at", utc_now_iso()),
        updated_at=data.get("updated_at", utc_now_iso()),
        node_checkpoints={
            node_id: node_checkpoint_from_dict(node_data)
            for node_id, node_data in data.get("node_checkpoints", {}).items()
        },
        completed_node_ids=list(data.get("completed_node_ids", [])),
        failed_node_ids=list(data.get("failed_node_ids", [])),
        pending_node_ids=list(data.get("pending_node_ids", [])),
        metadata=data.get("metadata", {}),
    )
    return checkpoint


def node_checkpoint_to_dict(checkpoint: NodeCheckpoint) -> dict:
    return {
        "node_id": checkpoint.node_id,
        "status": checkpoint.status,
        "agent_name": checkpoint.agent_name,
        "input_hash": checkpoint.input_hash,
        "output": checkpoint.output,
        "error": checkpoint.error,
        "started_at": checkpoint.started_at,
        "finished_at": checkpoint.finished_at,
        "metadata": serialize_checkpoint_value(checkpoint.metadata),
    }


def node_checkpoint_from_dict(data: dict) -> NodeCheckpoint:
    return NodeCheckpoint(
        node_id=data["node_id"],
        status=data.get("status", "PENDING"),
        agent_name=data.get("agent_name"),
        input_hash=data.get("input_hash"),
        output=data.get("output"),
        error=data.get("error"),
        started_at=data.get("started_at"),
        finished_at=data.get("finished_at"),
        metadata=data.get("metadata", {}),
    )


def serialize_checkpoint_output(value: Any) -> Any:
    return serialize_checkpoint_value(value)


def deserialize_checkpoint_output(value: Any) -> Any:
    return deserialize_checkpoint_value(value)


def serialize_checkpoint_value(value: Any) -> Any:
    if isinstance(value, AgentResult):
        return {
            "__checkpoint_type__": "AgentResult",
            "agent_name": value.agent_name,
            "success": value.success,
            "output": serialize_checkpoint_value(value.output),
            "error": value.error,
            "metadata": serialize_checkpoint_value(value.metadata),
        }
    if is_dataclass(value):
        return {
            "__checkpoint_dataclass__": value.__class__.__name__,
            "fields": {
                item.name: serialize_checkpoint_value(getattr(value, item.name))
                for item in fields(value)
            },
        }
    if isinstance(value, dict):
        return {str(key): serialize_checkpoint_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_checkpoint_value(item) for item in value]
    if isinstance(value, set):
        return sorted(serialize_checkpoint_value(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def deserialize_checkpoint_value(value: Any) -> Any:
    if isinstance(value, list):
        return [deserialize_checkpoint_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    checkpoint_type = value.get("__checkpoint_type__")
    if checkpoint_type == "AgentResult":
        return AgentResult(
            agent_name=value.get("agent_name", ""),
            success=bool(value.get("success", False)),
            output=deserialize_checkpoint_value(value.get("output")),
            error=value.get("error"),
            metadata=deserialize_checkpoint_value(value.get("metadata", {})),
        )
    dataclass_name = value.get("__checkpoint_dataclass__")
    if dataclass_name:
        data = {
            key: deserialize_checkpoint_value(item)
            for key, item in value.get("fields", {}).items()
        }
        dataclass_type = _SCHEMA_DATACLASSES.get(dataclass_name)
        if dataclass_type is not None:
            return dataclass_type(**data)
        return data
    return {key: deserialize_checkpoint_value(item) for key, item in value.items()}


_SCHEMA_DATACLASSES = {
    name: getattr(core_schema, name)
    for name in [
        "ResearchQuestion",
        "ResearchPlan",
        "SearchResult",
        "WebSearchResult",
        "PageContent",
        "Finding",
        "EvidenceSpan",
        "Citation",
        "GroundedFinding",
        "ResearchReport",
        "ReviewIssue",
        "RedReviewResult",
        "BlueRevisionResult",
    ]
    if hasattr(core_schema, name)
}
