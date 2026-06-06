"""AD-880: tests for reactive reclaim on agent removal.

Reclaim was poll-only (up to ``interval_seconds`` latency). AD-880 adds an
additive, default-off reactive path: ``AgentRegistry.unregister`` emits a new
``EventType.AGENT_REMOVED`` at the single removal chokepoint, and (when
``reactive_reclaim`` is enabled) the Quartermaster reclaims only that agent's
items via ``reconcile_for_agent`` — reusing the shared ``_process_item`` path
(AD-877/878/879 guards). BF-287: real ``AgentRegistry`` + real ``WorkItemStore``;
``_Fake`` only at the router/dispatch and runtime-bus boundary.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.agents.quartermaster import QuartermasterAgent
from probos.cognitive.work_reconciler import WorkItemReconciler
from probos.config import SystemConfig
from probos.events import EventType
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry
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
    """Records dispatch order; is_dispatchable reads metadata['dispatchable']."""

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


def _qm(
    *,
    store: WorkItemStore,
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
        min_item_age_seconds=0,  # tests use fresh items; disable boot-grace skip
    )


# ── EventType emission at the chokepoint ──────────────────────────────────────


@pytest.mark.asyncio
async def test_unregister_present_agent_emits_once() -> None:
    reg = AgentRegistry()
    captured: list[tuple[Any, dict[str, Any]]] = []
    reg._emit_event_fn = lambda et, data: captured.append((et, data))
    await reg.register(_LiveAgent(pool="workers", agent_id="a1"))

    await reg.unregister("a1")

    assert len(captured) == 1
    assert captured[0][0] is EventType.AGENT_REMOVED


@pytest.mark.asyncio
async def test_unregister_absent_agent_emits_nothing() -> None:
    reg = AgentRegistry()
    captured: list[tuple[Any, dict[str, Any]]] = []
    reg._emit_event_fn = lambda et, data: captured.append((et, data))

    result = await reg.unregister("ghost")

    assert result is None
    assert captured == []


@pytest.mark.asyncio
async def test_unregister_without_emit_fn_does_not_crash() -> None:
    reg = AgentRegistry()  # no _emit_event_fn bound
    await reg.register(_LiveAgent(pool="workers", agent_id="a1"))

    agent = await reg.unregister("a1")

    assert agent is not None
    assert agent.id == "a1"


@pytest.mark.asyncio
async def test_agent_removed_payload_carries_id_and_type() -> None:
    reg = AgentRegistry()
    captured: list[tuple[Any, dict[str, Any]]] = []
    reg._emit_event_fn = lambda et, data: captured.append((et, data))
    await reg.register(_LiveAgent(pool="workers", agent_id="a1"))

    await reg.unregister("a1")

    _, data = captured[0]
    assert data["agent_id"] == "a1"
    assert data["agent_type"] == "worker"


# ── scoped reclaim ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_for_agent_reclaims_only_named_agent(store: WorkItemStore) -> None:
    reg = AgentRegistry()  # neither dead-x nor dead-y is live
    router = _FakeRouter()
    a = await store.create_work_item(
        title="a", status="open", assigned_to="dead-x",
        metadata={"dispatchable": True},
    )
    await store.create_work_item(
        title="b", status="open", assigned_to="dead-y",
        metadata={"dispatchable": True},
    )
    qm = _qm(store=store, registry=reg, router=router)

    counts = await qm.reconcile_for_agent("dead-x")

    assert counts["scanned"] == 1
    assert counts["cleared"] == 1
    # only dead-x's item was rerouted; dead-y's item untouched
    assert router.dispatched == [a.id]


@pytest.mark.asyncio
async def test_reconcile_for_agent_honours_attempt_guard(store: WorkItemStore) -> None:
    reg = AgentRegistry()  # dead-x not live
    router = _FakeRouter()
    item = await store.create_work_item(
        title="thrash", status="open", assigned_to="dead-x",
        metadata={"dispatchable": True, "reconcile_attempts": 2},
    )
    qm = _qm(store=store, registry=reg, router=router)  # max_reconcile_attempts default 3

    counts = await qm.reconcile_for_agent("dead-x")

    assert counts["quarantined"] == 1
    assert counts["cleared"] == 0
    fresh = await store.get_work_item(item.id)
    assert fresh is not None
    assert fresh.metadata.get("quarantined") is True
    assert router.dispatched == []  # quarantined item is NOT rerouted


@pytest.mark.asyncio
async def test_reconcile_for_agent_records_reactive_last_sweep(store: WorkItemStore) -> None:
    reg = AgentRegistry()
    router = _FakeRouter()
    qm = _qm(store=store, registry=reg, router=router)

    await qm.reconcile_for_agent("dead-x")

    assert qm._last_sweep is not None
    assert qm._last_sweep["trigger"] == "reactive"


# ── subscription wiring (gated) ───────────────────────────────────────────────


class _FakeRuntime:
    """Minimal runtime surface for _wire_board_reconciler (bus + collaborators)."""

    def __init__(self, *, registry: AgentRegistry, store: WorkItemStore, router: _FakeRouter) -> None:
        self.registry = registry
        self.work_item_store = store
        self.work_item_router = router
        self.identity_registry = None
        self.episodic_memory = None
        self.listeners: list[tuple[Any, list[str] | None]] = []
        self.board_reconciler_ticker = None

    def emit_event(self, *args: Any, **kwargs: Any) -> None:
        pass

    def add_event_listener(self, fn: Any, event_types: list[str] | None = None) -> None:
        self.listeners.append((fn, event_types))


def _wiring_config(*, reactive_reclaim: bool) -> SystemConfig:
    cfg = SystemConfig()
    cfg.work_board_reconciler.enabled = True
    cfg.work_board_reconciler.warm_boot = False  # no warm-boot reconcile in tests
    cfg.work_board_reconciler.min_item_age_seconds = 0
    cfg.work_board_reconciler.reactive_reclaim = reactive_reclaim
    return cfg


async def _wire(rt: _FakeRuntime, cfg: SystemConfig):
    from probos.startup.finalize import _wire_board_reconciler

    _wire_board_reconciler(runtime=rt, config=cfg)


@pytest.mark.asyncio
async def test_reactive_reclaim_disabled_creates_no_subscription(store: WorkItemStore) -> None:
    reg = AgentRegistry()
    await reg.register(QuartermasterAgent(pool="quartermaster", agent_id="qm-1"))
    rt = _FakeRuntime(registry=reg, store=store, router=_FakeRouter())

    await _wire(rt, _wiring_config(reactive_reclaim=False))
    try:
        assert not any(
            "agent_removed" in (ets or []) for _, ets in rt.listeners
        )
        assert getattr(rt, "board_reactive_reclaim_handler", None) is None
    finally:
        if rt.board_reconciler_ticker is not None:
            await rt.board_reconciler_ticker.stop()


@pytest.mark.asyncio
async def test_reactive_reclaim_enabled_handler_reclaims_dead_agent(store: WorkItemStore) -> None:
    reg = AgentRegistry()
    await reg.register(QuartermasterAgent(pool="quartermaster", agent_id="qm-1"))
    router = _FakeRouter()
    item = await store.create_work_item(
        title="orphan", status="open", assigned_to="dead-x",
        metadata={"dispatchable": True},
    )
    rt = _FakeRuntime(registry=reg, store=store, router=router)

    await _wire(rt, _wiring_config(reactive_reclaim=True))
    try:
        # a listener for agent_removed was registered
        handlers = [fn for fn, ets in rt.listeners if "agent_removed" in (ets or [])]
        assert len(handlers) == 1
        # drive an AGENT_REMOVED event through the handler
        await handlers[0]({"type": "agent_removed", "data": {"agent_id": "dead-x"}})
        # the dead agent's orphan item was reclaimed (cleared + rerouted)
        assert router.dispatched == [item.id]
    finally:
        if rt.board_reconciler_ticker is not None:
            await rt.board_reconciler_ticker.stop()
