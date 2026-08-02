# Quality Evaluation Strategy

This project separates normal software regression, agent workflow regression, and model-backed report quality into explicit layers.

## Methodology

- Test pyramid and size discipline: most tests should be fast and deterministic, with browser/workbench and live-model checks kept narrower. See [Martin Fowler's Test Pyramid](https://martinfowler.com/bliki/TestPyramid.html) and [Google's small/medium/large test sizes](https://testing.googleblog.com/2010/12/test-sizes.html).
- AI TEVV: treat evaluation as an evidence trail: test, evaluate, verify, validate, and keep monitoring as the system changes. See [NIST AI TEVV](https://www.nist.gov/ai-test-evaluation-validation-and-verification-tevv).
- LLM application evals: keep datasets versioned, compare baseline/candidate runs on the same cases, and use evaluator functions or LLM-as-judge only where rule checks cannot capture quality. See [OpenAI Evals](https://github.com/openai/evals) and [LangSmith evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts?mode=ui).
- Grounded generation: separate evidence retrieval, citation validity, answer structure, and final report quality; this mirrors faithfulness/context-recall style RAG evaluation. See the [Ragas metric catalog](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/).

## Current Layers

Run: `python -m evaluation.test_inventory --report evaluation/results/latest_test_inventory.json`

Current inventory after adding the layer report:

| Layer | Purpose | Tests |
|---|---|---:|
| L0 unit/contract | Schema, memory stores, context compression, local clients, pure utilities | 74 |
| L1 agent orchestration | DAG execution, multi-agent collaboration, Red/Blue loops, workbench SSE | 129 |
| L2 evaluation quality | ResearchBench scoring, baseline/candidate comparison, citation grounding, LLM judge hooks, statistical tests | 62 |
| L3 resilience/security | Checkpoint/resume, persistent run store, safe fetching, provider boundaries, repository privacy | 62 |
| L4 live model smoke | Credentialed local model-backed report smoke | 6 |

The public inventory discovers `333` tests.

## Quantitative Gates

- ResearchBench-mini Plus regression: 20 cases, baseline composite `0.9625`, candidate composite `0.9625`, failed cases `0`; this is a no-regression gate, not an improvement claim.
- Statistical comparison tooling: paired bootstrap delta CI and paired Cohen's d_z are implemented and tested for baseline/candidate comparisons.
- Live model smoke: 9 model calls, 0 fallbacks, 2 Red/Blue review rounds, 18 handoffs, 4 citations, citation validation passed, 2,175-character final report.
- Security/resilience coverage: safe HTTP rejects local/private/reserved addresses and redirects; checkpoint/resume and SQLite run-store tests cover interrupted runs.

## Resume-Safe Wording

Built a layered evaluation system with 333 discovered tests across unit, orchestration, evaluation-quality, resilience/security, and live-smoke layers; ResearchBench-mini Plus held 20-case baseline/candidate regression at 0.9625 composite with 0 failed cases, and the live model smoke completed 9 calls, 0 fallbacks, 2 review rounds, and passed citation validation.
