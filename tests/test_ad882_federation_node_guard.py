"""AD-882: tests for the federation node-scope guard.

Liveness is checked against the **local** ``AgentRegistry``. In a multi-node
mesh, an item assigned to an agent on **another node** looks "not live" locally
and would be wrongly reclaimed by this node's sweep. AD-882 installs a
default-safe no-op guard: when ``federation_enabled`` is True and a work item
carries ``metadata['owner_node']`` that differs from the local node id, the
sweep skips it (``reason="remote_owner"``) instead of unassigning/re-dispatching,
and does not accrue a local reconcile attempt.

There is no per-agent or per-work-item node marker today, so the guard is a
forward seam keyed off the optional ``metadata['owner_node']`` convention. On a
single-node deployment (``federation.enabled=False``, default) it is a pure
no-op.

BF-287: real ``WorkItemStore`` (tmp_path SQLite via ``start()``), real
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
    federation_enabled: bool = False,
    local_node_id: str = "node-1",
) -> QuartermasterAgent:
    rec = WorkItemReconciler(registry=registry)
    return QuartermasterAgent(
        reconciler=rec,
        work_item_store=store,
        work_item_router=router,
        pool="utility",
        agent_id="qm-1",
        reconcile_backoff_seconds=0,  # no backoff window in these tests
        min_item_age_seconds=0,  # AD-878: disable boot-grace skip
        local_node_id=local_node_id,
        federation_enabled=federation_enabled,
    )


# ── federation off: guard is a no-op ────────────────────────────────────────


@pytest.mark.asyncio
async def test_federation_disabled_remote_marker_still_reclaimed(
    store: WorkItemStore,
) -> None:
    """federation_enabled=False -> owner_node marker is ignored; item reclaimed."""
    reg = await _registry_with()  # assignee absent -> clear_and_reroute
    router = _FakeRouter()
    await store.create_work_item(
        title="t", status="in_progress", assigned_to="ghost",
        metadata={"dispatchable": True, "owner_node": "node-2"},
    )
    qm = _qm(store=store, registry=reg, router=router, federation_enabled=False)

    counts = await qm.reconcile()

    assert counts["remote_owner_skipped"] == 0
    assert counts["cleared"] == 1


# ── federation on + remote owner: skipped ───────────────────────────────────


@pytest.mark.asyncio
async def test_remote_owner_skipped_not_unassigned(store: WorkItemStore) -> None:
    """Enabled + owner_node!=local -> remote_owner skip, item left untouched."""
    reg = await _registry_with()  # assignee absent locally
    router = _FakeRouter()
    item = await store.create_work_item(
        title="t", status="in_progress", assigned_to="ghost",
        metadata={"dispatchable": True, "owner_node": "node-2"},
    )
    qm = _qm(
        store=store, registry=reg, router=router,
        federation_enabled=True, local_node_id="node-1",
    )

    counts = await qm.reconcile()

    assert counts["remote_owner_skipped"] == 1
    assert counts["cleared"] == 0
    # not unassigned / not re-dispatched
    assert router.dispatched == []
    fresh = await store.get_work_item(item.id)
    assert fresh is not None
    assert fresh.assigned_to == "ghost"
    assert fresh.status == "in_progress"


# ── federation on + local owner: reclaimed normally ─────────────────────────


@pytest.mark.asyncio
async def test_local_owner_marker_reclaimed(store: WorkItemStore) -> None:
    """Enabled + owner_node==local -> guard inactive; item reclaimed normally."""
    reg = await _registry_with()  # assignee absent -> clear_and_reroute
    router = _FakeRouter()
    await store.create_work_item(
        title="t", status="in_progress", assigned_to="ghost",
        metadata={"dispatchable": True, "owner_node": "node-1"},
    )
    qm = _qm(
        store=store, registry=reg, router=router,
        federation_enabled=True, local_node_id="node-1",
    )

    counts = await qm.reconcile()

    assert counts["remote_owner_skipped"] == 0
    assert counts["cleared"] == 1


# ── federation on + no marker: treated as local ─────────────────────────────


@pytest.mark.asyncio
async def test_no_owner_marker_treated_as_local(store: WorkItemStore) -> None:
    """Enabled + no owner_node marker -> treated as local; item reclaimed."""
    reg = await _registry_with()  # assignee absent -> clear_and_reroute
    router = _FakeRouter()
    await store.create_work_item(
        title="t", status="in_progress", assigned_to="ghost",
        metadata={"dispatchable": True},
    )
    qm = _qm(
        store=store, registry=reg, router=router,
        federation_enabled=True, local_node_id="node-1",
    )

    counts = await qm.reconcile()

    assert counts["remote_owner_skipped"] == 0
    assert counts["cleared"] == 1


# ── remote skip does not accrue a reconcile attempt (AD-877 interaction) ─────


@pytest.mark.asyncio
async def test_remote_owner_skip_does_not_increment_attempts(
    store: WorkItemStore,
) -> None:
    """A remote_owner skip must not increment reconcile_attempts."""
    reg = await _registry_with()  # assignee absent locally
    router = _FakeRouter()
    item = await store.create_work_item(
        title="t", status="in_progress", assigned_to="ghost",
        metadata={
            "dispatchable": True,
            "owner_node": "node-2",
            "reconcile_attempts": 1,
        },
    )
    qm = _qm(
        store=store, registry=reg, router=router,
        federation_enabled=True, local_node_id="node-1",
    )

    counts = await qm.reconcile()

    assert counts["remote_owner_skipped"] == 1
    fresh = await store.get_work_item(item.id)
    assert fresh is not None
    assert int(fresh.metadata.get("reconcile_attempts")) == 1
