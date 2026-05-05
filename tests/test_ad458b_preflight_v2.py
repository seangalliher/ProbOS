"""AD-458b: Tests for LLMTierReachableCheck + TokenBudgetCheck."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.pre_flight import (
    LLMTierReachableCheck,
    PreFlightResult,
    TokenBudgetCheck,
)
from probos.config import PreFlightConfig


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class _FakeBuildSpec:
    def __init__(self, title: str = "test build", target_files: list[str] | None = None) -> None:
        self.title = title
        self.target_files = list(target_files or [])


def _make_runtime_with_llm(health: Any) -> SimpleNamespace:
    client = MagicMock()
    client.get_health_status = MagicMock(return_value=health)
    return SimpleNamespace(llm_client=client)


def _make_runtime_with_eps(exceeded: list[str]) -> SimpleNamespace:
    eps = MagicMock()
    eps.check_budgets = AsyncMock(return_value=exceeded)
    return SimpleNamespace(eps_coordinator=eps)


# ---------------------------------------------------------------------------
# Test 1 — PreFlightConfig defaults include AD-458b fields
# ---------------------------------------------------------------------------


def test_pre_flight_config_defaults_includes_new_fields() -> None:
    cfg = PreFlightConfig()
    assert cfg.enabled is True
    assert cfg.llm_tier_check_enabled is True
    assert cfg.required_llm_tier == "deep"
    assert cfg.token_budget_check_enabled is True
    assert cfg.token_budget_blocking is False


# ---------------------------------------------------------------------------
# Tests 2-6 — LLMTierReachableCheck
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_tier_reachable_passes_when_tier_operational() -> None:
    runtime = _make_runtime_with_llm({
        "tiers": {"deep": {"status": "operational"}},
        "overall": "operational",
    })
    check = LLMTierReachableCheck(runtime=runtime)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is True
    assert result.check_name == "llm_tier_reachable"
    assert "operational" in result.detail


@pytest.mark.asyncio
async def test_llm_tier_reachable_fails_when_tier_unreachable() -> None:
    runtime = _make_runtime_with_llm({
        "tiers": {"deep": {"status": "unreachable"}},
        "overall": "degraded",
    })
    check = LLMTierReachableCheck(runtime=runtime)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is False
    assert result.blocking is True
    assert result.detail == "tier 'deep' status: unreachable"


@pytest.mark.asyncio
async def test_llm_tier_reachable_skips_when_no_runtime_client() -> None:
    runtime = SimpleNamespace()  # no llm_client attribute
    check = LLMTierReachableCheck(runtime=runtime)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is True
    assert "no llm_client" in result.detail
    assert "skipped" in result.detail


@pytest.mark.asyncio
async def test_llm_tier_reachable_uses_required_tier_from_constructor() -> None:
    runtime = _make_runtime_with_llm({
        "tiers": {
            "fast": {"status": "operational"},
            "deep": {"status": "unreachable"},
        },
        "overall": "degraded",
    })
    check = LLMTierReachableCheck(runtime=runtime, required_tier="fast")
    result = await check.check(_FakeBuildSpec())
    assert result.passed is True
    assert "fast" in result.detail


@pytest.mark.asyncio
async def test_llm_tier_reachable_handles_unexpected_health_shape() -> None:
    """Defensive isinstance(dict) guards tolerate stub clients returning None
    or a non-dict from get_health_status()."""
    runtime = _make_runtime_with_llm(None)  # stub returns None
    check = LLMTierReachableCheck(runtime=runtime)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is False
    assert "unknown" in result.detail


@pytest.mark.asyncio
async def test_llm_tier_reachable_propagates_exception_to_runner() -> None:
    """When client.get_health_status() raises, the exception propagates UP
    to the PreFlightRunner exception envelope (not caught inside check())."""
    client = MagicMock()
    client.get_health_status = MagicMock(side_effect=RuntimeError("boom"))
    runtime = SimpleNamespace(llm_client=client)
    check = LLMTierReachableCheck(runtime=runtime)
    with pytest.raises(RuntimeError):
        await check.check(_FakeBuildSpec())


# ---------------------------------------------------------------------------
# Tests 7-10 — TokenBudgetCheck
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_budget_passes_when_no_eps_coordinator() -> None:
    runtime = SimpleNamespace()  # no eps_coordinator attribute
    check = TokenBudgetCheck(runtime=runtime)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is True
    assert "no eps_coordinator" in result.detail
    assert "skipped" in result.detail


@pytest.mark.asyncio
async def test_token_budget_passes_when_check_budgets_empty() -> None:
    """AD-469 v1 contract: check_budgets() returns []. Today's pass case."""
    runtime = _make_runtime_with_eps(exceeded=[])
    check = TokenBudgetCheck(runtime=runtime)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is True
    assert "within budget" in result.detail


@pytest.mark.asyncio
async def test_token_budget_warns_when_budgets_exceeded_default_non_blocking() -> None:
    """AD-469b activation simulation: check_budgets() returns department names.
    Default blocking=False — warning, not abort."""
    runtime = _make_runtime_with_eps(exceeded=["medical", "engineering"])
    check = TokenBudgetCheck(runtime=runtime)  # default blocking=False
    result = await check.check(_FakeBuildSpec())
    assert result.passed is False
    assert result.blocking is False  # warning, not abort
    assert "budgets exceeded" in result.detail
    assert "medical" in result.detail
    assert "engineering" in result.detail


@pytest.mark.asyncio
async def test_token_budget_blocking_flag_makes_failure_blocking() -> None:
    """Operator-tunable: PreFlightConfig.token_budget_blocking=True flips
    the failure to blocking via the constructor `blocking=True`."""
    runtime = _make_runtime_with_eps(exceeded=["science"])
    check = TokenBudgetCheck(runtime=runtime, blocking=True)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is False
    assert result.blocking is True
    assert "science" in result.detail


# ---------------------------------------------------------------------------
# Tests 11-12 — Protocol compliance + integrated runner ordering
# ---------------------------------------------------------------------------


def test_new_checks_satisfy_pre_flight_check_protocol() -> None:
    """Mirrors the AD-458 v1 Protocol-compliance test for the two new checks.

    `PreFlightCheck` is `@runtime_checkable` so concrete implementations
    must satisfy `isinstance(impl, PreFlightCheck)` via duck typing —
    they need `name: str` and `async def check(self, spec) -> PreFlightResult`.
    """
    from probos.cognitive.pre_flight import PreFlightCheck

    runtime = SimpleNamespace()
    llm_check = LLMTierReachableCheck(runtime=runtime)
    tok_check = TokenBudgetCheck(runtime=runtime)
    assert isinstance(llm_check, PreFlightCheck)
    assert isinstance(tok_check, PreFlightCheck)
    assert llm_check.name == "llm_tier_reachable"
    assert tok_check.name == "token_budget"


@pytest.mark.asyncio
async def test_runner_with_all_four_checks_runs_in_expected_order(tmp_path: Path) -> None:
    """End-to-end PreFlightRunner integration: assemble the 4 checks in the
    order finalize.py would produce them, run on a passing spec, assert
    every check fired and the aggregate report.passed is True."""
    from probos.cognitive.pre_flight import (
        PreFlightRunner,
        TargetFilesExistCheck,
        TargetFilesWritableCheck,
    )

    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")

    runtime = SimpleNamespace(
        llm_client=MagicMock(get_health_status=MagicMock(return_value={
            "tiers": {"deep": {"status": "operational"}},
            "overall": "operational",
        })),
        eps_coordinator=MagicMock(check_budgets=AsyncMock(return_value=[])),
    )
    runner = PreFlightRunner(checks=[
        TargetFilesExistCheck(repo_root=tmp_path),
        TargetFilesWritableCheck(repo_root=tmp_path),
        LLMTierReachableCheck(runtime=runtime),
        TokenBudgetCheck(runtime=runtime),
    ])
    spec = _FakeBuildSpec(target_files=["a.py"])
    report = await runner.run(spec)

    assert report.passed is True
    assert len(report.results) == 4
    assert [r.check_name for r in report.results] == [
        "target_files_exist",
        "target_files_writable",
        "llm_tier_reachable",
        "token_budget",
    ]
    assert all(r.passed for r in report.results)
