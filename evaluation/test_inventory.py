"""Classify the unittest suite into reviewable quality layers.

This module discovers tests without executing them, assigns each test class to a
quality layer, and can emit a JSON inventory for README/resume metrics.
"""

from __future__ import annotations

import argparse
import json
import unittest
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


LAYERS: dict[str, dict[str, str]] = {
    "L0_unit_contract": {
        "name": "Unit and deterministic contracts",
        "purpose": "Schemas, memory stores, context compression, local clients, and pure utility behavior.",
    },
    "L1_agent_orchestration": {
        "name": "Agent orchestration and workbench integration",
        "purpose": "DAG execution, planner/searcher/reader/writer collaboration, Red/Blue loops, and browser SSE workbench flows.",
    },
    "L2_eval_quality": {
        "name": "Evaluation science and grounded report quality",
        "purpose": "ResearchBench scoring, baseline/candidate comparison, citation grounding, LLM judge hooks, and statistical tests.",
    },
    "L3_resilience_security": {
        "name": "Resilience, persistence, and security boundaries",
        "purpose": "Checkpoint/resume, persistent run store, safe fetching, provider boundaries, and repository privacy.",
    },
    "L4_live_model_smoke": {
        "name": "Live model smoke",
        "purpose": "Credentialed local checks for the full model-backed report path.",
    },
}


CLASS_LAYER_OVERRIDES = {
    "TestAgentCollaborationLogic": "L1_agent_orchestration",
    "TestAsyncDAGExecutor": "L1_agent_orchestration",
    "TestDAGExecutor": "L1_agent_orchestration",
    "TestDAGReplanner": "L1_agent_orchestration",
    "TestExecutorReplan": "L1_agent_orchestration",
    "TestIterativeRedBlue": "L1_agent_orchestration",
    "TestMinimalPipeline": "L1_agent_orchestration",
    "TestMultiAgentRoles": "L1_agent_orchestration",
    "TestPipelineCollaboration": "L1_agent_orchestration",
    "TestRedBlueConvergence": "L1_agent_orchestration",
    "TestRedBlueReview": "L1_agent_orchestration",
    "TestReportWorkbench": "L1_agent_orchestration",
    "TestSearcherAgentProviderRegistry": "L1_agent_orchestration",
    "TestTaskGraph": "L1_agent_orchestration",
    "TestCitationGrounding": "L2_eval_quality",
    "TestEvalComparison": "L2_eval_quality",
    "TestEvalScoringPlus": "L2_eval_quality",
    "TestEvaluation": "L2_eval_quality",
    "TestLLMJudge": "L2_eval_quality",
    "TestResearchBenchPlus": "L2_eval_quality",
    "TestStatisticalEvaluation": "L2_eval_quality",
    "RepositoryPrivacyTests": "L3_resilience_security",
    "TestCheckpointStore": "L3_resilience_security",
    "TestDAGResume": "L3_resilience_security",
    "TestMainResume": "L3_resilience_security",
    "TestPersistentRunStore": "L3_resilience_security",
    "TestReaderAgentWebFetcher": "L3_resilience_security",
    "TestRuleBasedReplanPolicy": "L3_resilience_security",
    "TestSearchFetchTools": "L3_resilience_security",
    "TestSearchProviders": "L3_resilience_security",
    "TestWebFetchers": "L3_resilience_security",
    "TestLiveReportSmokeEnvironment": "L4_live_model_smoke",
}


def _iter_tests(suite: unittest.TestSuite) -> Iterable[unittest.case.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def _class_name(test_id: str) -> str:
    parts = test_id.split(".")
    if len(parts) < 2:
        return test_id
    return parts[-2]


def classify_test_class(class_name: str) -> str:
    return CLASS_LAYER_OVERRIDES.get(class_name, "L0_unit_contract")


def build_inventory(start_dir: str = "tests") -> dict[str, Any]:
    suite = unittest.defaultTestLoader.discover(start_dir)
    class_counts = Counter(_class_name(test.id()) for test in _iter_tests(suite))
    layers: dict[str, dict[str, Any]] = {
        layer_id: {**definition, "test_count": 0, "class_count": 0, "classes": []}
        for layer_id, definition in LAYERS.items()
    }
    by_layer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for class_name, test_count in sorted(class_counts.items()):
        layer_id = classify_test_class(class_name)
        by_layer[layer_id].append({"class": class_name, "test_count": test_count})
    for layer_id, rows in by_layer.items():
        layers[layer_id]["classes"] = rows
        layers[layer_id]["class_count"] = len(rows)
        layers[layer_id]["test_count"] = sum(row["test_count"] for row in rows)
    return {
        "project": "deep-research-agent",
        "total_tests": sum(class_counts.values()),
        "total_classes": len(class_counts),
        "layers": layers,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    inventory = build_inventory()
    print(f"total_tests: {inventory['total_tests']}")
    for layer_id, layer in inventory["layers"].items():
        print(f"{layer_id}: {layer['test_count']} tests / {layer['class_count']} classes")
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
