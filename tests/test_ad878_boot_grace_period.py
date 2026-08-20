"""AD-878: tests for the boot-race grace period (skip too-fresh items).

The warm-boot sweep can fire ~10s after boot, while a freshly-created item is
mid-first-dispatch and looks stranded (no live assignee yet). AD-878 skips items
younger than ``min_item_age_seconds`` *before* any classify/attempt logic, so a
mid-dispatch item is neither reclaimed nor charged a reconcile attempt. BF-287:
real ``WorkItemStore`` + real ``WorkItem``; ``_FakeRouter`` only at the dispatch
boundary.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from probos.agents.quartermaster import QuartermasterAgent
from probos.cognitive.work_reconciler import WorkItemReconciler
from probos.substrate.registry import AgentRegistry
from probos.workforce import WorkItemStore


class _FakeRouter:
    """Records dispatch order; is_dispatchable reads metadata['dispatchable']."""

    def __init__(self, *, admits: bool = True) -> None:
        self.dispatched: list[str] = []
        self._admits = admits

    def is_dispatchable(self, wi: dict[str, Any]) -> bool:
        return bool((wi.get("metadata") or {}).get("dispatchable", False))

    async def dispatch_work_item(self, wi: dict[str, Any]) -> bool:
        # BF-810: the real router reports whether the delivery substrate
        # admitted the item, and the Quartermaster counts on that. Returning
        # None made every redispatch look failed.
        self.dispatched.append(wi.get("id", ""))
        return self._admits


@pytest.fixture
async def store(tmp_path: Path):
    s = WorkItemStore(db_path=str(tmp_path / "wf.db"))
    await s.start()
    yield s
    await s.stop()


def _qm(
    *,
    store: WorkItemStore,
    router: _FakeRouter,
    registry: AgentRegistry | None = None,
    min_item_age_seconds: int = 30,
) -> QuartermasterAgent:
    rec = WorkItemReconciler(registry=registry or AgentRegistry())
    return QuartermasterAgent(
        reconciler=rec,
        work_item_store=store,
        work_item_router=router,
        pool="utility",
        agent_id="qm-1",
        min_item_age_seconds=min_item_age_seconds,
    )


async def _open_item(store: WorkItemStore, *, created_at: float, **md: Any):
    return await store.create_work_item(
        title="t",
        status="open",
        created_at=created_at,
        metadata={"dispatchable": True, **md},
    )


# ── grace period ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fresh_item_skipped_never_dispatched(store: WorkItemStore) -> None:
    await _open_item(store, created_at=time.time())  # brand new
    router = _FakeRouter()
    qm = _qm(store=store, router=router, min_item_age_seconds=30)

    counts = await qm.reconcile()

    assert counts["too_fresh"] == 1
    assert router.dispatched == []
    assert counts["redispatched"] == 0


@pytest.mark.asyncio
async def test_old_item_processed_normally(store: WorkItemStore) -> None:
    item = await _open_item(store, created_at=time.time() - 120)  # 2 min old
    router = _FakeRouter()
    qm = _qm(store=store, router=router, min_item_age_seconds=30)

    counts = await qm.reconcile()

    assert counts["too_fresh"] == 0
    assert router.dispatched == [item.id]
    assert counts["redispatched"] == 1


@pytest.mark.asyncio
async def test_boundary_exactly_at_age_is_processed(store: WorkItemStore) -> None:
    # Strict `>` skip: an item exactly min_item_age_seconds old is processed.
    item = await _open_item(store, created_at=time.time() - 30)
    router = _FakeRouter()
    qm = _qm(store=store, router=router, min_item_age_seconds=30)

    counts = await qm.reconcile()

    assert counts["too_fresh"] == 0
    assert router.dispatched == [item.id]


@pytest.mark.asyncio
async def test_zero_age_disables_grace_period(store: WorkItemStore) -> None:
    item = await _open_item(store, created_at=time.time())  # brand new
    router = _FakeRouter()
    qm = _qm(store=store, router=router, min_item_age_seconds=0)

    counts = await qm.reconcile()

    assert counts["too_fresh"] == 0
    assert router.dispatched == [item.id]


@pytest.mark.asyncio
async def test_too_fresh_key_present_when_zero(store: WorkItemStore) -> None:
    await _open_item(store, created_at=time.time() - 120)
    router = _FakeRouter()
    qm = _qm(store=store, router=router, min_item_age_seconds=30)

    counts = await qm.reconcile()

    assert "too_fresh" in counts
    assert counts["too_fresh"] == 0


@pytest.mark.asyncio
async def test_too_fresh_clear_and_reroute_does_not_increment_attempts(
    store: WorkItemStore,
) -> None:
    # Dead assignee + open + dispatchable would be clear_and_reroute, but the
    # item is too fresh, so AD-877 attempt tracking must not run.
    item = await store.create_work_item(
        title="t",
        status="open",
        assigned_to="slot-dead",
        created_at=time.time(),  # brand new
        metadata={"dispatchable": True},
    )
    router = _FakeRouter()
    qm = _qm(store=store, router=router, min_item_age_seconds=30)  # empty registry

    counts = await qm.reconcile()

    assert counts["too_fresh"] == 1
    assert counts["cleared"] == 0
    fresh = await store.get_work_item(item.id)
    assert fresh is not None
    assert "reconcile_attempts" not in fresh.metadata
