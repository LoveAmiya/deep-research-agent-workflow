import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


@dataclass
class LLMConfig:
    provider: str = "openai_compatible"
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 60.0
    enabled: bool = False


@dataclass
class SearchConfig:
    enabled: bool = False
    provider: str = "mock"
    max_results: int = 5
    timeout_seconds: float = 15.0
    user_agent: str = DEFAULT_USER_AGENT


@dataclass
class DAGExecutionConfig:
    use_async: bool = False
    max_concurrency: int = 3
    task_timeout_seconds: Optional[float] = None


@dataclass
class RedBlueLoopExecutionConfig:
    enabled: bool = False
    max_rounds: int = 3
    stop_if_no_improvement_rounds: int = 2
    enable_oscillation_detection: bool = True


@dataclass
class RunStoreConfig:
    enabled: bool = False
    db_path: str = "runs/deep_research_runs.sqlite3"


def _load_dotenv_file(path: str = ".env") -> None:
    dotenv_path = Path(path)
    if not dotenv_path.exists() or not dotenv_path.is_file():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _maybe_load_dotenv(load_dotenv: bool) -> None:
    if not load_dotenv:
        return
    dotenv_path = os.getenv("DEEP_RESEARCH_DOTENV_PATH", ".env")
    _load_dotenv_file(dotenv_path)


def _parse_bool_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true"}


def _parse_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        return float(raw_value)
    except ValueError:
        return default


def _parse_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        return max(1, int(raw_value))
    except ValueError:
        return default


def load_llm_config_from_env(load_dotenv: bool = False) -> LLMConfig:
    _maybe_load_dotenv(load_dotenv)
    enabled_raw = os.getenv("DEEP_RESEARCH_USE_LLM", "").strip().lower()
    timeout_seconds = _parse_float_env("DEEP_RESEARCH_LLM_TIMEOUT_SECONDS", 60.0)

    return LLMConfig(
        provider=os.getenv("DEEP_RESEARCH_LLM_PROVIDER", "openai_compatible"),
        model=os.getenv("DEEP_RESEARCH_LLM_MODEL"),
        api_key=os.getenv("DEEP_RESEARCH_LLM_API_KEY"),
        base_url=os.getenv("DEEP_RESEARCH_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        timeout_seconds=timeout_seconds,
        enabled=enabled_raw in {"1", "true"},
    )


def load_search_config_from_env(load_dotenv: bool = False) -> SearchConfig:
    _maybe_load_dotenv(load_dotenv)
    enabled = _parse_bool_env("DEEP_RESEARCH_USE_WEB_SEARCH")
    default_provider = "duckduckgo_html" if enabled else "mock"
    return SearchConfig(
        enabled=enabled,
        provider=os.getenv("DEEP_RESEARCH_SEARCH_PROVIDER", default_provider),
        max_results=_parse_int_env("DEEP_RESEARCH_SEARCH_MAX_RESULTS", 5),
        timeout_seconds=_parse_float_env("DEEP_RESEARCH_SEARCH_TIMEOUT_SECONDS", 15.0),
        user_agent=os.getenv("DEEP_RESEARCH_USER_AGENT", DEFAULT_USER_AGENT),
    )


def load_dag_execution_config_from_env(load_dotenv: bool = False) -> DAGExecutionConfig:
    _maybe_load_dotenv(load_dotenv)
    timeout_raw = os.getenv("DEEP_RESEARCH_DAG_TASK_TIMEOUT_SECONDS", "").strip()
    timeout_seconds = None
    if timeout_raw:
        timeout_seconds = _parse_float_env("DEEP_RESEARCH_DAG_TASK_TIMEOUT_SECONDS", 0.0)
        if timeout_seconds <= 0:
            timeout_seconds = None
    return DAGExecutionConfig(
        use_async=_parse_bool_env("DEEP_RESEARCH_USE_ASYNC_DAG"),
        max_concurrency=_parse_int_env("DEEP_RESEARCH_DAG_MAX_CONCURRENCY", 3),
        task_timeout_seconds=timeout_seconds,
    )


def load_red_blue_loop_config_from_env(load_dotenv: bool = False) -> RedBlueLoopExecutionConfig:
    _maybe_load_dotenv(load_dotenv)
    oscillation_raw = os.getenv("DEEP_RESEARCH_RED_BLUE_OSCILLATION_DETECTION", "true")
    return RedBlueLoopExecutionConfig(
        enabled=_parse_bool_env("DEEP_RESEARCH_USE_RED_BLUE_LOOP"),
        max_rounds=_parse_int_env("DEEP_RESEARCH_RED_BLUE_MAX_ROUNDS", 3),
        stop_if_no_improvement_rounds=_parse_int_env(
            "DEEP_RESEARCH_RED_BLUE_NO_IMPROVEMENT_ROUNDS",
            2,
        ),
        enable_oscillation_detection=oscillation_raw.strip().lower() not in {"0", "false"},
    )


def load_run_store_config_from_env(load_dotenv: bool = False) -> RunStoreConfig:
    _maybe_load_dotenv(load_dotenv)
    return RunStoreConfig(
        enabled=_parse_bool_env("DEEP_RESEARCH_SAVE_RUN"),
        db_path=os.getenv("DEEP_RESEARCH_RUN_STORE_PATH", "runs/deep_research_runs.sqlite3"),
    )
