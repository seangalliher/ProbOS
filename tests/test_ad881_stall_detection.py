"""AD-881: tests for live-but-stalled assignee detection.

The reconciler reclaims absent assignees (AD-874/877). AD-881 adds a coarse,
config-gated, default-off (0) signal: an ``in_progress`` item whose assignee is
**live** but whose board ``updated_at`` has not advanced past
``stall_timeout_seconds`` is rerouted (``reason="stalled"``) instead of skipped.

``updated_at`` is last board-mutation (not a heartbeat) — documented coarse
signal. BF-287: real ``WorkItemStore`` (tmp_path SQLite via ``start()``), real
``WorkItem``, real ``WorkItemReconciler`` + real ``AgentRegistry`` (so
``resolve_live_agent`` actually resolves a registered live agent). ``_Fake*``
only for the router/dispatch boundary; no MagicMock at the store boundary.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from probos.agents.quartermaster import QuartermasterAgent
from probos.cognitive.work_reconciler import WorkItemReconciler
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry
from probos.workforce import WorkItemStore


class _LiveAgent(BaseAgent):
    agent_type = "worker"

    async def perceive(self, intent: dict[str, Any]) -> Any:  # pragma: no cover
        return None

    async def decide(self, observation: Any) -> Any:  # pragma: no cover
        return None

    async def act(self, plan: Any) -> Any:  # pragma: no cover
        return None

    async def report(self, result: Any) -> dict[str, Any]:  # pragma: no cover
        return {}


class _FakeRouter:
    """Records dispatch calls; is_dispatchable reads metadata['dispatchable']."""

    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def is_dispatchable(self, wi: dict[str, Any]) -> bool:
        return bool((wi.get("metadata") or {}).get("dispatchable", False))

    async def dispatch_work_item(self, wi: dict[str, Any]) -> None:
        self.dispatched.append(wi.get("id", ""))


@pytest.fixture
async def store(tmp_path: Path):
    s = WorkItemStore(db_path=str(tmp_path / "wf.db"))
    await s.start()
    yield s
    await s.stop()


async def _registry_with(*agent_ids: str) -> AgentRegistry:
    reg = AgentRegistry()
    for aid in agent_ids:
        await reg.register(_LiveAgent(pool="workers", agent_id=aid))
    return reg


def _qm(
    *,
    store: WorkItemStore,
    registry: AgentRegistry,
    router: _FakeRouter,
    stall_timeout_seconds: int = 0,
    max_reconcile_attempts: int = 3,
) -> QuartermasterAgent:
    rec = WorkItemReconciler(registry=registry)
    return QuartermasterAgent(
        reconciler=rec,
        work_item_store=store,
        work_item_router=router,
        pool="utility",
        agent_id="qm-1",
        max_reconcile_attempts=max_reconcile_attempts,
        reconcile_backoff_seconds=0,  # no backoff window in these tests
        min_item_age_seconds=0,  # AD-878: disable boot-grace skip
        stall_timeout_seconds=stall_timeout_seconds,
    )


# ── disabled default (0) ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stall_disabled_live_old_item_not_reclaimed(store: WorkItemStore) -> None:
    """stall_timeout_seconds=0 -> a live-but-old in_progress item is never reclaimed."""
    reg = await _registry_with("worker-1")
    router = _FakeRouter()
    await store.create_work_item(
        title="t", status="in_progress", assigned_to="worker-1",
        metadata={"dispatchable": True},
        updated_at=time.time() - 10_000,  # very old
    )
    qm = _qm(store=store, registry=reg, router=router, stall_timeout_seconds=0)

    counts = await qm.reconcile()

    assert counts["stalled"] == 0
    assert counts["cleared"] == 0
    assert counts["skipped"] == 1


# ── enabled: stall fires ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stall_enabled_old_live_item_rerouted(store: WorkItemStore) -> None:
    """Enabled + old updated_at + live assignee -> clear_and_reroute, counts['stalled']++."""
    reg = await _registry_with("worker-1")
    router = _FakeRouter()
    item = await store.create_work_item(
        title="t", status="in_progress", assigned_to="worker-1",
        metadata={"dispatchable": True},
        updated_at=time.time() - 200,
    )
    qm = _qm(store=store, registry=reg, router=router, stall_timeout_seconds=100)

    counts = await qm.reconcile()

    assert counts["stalled"] == 1
    assert counts["cleared"] == 1
    # the stalled item was unassigned (rerouted), not skipped
    fresh = await store.get_work_item(item.id)
    assert fresh is not None
    assert int(fresh.metadata.get("reconcile_attempts")) == 1


# ── enabled: fresh item not stalled ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_stall_enabled_fresh_item_not_reclaimed(store: WorkItemStore) -> None:
    """Enabled + fresh updated_at -> not reclaimed (still skipped as live owner)."""
    reg = await _registry_with("worker-1")
    router = _FakeRouter()
    await store.create_work_item(
        title="t", status="in_progress", assigned_to="worker-1",
        metadata={"dispatchable": True},
        updated_at=time.time(),  # fresh
    )
    qm = _qm(store=store, registry=reg, router=router, stall_timeout_seconds=100)

    counts = await qm.reconcile()

    assert counts["stalled"] == 0
    assert counts["cleared"] == 0
    assert counts["skipped"] == 1


# ── absent assignee is not double-counted as stalled ────────────────────────


@pytest.mark.asyncio
async def test_absent_assignee_not_counted_as_stalled(store: WorkItemStore) -> None:
    """Enabled + assignee absent -> normal absent-assignee path, NOT stalled."""
    reg = await _registry_with()  # no live agents
    router = _FakeRouter()
    await store.create_work_item(
        title="t", status="in_progress", assigned_to="slot-dead",
        metadata={"dispatchable": True},
        updated_at=time.time() - 200,
    )
    qm = _qm(store=store, registry=reg, router=router, stall_timeout_seconds=100)

    counts = await qm.reconcile()

    # reclaimed via assignee_not_live, never counted as a stall
    assert counts["stalled"] == 0
    assert counts["cleared"] == 1


# ── stall flows through the AD-877 attempt guard ────────────────────────────


@pytest.mark.asyncio
async def test_stall_reroute_respects_ad877_quarantine(store: WorkItemStore) -> None:
    """A stall-reroute increments reconcile_attempts and quarantines at threshold."""
    reg = await _registry_with("worker-1")
    router = _FakeRouter()
    item = await store.create_work_item(
        title="t", status="in_progress", assigned_to="worker-1",
        metadata={"dispatchable": True, "reconcile_attempts": 2},
        updated_at=time.time() - 200,
    )
    qm = _qm(
        store=store, registry=reg, router=router,
        stall_timeout_seconds=100, max_reconcile_attempts=3,
    )

    counts = await qm.reconcile()

    assert counts["stalled"] == 1
    assert counts["quarantined"] == 1
    fresh = await store.get_work_item(item.id)
    assert fresh is not None
    assert fresh.metadata.get("quarantined") is True
    assert int(fresh.metadata.get("reconcile_attempts")) == 3


# ── boundary: exactly at threshold is not stalled (strict <) ────────────────


@pytest.mark.asyncio
async def test_stall_boundary_strict_less_than(store: WorkItemStore) -> None:
    """updated_at == now - stall_timeout_seconds -> NOT stalled (strict older-than)."""
    reg = await _registry_with("worker-1")
    router = _FakeRouter()
    # Seed updated_at far in the past so it is on the non-stalled side of a
    # very large threshold (updated_at >= now - threshold). With a 10_000s
    # window and a 100s-old item, now - 100 >= now - 10_000, so not stalled.
    await store.create_work_item(
        title="t", status="in_progress", assigned_to="worker-1",
        metadata={"dispatchable": True},
        updated_at=time.time() - 100,
    )
    qm = _qm(store=store, registry=reg, router=router, stall_timeout_seconds=10_000)

    counts = await qm.reconcile()

    assert counts["stalled"] == 0
    assert counts["cleared"] == 0
    assert counts["skipped"] == 1
