import json
from dataclasses import asdict, dataclass, is_dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4


def _to_json_friendly(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_json_friendly(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _to_json_friendly(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_json_friendly(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_friendly(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


@dataclass
class MemoryItem:
    item_id: str
    item_type: str
    content: Any
    source_agent: str
    task_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SharedMemory:
    _items: List[MemoryItem] = field(default_factory=list)

    def add(self, item: MemoryItem) -> MemoryItem:
        existing = self._find_duplicate(item.item_type, item.source_agent, item.content)
        if existing is not None:
            return existing
        self._items.append(item)
        return item

    def add_record(
        self,
        item_type: str,
        content: Any,
        source_agent: str,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryItem:
        item = MemoryItem(
            item_id=str(uuid4()),
            item_type=item_type,
            content=content,
            source_agent=source_agent,
            task_id=task_id,
            metadata=metadata or {},
        )
        return self.add(item)

    def get(self, item_id: str) -> Optional[MemoryItem]:
        for item in self._items:
            if item.item_id == item_id:
                return item
        return None

    def list_by_type(self, item_type: str) -> List[MemoryItem]:
        return [item for item in self._items if item.item_type == item_type]

    def list_by_agent(self, source_agent: str) -> List[MemoryItem]:
        return [item for item in self._items if item.source_agent == source_agent]

    def all_items(self) -> List[MemoryItem]:
        return list(self._items)

    def to_dict_list(self) -> List[Dict[str, Any]]:
        return [
            {
                "item_id": item.item_id,
                "item_type": item.item_type,
                "content": _to_json_friendly(item.content),
                "source_agent": item.source_agent,
                "task_id": item.task_id,
                "metadata": _to_json_friendly(item.metadata),
            }
            for item in self._items
        ]

    def _find_duplicate(
        self,
        item_type: str,
        source_agent: str,
        content: Any,
    ) -> Optional[MemoryItem]:
        content_key = self._content_key(content)
        for item in self._items:
            if (
                item.item_type == item_type
                and item.source_agent == source_agent
                and self._content_key(item.content) == content_key
            ):
                return item
        return None

    @staticmethod
    def _content_key(content: Any) -> str:
        return json.dumps(_to_json_friendly(content), sort_keys=True, ensure_ascii=True)


MemoryStore = SharedMemory
