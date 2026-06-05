"""AD-877: tests for the Quartermaster reconcile thrash guard.

Bounded re-route attempts + dead-letter quarantine (metadata flag) + per-item
backoff. BF-287: real ``WorkItemStore`` (tmp_path SQLite via ``start()``), real
``WorkItem``, real ``WorkItemReconciler`` + real ``AgentRegistry``. ``_Fake*``
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

    def __init__(self, *, raise_on_id: str | None = None) -> None:
        self.dispatched: list[str] = []
        self._raise_on_id = raise_on_id

    def is_dispatchable(self, wi: dict[str, Any]) -> bool:
        if self._raise_on_id is not None and wi.get("id") == self._raise_on_id:
            raise RuntimeError("boom")
        return bool((wi.get("metadata") or {}).get("dispatchable", False))

    async def dispatch_work_item(self, wi: dict[str, Any]) -> None:
        self.dispatched.append(wi.get("id", ""))


class _EmitRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


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
    emit: _EmitRecorder | None = None,
    max_reconcile_attempts: int = 3,
    reconcile_backoff_seconds: int = 600,
) -> QuartermasterAgent:
    rec = WorkItemReconciler(registry=registry)
    return QuartermasterAgent(
        reconciler=rec,
        work_item_store=store,
        work_item_router=router,
        emit_fn=emit,
        pool="utility",
        agent_id="qm-1",
        max_reconcile_attempts=max_reconcile_attempts,
        reconcile_backoff_seconds=reconcile_backoff_seconds,
    )


# ── attempt tracking ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clear_and_reroute_increments_attempts(store: WorkItemStore) -> None:
    reg = await _registry_with()  # no live agents -> dead assignee
    router = _FakeRouter()
    item = await store.create_work_item(
        title="t", status="open", assigned_to="slot-dead",
        metadata={"dispatchable": True},
    )
    qm = _qm(store=store, registry=reg, router=router)

    counts = await qm.reconcile()

    assert counts["cleared"] == 1
    fresh = await store.get_work_item(item.id)
    assert fresh is not None
    assert int(fresh.metadata.get("reconcile_attempts")) == 1


@pytest.mark.asyncio
async def test_clear_and_reroute_writes_last_reconcile_at(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    before = time.time()
    item = await store.create_work_item(
        title="t", status="open", assigned_to="slot-dead",
        metadata={"dispatchable": True},
    )
    qm = _qm(store=store, registry=reg, router=router)

    await qm.reconcile()

    fresh = await store.get_work_item(item.id)
    assert fresh is not None
    assert float(fresh.metadata.get("last_reconcile_at")) >= before


# ── quarantine ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reaches_max_attempts_quarantines_not_redispatched(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    item = await store.create_work_item(
        title="t", status="open", assigned_to="slot-dead",
        metadata={"dispatchable": True, "reconcile_attempts": 2},
    )
    qm = _qm(store=store, registry=reg, router=router, max_reconcile_attempts=3)

    counts = await qm.reconcile()

    assert counts["quarantined"] == 1
    assert counts["cleared"] == 0
    assert router.dispatched == []  # not re-dispatched
    fresh = await store.get_work_item(item.id)
    assert fresh is not None
    assert fresh.metadata.get("quarantined") is True
    assert fresh.metadata.get("quarantine_reason") == "max_reconcile_attempts"
    assert int(fresh.metadata.get("reconcile_attempts")) == 3
    # assignee untouched (we did not unassign on the quarantine path)
    assert fresh.assigned_to == "slot-dead"


@pytest.mark.asyncio
async def test_quarantine_emits_work_item_quarantined(store: WorkItemStore) -> None:
    from probos.events import EventType

    reg = await _registry_with()
    router = _FakeRouter()
    emit = _EmitRecorder()
    item = await store.create_work_item(
        title="t", status="open", assigned_to="slot-dead",
        metadata={"dispatchable": True, "reconcile_attempts": 2},
    )
    qm = _qm(store=store, registry=reg, router=router, emit=emit, max_reconcile_attempts=3)

    await qm.reconcile()

    quarantine_events = [
        p for et, p in emit.events if et == EventType.WORK_ITEM_QUARANTINED
    ]
    assert len(quarantine_events) == 1
    payload = quarantine_events[0]
    assert payload["work_item_id"] == item.id
    assert payload["reason"] == "max_reconcile_attempts"
    assert payload["attempts"] == 3


@pytest.mark.asyncio
async def test_max_attempts_one_quarantines_on_first_clear(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    item = await store.create_work_item(
        title="t", status="open", assigned_to="slot-dead",
        metadata={"dispatchable": True},  # no prior attempts
    )
    qm = _qm(store=store, registry=reg, router=router, max_reconcile_attempts=1)

    counts = await qm.reconcile()

    assert counts["quarantined"] == 1
    assert router.dispatched == []
    fresh = await store.get_work_item(item.id)
    assert fresh is not None
    assert fresh.metadata.get("quarantined") is True


@pytest.mark.asyncio
async def test_already_quarantined_item_is_skipped(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    item = await store.create_work_item(
        title="t", status="open", assigned_to="slot-dead",
        metadata={"dispatchable": True, "quarantined": True},
    )
    qm = _qm(store=store, registry=reg, router=router)

    counts = await qm.reconcile()

    assert counts["quarantined_skipped"] == 1
    assert counts["cleared"] == 0
    assert counts["quarantined"] == 0
    assert router.dispatched == []
    # untouched
    fresh = await store.get_work_item(item.id)
    assert fresh is not None
    assert fresh.assigned_to == "slot-dead"


# ── backoff ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recent_last_reconcile_at_backoff_skips(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    await store.create_work_item(
        title="t", status="open", assigned_to="slot-dead",
        metadata={"dispatchable": True, "last_reconcile_at": time.time()},
    )
    qm = _qm(store=store, registry=reg, router=router, reconcile_backoff_seconds=600)

    counts = await qm.reconcile()

    assert counts["backoff_skipped"] == 1
    assert counts["cleared"] == 0
    assert router.dispatched == []


@pytest.mark.asyncio
async def test_backoff_zero_disables_backoff(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    await store.create_work_item(
        title="t", status="open", assigned_to="slot-dead",
        metadata={"dispatchable": True, "last_reconcile_at": time.time()},
    )
    qm = _qm(store=store, registry=reg, router=router, reconcile_backoff_seconds=0)

    counts = await qm.reconcile()

    assert counts["backoff_skipped"] == 0
    assert counts["cleared"] == 1


# ── counts shape + degrade ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_counts_always_carry_new_keys(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    qm = _qm(store=store, registry=reg, router=router)

    counts = await qm.reconcile()  # empty board

    for key in ("quarantined", "quarantined_skipped", "backoff_skipped"):
        assert key in counts
        assert counts[key] == 0


@pytest.mark.asyncio
async def test_per_item_exception_degrades_and_continues(store: WorkItemStore) -> None:
    reg = await _registry_with()
    bad = await store.create_work_item(
        title="bad", status="open", assigned_to="slot-dead",
        metadata={"dispatchable": True},
    )
    good = await store.create_work_item(
        title="good", status="open", assigned_to="slot-dead",
        metadata={"dispatchable": True},
    )
    router = _FakeRouter(raise_on_id=bad.id)
    qm = _qm(store=store, registry=reg, router=router)

    counts = await qm.reconcile()

    assert counts["degraded"] is True
    assert counts["scanned"] == 2
    # the good item was still cleared despite the bad one raising
    assert counts["cleared"] == 1
    good_fresh = await store.get_work_item(good.id)
    assert good_fresh is not None
    assert int(good_fresh.metadata.get("reconcile_attempts")) == 1
