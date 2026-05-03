"""AD-469 EPS Compute/Token Distribution tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.eps import (
    CapacitySummary,
    CapacityTracker,
    DepartmentBudget,
    DepartmentBudgetTable,
    EPSCoordinator,
    EPSReport,
)
from probos.config import EPSConfig
from probos.events import EventType


# ----- EventTypes -----


def test_event_type_eps_budget_exceeded_exists():
    assert EventType.EPS_BUDGET_EXCEEDED.value == "eps_budget_exceeded"


def test_event_type_eps_reallocation_exists():
    assert EventType.EPS_REALLOCATION.value == "eps_reallocation"


# ----- Config -----


def test_eps_config_defaults():
    cfg = EPSConfig()
    assert cfg.enabled is True
    assert cfg.window_seconds == 60.0
    assert cfg.over_budget_threshold == 1.25
    assert len(cfg.departments) == 6
    names = {d.name for d in cfg.departments}
    assert names == {"engineering", "science", "medical", "security", "operations", "other"}


# ----- CapacityTracker -----


@pytest.mark.asyncio
async def test_capacity_tracker_no_runtime_returns_empty():
    tracker = CapacityTracker(runtime=None)
    snap = await tracker.summary()
    assert isinstance(snap, CapacitySummary)
    assert snap.total_tokens == 0
    assert snap.by_agent == {}


@pytest.mark.asyncio
async def test_capacity_tracker_no_journal_returns_empty():
    rt = SimpleNamespace()  # no cognitive_journal attribute
    tracker = CapacityTracker(runtime=rt)
    snap = await tracker.summary()
    assert snap.total_tokens == 0


@pytest.mark.asyncio
async def test_capacity_tracker_aggregates_by_agent_tier_model():
    fake_journal = SimpleNamespace()
    fake_journal.get_token_usage_by = AsyncMock()

    def _by(group_by: str = "model", agent_id=None):
        return {
            "agent_id": [
                {"agent_id": "a1", "total_tokens": 100, "total_calls": 5},
                {"agent_id": "a2", "total_tokens": 200, "total_calls": 3},
            ],
            "tier": [
                {"tier": "fast", "total_tokens": 250, "total_calls": 6},
                {"tier": "deep", "total_tokens": 50, "total_calls": 2},
            ],
            "model": [
                {"model": "claude-sonnet-4", "total_tokens": 300, "total_calls": 8},
            ],
        }[group_by]

    fake_journal.get_token_usage_by.side_effect = lambda *, group_by="model", agent_id=None: _by(group_by)

    rt = SimpleNamespace(cognitive_journal=fake_journal)
    tracker = CapacityTracker(runtime=rt, window_seconds=60.0)
    snap = await tracker.summary()

    assert snap.total_tokens == 300  # sum of by_agent
    assert snap.total_calls == 8
    assert snap.by_agent == {"a1": 100, "a2": 200}
    assert snap.by_tier == {"fast": 250, "deep": 50}
    assert snap.by_model == {"claude-sonnet-4": 300}
    assert snap.tokens_per_minute == 300.0  # 300 tokens / 60s * 60 = 300/min


# ----- DepartmentBudgetTable -----


def _default_table() -> DepartmentBudgetTable:
    return DepartmentBudgetTable(departments=[
        DepartmentBudget(name="engineering", percent=0.30, priority=3),
        DepartmentBudget(name="science", percent=0.20, priority=4),
        DepartmentBudget(name="medical", percent=0.15, priority=2),
        DepartmentBudget(name="security", percent=0.15, priority=2),
        DepartmentBudget(name="operations", percent=0.10, priority=4),
        DepartmentBudget(name="other", percent=0.10, priority=6),
    ])


def test_department_budget_table_default_allocations_sum_to_one():
    table = _default_table()
    alloc = table.allocations()
    assert abs(sum(alloc.values()) - 1.0) < 0.001


def test_department_budget_table_renormalizes_on_override():
    table = _default_table()
    assert table.set_override("engineering", 0.50) is True
    alloc = table.allocations()
    # Engineering is exactly 0.50; rest sum to 0.50
    assert alloc["engineering"] == 0.50
    rest = sum(v for k, v in alloc.items() if k != "engineering")
    assert abs(rest - 0.50) < 0.001
    # Sum = 1.0
    assert abs(sum(alloc.values()) - 1.0) < 0.001


def test_department_budget_table_clear_override_restores():
    table = _default_table()
    assert table.set_override("engineering", 0.50)
    pre_clear = table.allocations()
    assert table.clear_override("engineering")
    post_clear = table.allocations()
    # Engineering returns to ~0.30 baseline
    assert abs(post_clear["engineering"] - 0.30) < 0.001
    assert pre_clear["engineering"] != post_clear["engineering"]


def test_department_budget_table_rejects_unknown_department():
    table = _default_table()
    assert table.set_override("nonexistent", 0.5) is False


# ----- EPSCoordinator -----


@pytest.mark.asyncio
async def test_eps_coordinator_report_includes_capacity_and_allocations():
    fake_capacity = MagicMock()
    fake_capacity.summary = AsyncMock(return_value=CapacitySummary(
        window_seconds=60.0,
        total_tokens=100,
        total_calls=5,
        tokens_per_minute=100.0,
        calls_per_minute=5.0,
        by_agent={"a1": 100},
    ))

    table = _default_table()
    coord = EPSCoordinator(
        capacity_tracker=fake_capacity,
        budget_table=table,
    )
    report = await coord.report()
    assert isinstance(report, EPSReport)
    assert report.capacity.total_tokens == 100
    assert "engineering" in report.allocations
    assert report.saturated is True  # a1 = 100% of 100 -- > 50%


def test_eps_coordinator_override_emits_reallocation():
    emit = MagicMock()
    table = _default_table()
    coord = EPSCoordinator(
        capacity_tracker=MagicMock(),
        budget_table=table,
        emit_event=emit,
    )
    assert coord.override("medical", 0.50) is True
    emit.assert_called_once()
    et, payload = emit.call_args[0]
    assert et == EventType.EPS_REALLOCATION
    assert payload["department"] == "medical"
    assert payload["percent"] == 0.50
    assert payload["cleared"] is False


@pytest.mark.asyncio
async def test_eps_coordinator_check_budgets_returns_empty_list_v1():
    """v1 contract: returns [] without emit (honest deferral per convention #7)."""
    emit = MagicMock()
    coord = EPSCoordinator(
        capacity_tracker=MagicMock(),
        budget_table=_default_table(),
        emit_event=emit,
    )
    offenders = await coord.check_budgets()
    assert offenders == []
    emit.assert_not_called()
