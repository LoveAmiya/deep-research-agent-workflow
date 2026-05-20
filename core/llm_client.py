import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.config import LLMConfig


class LLMClientError(Exception):
    pass


@dataclass
class LLMMessage:
    role: str
    content: str


@dataclass
class LLMResponse:
    content: str
    model: Optional[str] = None
    usage: Dict = field(default_factory=dict)
    raw: Optional[Dict] = None


class BaseLLMClient:
    def generate(self, messages: List[LLMMessage], temperature: float = 0.2) -> LLMResponse:
        raise NotImplementedError


class MockLLMClient(BaseLLMClient):
    def generate(self, messages: List[LLMMessage], temperature: float = 0.2) -> LLMResponse:
        last_user_message = ""
        for message in reversed(messages):
            if message.role == "user":
                last_user_message = message.content
                break
        content = (
            "Mock LLM response. This deterministic response is based on the last user message: "
            f"{last_user_message[:200]}"
        )
        return LLMResponse(
            content=content,
            model="mock-llm",
            usage={"prompt_messages": len(messages), "temperature": temperature},
            raw={"provider": "mock"},
        )


class OpenAICompatibleLLMClient(BaseLLMClient):
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def generate(self, messages: List[LLMMessage], temperature: float = 0.2) -> LLMResponse:
        payload = {
            "model": self.config.model,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "temperature": temperature,
        }
        request = urllib.request.Request(
            url=f"{self.config.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise LLMClientError(f"LLM request failed: {exc}") from exc

        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("LLM response did not contain choices[0].message.content.") from exc

        return LLMResponse(
            content=content,
            model=raw.get("model", self.config.model),
            usage=raw.get("usage", {}),
            raw=raw,
        )


def create_llm_client(config: LLMConfig) -> BaseLLMClient:
    if config.enabled and config.api_key and config.model and config.base_url:
        return OpenAICompatibleLLMClient(config)
    return MockLLMClient()
