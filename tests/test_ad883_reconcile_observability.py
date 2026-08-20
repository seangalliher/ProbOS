"""AD-883: tests for the reconcile observability surface.

The sweep records a last-sweep summary on the agent and surfaces it through the
``info()`` override (reachable via the ``agent_info`` introspection intent — no
new slash command or HTTP endpoint). BF-287: real ``WorkItemStore`` + real
``QuartermasterAgent``; ``_FakeRouter`` only at the dispatch boundary.
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


def _qm(*, store: WorkItemStore, router: _FakeRouter) -> QuartermasterAgent:
    return QuartermasterAgent(
        reconciler=WorkItemReconciler(registry=AgentRegistry()),
        work_item_store=store,
        work_item_router=router,
        pool="utility",
        agent_id="qm-1",
        min_item_age_seconds=0,
    )


@pytest.mark.asyncio
async def test_reconcile_records_last_sweep(store: WorkItemStore) -> None:
    qm = _qm(store=store, router=_FakeRouter())

    counts = await qm.reconcile()

    assert qm._last_sweep is not None
    assert qm._last_sweep["counts"] == counts
    assert qm._last_sweep["trigger"] == "periodic"
    assert isinstance(qm._last_sweep["at"], float)


@pytest.mark.asyncio
async def test_info_includes_reconciliation_block(store: WorkItemStore) -> None:
    qm = _qm(store=store, router=_FakeRouter())

    counts = await qm.reconcile()
    snapshot = qm.info()

    block = snapshot["reconciliation"]
    assert block["last_sweep"] == counts
    assert block["trigger"] == "periodic"
    assert block["age_seconds"] >= 0.0


def test_info_never_run_reports_none() -> None:
    qm = QuartermasterAgent(pool="utility", agent_id="qm-1")

    block = qm.info()["reconciliation"]

    assert block == {"last_sweep": None}


@pytest.mark.asyncio
async def test_info_age_seconds_reflects_elapsed(store: WorkItemStore) -> None:
    qm = _qm(store=store, router=_FakeRouter())
    await qm.reconcile()

    qm._last_sweep["at"] = time.time() - 5.0
    age = qm.info()["reconciliation"]["age_seconds"]

    assert 4.5 <= age <= 6.5


def test_info_renders_with_later_ad_counts_keys() -> None:
    qm = QuartermasterAgent(pool="utility", agent_id="qm-1")
    qm._last_sweep = {
        "counts": {"scanned": 3, "quarantined": 1, "stalled": 2, "remote_owner_skipped": 1},
        "at": time.time(),
        "trigger": "periodic",
    }

    block = qm.info()["reconciliation"]

    assert block["last_sweep"]["quarantined"] == 1
    assert block["last_sweep"]["stalled"] == 2
    assert block["last_sweep"]["remote_owner_skipped"] == 1
