"""AD-508 v1: DutyScopeProvider tests."""

from __future__ import annotations

import asyncio
import dataclasses
from unittest.mock import MagicMock

import pytest

from probos.cognitive.scoped_cognition import DutyScopeProvider, DutyScopeSnapshot
from probos.config import SystemConfig
from probos.events import EventType
from probos.startup.finalize import _wire_duty_scope_provider


# ---------- DutyScopeSnapshot --------------------------------------------


def test_duty_scope_snapshot_is_frozen_dataclass() -> None:
    snap = DutyScopeSnapshot(agent_id="a1", open_work_item_count=0, work_item_titles=(), captured_at=1.0)
    assert dataclasses.is_dataclass(snap)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.agent_id = "other"  # type: ignore[misc]


# ---------- snapshot() --------------------------------------------------


def test_snapshot_empty_agent_id_returns_empty() -> None:
    runtime = MagicMock()
    provider = DutyScopeProvider(runtime)
    snap = asyncio.run(provider.snapshot(""))
    assert snap.agent_id == ""
    assert snap.open_work_item_count == 0
    assert snap.work_item_titles == ()


def test_snapshot_no_work_item_store_returns_empty() -> None:
    runtime = MagicMock(spec=[])  # no work_item_store attribute
    provider = DutyScopeProvider(runtime)
    snap = asyncio.run(provider.snapshot("agent_a"))
    assert snap.agent_id == "agent_a"
    assert snap.open_work_item_count == 0
    assert snap.work_item_titles == ()


def test_snapshot_calls_list_work_items_with_open_status_assigned_to() -> None:
    runtime = MagicMock()

    async def _list(**kwargs):
        _list.kwargs = kwargs  # type: ignore[attr-defined]
        return []

    runtime.work_item_store.list_work_items = _list
    provider = DutyScopeProvider(runtime)
    asyncio.run(provider.snapshot("agent_b"))
    assert _list.kwargs == {"status": "open", "assigned_to": "agent_b", "limit": 5}  # type: ignore[attr-defined]


def test_snapshot_extracts_titles_up_to_5() -> None:
    runtime = MagicMock()
    items = [MagicMock(title=f"t{i}") for i in range(7)]

    async def _list(**kwargs):
        return items[:5]

    runtime.work_item_store.list_work_items = _list
    provider = DutyScopeProvider(runtime)
    snap = asyncio.run(provider.snapshot("agent_c"))
    assert snap.open_work_item_count == 5
    assert snap.work_item_titles == ("t0", "t1", "t2", "t3", "t4")


def test_snapshot_emits_duty_scope_queried_event() -> None:
    runtime = MagicMock()
    captured: list[tuple] = []

    async def _list(**kwargs):
        return [MagicMock(title="hello")]

    runtime.work_item_store.list_work_items = _list

    def emit(event_type, payload):
        captured.append((event_type, payload))

    provider = DutyScopeProvider(runtime, emit_event=emit)
    asyncio.run(provider.snapshot("agent_d"))
    assert len(captured) == 1
    evt_type, payload = captured[0]
    assert evt_type == EventType.DUTY_SCOPE_QUERIED
    assert payload == {"agent_id": "agent_d", "open_count": 1}


def test_snapshot_list_work_items_failure_returns_empty_and_does_not_raise() -> None:
    runtime = MagicMock()

    async def _list(**kwargs):
        raise RuntimeError("db down")

    runtime.work_item_store.list_work_items = _list
    provider = DutyScopeProvider(runtime)
    snap = asyncio.run(provider.snapshot("agent_e"))
    assert snap.agent_id == "agent_e"
    assert snap.open_work_item_count == 0
    assert snap.work_item_titles == ()


# ---------- Wiring ------------------------------------------------------


def test_runtime_attribute_set_when_enabled() -> None:
    runtime = MagicMock()
    config = SystemConfig()
    assert config.scoped_cognition.enabled is True
    wired = _wire_duty_scope_provider(runtime=runtime, config=config)
    assert wired is True
    assert isinstance(runtime.duty_scope_provider, DutyScopeProvider)


def test_runtime_attribute_not_set_when_disabled() -> None:
    runtime = MagicMock()
    config = SystemConfig()
    config.scoped_cognition.enabled = False
    wired = _wire_duty_scope_provider(runtime=runtime, config=config)
    assert wired is False
