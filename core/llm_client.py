import json
import re
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
        if any("evaluation judge" in message.content.lower() for message in messages):
            return LLMResponse(
                content=json.dumps(
                    {
                        "dimension_scores": {
                            "answer_relevance": 4,
                            "factual_consistency": 4,
                            "citation_quality": 4,
                            "completeness": 4,
                            "clarity": 4,
                        },
                        "overall_score": 4.0,
                        "strengths": ["Clear structure and grounded citations."],
                        "weaknesses": ["Mock judge cannot verify external facts."],
                        "suggested_improvements": ["Use real evidence review for production evaluation."],
                        "passed": True,
                    }
                ),
                model="mock-llm",
                usage={"prompt_messages": len(messages), "temperature": temperature},
                raw={"provider": "mock", "mode": "judge"},
            )
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
        if self.config.wire_api == "responses":
            return self._generate_responses(messages, temperature=temperature)
        return self._generate_chat_completions(messages, temperature=temperature)

    def _generate_chat_completions(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
    ) -> LLMResponse:
        payload = {
            "model": self.config.model,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "temperature": temperature,
        }
        if self.config.max_output_tokens:
            payload["max_tokens"] = self.config.max_output_tokens
        raw = self._post_json(f"{self.config.base_url}/chat/completions", payload)

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

    def _generate_responses(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
    ) -> LLMResponse:
        payload = {
            "model": self.config.model,
            "input": self._responses_input(messages),
            "temperature": temperature,
        }
        if self.config.max_output_tokens:
            payload["max_output_tokens"] = self.config.max_output_tokens
        instructions = self._responses_instructions(messages)
        if instructions:
            payload["instructions"] = instructions
        if self.config.reasoning_effort:
            payload["reasoning"] = {"effort": self.config.reasoning_effort}
        if self.config.disable_response_storage:
            payload["store"] = False

        raw = self._post_json(f"{self.config.base_url}/responses", payload)
        content = self._extract_responses_content(raw)
        return LLMResponse(
            content=content,
            model=raw.get("model", self.config.model),
            usage=raw.get("usage", {}),
            raw=raw,
        )

    def _post_json(self, url: str, payload: dict) -> dict:
        request = urllib.request.Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": self.config.user_agent,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            response_body = self._read_error_body(exc)
            raise LLMClientError(
                f"LLM request failed: HTTP {exc.code} {exc.reason}; response: {response_body}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise LLMClientError(f"LLM request failed: {exc}") from exc

    @staticmethod
    def _read_error_body(exc: urllib.error.HTTPError) -> str:
        try:
            raw_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw_body = ""
        sanitized = _sanitize_error_text(raw_body)
        return sanitized[:1200] if sanitized else "(empty response body)"

    @staticmethod
    def _extract_responses_content(raw: dict) -> str:
        if isinstance(raw.get("output_text"), str):
            return raw["output_text"]

        text_parts: list[str] = []
        for output_item in raw.get("output", []) or []:
            content_items = output_item.get("content", []) if isinstance(output_item, dict) else []
            for content_item in content_items:
                if not isinstance(content_item, dict):
                    continue
                text_value = content_item.get("text")
                if isinstance(text_value, str):
                    text_parts.append(text_value)
        if text_parts:
            return "\n".join(text_parts)

        raise LLMClientError("Responses API result did not contain output_text or output content text.")

    @staticmethod
    def _responses_instructions(messages: List[LLMMessage]) -> str:
        return "\n\n".join(message.content for message in messages if message.role == "system").strip()

    @staticmethod
    def _responses_input(messages: List[LLMMessage]) -> str:
        non_system_messages = [message for message in messages if message.role != "system"]
        if not non_system_messages:
            return ""
        return "\n\n".join(
            f"{message.role.upper()}:\n{message.content}"
            for message in non_system_messages
        )


def create_llm_client(config: LLMConfig) -> BaseLLMClient:
    if config.enabled and config.api_key and config.model and config.base_url:
        return OpenAICompatibleLLMClient(config)
    return MockLLMClient()


def _sanitize_error_text(text: str) -> str:
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[redacted-api-key]", text)
    text = re.sub(
        r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?bearer\s+)[^\"'\s,}]+",
        r"\1[redacted]",
        text,
    )
    return text
