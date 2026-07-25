"""Small, dependency-free helpers for structured LLM responses."""

from __future__ import annotations

import json
from typing import Any


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Return the first JSON object in plain text or a fenced model response."""
    source = str(text or "").strip()
    if source.startswith("```"):
        source = source.split("\n", 1)[1] if "\n" in source else ""
        if source.rstrip().endswith("```"):
            source = source.rstrip()[:-3].rstrip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(source):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(source[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
