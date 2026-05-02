"""AD-475 Captain's Ready Room tests."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.ready_room import (
    Idea,
    IdeaCaptureStore,
    ReadyRoomSession,
    ReadyRoomSessionManager,
    SessionPhase,
)
from probos.config import ReadyRoomConfig
from probos.events import EventType


# ----- EventTypes -----


def test_event_type_ready_room_session_started_exists():
    assert EventType.READY_ROOM_SESSION_STARTED.value == "ready_room_session_started"


def test_event_type_idea_captured_exists():
    assert EventType.IDEA_CAPTURED.value == "idea_captured"


# ----- Config -----


def test_ready_room_config_defaults():
    cfg = ReadyRoomConfig()
    assert cfg.enabled is True
    assert cfg.idea_store_filename == "ready_room/ideas.json"
    assert cfg.wardroom_channel_id == "ready_room"


# ----- Idea dataclass -----


def test_idea_immutable():
    """Frozen dataclass; replace returns a new instance."""
    orig = Idea(id="a", title="t", body="b", captured_at=1.0)
    updated = replace(orig, status="resolved")
    assert orig.status == "open"
    assert updated.status == "resolved"
    assert orig is not updated


# ----- IdeaCaptureStore -----


def test_idea_store_capture_persists_and_emits(tmp_path):
    store_path = tmp_path / "ideas.json"
    emit = MagicMock()
    store = IdeaCaptureStore(store_path=store_path, emit_event=emit)

    idea = store.capture(title="Refactor decomposer", body="LLM tier-1 gate")

    assert idea.title == "Refactor decomposer"
    assert idea.status == "open"
    assert store_path.exists()
    emit.assert_called_once()
    et, payload = emit.call_args[0]
    assert et == EventType.IDEA_CAPTURED
    assert payload["idea_id"] == idea.id


def test_idea_store_list_ideas_filters_by_status(tmp_path):
    store_path = tmp_path / "ideas.json"
    store = IdeaCaptureStore(store_path=store_path)
    a = store.capture(title="A")
    b = store.capture(title="B")
    c = store.capture(title="C")
    store.mark_status(a.id, "resolved")

    open_ideas = store.list_ideas(status="open")
    all_ideas = store.list_ideas(status="all")

    assert len(open_ideas) == 2
    assert {i.id for i in open_ideas} == {b.id, c.id}
    assert len(all_ideas) == 3


def test_idea_store_mark_status_rejects_invalid_status(tmp_path):
    store = IdeaCaptureStore(store_path=tmp_path / "ideas.json")
    idea = store.capture(title="X")
    assert store.mark_status(idea.id, "garbage") is False


def test_idea_store_get_idea_returns_none_for_unknown(tmp_path):
    store = IdeaCaptureStore(store_path=tmp_path / "ideas.json")
    assert store.get_idea("nonexistent") is None


# ----- ReadyRoomSessionManager -----


@pytest.mark.asyncio
async def test_session_manager_start_session_creates_thread_and_emits():
    fake_thread = SimpleNamespace(id="t1")
    rt = SimpleNamespace()
    rt.ward_room = SimpleNamespace()
    rt.ward_room.create_thread = AsyncMock(return_value=fake_thread)
    emit = MagicMock()

    manager = ReadyRoomSessionManager(runtime=rt, emit_event=emit)
    session = await manager.start_session(
        topic="Phase 36 architecture", participants=["bones", "scotty"],
    )

    assert isinstance(session, ReadyRoomSession)
    assert session.thread_id == "t1"
    assert session.phase == SessionPhase.PRESENT.value
    assert session.topic == "Phase 36 architecture"
    rt.ward_room.create_thread.assert_awaited_once()
    emit.assert_called_once()
    et, payload = emit.call_args[0]
    assert et == EventType.READY_ROOM_SESSION_STARTED
    assert payload["session_id"] == session.id


@pytest.mark.asyncio
async def test_session_manager_start_session_handles_ward_room_failure():
    rt = SimpleNamespace()
    rt.ward_room = SimpleNamespace()
    rt.ward_room.create_thread = AsyncMock(side_effect=RuntimeError("boom"))
    emit = MagicMock()

    manager = ReadyRoomSessionManager(runtime=rt, emit_event=emit)
    session = await manager.start_session(topic="T", participants=["a"])

    # Fail-soft: session continues without thread (Wave-5 superset-filter #4)
    assert session.thread_id == ""
    assert session.journal_correlation_id != ""
    emit.assert_called_once()


def test_session_manager_advance_phase_progresses_present_discuss_converge():
    rt = SimpleNamespace(ward_room=None)
    manager = ReadyRoomSessionManager(runtime=rt)
    # Construct session directly without async create_thread call
    sess = ReadyRoomSession(
        id="sid", topic="t", participants=["a"],
        phase=SessionPhase.PRESENT.value,
    )
    manager._sessions[sess.id] = sess

    s1 = manager.advance_phase("sid")
    assert s1.phase == SessionPhase.DISCUSS.value
    s2 = manager.advance_phase("sid")
    assert s2.phase == SessionPhase.CONVERGE.value
    s3 = manager.advance_phase("sid")
    # Idempotent at terminal
    assert s3.phase == SessionPhase.CONVERGE.value


def test_session_manager_end_session_sets_ended_at_and_phase_converge():
    import time as _time

    rt = SimpleNamespace(ward_room=None)
    manager = ReadyRoomSessionManager(runtime=rt)
    sess = ReadyRoomSession(
        id="sid2", topic="t", participants=["a"],
        phase=SessionPhase.DISCUSS.value, started_at=_time.time(),
    )
    manager._sessions[sess.id] = sess

    ended = manager.end_session("sid2")
    assert ended.phase == SessionPhase.CONVERGE.value
    assert ended.ended_at > 0
    active = manager.list_sessions(state="active")
    assert ended.id not in {s.id for s in active}


def test_session_manager_advance_phase_returns_none_for_unknown_id():
    rt = SimpleNamespace(ward_room=None)
    manager = ReadyRoomSessionManager(runtime=rt)
    assert manager.advance_phase("nonexistent") is None
