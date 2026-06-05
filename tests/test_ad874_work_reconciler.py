"""AD-874: tests for WorkItemReconciler (deterministic stranded-item classifier).

BF-287: real AgentRegistry + real AgentIdentityRegistry (tmp DB via start()),
concrete BaseAgent subclass for live agents. No MagicMock at these boundaries.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.work_reconciler import ReconcileDecision, WorkItemReconciler
from probos.identity import AgentIdentityRegistry
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry


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


@pytest.fixture
async def identity_registry(tmp_path: Path):
    reg = AgentIdentityRegistry(data_dir=tmp_path)
    await reg.start(instance_id="inst-A", vessel_name="USS Enterprise", version="v0.5.0")
    yield reg
    await reg.stop()


async def _make_registry_with_agent(agent_id: str) -> AgentRegistry:
    reg = AgentRegistry()
    await reg.register(_LiveAgent(pool="workers", agent_id=agent_id))
    return reg


def _wi(
    *,
    wid: str = "wi-1",
    status: str = "open",
    assigned_to: str | None = None,
) -> dict[str, Any]:
    return {"id": wid, "status": status, "assigned_to": assigned_to}


# ── resolve_live_agent ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_live_agent_live_slot_returns_it() -> None:
    reg = await _make_registry_with_agent("slot-live")
    rec = WorkItemReconciler(registry=reg)
    assert rec.resolve_live_agent("slot-live") == "slot-live"


@pytest.mark.asyncio
async def test_resolve_live_agent_dead_assignee_sovereign_did_maps_to_new_slot(
    identity_registry: AgentIdentityRegistry,
) -> None:
    # Live agent occupies slot-B; dead assignee is slot-A. Both slots map to the
    # SAME sovereign agent_uuid — the AD-441 migration seam. Seed the second
    # mapping directly: there is no public API to point two slots at one uuid
    # yet (issue_birth_certificate mints a fresh uuid each call), so we
    # construct the artificial future-state with the real cert object.
    reg = await _make_registry_with_agent("slot-B")
    cert = await identity_registry.issue_birth_certificate(
        agent_type="worker", callsign="W", instance_id="inst-A",
        vessel_name="USS Enterprise", department="ops", post_id="worker",
        baseline_version="v0.5.0", slot_id="slot-A",
    )
    identity_registry._slot_cache["slot-B"] = cert  # AD-441 seam (test-only)

    rec = WorkItemReconciler(registry=reg, identity_registry=identity_registry)
    assert rec.resolve_live_agent("slot-A") == "slot-B"


@pytest.mark.asyncio
async def test_resolve_live_agent_dead_assignee_no_cert_returns_none(
    identity_registry: AgentIdentityRegistry,
) -> None:
    reg = AgentRegistry()
    rec = WorkItemReconciler(registry=reg, identity_registry=identity_registry)
    assert rec.resolve_live_agent("slot-unknown") is None


@pytest.mark.asyncio
async def test_resolve_live_agent_no_identity_registry_dead_assignee_returns_none() -> None:
    reg = AgentRegistry()
    rec = WorkItemReconciler(registry=reg, identity_registry=None)
    assert rec.resolve_live_agent("slot-dead") is None


@pytest.mark.asyncio
async def test_resolve_live_agent_falsy_returns_none() -> None:
    reg = AgentRegistry()
    rec = WorkItemReconciler(registry=reg)
    assert rec.resolve_live_agent(None) is None
    assert rec.resolve_live_agent("") is None


@pytest.mark.asyncio
async def test_resolve_live_agent_collaborator_raises_degrades_to_none() -> None:
    class _BoomRegistry:
        def get(self, _id: str) -> Any:
            raise RuntimeError("registry down")

        def all(self) -> list[Any]:  # pragma: no cover
            return []

    rec = WorkItemReconciler(registry=_BoomRegistry())
    assert rec.resolve_live_agent("slot-x") is None


# ── classify ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classify_unassigned_open_dispatchable_live_redispatch() -> None:
    reg = AgentRegistry()
    rec = WorkItemReconciler(registry=reg)
    d = rec.classify(_wi(status="open", assigned_to=None), is_dispatchable=True)
    assert d.action == "live_redispatch"
    assert d.reason == "unassigned_dispatchable"
    assert d.resolved_agent_id is None


@pytest.mark.asyncio
async def test_classify_live_owner_in_progress_skip() -> None:
    reg = await _make_registry_with_agent("slot-live")
    rec = WorkItemReconciler(registry=reg)
    d = rec.classify(
        _wi(status="in_progress", assigned_to="slot-live"), is_dispatchable=True
    )
    assert d.action == "skip"
    assert d.reason == "in_progress_live_owner"
    assert d.resolved_agent_id == "slot-live"


@pytest.mark.asyncio
async def test_classify_live_assignee_open_live_redispatch() -> None:
    reg = await _make_registry_with_agent("slot-live")
    rec = WorkItemReconciler(registry=reg)
    d = rec.classify(
        _wi(status="open", assigned_to="slot-live"), is_dispatchable=True
    )
    assert d.action == "live_redispatch"
    assert d.reason == "assignee_live"
    assert d.resolved_agent_id == "slot-live"


@pytest.mark.asyncio
async def test_classify_dead_assignee_clear_and_reroute() -> None:
    reg = AgentRegistry()
    rec = WorkItemReconciler(registry=reg)
    d = rec.classify(
        _wi(status="open", assigned_to="slot-dead"), is_dispatchable=True
    )
    assert d.action == "clear_and_reroute"
    assert d.reason == "assignee_not_live"
    assert d.resolved_agent_id is None


@pytest.mark.asyncio
async def test_classify_terminal_status_skip_even_if_assignee_dead() -> None:
    reg = AgentRegistry()
    rec = WorkItemReconciler(registry=reg)
    for status in ("done", "failed", "cancelled"):
        d = rec.classify(
            _wi(status=status, assigned_to="slot-dead"), is_dispatchable=True
        )
        assert d.action == "skip"
        assert d.reason == "terminal"


@pytest.mark.asyncio
async def test_classify_not_dispatchable_skip() -> None:
    reg = AgentRegistry()
    rec = WorkItemReconciler(registry=reg)
    d = rec.classify(_wi(status="open", assigned_to=None), is_dispatchable=False)
    assert d.action == "skip"
    assert d.reason == "not_dispatchable"


@pytest.mark.asyncio
async def test_reconcile_decision_carries_assignee_and_resolved_id() -> None:
    reg = await _make_registry_with_agent("slot-live")
    rec = WorkItemReconciler(registry=reg)
    d = rec.classify(
        _wi(wid="wi-42", status="open", assigned_to="slot-live"),
        is_dispatchable=True,
    )
    assert isinstance(d, ReconcileDecision)
    assert d.work_item_id == "wi-42"
    assert d.assignee == "slot-live"
    assert d.resolved_agent_id == "slot-live"
