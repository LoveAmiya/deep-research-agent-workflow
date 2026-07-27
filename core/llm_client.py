import json
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

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
    supports_streaming = False

    def generate(self, messages: List[LLMMessage], temperature: float = 0.2) -> LLMResponse:
        raise NotImplementedError

    def generate_stream(self, messages: List[LLMMessage], temperature: float = 0.2) -> Iterator[str]:
        raise LLMClientError("This LLM client does not support streaming.")

    def cancel_active_requests(self) -> None:
        """Best-effort interruption hook used by local request timeouts."""


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
    supports_streaming = True

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._active_response_lock = threading.Lock()
        self._active_responses: dict[int, object] = {}
        self._request_failure: str | None = None

    def cancel_active_requests(self) -> None:
        with self._active_response_lock:
            responses = list(self._active_responses.values())
        for response in responses:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except OSError:
                    pass

    def _register_response(self, response: object) -> None:
        with self._active_response_lock:
            self._active_responses[id(response)] = response

    def _unregister_response(self, response: object) -> None:
        with self._active_response_lock:
            self._active_responses.pop(id(response), None)

    def _ensure_request_available(self) -> None:
        with self._active_response_lock:
            unavailable = self._request_failure is not None
        if unavailable:
            raise LLMClientError("LLM request skipped after an earlier request failure.")

    def _record_request_failure(self, error: Exception) -> None:
        with self._active_response_lock:
            if self._request_failure is None:
                self._request_failure = str(error)

    def generate(self, messages: List[LLMMessage], temperature: float = 0.2) -> LLMResponse:
        self._ensure_request_available()
        if self.config.wire_api == "responses":
            return self._generate_responses(messages, temperature=temperature)
        return self._generate_chat_completions(messages, temperature=temperature)

    def generate_stream(self, messages: List[LLMMessage], temperature: float = 0.2) -> Iterator[str]:
        self._ensure_request_available()
        if self.config.wire_api == "responses":
            payload = {
                "model": self.config.model,
                "input": self._responses_input(messages),
                "temperature": temperature,
                "stream": True,
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
            yield from self._post_sse(f"{self.config.base_url}/responses", payload)
            return

        payload = {
            "model": self.config.model,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "temperature": temperature,
            "stream": True,
        }
        if self.config.max_output_tokens:
            payload["max_tokens"] = self.config.max_output_tokens
        yield from self._post_sse(f"{self.config.base_url}/chat/completions", payload)

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
            response = urllib.request.urlopen(request, timeout=self.config.timeout_seconds)
            self._register_response(response)
            try:
                with response:
                    return json.loads(response.read().decode("utf-8"))
            finally:
                self._unregister_response(response)
        except urllib.error.HTTPError as exc:
            self._record_request_failure(exc)
            response_body = self._read_error_body(exc)
            raise LLMClientError(
                f"LLM request failed: HTTP {exc.code} {exc.reason}; response: {response_body}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            self._record_request_failure(exc)
            raise LLMClientError(f"LLM request failed: {exc}") from exc

    def _post_sse(self, url: str, payload: dict) -> Iterator[str]:
        request = urllib.request.Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": self.config.user_agent,
            },
            method="POST",
        )
        data_lines: list[str] = []
        try:
            response = urllib.request.urlopen(request, timeout=self.config.timeout_seconds)
            self._register_response(response)
            try:
                with response:
                    for raw_line in response:
                        line = raw_line.decode("utf-8", errors="replace").rstrip()
                        if line.startswith("data:"):
                            data_lines.append(line[5:].lstrip())
                            continue
                        if line:
                            continue
                        terminal = self._sse_terminal_state(data_lines)
                        yield from self._sse_data_deltas(data_lines)
                        data_lines = []
                        if terminal == "completed":
                            return
                        if terminal == "failed":
                            raise LLMClientError("LLM streaming response ended before completion.")
                    terminal = self._sse_terminal_state(data_lines)
                    yield from self._sse_data_deltas(data_lines)
                    if terminal == "failed":
                        raise LLMClientError("LLM streaming response ended before completion.")
            finally:
                self._unregister_response(response)
        except urllib.error.HTTPError as exc:
            self._record_request_failure(exc)
            response_body = self._read_error_body(exc)
            raise LLMClientError(
                f"LLM streaming request failed: HTTP {exc.code} {exc.reason}; response: {response_body}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            self._record_request_failure(exc)
            raise LLMClientError(f"LLM streaming request failed: {exc}") from exc

    @staticmethod
    def _sse_data_deltas(data_lines: list[str]) -> Iterator[str]:
        if not data_lines:
            return
        payload_text = "\n".join(data_lines).strip()
        if not payload_text or payload_text == "[DONE]":
            return
        try:
            event = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise LLMClientError("LLM streaming response contained invalid SSE JSON.") from exc

        if isinstance(event.get("choices"), list) and event["choices"]:
            delta = event["choices"][0].get("delta", {})
            content = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(content, str) and content:
                yield content
            return

        if event.get("type") == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                yield delta

    @staticmethod
    def _sse_terminal_state(data_lines: list[str]) -> str | None:
        if not data_lines:
            return None
        payload_text = "\n".join(data_lines).strip()
        if payload_text == "[DONE]":
            return "completed"
        try:
            event = json.loads(payload_text)
        except json.JSONDecodeError:
            return None
        event_type = event.get("type") if isinstance(event, dict) else None
        if event_type == "response.completed":
            return "completed"
        if event_type in {"response.failed", "response.incomplete", "error"}:
            return "failed"
        return None

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
