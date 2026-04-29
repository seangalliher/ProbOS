import json
import re
from types import SimpleNamespace

import pytest

from probos.cognitive.anomaly_window import AnomalyWindowManager
from probos.cognitive.episodic import EpisodicMemory
from probos.config import AnomalyWindowConfig
from probos.events import EventType, LlmHealthChangedEvent
from probos.startup.finalize import _wire_anomaly_window
from probos.types import AnchorFrame, Episode


class _FakeCollection:
    def __init__(self) -> None:
        self.metadata_store: dict[str, dict] = {}
        self.document_store: dict[str, str] = {}

    def get(self, ids: list[str] | None = None, include: list[str] | None = None, **kwargs) -> dict:
        if ids is None:
            return {"ids": list(self.metadata_store), "metadatas": list(self.metadata_store.values())}
        found_ids = [episode_id for episode_id in ids if episode_id in self.metadata_store]
        result = {"ids": found_ids}
        if include and "metadatas" in include:
            result["metadatas"] = [self.metadata_store[episode_id] for episode_id in found_ids]
        return result

    def add(self, ids: list[str], documents: list[str], metadatas: list[dict]) -> None:
        for episode_id, document, metadata in zip(ids, documents, metadatas):
            self.document_store[episode_id] = document
            self.metadata_store[episode_id] = metadata

    def count(self) -> int:
        return len(self.metadata_store)


class _FakeEpisodicMemory:
    def __init__(self) -> None:
        self.manager = None

    def set_anomaly_window_manager(self, manager: AnomalyWindowManager) -> None:
        self.manager = manager


class _FakeRuntime:
    def __init__(self) -> None:
        self.episodic_memory = _FakeEpisodicMemory()
        self.events: list[tuple] = []
        self.listeners: list[tuple] = []

    def _emit_event(self, event_type, data: dict) -> None:
        self.events.append((event_type, data))

    def add_event_listener(self, fn, event_types=None) -> None:
        self.listeners.append((fn, event_types))


def _make_manager(**kwargs) -> AnomalyWindowManager:
    return AnomalyWindowManager(config=AnomalyWindowConfig(**kwargs))


def _make_episode(episode_id: str = "episode-1") -> Episode:
    return Episode(
        id=episode_id,
        user_input="system observation",
        anchors=AnchorFrame(channel="ward_room"),
    )


def test_open_window() -> None:
    manager = _make_manager()

    window_id = manager.open_window("trust_cascade", "trust dropped")

    assert window_id.startswith("aw-")
    assert manager.is_active() is True


def test_close_window() -> None:
    manager = _make_manager()
    window_id = manager.open_window("trust_cascade")

    manager.close_window(window_id)

    assert manager.is_active() is False


def test_get_active_window() -> None:
    manager = _make_manager()

    assert manager.get_active_window() is None
    window_id = manager.open_window("llm_degraded")
    assert manager.get_active_window() == window_id


def test_is_active() -> None:
    manager = _make_manager()

    assert manager.is_active() is False
    window_id = manager.open_window("llm_degraded")
    assert manager.is_active() is True
    manager.close_window(window_id)
    assert manager.is_active() is False


def test_auto_expire() -> None:
    manager = _make_manager(max_window_duration_seconds=0.01)
    manager.open_window("llm_degraded")
    manager._opened_at -= 1.0

    assert manager.get_active_window() is None
    assert manager.is_active() is False


def test_window_id_format() -> None:
    manager = _make_manager()
    window_id = manager.open_window("trust_cascade")

    assert re.fullmatch(r"aw-[0-9a-f]{8}", window_id)


@pytest.mark.asyncio
async def test_episode_stamping(tmp_path) -> None:
    memory = EpisodicMemory(tmp_path / "memory")
    collection = _FakeCollection()
    memory._collection = collection
    manager = _make_manager()
    active_window = manager.open_window("trust_cascade")
    memory.set_anomaly_window_manager(manager)

    await memory.store(_make_episode())

    anchors = json.loads(collection.metadata_store["episode-1"]["anchors_json"])
    assert anchors["anomaly_window_id"] == active_window


@pytest.mark.asyncio
async def test_no_stamp_when_inactive(tmp_path) -> None:
    memory = EpisodicMemory(tmp_path / "memory")
    collection = _FakeCollection()
    memory._collection = collection
    memory.set_anomaly_window_manager(_make_manager())

    await memory.store(_make_episode())

    anchors = json.loads(collection.metadata_store["episode-1"]["anchors_json"])
    assert anchors["anomaly_window_id"] == ""


def test_retrospective_tagging() -> None:
    manager = _make_manager()

    assert manager.tag_recent("aw-12345678", 60.0) == 0


@pytest.mark.asyncio
async def test_trust_cascade_triggers() -> None:
    runtime = _FakeRuntime()
    config = SimpleNamespace(anomaly_window=AnomalyWindowConfig())
    assert _wire_anomaly_window(runtime=runtime, config=config) is True

    listener = runtime.listeners[0][0]
    await listener({"type": EventType.TRUST_CASCADE_WARNING.value, "data": {"score": 0.2}})

    assert runtime._anomaly_window_manager.is_active() is True


@pytest.mark.asyncio
async def test_llm_degraded_triggers() -> None:
    runtime = _FakeRuntime()
    config = SimpleNamespace(anomaly_window=AnomalyWindowConfig())
    _wire_anomaly_window(runtime=runtime, config=config)

    listener = runtime.listeners[0][0]
    event = LlmHealthChangedEvent(old_status="operational", new_status="degraded")
    await listener(event.to_dict())

    assert runtime._anomaly_window_manager.is_active() is True


@pytest.mark.asyncio
async def test_llm_operational_closes() -> None:
    runtime = _FakeRuntime()
    config = SimpleNamespace(anomaly_window=AnomalyWindowConfig())
    _wire_anomaly_window(runtime=runtime, config=config)
    listener = runtime.listeners[0][0]

    await listener(LlmHealthChangedEvent(old_status="operational", new_status="degraded").to_dict())
    await listener(LlmHealthChangedEvent(old_status="degraded", new_status="operational").to_dict())

    assert runtime._anomaly_window_manager.is_active() is False


def test_config_disabled() -> None:
    runtime = _FakeRuntime()
    config = SimpleNamespace(anomaly_window=AnomalyWindowConfig(enabled=False))

    assert _wire_anomaly_window(runtime=runtime, config=config) is False
    assert not hasattr(runtime, "_anomaly_window_manager")


def test_concurrent_signals_single_window() -> None:
    manager = _make_manager()
    first_window = manager.open_window("trust_cascade")
    second_window = manager.open_window("llm_degraded")

    assert second_window == first_window