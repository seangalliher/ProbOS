"""BF-331: Workforce resource registration ordering.

``_register_workforce_resources`` ran during the communication startup phase
*before* ``self.work_item_store`` was assigned from ``init_communication``'s
result, so its ``if not store: return`` guard fired and zero BookableResources
were registered — making every dispatched task render as "Unassigned" on the
Kanban board.

BF-331 adds an explicit ``work_item_store`` parameter so the startup phase can
pass the freshly-created store directly. These tests prove registration works
when the store is passed explicitly even while ``self.work_item_store`` is
still ``None``.
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.runtime import ProbOSRuntime


class _FakeAgent:
    def __init__(self, agent_uuid: str, agent_type: str) -> None:
        self.agent_uuid = agent_uuid
        self.id = agent_uuid
        self.agent_type = agent_type
        self.callsign = agent_type.title()
        self.department = "counseling"
        self.personality = object()  # marks this as a crew agent


class _FakeRegistry:
    def __init__(self, agents: list[_FakeAgent]) -> None:
        self._agents = agents

    def all(self) -> list[_FakeAgent]:
        return list(self._agents)


class _FakeWorkforceConfig:
    default_capacity = 1.0


class _FakeConfig:
    workforce = _FakeWorkforceConfig()


class _RecordingStore:
    def __init__(self) -> None:
        self.resources: list[Any] = []
        self.calendars: list[Any] = []

    def register_resource(self, resource: Any) -> None:
        self.resources.append(resource)

    def register_calendar(self, calendar: Any) -> None:
        self.calendars.append(calendar)


def _make_runtime(work_item_store: Any) -> ProbOSRuntime:
    rt = object.__new__(ProbOSRuntime)
    rt.work_item_store = work_item_store
    rt.registry = _FakeRegistry(
        [_FakeAgent("counselor-uuid-1", "counselor")]
    )
    rt.config = _FakeConfig()
    rt.trust_network = None
    return rt


@pytest.mark.asyncio
async def test_registers_resources_when_store_passed_before_attr_set() -> None:
    """BF-331: store passed explicitly registers even when attr is None."""
    store = _RecordingStore()
    rt = _make_runtime(work_item_store=None)  # attr not yet assigned

    await rt._register_workforce_resources(store)

    assert len(store.resources) == 1
    assert store.resources[0].resource_id == "counselor-uuid-1"
    assert store.resources[0].active is True
    assert len(store.calendars) == 1
    assert store.calendars[0].resource_id == "counselor-uuid-1"


@pytest.mark.asyncio
async def test_falls_back_to_instance_attr_when_no_arg() -> None:
    """Existing zero-argument call sites keep working via the attr fallback."""
    store = _RecordingStore()
    rt = _make_runtime(work_item_store=store)

    await rt._register_workforce_resources()

    assert len(store.resources) == 1
    assert store.resources[0].resource_id == "counselor-uuid-1"


@pytest.mark.asyncio
async def test_no_store_available_is_a_noop() -> None:
    """No store anywhere: the method degrades to a no-op without raising."""
    rt = _make_runtime(work_item_store=None)

    await rt._register_workforce_resources(None)  # nothing to register against
