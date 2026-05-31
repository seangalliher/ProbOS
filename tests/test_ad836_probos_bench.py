"""AD-836: always-on self-tests for the ProbOS-Bench v1 scorer.

These guardrails exercise the pure scoring functions in
``tests/benchmarks/probos_bench.py`` and run in the normal gate (they are NOT
under ``tests/benchmarks/``, so no opt-in env var is required). The opt-in
decomposer runner that drives a real ``IntentDecomposer`` lives in
``tests/benchmarks/test_probos_bench_decomposer.py``.
"""

from __future__ import annotations

from tests.benchmarks.probos_bench import aggregate, score_case


def test_score_case_exact_match_happy_path() -> None:
    case = {
        "id": "simple_read",
        "input": "Read the file src/probos/types.py",
        "expected_intents": [
            {"intent": "read_file", "params": {"path": "src/probos/types.py"}}
        ],
    }
    produced = [{"intent": "read_file", "params": {"path": "src/probos/types.py"}}]

    result = score_case(case, produced)

    assert result["resolved"] is True
    assert result["precision"] == 1.0
    assert result["n_intents"] == 1


def test_score_case_min_intents_satisfied_and_unsatisfied() -> None:
    case = {"id": "ambiguous_refactor", "input": "refactor it", "min_intents": 2}

    satisfied = score_case(
        case, [{"intent": "read_file"}, {"intent": "edit_file"}]
    )
    assert satisfied["resolved"] is True
    assert satisfied["precision"] == 1.0
    assert satisfied["n_intents"] == 2

    unsatisfied = score_case(case, [{"intent": "read_file"}])
    assert unsatisfied["resolved"] is False
    assert unsatisfied["precision"] == 0.0
    assert unsatisfied["n_intents"] == 1


def test_score_case_conversational_empty_and_nonempty_produced() -> None:
    # Conversational case: expected_intents == [] means "produce no intents".
    case = {"id": "greeting", "input": "hi", "expected_intents": []}

    correct = score_case(case, [])
    assert correct["resolved"] is True
    assert correct["precision"] == 1.0
    assert correct["n_intents"] == 0

    wrong = score_case(case, [{"intent": "read_file"}])
    assert wrong["resolved"] is False
    assert wrong["precision"] == 0.0
    assert wrong["n_intents"] == 1

    # Missing expected_intents key behaves like a conversational case.
    missing_key = score_case({"id": "x", "input": "hi"}, [])
    assert missing_key["resolved"] is True
    assert missing_key["precision"] == 1.0


def test_score_case_empty_produced_exact_match_edge() -> None:
    case = {
        "id": "simple_read",
        "input": "Read the file foo.py",
        "expected_intents": [{"intent": "read_file"}],
    }

    result = score_case(case, [])

    assert result["resolved"] is False
    assert result["precision"] == 0.0
    assert result["n_intents"] == 0


def test_aggregate_mixed_results() -> None:
    results = [
        {"resolved": True, "precision": 1.0, "n_intents": 1},
        {"resolved": False, "precision": 0.0, "n_intents": 2},
        {"resolved": True, "precision": 0.5, "n_intents": 3},
    ]

    scorecard = aggregate(results, total_tokens=0)

    assert scorecard["resolution_rate"] == 2 / 3
    assert scorecard["intent_precision"] == 0.5
    assert scorecard["mean_intents"] == 2.0
    assert scorecard["total_tokens"] == 0

    # Empty result list yields zeroed rates (boundary).
    empty = aggregate([], total_tokens=0)
    assert empty["resolution_rate"] == 0.0
    assert empty["intent_precision"] == 0.0
    assert empty["mean_intents"] == 0.0
