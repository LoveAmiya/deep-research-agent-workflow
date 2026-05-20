"""Core data structures for DeepResearchAgent."""

from .config import LLMConfig, load_llm_config_from_env
from .llm_client import (
    BaseLLMClient,
    LLMClientError,
    LLMMessage,
    LLMResponse,
    MockLLMClient,
    OpenAICompatibleLLMClient,
    create_llm_client,
)
from .prompt_loader import load_prompt
from .schema import (
    BlueRevisionResult,
    Finding,
    RedReviewResult,
    ResearchPlan,
    ResearchQuestion,
    ResearchReport,
    ReviewIssue,
    SearchResult,
)

__all__ = [
    "BaseLLMClient",
    "BlueRevisionResult",
    "Finding",
    "LLMClientError",
    "LLMConfig",
    "LLMMessage",
    "LLMResponse",
    "MockLLMClient",
    "OpenAICompatibleLLMClient",
    "RedReviewResult",
    "ResearchPlan",
    "ResearchQuestion",
    "ResearchReport",
    "ReviewIssue",
    "SearchResult",
    "create_llm_client",
    "load_llm_config_from_env",
    "load_prompt",
]
