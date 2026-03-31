"""Tests for the Structural Integrity Field (AD-370)."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter
from probos.sif import SIFCheckResult, SIFReport, StructuralIntegrityField
from probos.substrate.pool import ResourcePool
from probos.substrate.spawner import AgentSpawner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trust_network(scores: dict[str, float]) -> MagicMock:
    tn = MagicMock(spec=TrustNetwork)
    tn.all_scores.return_value = scores
    return tn


def _make_hebbian_router(weights: dict) -> MagicMock:
    hr = MagicMock(spec=HebbianRouter)
    hr._weights = weights
    return hr


def _make_spawner(templates: list[str], registered_ids: set[str] | None = None) -> MagicMock:
    sp = MagicMock(spec=AgentSpawner)
    sp.available_templates = templates
    sp.registry = MagicMock()  # BF-079: instance attr — must set explicitly
    if registered_ids is not None:
        agent_mocks = [MagicMock(id=aid) for aid in registered_ids]
        sp.registry.all.return_value = agent_mocks
    else:
        sp.registry.all.return_value = []
    return sp


def _make_pool(agent_type: str) -> MagicMock:
    pool = MagicMock(spec=ResourcePool)
    pool.agent_type = agent_type
    return pool


# ---------------------------------------------------------------------------
# Trust bounds
# ---------------------------------------------------------------------------


class TestTrustBounds:
    def test_trust_bounds_nan(self) -> None:
        sif = StructuralIntegrityField(
            trust_network=_make_trust_network({"agent_a": float("nan")}),
        )
        result = sif.check_trust_bounds()
        assert not result.passed
        assert "not finite" in result.details

    def test_trust_bounds_out_of_range(self) -> None:
        sif = StructuralIntegrityField(
            trust_network=_make_trust_network({"agent_a": 1.5}),
        )
        result = sif.check_trust_bounds()
        assert not result.passed
        assert "out of range" in result.details

    def test_trust_bounds_pass(self) -> None:
        sif = StructuralIntegrityField(
            trust_network=_make_trust_network({"a": 0.5, "b": 0.0, "c": 1.0}),
        )
        result = sif.check_trust_bounds()
        assert result.passed


# ---------------------------------------------------------------------------
# Hebbian bounds
# ---------------------------------------------------------------------------


class TestHebbianBounds:
    def test_hebbian_bounds_explosion(self) -> None:
        sif = StructuralIntegrityField(
            hebbian_router=_make_hebbian_router(
                {("a", "b", "intent"): 15.0}
            ),
        )
        result = sif.check_hebbian_bounds()
        assert not result.passed
        assert "out of range" in result.details

    def test_hebbian_bounds_nan(self) -> None:
        sif = StructuralIntegrityField(
            hebbian_router=_make_hebbian_router(
                {("a", "b", "intent"): float("nan")}
            ),
        )
        result = sif.check_hebbian_bounds()
        assert not result.passed
        assert "not finite" in result.details

    def test_hebbian_bounds_pass(self) -> None:
        sif = StructuralIntegrityField(
            hebbian_router=_make_hebbian_router(
                {("a", "b", "intent"): 0.5, ("c", "d", "agent"): -2.0}
            ),
        )
        result = sif.check_hebbian_bounds()
        assert result.passed


# ---------------------------------------------------------------------------
# Pool consistency
# ---------------------------------------------------------------------------


class TestPoolConsistency:
    def test_pool_consistency_orphan(self) -> None:
        sif = StructuralIntegrityField(
            spawner=_make_spawner(["file_reader", "shell_command"]),
            pool_manager={
                "search": _make_pool("file_search"),  # not in templates
            },
        )
        result = sif.check_pool_consistency()
        assert not result.passed
        assert "file_search" in result.details

    def test_pool_consistency_pass(self) -> None:
        sif = StructuralIntegrityField(
            spawner=_make_spawner(["file_reader", "shell_command"]),
            pool_manager={
                "readers": _make_pool("file_reader"),
                "shell": _make_pool("shell_command"),
            },
        )
        result = sif.check_pool_consistency()
        assert result.passed


# ---------------------------------------------------------------------------
# Aggregate / report
# ---------------------------------------------------------------------------


class TestRunAllChecks:
    @pytest.mark.asyncio
    async def test_run_all_checks_health_pct(self) -> None:
        """Mix of pass/fail gives correct health_pct."""
        sif = StructuralIntegrityField(
            trust_network=_make_trust_network({"a": float("nan")}),  # will fail
            # others None → pass
        )
        report = await sif.run_all_checks()
        # 1 failing out of 7 checks → ~85.7%
        assert report.health_pct == pytest.approx(6 / 7 * 100, abs=0.1)
        assert not report.all_passed

    @pytest.mark.asyncio
    async def test_run_all_checks_all_none(self) -> None:
        """All subsystems None → 100% health (graceful degradation)."""
        sif = StructuralIntegrityField()
        report = await sif.run_all_checks()
        assert report.health_pct == 100.0
        assert report.all_passed
        assert len(report.checks) == 7

    def test_violations_property(self) -> None:
        """violations returns only failed checks."""
        report = SIFReport(
            checks=[
                SIFCheckResult(name="a", passed=True),
                SIFCheckResult(name="b", passed=False, details="bad"),
                SIFCheckResult(name="c", passed=True),
                SIFCheckResult(name="d", passed=False, details="also bad"),
            ],
            timestamp=0.0,
        )
        violations = report.violations
        assert len(violations) == 2
        assert violations[0].name == "b"
        assert violations[1].name == "d"


class TestConfigValidity:
    def test_config_validity_pass(self) -> None:
        """Config check passes when no config ref is held."""
        sif = StructuralIntegrityField()
        result = sif.check_config_validity()
        assert result.passed
