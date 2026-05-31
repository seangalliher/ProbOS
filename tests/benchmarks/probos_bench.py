"""AD-836: ProbOS-Bench v1 — offline agent-behavior scoring.

Pure scoring functions for the opt-in decomposer benchmark. No I/O at import
and no production-code imports here; the runner
(``test_probos_bench_decomposer.py``) wires these against a real
``IntentDecomposer`` driven by the deterministic mock LLM client.

Directional, not publishable — same disclaimer as the AD-716 micro-LoCoMo
harness. The benchmark gives ``AgenticLoop``/decomposer changes an aggregate
behavioral score (resolution_rate, intent_precision, mean_intents,
total_tokens) before they ship, mirroring the VS Code harness's VSC-Bench.

Full agent-trajectory (tool-call) scoring is deferred to AD-836b via a
``score_trajectory(AgenticResult)`` function mirroring ``score_case``.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_cases(path: Path) -> list[dict]:
    """Load a JSON list of eval cases from ``path``.

    Each case is a dict with at least ``id`` and ``input``; expectations are
    expressed as ``expected_intents`` (list) and/or ``min_intents`` (int).
    """
    return json.loads(path.read_text(encoding="utf-8"))


def score_case(case: dict, produced_intents: list[dict]) -> dict:
    """Score one case's produced intents against its expectation.

    Honors three case shapes:

    - ``min_intents`` given (effort floor): ``resolved`` iff
      ``len(produced) >= min_intents``. ``precision`` is ``1.0`` when resolved
      (no per-intent expected set exists to score against), else ``0.0``.
    - ``expected_intents`` given and non-empty: every expected intent name must
      appear among the produced intent names → ``resolved``. ``precision`` is
      the fraction of produced intents whose names are in the expected set
      (``0.0`` when nothing was produced).
    - conversational (``expected_intents`` absent or ``[]``): ``resolved`` iff
      no intents were produced. ``precision`` is ``1.0`` when nothing was
      produced (no false positives), else ``0.0``.

    Returns ``{"resolved": bool, "precision": float, "n_intents": int}``.
    """
    n_intents = len(produced_intents)
    produced_names = [str(i.get("intent", "")) for i in produced_intents]

    if "min_intents" in case:
        min_intents = int(case["min_intents"])
        resolved = n_intents >= min_intents
        return {
            "resolved": resolved,
            "precision": 1.0 if resolved else 0.0,
            "n_intents": n_intents,
        }

    expected = case.get("expected_intents", [])
    expected_names = {str(e.get("intent", "")) for e in expected}

    if not expected_names:
        # Conversational: the correct answer is to produce no task intents.
        return {
            "resolved": n_intents == 0,
            "precision": 1.0 if n_intents == 0 else 0.0,
            "n_intents": n_intents,
        }

    resolved = all(name in produced_names for name in expected_names)
    if n_intents == 0:
        precision = 0.0
    else:
        hits = sum(1 for name in produced_names if name in expected_names)
        precision = hits / n_intents
    return {"resolved": resolved, "precision": precision, "n_intents": n_intents}


def aggregate(results: list[dict], total_tokens: int) -> dict:
    """Aggregate per-case score dicts into the v1 metric scorecard.

    Returns ``resolution_rate`` (fraction resolved), ``intent_precision`` (mean
    per-case precision), ``mean_intents`` (agent-effort proxy), and
    ``total_tokens`` (token-efficiency proxy; ``0`` when the mock client
    reports none). An empty ``results`` list yields zeroed rates.
    """
    n = len(results)
    if n == 0:
        return {
            "resolution_rate": 0.0,
            "intent_precision": 0.0,
            "mean_intents": 0.0,
            "total_tokens": total_tokens,
        }
    resolution_rate = sum(1 for r in results if r["resolved"]) / n
    intent_precision = sum(r["precision"] for r in results) / n
    mean_intents = sum(r["n_intents"] for r in results) / n
    return {
        "resolution_rate": resolution_rate,
        "intent_precision": intent_precision,
        "mean_intents": mean_intents,
        "total_tokens": total_tokens,
    }
