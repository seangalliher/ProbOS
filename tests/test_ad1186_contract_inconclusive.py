"""AD-1186 (#1123) slice 1: an AD-713 contract run that measured nothing is inconclusive (BF-711).

A case whose invoker raised measured nothing, so the contract neither passes nor fails, and the
result carries AD-566a's ``TestResult`` fields exactly. ``probos qa run-contracts`` exits 3 for not
measured; 0 and 1 stay a measured pass and a measured failure (or a file that does not load).
"""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive import behavior_contract, qualification
from probos.cognitive.behavior_contract import (
    BehaviorContract,
    ContractCase,
    _MustRule,
    evaluate_contract,
)

_MUST_CONTRACT_YAML = (
    "name: needs_must\n"
    "agent: a\n"
    "threshold: 0.5\n"
    "cases:\n"
    "  - prompt: p\n"
    "    must:\n"
    "      - substring: ok\n"
)


def _contract() -> BehaviorContract:
    return BehaviorContract(
        name="t",
        agent="a",
        threshold=0.5,
        cases=[
            ContractCase(prompt="p1", must=[_MustRule(substring="ok")]),
            ContractCase(prompt="p2", must=[_MustRule(substring="ok")]),
        ],
    )


def _run_cli(path: Path) -> int:
    from probos.__main__ import _cmd_qa_run_contracts

    return _cmd_qa_run_contracts(argparse.Namespace(path=str(path)))


async def test_an_invoker_exception_makes_the_contract_inconclusive_and_not_passed() -> None:
    calls = 0

    async def invoker(agent_id: str, prompt: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("proxy down")
        return "ok"

    result = await evaluate_contract(_contract(), invoker)
    # The measured case passed, so the score (0.5) meets the threshold: before AD-1186 this read as a pass.
    assert result["score"] == 0.5
    assert result["inconclusive"] is True
    assert result["passed"] is False
    assert result["error"] == "proxy down"


async def test_a_measured_pass_and_a_measured_failure_are_not_inconclusive() -> None:
    async def agrees(agent_id: str, prompt: str) -> str:
        return "ok"

    async def disagrees(agent_id: str, prompt: str) -> str:
        return "no"

    passed = await evaluate_contract(_contract(), agrees)
    failed = await evaluate_contract(_contract(), disagrees)
    assert (passed["passed"], passed["inconclusive"]) == (True, False)
    assert (failed["passed"], failed["inconclusive"]) == (False, False)


async def test_the_result_is_a_qualification_test_result_and_round_trips_the_store(tmp_path: Path) -> None:
    async def unreachable(agent_id: str, prompt: str) -> str:
        raise RuntimeError("proxy down")

    result = await evaluate_contract(_contract(), unreachable)
    assert set(result) == {item.name for item in dataclasses.fields(qualification.TestResult)}
    store = qualification.QualificationStore(data_dir=tmp_path)
    await store.start()
    try:
        await store.save_result(qualification.TestResult(**result))
        stored = await store.get_latest("a", "t")
    finally:
        await store.stop()
    assert stored is not None
    assert stored.inconclusive is True
    assert stored.passed is False
    assert stored.error == "proxy down"


def test_the_cli_exits_one_when_a_file_fails_to_load_beside_an_unmeasured_contract(tmp_path: Path) -> None:
    (tmp_path / "a_measurable.yaml").write_text(_MUST_CONTRACT_YAML, encoding="utf-8")
    (tmp_path / "b_broken.yaml").write_text("name: no_agent_no_cases\n", encoding="utf-8")
    # A file that does not load is a failure; the unmeasured contract beside it does not mask it.
    assert _run_cli(tmp_path) == 1


@pytest.mark.parametrize(
    ("passed", "expected"),
    [(True, 0), (False, 1)],
    ids=["measured-pass", "measured-fail"],
)
def test_the_cli_maps_measured_verdicts_to_zero_and_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, passed: bool, expected: int
) -> None:
    """The stub cannot measure anything, so the evaluator is replaced here: this pins the exit
    codes of a measured pass and a measured failure."""
    (tmp_path / "c.yaml").write_text(_MUST_CONTRACT_YAML, encoding="utf-8")

    async def measured(contract: Any, invoke_agent: Any) -> dict[str, Any]:
        return {"score": 1.0 if passed else 0.0, "passed": passed, "inconclusive": False}

    monkeypatch.setattr(behavior_contract, "evaluate_contract", measured)
    assert _run_cli(tmp_path) == expected
