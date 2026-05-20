from typing import List, TypeVar

T = TypeVar("T")


def compress_findings(findings: List[T], max_items: int = 5) -> List[T]:
    if len(findings) <= max_items:
        return list(findings)
    return list(findings[:max_items])
