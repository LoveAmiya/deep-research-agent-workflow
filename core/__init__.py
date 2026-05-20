"""Core data structures for DeepResearchAgent."""

from .config import LLMConfig, SearchConfig, load_llm_config_from_env, load_search_config_from_env
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
    PageContent,
    RedReviewResult,
    ResearchPlan,
    ResearchQuestion,
    ResearchReport,
    ReviewIssue,
    SearchResult,
    WebSearchResult,
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
    "PageContent",
    "RedReviewResult",
    "ResearchPlan",
    "ResearchQuestion",
    "ResearchReport",
    "ReviewIssue",
    "SearchResult",
    "SearchConfig",
    "WebSearchResult",
    "create_llm_client",
    "load_llm_config_from_env",
    "load_search_config_from_env",
    "load_prompt",
]
