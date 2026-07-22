from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from probos.runtime import ProbOSRuntime
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.task_completion_notifier import (
    notify_captain_of_task_completion,
)
from probos.workforce import WorkItem, WorkItemStore


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


class _RuntimeEnvelopeRecorder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.nats_bus = None

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        ProbOSRuntime._emit_event(self, event_type, data)  # type: ignore[arg-type]

    def _check_night_order_escalation(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        return None

    def _emit_event_local(self, event: dict[str, Any], type_str: str) -> None:
        self.events.append(copy.deepcopy(event))


def _yeo_item(**overrides: Any) -> dict[str, Any]:
    item = {
        "id": "wi-abc123456789",
        "title": "Summarize the latest scout report",
        "status": "done",
        "work_type": "task",
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


def _dict_event(work_item: dict[str, Any], new_status: str) -> dict[str, Any]:
    return {
        "type": "work_item_status_changed",
        "data": {
            "work_item": work_item,
            "old_status": "in_progress",
            "new_status": new_status,
        },
        "timestamp": 1_000.0,
    }


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


async def test_ad846_dict_and_object_envelopes_are_exactly_equivalent() -> None:
    item = WorkItem(
        id="wi-abc123456789",
        title="Summarize the latest scout report",
        description="Produce a concise summary",
        work_type="task",
        status="done",
        assigned_to="yeoman-0abc1234",
        created_by="yeoman-0abc1234",
        tags=["yeo-delegated"],
        metadata={"dispatchable": True},
        created_at=1_000.0,
        updated_at=1_001.0,
    ).to_dict()
    object_ward = _FakeWardRoom()
    dict_ward = _FakeWardRoom()
    object_runtime = _Runtime(
        object_ward,
        registry=_FakeRegistry(_FakeYeo()),
    )
    dict_runtime = _Runtime(
        dict_ward,
        registry=_FakeRegistry(_FakeYeo()),
    )

    await notify_captain_of_task_completion(
        object_runtime,
        _event(copy.deepcopy(item), "done"),
    )
    await notify_captain_of_task_completion(
        dict_runtime,
        _dict_event(copy.deepcopy(item), "done"),
    )

    assert dict_ward.created_channels == object_ward.created_channels
    assert dict_ward.created_threads == object_ward.created_threads
    assert dict_ward.created_threads == [{
        "channel_id": "ch-new",
        "author_id": "yeoman-0abc1234",
        "title": "[Task update from @Yeo]",
        "body": "Task complete: Summarize the latest scout report.",
        "author_callsign": "Yeo",
    }]


async def test_real_store_emitted_non_session_event_posts_same_dm(
    tmp_path: Path,
) -> None:
    events = _RuntimeEnvelopeRecorder()
    store = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"),
        emit_event=events,
        tick_interval=1_000,
        connection_factory=SQLiteConnectionFactory(),
    )
    await store.start()
    try:
        item = await store.create_work_item(
            id="yeo-real-event-task",
            title="Summarize the latest scout report",
            description="Produce a concise summary",
            work_type="task",
            status="in_progress",
            assigned_to="yeoman-0abc1234",
            created_by="yeoman-0abc1234",
            tags=["yeo-delegated"],
            metadata={"dispatchable": True},
        )
        updated = await store.transition_work_item(item.id, "done")
        assert updated is not None
        event = next(
            event
            for event in reversed(events.events)
            if event.get("type") == "work_item_status_changed"
        )
        ward = _FakeWardRoom()
        runtime = _Runtime(ward, registry=_FakeRegistry(_FakeYeo()))

        await notify_captain_of_task_completion(runtime, event)

        assert len(ward.created_threads) == 1
        assert ward.created_threads[0]["body"] == (
            "Task complete: Summarize the latest scout report."
        )
    finally:
        await store.stop()


async def test_crew_session_live_dict_never_creates_ad846_dm() -> None:
    ward = _FakeWardRoom()
    runtime = _Runtime(ward, registry=_FakeRegistry(_FakeYeo()))

    await notify_captain_of_task_completion(
        runtime,
        _dict_event(_yeo_item(work_type="crew_session"), "done"),
    )

    assert ward.created_channels == []
    assert ward.created_threads == []


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
