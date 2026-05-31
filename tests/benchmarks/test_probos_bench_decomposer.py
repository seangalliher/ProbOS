"""AD-836: ProbOS-Bench v1 — opt-in decomposer benchmark runner.

Runs every case in ``tests/fixtures/eval/decomposer_cases.json`` through a real
``IntentDecomposer`` driven by the deterministic ``MockLLMClient`` (no
live-model call), scores each with ``probos_bench.score_case``, and prints a
single ``PROBOS_BENCH {json}`` score line. Skipped by default; set
``PROBOS_BENCHMARK=1`` to opt in.

The score is intentionally directional, not publishable — same disclaimer as
the AD-716 micro-LoCoMo harness. ``total_tokens`` is ``0`` because the mock
client reports no usage; a live-usage path is out of v1 scope.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.benchmarks.probos_bench import aggregate, load_cases, score_case

pytestmark = pytest.mark.skipif(
    os.environ.get("PROBOS_BENCHMARK") != "1",
    reason="Set PROBOS_BENCHMARK=1 to run the ProbOS-Bench decomposer benchmark",
)

FIXTURE_PATH = (
    Path(__file__).parent.parent / "fixtures" / "eval" / "decomposer_cases.json"
)


@pytest.mark.asyncio
async def test_probos_bench_decomposer_score() -> None:
    from probos.cognitive.decomposer import IntentDecomposer
    from probos.cognitive.llm_client import MockLLMClient
    from probos.cognitive.working_memory import WorkingMemoryManager

    cases = load_cases(FIXTURE_PATH)
    decomposer = IntentDecomposer(
        llm_client=MockLLMClient(),
        working_memory=WorkingMemoryManager(),
    )

    results: list[dict] = []
    total_tokens = 0  # MockLLMClient reports no token usage in v1.
    for case in cases:
        dag = await decomposer.decompose(case["input"])
        produced = [{"intent": n.intent, "params": n.params} for n in dag.nodes]
        results.append(score_case(case, produced))

    scorecard = aggregate(results, total_tokens)
    scorecard["benchmark"] = "probos_bench_decomposer_v1"
    scorecard["n_cases"] = len(cases)
    print("PROBOS_BENCH " + json.dumps(scorecard))

    # Assert the scoreline is well-formed so CI exercises the path even though
    # the benchmark body is opt-in.
    assert scorecard["n_cases"] == len(cases)
    assert 0.0 <= scorecard["resolution_rate"] <= 1.0
    assert 0.0 <= scorecard["intent_precision"] <= 1.0
    assert scorecard["mean_intents"] >= 0.0
    assert scorecard["total_tokens"] >= 0
