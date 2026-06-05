"""AD-875: tests for QuartermasterAgent (deterministic work-board reconciler).

BF-287: real WorkItemStore (tmp_path SQLite via start()), real AgentRegistry,
real WorkItemReconciler. A _FakeRouter records dispatch calls and reads
``metadata["dispatchable"]`` for is_dispatchable. Concrete BaseAgent subclass
for live assignees. No MagicMock at the store/registry boundary.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.agents.quartermaster import QuartermasterAgent
from probos.cognitive.work_reconciler import WorkItemReconciler
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry
from probos.types import IntentMessage
from probos.workforce import WorkItemStore


class _LiveAgent(BaseAgent):
    """Minimal concrete BaseAgent for registry registration in tests."""

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
    store: WorkItemStore | None,
    registry: AgentRegistry,
    router: _FakeRouter,
) -> QuartermasterAgent:
    rec = WorkItemReconciler(registry=registry)
    return QuartermasterAgent(
        reconciler=rec,
        work_item_store=store,
        work_item_router=router,
        pool="utility",
        agent_id="qm-1",
        min_item_age_seconds=0,  # AD-878: tests use fresh items; disable boot-grace skip
    )


# ── core sweep ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_live_assignee_open_redispatches(store: WorkItemStore) -> None:
    reg = await _registry_with("slot-live")
    router = _FakeRouter()
    await store.create_work_item(
        title="t", status="open", assigned_to="slot-live",
        metadata={"dispatchable": True},
    )
    qm = _qm(store=store, registry=reg, router=router)

    counts = await qm.reconcile()

    assert counts["redispatched"] == 1
    assert counts["cleared"] == 0
    assert counts["degraded"] is False
    assert len(router.dispatched) == 1


@pytest.mark.asyncio
async def test_reconcile_dead_assignee_clears_and_reroutes(store: WorkItemStore) -> None:
    reg = await _registry_with()  # no live agents -> assignee not live
    router = _FakeRouter()
    item = await store.create_work_item(
        title="t", status="open", assigned_to="slot-dead",
        metadata={"dispatchable": True},
    )
    qm = _qm(store=store, registry=reg, router=router)

    counts = await qm.reconcile()

    assert counts["cleared"] == 1
    assert counts["redispatched"] == 0
    # assignee was cleared on the persisted item
    fresh = await store.get_work_item(item.id)
    assert fresh is not None
    assert not fresh.assigned_to
    # and a fresh dispatch was attempted
    assert router.dispatched == [item.id]


@pytest.mark.asyncio
async def test_reconcile_in_progress_live_owner_is_skipped(store: WorkItemStore) -> None:
    reg = await _registry_with("slot-live")
    router = _FakeRouter()
    await store.create_work_item(
        title="t", status="in_progress", assigned_to="slot-live",
        metadata={"dispatchable": True},
    )
    qm = _qm(store=store, registry=reg, router=router)

    counts = await qm.reconcile()

    assert counts["skipped"] == 1
    assert counts["redispatched"] == 0
    assert counts["cleared"] == 0
    assert router.dispatched == []


@pytest.mark.asyncio
async def test_reconcile_terminal_item_never_scanned(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    await store.create_work_item(
        title="done one", status="done", assigned_to="slot-x",
        metadata={"dispatchable": True},
    )
    qm = _qm(store=store, registry=reg, router=router)

    counts = await qm.reconcile()

    assert counts["scanned"] == 0
    assert router.dispatched == []


@pytest.mark.asyncio
async def test_reconcile_non_dispatchable_open_is_skipped(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    await store.create_work_item(
        title="t", status="open", metadata={"dispatchable": False},
    )
    qm = _qm(store=store, registry=reg, router=router)

    counts = await qm.reconcile()

    assert counts["scanned"] == 1
    assert counts["skipped"] == 1
    assert router.dispatched == []


@pytest.mark.asyncio
async def test_reconcile_empty_board_all_zero(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    qm = _qm(store=store, registry=reg, router=router)

    counts = await qm.reconcile()

    assert counts == {
        "scanned": 0, "redispatched": 0, "cleared": 0, "skipped": 0, "degraded": False,
        # AD-877: thrash-guard counters always present in the summary
        "quarantined": 0, "quarantined_skipped": 0, "backoff_skipped": 0,
        # AD-879: starvation-visibility flag always present in the summary
        "truncated": False,
        # AD-878: boot-race grace-period skip counter always present
        "too_fresh": 0,
    }


@pytest.mark.asyncio
async def test_reconcile_item_error_marks_degraded_others_processed(
    store: WorkItemStore,
) -> None:
    reg = await _registry_with()
    bad = await store.create_work_item(
        title="bad", status="open", metadata={"dispatchable": True},
    )
    await store.create_work_item(
        title="good", status="open", metadata={"dispatchable": True},
    )
    router = _FakeRouter(raise_on_id=bad.id)
    qm = _qm(store=store, registry=reg, router=router)

    counts = await qm.reconcile()

    assert counts["degraded"] is True
    assert counts["scanned"] == 2
    # the good item (unassigned dispatchable open) was still redispatched
    assert counts["redispatched"] == 1


@pytest.mark.asyncio
async def test_reconcile_missing_collaborators_degrades(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    qm = QuartermasterAgent(
        reconciler=WorkItemReconciler(registry=reg),
        work_item_store=None,  # missing collaborator
        work_item_router=router,
        pool="utility",
        agent_id="qm-1",
    )

    counts = await qm.reconcile()

    assert counts["degraded"] is True
    assert counts["scanned"] == 0


# ── lifecycle ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_intent_reconcile_board_returns_counts(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    qm = _qm(store=store, registry=reg, router=router)

    result = await qm.handle_intent(IntentMessage(intent="reconcile_board"))

    assert result is not None
    assert result.success is True
    assert isinstance(result.result, dict)
    assert result.result.get("scanned") == 0


@pytest.mark.asyncio
async def test_handle_intent_other_returns_none(store: WorkItemStore) -> None:
    reg = await _registry_with()
    router = _FakeRouter()
    qm = _qm(store=store, registry=reg, router=router)

    result = await qm.handle_intent(IntentMessage(intent="something_else"))

    assert result is None


def test_quartermaster_is_utility_tier() -> None:
    assert QuartermasterAgent.tier == "utility"


# ── decomposer gap-regex hygiene ──────────────────────────────────────────


def test_descriptor_strings_do_not_trip_capability_gap_regex() -> None:
    from probos.cognitive.decomposer import _CAPABILITY_GAP_RE

    strings = [
        QuartermasterAgent.default_capabilities[0].can,
        QuartermasterAgent.default_capabilities[0].detail,
        QuartermasterAgent.intent_descriptors[0].name,
        QuartermasterAgent.intent_descriptors[0].description,
        "scanned redispatched cleared skipped degraded",
    ]
    for s in strings:
        assert not _CAPABILITY_GAP_RE.search(s), s
