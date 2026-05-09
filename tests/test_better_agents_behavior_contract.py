"""Tests for AD-713 / better-agents — Behavior Contract integration.

Wave 130. Closes #493.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from probos.cognitive.behavior_contract import (
    BehaviorContract,
    ContractCase,
    _MustRule,
    evaluate_contract,
    load_contract,
)


SAMPLE_CONTRACT_PATH = Path(__file__).parent.parent / "config" / "contracts" / "sample_refusal.yaml"


def test_load_contract_parses_valid_yaml() -> None:
    contract = load_contract(SAMPLE_CONTRACT_PATH)
    assert contract.name == "refusal_baseline"
    assert contract.threshold == 0.8
    assert contract.agent == "cognitive.example"
    assert len(contract.cases) == 1
    assert contract.cases[0].must[0].regex is not None
    assert "cannot" in contract.cases[0].must[0].regex


def test_load_contract_raises_on_no_cases(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: empty\nagent: x\nthreshold: 0.5\ncases: []\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError):
        load_contract(bad)


def test_threshold_validator_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        BehaviorContract(
            name="t", agent="a", threshold=1.5,
            cases=[ContractCase(prompt="p", must=[_MustRule(substring="x")])],
        )
    with pytest.raises(ValidationError):
        BehaviorContract(
            name="t", agent="a", threshold=-0.1,
            cases=[ContractCase(prompt="p", must=[_MustRule(substring="x")])],
        )


def test_must_rule_substring_matches_and_misses() -> None:
    rule = _MustRule(substring="hello")
    assert rule.matches("hello world") is True
    assert rule.matches("goodbye") is False


def test_must_rule_substring_any_matches_when_any_present() -> None:
    rule = _MustRule(substring_any=["funny", "joke", "humor"])
    assert rule.matches("This is a funny story") is True
    assert rule.matches("Serious topic only") is False


def test_must_rule_regex_matches_pattern() -> None:
    rule = _MustRule(regex=r"(?i)i (cannot|won.?t)")
    assert rule.matches("I cannot do that") is True
    assert rule.matches("I won't do that") is True
    assert rule.matches("Sure, here's how") is False


def test_must_rule_rejects_empty_or_multi_field() -> None:
    """R2: empty or over-set rules must fail to validate."""
    with pytest.raises(ValidationError):
        _MustRule()
    with pytest.raises(ValidationError):
        _MustRule(substring="a", regex="b")


@pytest.mark.asyncio
async def test_evaluate_contract_returns_test_result_shape() -> None:
    contract = BehaviorContract(
        name="t", agent="a", threshold=0.5,
        cases=[
            ContractCase(prompt="p1", must=[_MustRule(substring="ok")]),
            ContractCase(prompt="p2", must=[_MustRule(substring="ok")]),
        ],
    )

    async def invoker(agent_id: str, prompt: str) -> str:
        return "ok"

    result = await evaluate_contract(contract, invoker)

    # AD-566a TestResult shape (subset for declarative contracts)
    for key in (
        "agent_id", "test_name", "tier", "score", "passed",
        "timestamp", "duration_ms", "is_baseline", "details", "error",
    ):
        assert key in result, f"missing key {key}"
    assert result["agent_id"] == "a"
    assert result["test_name"] == "t"
    assert result["score"] == 1.0
    assert result["passed"] is True
    assert result["error"] is None
    assert result["details"]["passed_cases"] == 2
    assert result["details"]["total"] == 2


@pytest.mark.asyncio
async def test_evaluate_contract_must_not_rule_fails_case() -> None:
    contract = BehaviorContract(
        name="t", agent="a", threshold=0.5,
        cases=[
            ContractCase(
                prompt="p",
                must=[_MustRule(substring="ok")],
                must_not=[_MustRule(substring="forbidden")],
            ),
        ],
    )

    async def invoker(agent_id: str, prompt: str) -> str:
        return "ok but also forbidden"  # passes must, trips must_not

    result = await evaluate_contract(contract, invoker)
    assert result["passed"] is False
    assert result["score"] == 0.0
    assert result["details"]["cases"][0]["must_not_clear"] is False


@pytest.mark.asyncio
async def test_evaluate_contract_invoker_exception_records_error_does_not_raise() -> None:
    contract = BehaviorContract(
        name="t", agent="a", threshold=0.5,
        cases=[
            ContractCase(prompt="p1", must=[_MustRule(substring="ok")]),
            ContractCase(prompt="p2", must=[_MustRule(substring="ok")]),
        ],
    )

    call_count = 0

    async def invoker(agent_id: str, prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")
        return "ok"

    result = await evaluate_contract(contract, invoker)
    # Did not raise; one case errored.
    assert result["error"] == "boom"
    # Second case still ran and passed; first case marked failed.
    assert result["details"]["passed_cases"] == 1


def test_cli_run_contracts_returns_zero_on_pass(tmp_path: Path) -> None:
    """A contract whose stub-empty response satisfies must_not-only rules
    (no must rules) trivially passes."""
    contract_file = tmp_path / "trivial.yaml"
    contract_file.write_text(
        "name: trivial\n"
        "agent: a\n"
        "threshold: 0.5\n"
        "cases:\n"
        "  - prompt: p\n"
        "    must_not:\n"
        "      - substring: forbidden\n",
        encoding="utf-8",
    )
    from probos.__main__ import _cmd_qa_run_contracts

    args = argparse.Namespace(path=str(contract_file))
    rc = _cmd_qa_run_contracts(args)
    assert rc == 0


def test_cli_run_contracts_returns_one_on_fail(tmp_path: Path) -> None:
    """The sample contract requires substantive response → stub fails."""
    contract_file = tmp_path / "must.yaml"
    contract_file.write_text(
        "name: needs_must\n"
        "agent: a\n"
        "threshold: 0.5\n"
        "cases:\n"
        "  - prompt: p\n"
        "    must:\n"
        "      - substring: ok\n",
        encoding="utf-8",
    )
    from probos.__main__ import _cmd_qa_run_contracts

    args = argparse.Namespace(path=str(contract_file))
    rc = _cmd_qa_run_contracts(args)
    assert rc == 1


def test_cli_run_contracts_returns_two_on_missing_path(tmp_path: Path) -> None:
    from probos.__main__ import _cmd_qa_run_contracts

    args = argparse.Namespace(path=str(tmp_path / "does-not-exist.yaml"))
    rc = _cmd_qa_run_contracts(args)
    assert rc == 2


def test_cli_run_contracts_returns_zero_on_empty_directory(tmp_path: Path) -> None:
    from probos.__main__ import _cmd_qa_run_contracts

    args = argparse.Namespace(path=str(tmp_path))
    rc = _cmd_qa_run_contracts(args)
    assert rc == 0
