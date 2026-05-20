import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMConfig:
    provider: str = "openai_compatible"
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 60.0
    enabled: bool = False


def load_llm_config_from_env() -> LLMConfig:
    enabled_raw = os.getenv("DEEP_RESEARCH_USE_LLM", "").strip().lower()
    timeout_raw = os.getenv("DEEP_RESEARCH_LLM_TIMEOUT_SECONDS", "60").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError:
        timeout_seconds = 60.0

    return LLMConfig(
        provider=os.getenv("DEEP_RESEARCH_LLM_PROVIDER", "openai_compatible"),
        model=os.getenv("DEEP_RESEARCH_LLM_MODEL"),
        api_key=os.getenv("DEEP_RESEARCH_LLM_API_KEY"),
        base_url=os.getenv("DEEP_RESEARCH_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        timeout_seconds=timeout_seconds,
        enabled=enabled_raw in {"1", "true"},
    )
