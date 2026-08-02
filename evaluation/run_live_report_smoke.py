"""Live local report-generation smoke test for the Deep Research workbench.

The test uses the same OpenAI-compatible environment variables as the browser
workbench, generates a full multi-agent report locally, and writes a sanitized
summary report without secrets or raw provider responses.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow ``python evaluation/run_live_report_smoke.py`` from the repository root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from report_workbench import build_report_workbench_payload


DEFAULT_REPORT = Path("evaluation/results/latest_live_report_smoke.json")
DEFAULT_QUESTION = "How should teams evaluate Agentic Research tools for reliability and evidence quality?"
RELAY_BASE_URL = "https://crs.ruinique.com"
OFFICIAL_OPENAI_BASE_URL = "https://api.openai.com/v1"


def _copy_openai_env_to_deep_research() -> None:
    mappings = {
        "DEEP_RESEARCH_LLM_API_KEY": "OPENAI_API_KEY",
        "DEEP_RESEARCH_LLM_MODEL": "OPENAI_MODEL",
        "DEEP_RESEARCH_LLM_WIRE_API": "OPENAI_WIRE_API",
    }
    for target, source in mappings.items():
        if os.getenv(target):
            continue
        value = os.getenv(source)
        if value:
            os.environ[target] = value

    # This smoke test shares the Clash Royale project's relay contract. A stale
    # machine-level official OpenAI URL must not silently bypass that relay.
    if not os.getenv("DEEP_RESEARCH_LLM_BASE_URL"):
        openai_base_url = os.getenv("OPENAI_BASE_URL", "").rstrip("/")
        if openai_base_url and openai_base_url != OFFICIAL_OPENAI_BASE_URL:
            os.environ["DEEP_RESEARCH_LLM_BASE_URL"] = openai_base_url
        else:
            os.environ["DEEP_RESEARCH_LLM_BASE_URL"] = RELAY_BASE_URL
    os.environ.setdefault("DEEP_RESEARCH_USE_LLM", "1")
    os.environ.setdefault("DEEP_RESEARCH_LLM_WIRE_API", "responses")
    os.environ.setdefault("DEEP_RESEARCH_LLM_DISABLE_RESPONSE_STORAGE", "true")
    os.environ.setdefault("DEEP_RESEARCH_LLM_TIMEOUT_SECONDS", "120")
    # Nine model stages run in one smoke check. Keep the default bounded so the
    # validation completes locally while callers can still raise it explicitly.
    os.environ.setdefault("DEEP_RESEARCH_LLM_MAX_OUTPUT_TOKENS", "500")
    os.environ.setdefault("DEEP_RESEARCH_LLM_REASONING_EFFORT", "medium")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    _copy_openai_env_to_deep_research()
    payload = build_report_workbench_payload(
        args.question,
        use_env_llm=True,
        model_workbench=args.model_workbench,
        red_blue_rounds=args.red_blue_rounds,
    )
    model_run = payload.get("modelRun") or {}
    citation_validation = payload.get("citationValidation") or {}
    final_markdown = str(payload.get("finalReportMarkdown") or "")
    review_rounds = payload.get("reviewRounds") or []
    model_call_count = int(model_run.get("modelCalls") or model_run.get("llmCallCount") or 0)
    fallback_count = int(model_run.get("fallbackCount") or 0)
    model_backed = model_call_count > 0 and model_run.get("mode") == "llm"
    report = {
        "benchmark": "Live local Deep Research report smoke",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "question": args.question,
        "model_workbench": args.model_workbench,
        "summary": {
            "model_backed": model_backed,
            "model_mode": model_run.get("mode"),
            "llm_call_count": model_call_count,
            "fallback_count": fallback_count,
            "final_report_chars": len(final_markdown),
            "review_round_count": len(review_rounds),
            "citation_validation_passed": bool(citation_validation.get("passed")),
            "citation_count": len(citation_validation.get("sources") or []),
            "handoff_count": len(payload.get("executionTrace") or payload.get("handoffs") or []),
        },
    }
    report["passed"] = bool(
        report["summary"]["model_backed"]
        and report["summary"]["llm_call_count"] >= 9
        and report["summary"]["fallback_count"] == 0
        and report["summary"]["final_report_chars"] >= 500
        and report["summary"]["review_round_count"] >= 2
        and report["summary"]["citation_validation_passed"]
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--red-blue-rounds", type=int, default=2)
    parser.add_argument("--model-workbench", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    report = build_report(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"benchmark": report["benchmark"], "passed": report["passed"], **report["summary"]}, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
