"""AD-876: tests for the Quartermaster board-reconciler wiring + cadence ticker.

BF-287: real :class:`SystemConfig`, real :class:`WorkItemStore` (tmp_path
SQLite), real :class:`AgentRegistry`, real :class:`WorkItemReconciler`, real
:class:`QuartermasterAgent`. ``_FakeRouter`` records dispatch calls and a tiny
``_FakeAgent`` is used only where the test isolates the ticker's cadence from
the real reconcile path. No MagicMock at the store / registry / config boundary.
"""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from probos.config import SystemConfig, WorkBoardReconcilerConfig
from probos.agents.quartermaster import QuartermasterAgent
from probos.mesh.board_reconciler_ticker import BoardReconcilerTicker
from probos.startup.finalize import _wire_board_reconciler
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry
from probos.workforce import WorkItemStore


# ── fakes (collaborators only — never the store/registry/config) ──────────


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

    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def is_dispatchable(self, wi: dict[str, Any]) -> bool:
        return bool((wi.get("metadata") or {}).get("dispatchable", False))

    async def dispatch_work_item(self, wi: dict[str, Any]) -> None:
        self.dispatched.append(wi.get("id", ""))


class _FakeAgent:
    """Counts reconcile() invocations (cadence-isolation tests only)."""

    def __init__(self) -> None:
        self.calls = 0

    async def reconcile(self) -> dict[str, Any]:
        self.calls += 1
        return {"scanned": 0}


class _FakeRuntime:
    """Attribute bag standing in for ProbOSRuntime during wiring.

    The substrate it carries (registry, store, router) is real; only the
    runtime container itself is a stand-in.
    """

    def __init__(
        self,
        *,
        registry: Any = None,
        work_item_store: Any = None,
        work_item_router: Any = None,
    ) -> None:
        self.registry = registry
        self.work_item_store = work_item_store
        self.work_item_router = work_item_router
        self.identity_registry = None
        self.episodic_memory = None
        self._events: list[tuple[Any, dict[str, Any] | None]] = []

    def emit_event(self, event: Any, data: dict[str, Any] | None = None) -> None:
        self._events.append((event, data))


@pytest.fixture
async def store(tmp_path: Path):
    s = WorkItemStore(db_path=str(tmp_path / "wf.db"))
    await s.start()
    yield s
    await s.stop()


async def _registry_with_quartermaster() -> tuple[AgentRegistry, QuartermasterAgent]:
    reg = AgentRegistry()
    qm = QuartermasterAgent(pool="quartermaster", agent_id="qm-1")
    await reg.register(qm)
    return reg, qm


# ── §1 config defaults + bounds ───────────────────────────────────────────


def test_config_defaults() -> None:
    cfg = SystemConfig()
    wbr = cfg.work_board_reconciler
    assert wbr.enabled is False
    assert wbr.interval_seconds == 300
    assert wbr.warm_boot is True
    assert wbr.scan_limit == 200


def test_config_interval_bounds_reject() -> None:
    with pytest.raises(ValidationError):
        WorkBoardReconcilerConfig(interval_seconds=10)
    with pytest.raises(ValidationError):
        WorkBoardReconcilerConfig(interval_seconds=99999)


def test_config_scan_limit_bounds_reject() -> None:
    with pytest.raises(ValidationError):
        WorkBoardReconcilerConfig(scan_limit=0)
    with pytest.raises(ValidationError):
        WorkBoardReconcilerConfig(scan_limit=99999)


# ── §3 wiring guards ──────────────────────────────────────────────────────


def test_wire_disabled_is_noop() -> None:
    cfg = SystemConfig()  # enabled defaults False
    runtime = _FakeRuntime()
    assert _wire_board_reconciler(runtime=runtime, config=cfg) is False
    assert getattr(runtime, "board_reconciler_ticker", None) is None


def test_wire_missing_router_returns_false() -> None:
    cfg = SystemConfig()
    cfg.work_board_reconciler.enabled = True
    # store + registry present, but no work_item_router (hybrid_dispatch off)
    runtime = _FakeRuntime(registry=AgentRegistry(), work_item_store=object())
    assert _wire_board_reconciler(runtime=runtime, config=cfg) is False
    assert getattr(runtime, "board_reconciler_ticker", None) is None


@pytest.mark.asyncio
async def test_wire_enabled_injects_and_sets_ticker(store: WorkItemStore) -> None:
    cfg = SystemConfig()
    cfg.work_board_reconciler.enabled = True
    cfg.work_board_reconciler.scan_limit = 77
    reg, qm = await _registry_with_quartermaster()
    router = _FakeRouter()
    runtime = _FakeRuntime(
        registry=reg, work_item_store=store, work_item_router=router
    )

    result = _wire_board_reconciler(runtime=runtime, config=cfg)
    try:
        assert result is True
        assert runtime.board_reconciler_ticker is not None
        # collaborators injected by exact private attr
        assert qm._reconciler is not None
        assert qm._store is store
        assert qm._router is router
        assert qm._emit == runtime.emit_event
        assert qm._scan_limit == 77
    finally:
        await runtime.board_reconciler_ticker.stop()


@pytest.mark.asyncio
async def test_wire_missing_agent_returns_false(store: WorkItemStore) -> None:
    cfg = SystemConfig()
    cfg.work_board_reconciler.enabled = True
    reg = AgentRegistry()  # no quartermaster registered
    router = _FakeRouter()
    runtime = _FakeRuntime(
        registry=reg, work_item_store=store, work_item_router=router
    )
    assert _wire_board_reconciler(runtime=runtime, config=cfg) is False
    assert getattr(runtime, "board_reconciler_ticker", None) is None


# ── §5 ticker lifecycle ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ticker_start_holds_task_reference() -> None:
    agent = _FakeAgent()
    ticker = BoardReconcilerTicker(
        agent=agent, interval_seconds=300, warm_boot=False, startup_delay=0.0
    )
    ticker.start()
    try:
        assert ticker._task is not None
    finally:
        await ticker.stop()
    # source proves the loop task reference is stored, not fire-and-forget
    src = inspect.getsource(BoardReconcilerTicker.start)
    assert "self._task = asyncio.create_task" in src


@pytest.mark.asyncio
async def test_ticker_warm_boot_reconciles_once() -> None:
    agent = _FakeAgent()
    ticker = BoardReconcilerTicker(
        agent=agent, interval_seconds=3600, warm_boot=True, startup_delay=0.0
    )
    ticker.start()
    try:
        await asyncio.sleep(0.05)
        assert agent.calls == 1  # warm boot fired; interval far away
    finally:
        await ticker.stop()


@pytest.mark.asyncio
async def test_ticker_stop_cancels_cleanly() -> None:
    agent = _FakeAgent()
    ticker = BoardReconcilerTicker(
        agent=agent, interval_seconds=300, warm_boot=False, startup_delay=0.0
    )
    ticker.start()
    await ticker.stop()
    assert ticker._task is None
    # idempotent second stop
    await ticker.stop()
    assert ticker._task is None


# ── §integration: wire + warm-boot reconcile through the store ────────────


@pytest.mark.asyncio
async def test_warm_boot_integration_redispatches_stranded(store: WorkItemStore) -> None:
    cfg = SystemConfig()
    cfg.work_board_reconciler.enabled = True
    reg, qm = await _registry_with_quartermaster()
    # register a live assignee so the open item is re-dispatched (not cleared)
    await reg.register(_LiveAgent(pool="workers", agent_id="slot-live"))
    router = _FakeRouter()
    await store.create_work_item(
        title="stranded", status="open", assigned_to="slot-live",
        metadata={"dispatchable": True},
    )
    runtime = _FakeRuntime(
        registry=reg, work_item_store=store, work_item_router=router
    )

    assert _wire_board_reconciler(runtime=runtime, config=cfg) is True
    # stop the wire-created ticker (10s warm delay) and drive a deterministic one
    await runtime.board_reconciler_ticker.stop()

    ticker = BoardReconcilerTicker(
        agent=qm, interval_seconds=3600, warm_boot=True, startup_delay=0.0
    )
    ticker.start()
    try:
        await asyncio.sleep(0.1)
        assert router.dispatched  # warm-boot reconcile dispatched the item
    finally:
        await ticker.stop()


# ── §regression: default config creates neither pool nor ticker ───────────


def test_default_config_no_pool_no_ticker() -> None:
    cfg = SystemConfig()
    # agent_fleet gate predicate is False by default -> no quartermaster pool
    gate = bool(
        getattr(cfg, "work_board_reconciler", None)
        and cfg.work_board_reconciler.enabled
    )
    assert gate is False
    # and even with full deps present, default-disabled config wires no ticker
    runtime = _FakeRuntime(
        registry=AgentRegistry(),
        work_item_store=object(),
        work_item_router=_FakeRouter(),
    )
    assert _wire_board_reconciler(runtime=runtime, config=cfg) is False
    assert getattr(runtime, "board_reconciler_ticker", None) is None
