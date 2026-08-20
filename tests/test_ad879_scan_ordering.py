"""AD-879: tests for deterministic oldest-first scan ordering + starvation guard.

The reconcile sweep must process items ``(priority asc, created_at asc)`` — oldest
first within a priority band — because ``list_work_items`` returns ``created_at DESC``
(newest-first) and the oldest stranded items would otherwise starve under the
``scan_limit`` cap. BF-287: real ``WorkItemStore``; ``_FakeRouter`` only at the
dispatch boundary (it records dispatch call order).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.agents.quartermaster import QuartermasterAgent
from probos.cognitive.work_reconciler import WorkItemReconciler
from probos.substrate.registry import AgentRegistry
from probos.workforce import WorkItemStore


class _FakeRouter:
    """Records dispatch order; everything dispatchable so each item re-dispatches."""

    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def is_dispatchable(self, wi: dict[str, Any]) -> bool:
        return bool((wi.get("metadata") or {}).get("dispatchable", False))

    async def dispatch_work_item(self, wi: dict[str, Any]) -> bool:
        # BF-810: the real router reports whether the substrate admitted it.
        self.dispatched.append(wi.get("id", ""))
        return True


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
    scan_limit: int = 200,
) -> QuartermasterAgent:
    # No live agents needed: unassigned + open + dispatchable -> live_redispatch,
    # which records dispatch in processing order without mutating metadata.
    rec = WorkItemReconciler(registry=AgentRegistry())
    qm = QuartermasterAgent(
        reconciler=rec,
        work_item_store=store,
        work_item_router=router,
        pool="utility",
        agent_id="qm-1",
    )
    qm._scan_limit = scan_limit
    return qm


async def _open_item(
    store: WorkItemStore, *, title: str, priority: int, created_at: float
):
    return await store.create_work_item(
        title=title,
        status="open",
        priority=priority,
        created_at=created_at,
        metadata={"dispatchable": True},
    )


# ── ordering ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_processing_order_priority_then_created_at(store: WorkItemStore) -> None:
    # Seeded newest-first / mixed priority; expected sweep order is (prio asc, age asc).
    a = await _open_item(store, title="p1-old", priority=1, created_at=100.0)
    b = await _open_item(store, title="p1-new", priority=1, created_at=300.0)
    c = await _open_item(store, title="p0-mid", priority=0, created_at=200.0)
    router = _FakeRouter()
    qm = _qm(store=store, router=router)

    await qm.reconcile()

    # priority 0 first (c), then priority 1 oldest-first (a before b)
    assert router.dispatched == [c.id, a.id, b.id]


@pytest.mark.asyncio
async def test_same_priority_older_first(store: WorkItemStore) -> None:
    newer = await _open_item(store, title="newer", priority=2, created_at=500.0)
    older = await _open_item(store, title="older", priority=2, created_at=100.0)
    router = _FakeRouter()
    qm = _qm(store=store, router=router)

    await qm.reconcile()

    assert router.dispatched == [older.id, newer.id]


@pytest.mark.asyncio
async def test_lower_priority_number_first_regardless_of_age(
    store: WorkItemStore,
) -> None:
    # Critical (priority 0) but newest; routine (priority 5) but oldest.
    critical_new = await _open_item(store, title="crit", priority=0, created_at=900.0)
    routine_old = await _open_item(store, title="rout", priority=5, created_at=1.0)
    router = _FakeRouter()
    qm = _qm(store=store, router=router)

    await qm.reconcile()

    assert router.dispatched == [critical_new.id, routine_old.id]


# ── starvation guard ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_truncated_true_at_scan_limit(store: WorkItemStore) -> None:
    await _open_item(store, title="a", priority=1, created_at=1.0)
    await _open_item(store, title="b", priority=1, created_at=2.0)
    router = _FakeRouter()
    qm = _qm(store=store, router=router, scan_limit=2)

    counts = await qm.reconcile()

    assert counts["truncated"] is True


@pytest.mark.asyncio
async def test_truncated_false_small_backlog(store: WorkItemStore) -> None:
    await _open_item(store, title="solo", priority=1, created_at=1.0)
    router = _FakeRouter()
    qm = _qm(store=store, router=router, scan_limit=200)

    counts = await qm.reconcile()

    assert "truncated" in counts
    assert counts["truncated"] is False
