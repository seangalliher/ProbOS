from __future__ import annotations

from typing import Any

from probos.capability_request_notifier import (
    notify_captain_of_capability_request,
)


class _FakeChannel:
    def __init__(self, channel_id: str, name: str, channel_type: str) -> None:
        self.id = channel_id
        self.name = name
        self.channel_type = channel_type


class _FakeWardRoom:
    def __init__(self, channels: list[_FakeChannel] | None = None) -> None:
        self._channels = channels or []
        self.created_channels: list[dict[str, Any]] = []
        self.created_threads: list[dict[str, Any]] = []

    async def list_channels(self) -> list[_FakeChannel]:
        return list(self._channels)

    async def create_channel(self, **kwargs: Any) -> _FakeChannel:
        self.created_channels.append(kwargs)
        ch = _FakeChannel("ch-new", kwargs["name"], kwargs["channel_type"])
        self._channels.append(ch)
        return ch

    async def create_thread(self, **kwargs: Any) -> None:
        self.created_threads.append(kwargs)


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class _FakeRegistry:
    def __init__(self, agent: _FakeAgent | None) -> None:
        self._agent = agent

    def get(self, agent_id: str) -> _FakeAgent | None:
        return self._agent


class _FakeCallsignRegistry:
    def __init__(self, callsign: str) -> None:
        self._callsign = callsign

    def get_callsign(self, agent_type: str) -> str:
        return self._callsign


class _Event:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


class _Runtime:
    def __init__(self, ward_room: Any, registry: Any = None, callsign_registry: Any = None) -> None:
        self.ward_room = ward_room
        self.registry = registry
        self.callsign_registry = callsign_registry


async def test_notifier_creates_dm_channel_and_thread() -> None:
    ward = _FakeWardRoom()
    runtime = _Runtime(
        ward,
        registry=_FakeRegistry(_FakeAgent("scraper")),
        callsign_registry=_FakeCallsignRegistry("Scout"),
    )
    event = _Event({
        "id": "req-123456789012",
        "agent_id": "agent-abcdef012345",
        "kind": "install",
        "target": "numpy",
        "work_item_id": "wi-1",
    })

    await notify_captain_of_capability_request(runtime, event)

    assert len(ward.created_channels) == 1
    assert ward.created_channels[0]["name"] == "dm-captain-agent-ab"
    assert ward.created_channels[0]["channel_type"] == "dm"
    assert len(ward.created_threads) == 1
    thread = ward.created_threads[0]
    assert "Scout" in thread["title"]
    assert "numpy" in thread["body"]
    assert thread["author_callsign"] == "Scout"


async def test_notifier_reuses_existing_dm_channel() -> None:
    existing = _FakeChannel("ch-existing", "dm-captain-agent-ab", "dm")
    ward = _FakeWardRoom(channels=[existing])
    runtime = _Runtime(ward, registry=_FakeRegistry(None), callsign_registry=None)
    event = _Event({
        "id": "req-1",
        "agent_id": "agent-abcdef012345",
        "kind": "grant",
        "target": "fs.write",
    })

    await notify_captain_of_capability_request(runtime, event)

    assert ward.created_channels == []
    assert len(ward.created_threads) == 1
    assert ward.created_threads[0]["channel_id"] == "ch-existing"


async def test_notifier_degrades_when_no_ward_room() -> None:
    runtime = _Runtime(ward_room=None)
    event = _Event({"id": "req-1", "agent_id": "agent-1", "kind": "grant", "target": "x"})

    # Must not raise.
    await notify_captain_of_capability_request(runtime, event)


async def test_notifier_degrades_when_no_agent_id() -> None:
    ward = _FakeWardRoom()
    runtime = _Runtime(ward)
    event = _Event({"id": "req-1", "agent_id": "", "kind": "grant", "target": "x"})

    await notify_captain_of_capability_request(runtime, event)

    assert ward.created_channels == []
    assert ward.created_threads == []
