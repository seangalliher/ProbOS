from __future__ import annotations

from typing import Any

from probos.task_completion_notifier import (
    notify_captain_of_task_completion,
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


class _FakeYeo:
    def __init__(self, agent_id: str = "yeoman-0abc1234", callsign: str = "Yeo") -> None:
        self.id = agent_id
        self.callsign = callsign


class _FakeRegistry:
    def __init__(self, yeo: _FakeYeo | None) -> None:
        self._yeo = yeo

    def get_by_pool(self, pool: str) -> list[_FakeYeo]:
        if pool == "yeoman" and self._yeo is not None:
            return [self._yeo]
        return []


class _BoomRegistry:
    def get_by_pool(self, pool: str) -> list[Any]:
        raise RuntimeError("registry unavailable")


class _Event:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


class _Runtime:
    def __init__(self, ward_room: Any, registry: Any = None) -> None:
        self.ward_room = ward_room
        self.registry = registry


def _yeo_item(**overrides: Any) -> dict[str, Any]:
    item = {
        "id": "wi-abc123456789",
        "title": "Summarize the latest scout report",
        "status": "done",
        "tags": ["yeo-delegated"],
        "metadata": {"dispatchable": True},
    }
    item.update(overrides)
    return item


def _event(work_item: dict[str, Any], new_status: str) -> _Event:
    return _Event({
        "work_item": work_item,
        "old_status": "in_progress",
        "new_status": new_status,
    })


async def test_done_yeo_delegated_posts_captain_dm() -> None:
    ward = _FakeWardRoom()
    runtime = _Runtime(ward, registry=_FakeRegistry(_FakeYeo()))

    await notify_captain_of_task_completion(runtime, _event(_yeo_item(), "done"))

    assert len(ward.created_channels) == 1
    assert ward.created_channels[0]["name"] == "dm-captain-yeoman-0"
    assert ward.created_channels[0]["channel_type"] == "dm"
    assert len(ward.created_threads) == 1
    thread = ward.created_threads[0]
    assert "Yeo" in thread["title"]
    assert "Task complete" in thread["body"]
    assert "Summarize the latest scout report" in thread["body"]
    assert thread["author_callsign"] == "Yeo"


async def test_failed_uses_distinct_message() -> None:
    ward = _FakeWardRoom()
    runtime = _Runtime(ward, registry=_FakeRegistry(_FakeYeo()))

    await notify_captain_of_task_completion(
        runtime, _event(_yeo_item(status="failed"), "failed")
    )

    assert len(ward.created_threads) == 1
    body = ward.created_threads[0]["body"]
    assert "did not finish" in body
    assert "Task complete" not in body


async def test_missing_yeo_delegated_tag_no_dm() -> None:
    ward = _FakeWardRoom()
    runtime = _Runtime(ward, registry=_FakeRegistry(_FakeYeo()))

    await notify_captain_of_task_completion(
        runtime, _event(_yeo_item(tags=["routine"]), "done")
    )

    assert ward.created_channels == []
    assert ward.created_threads == []


async def test_missing_dispatchable_metadata_no_dm() -> None:
    ward = _FakeWardRoom()
    runtime = _Runtime(ward, registry=_FakeRegistry(_FakeYeo()))

    await notify_captain_of_task_completion(
        runtime, _event(_yeo_item(metadata={}), "done")
    )

    assert ward.created_threads == []


async def test_non_terminal_status_no_dm() -> None:
    ward = _FakeWardRoom()
    runtime = _Runtime(ward, registry=_FakeRegistry(_FakeYeo()))

    await notify_captain_of_task_completion(
        runtime, _event(_yeo_item(status="in_progress"), "in_progress")
    )

    assert ward.created_threads == []


async def test_degrades_when_no_ward_room() -> None:
    runtime = _Runtime(ward_room=None, registry=_FakeRegistry(_FakeYeo()))

    # Must not raise.
    await notify_captain_of_task_completion(runtime, _event(_yeo_item(), "done"))


async def test_degrades_when_no_yeo_agent() -> None:
    ward = _FakeWardRoom()
    runtime = _Runtime(ward, registry=_FakeRegistry(None))

    await notify_captain_of_task_completion(runtime, _event(_yeo_item(), "done"))

    assert ward.created_channels == []
    assert ward.created_threads == []


async def test_degrades_when_registry_raises() -> None:
    ward = _FakeWardRoom()
    runtime = _Runtime(ward, registry=_BoomRegistry())

    # Must not raise despite the registry blowing up.
    await notify_captain_of_task_completion(runtime, _event(_yeo_item(), "done"))

    assert ward.created_threads == []


async def test_reuses_existing_dm_channel() -> None:
    existing = _FakeChannel("ch-existing", "dm-captain-yeoman-0", "dm")
    ward = _FakeWardRoom(channels=[existing])
    runtime = _Runtime(ward, registry=_FakeRegistry(_FakeYeo()))

    await notify_captain_of_task_completion(runtime, _event(_yeo_item(), "done"))

    assert ward.created_channels == []
    assert len(ward.created_threads) == 1
    assert ward.created_threads[0]["channel_id"] == "ch-existing"
