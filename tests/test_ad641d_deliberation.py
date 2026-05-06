"""AD-641d: Crew Deliberation Protocol tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.deliberation import (
    DeliberationOutcome,
    DeliberationPhase,
    DeliberationProtocol,
    DeliberationSession,
)
from probos.cognitive.deliberation.protocol import DeliberationArgument
from probos.config import DeliberationConfig
from probos.config import DiscoveryLearningConfig
from probos.events import EventType
from probos.ward_room.service import WardRoomService


def _ward_room_mock() -> MagicMock:
    """AsyncMock-spec'd Ward Room with a minimal thread/post return shape."""
    ward = AsyncMock(spec=WardRoomService)
    thread = MagicMock()
    thread.id = "thread-abc"
    ward.create_thread = AsyncMock(return_value=thread)
    post = MagicMock()
    post.id = "post-xyz"
    ward.create_post = AsyncMock(return_value=post)
    return ward


# --------------------------------------------------------------------------- #
# Section 0: EventTypes
# --------------------------------------------------------------------------- #


def test_event_type_deliberation_initiated_exists() -> None:
    assert EventType.DELIBERATION_INITIATED.value == "deliberation_initiated"


def test_event_type_deliberation_argument_submitted_exists() -> None:
    assert EventType.DELIBERATION_ARGUMENT_SUBMITTED.value == "deliberation_argument_submitted"


def test_event_type_deliberation_resolved_exists() -> None:
    assert EventType.DELIBERATION_RESOLVED.value == "deliberation_resolved"


# --------------------------------------------------------------------------- #
# Section 3: Config
# --------------------------------------------------------------------------- #


def test_deliberation_config_defaults() -> None:
    cfg = DeliberationConfig()
    assert cfg.enabled is True
    assert cfg.captain_callsign == "Captain"


# --------------------------------------------------------------------------- #
# Section 2: dataclasses
# --------------------------------------------------------------------------- #


def test_deliberation_session_is_frozen_dataclass() -> None:
    s = DeliberationSession(
        id="s1", topic="t", initiator_id="a", initiator_callsign="cs",
        participants=[], phase=DeliberationPhase.ARGUE, started_at=0.0,
    )
    with pytest.raises(FrozenInstanceError):
        s.topic = "other"  # type: ignore[misc]


def test_deliberation_argument_is_frozen_dataclass() -> None:
    a = DeliberationArgument(
        id="a1", agent_id="x", agent_callsign="cs", stance="for", body="b", submitted_at=0.0,
    )
    with pytest.raises(FrozenInstanceError):
        a.stance = "against"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Section 2: Protocol
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_initiate_creates_session_in_argue_phase() -> None:
    ward = _ward_room_mock()
    protocol = DeliberationProtocol(ward_room=ward)
    session = await protocol.initiate(
        topic="onboard vendor",
        initiator_id="captain-1",
        initiator_callsign="Captain",
        participants=["a", "b"],
    )
    assert session.phase == DeliberationPhase.ARGUE
    assert session.topic == "onboard vendor"
    assert session.thread_id == "thread-abc"
    assert session.outcome == DeliberationOutcome.PENDING
    assert session.participants == ["a", "b"]
    ward.create_thread.assert_awaited_once()
    kwargs = ward.create_thread.await_args.kwargs
    assert kwargs["channel_id"] == "deliberation"
    assert kwargs["thread_mode"] == "discuss"


@pytest.mark.asyncio
async def test_initiate_emits_event() -> None:
    ward = _ward_room_mock()
    emit = MagicMock()
    protocol = DeliberationProtocol(ward_room=ward, emit_event=emit)
    session = await protocol.initiate(
        topic="t", initiator_id="c1", initiator_callsign="Captain",
    )
    emit.assert_called_once()
    args, _ = emit.call_args
    assert args[0] == EventType.DELIBERATION_INITIATED
    assert args[1]["session_id"] == session.id
    assert args[1]["thread_id"] == "thread-abc"


@pytest.mark.asyncio
async def test_submit_argument_appends_and_emits() -> None:
    ward = _ward_room_mock()
    emit = MagicMock()
    protocol = DeliberationProtocol(ward_room=ward, emit_event=emit)
    session = await protocol.initiate(
        topic="t", initiator_id="c1", initiator_callsign="Captain",
    )
    ok = await protocol.submit_argument(
        session_id=session.id, agent_id="a1", agent_callsign="Sci",
        stance="for", body="reasons",
    )
    assert ok is True
    refreshed = protocol.get_session(session.id)
    assert refreshed is not None
    assert len(refreshed.arguments) == 1
    assert refreshed.arguments[0].stance == "for"
    ward.create_post.assert_awaited_once()
    post_kwargs = ward.create_post.await_args.kwargs
    assert post_kwargs["thread_id"] == "thread-abc"
    assert post_kwargs["body"] == "[FOR] reasons"
    # Two emits total: initiate + submit
    assert emit.call_count == 2
    last_args, _ = emit.call_args_list[-1]
    assert last_args[0] == EventType.DELIBERATION_ARGUMENT_SUBMITTED
    assert last_args[1]["stance"] == "for"


@pytest.mark.asyncio
async def test_submit_argument_rejects_after_resolved() -> None:
    ward = _ward_room_mock()
    protocol = DeliberationProtocol(ward_room=ward)
    session = await protocol.initiate(
        topic="t", initiator_id="c1", initiator_callsign="Captain",
    )
    await protocol.resolve(
        session_id=session.id, captain_id="c1", captain_callsign="Captain",
        outcome=DeliberationOutcome.ADOPTED,
    )
    ok = await protocol.submit_argument(
        session_id=session.id, agent_id="a1", agent_callsign="Sci",
        stance="for", body="b",
    )
    assert ok is False


@pytest.mark.asyncio
async def test_submit_argument_rejects_invalid_stance() -> None:
    ward = _ward_room_mock()
    protocol = DeliberationProtocol(ward_room=ward)
    session = await protocol.initiate(
        topic="t", initiator_id="c1", initiator_callsign="Captain",
    )
    ok = await protocol.submit_argument(
        session_id=session.id, agent_id="a1", agent_callsign="Sci",
        stance="maybe", body="b",
    )
    assert ok is False
    refreshed = protocol.get_session(session.id)
    assert refreshed is not None
    assert refreshed.arguments == []


@pytest.mark.asyncio
async def test_resolve_only_captain_callsign_accepts() -> None:
    ward = _ward_room_mock()
    protocol = DeliberationProtocol(ward_room=ward)
    session = await protocol.initiate(
        topic="t", initiator_id="c1", initiator_callsign="Captain",
    )
    bad = await protocol.resolve(
        session_id=session.id, captain_id="x", captain_callsign="Ensign",
        outcome=DeliberationOutcome.ADOPTED,
    )
    assert bad is None
    untouched = protocol.get_session(session.id)
    assert untouched is not None
    assert untouched.phase == DeliberationPhase.ARGUE
    assert untouched.outcome == DeliberationOutcome.PENDING


@pytest.mark.asyncio
async def test_resolve_idempotent_after_first_call() -> None:
    ward = _ward_room_mock()
    protocol = DeliberationProtocol(ward_room=ward)
    session = await protocol.initiate(
        topic="t", initiator_id="c1", initiator_callsign="Captain",
    )
    first = await protocol.resolve(
        session_id=session.id, captain_id="c1", captain_callsign="Captain",
        outcome=DeliberationOutcome.ADOPTED, rationale="ok",
    )
    second = await protocol.resolve(
        session_id=session.id, captain_id="c1", captain_callsign="Captain",
        outcome=DeliberationOutcome.REJECTED, rationale="no",
    )
    assert first is not None
    assert first.outcome == DeliberationOutcome.ADOPTED
    assert second is not None
    assert second.outcome == DeliberationOutcome.ADOPTED
    assert second.rationale == "ok"


@pytest.mark.asyncio
async def test_resolve_emits_event_with_outcome() -> None:
    ward = _ward_room_mock()
    emit = MagicMock()
    protocol = DeliberationProtocol(ward_room=ward, emit_event=emit)
    session = await protocol.initiate(
        topic="t", initiator_id="c1", initiator_callsign="Captain",
    )
    await protocol.resolve(
        session_id=session.id, captain_id="c1", captain_callsign="Captain",
        outcome=DeliberationOutcome.DEFERRED, rationale="later",
    )
    # Two emits: initiate + resolve
    assert emit.call_count == 2
    last_args, _ = emit.call_args_list[-1]
    assert last_args[0] == EventType.DELIBERATION_RESOLVED
    assert last_args[1]["outcome"] == "deferred"
    assert last_args[1]["session_id"] == session.id


@pytest.mark.asyncio
async def test_runtime_deliberation_protocol_is_none_when_disabled() -> None:
    """Round-trip DeliberationConfig.enabled=False through finalize.py.

    Per Wave 8.5 retrospective: cover the disabled-config branch of every
    wiring block.
    """
    from types import SimpleNamespace

    from probos.startup.finalize import finalize_startup

    ward_room = AsyncMock()
    ward_room.get_channel_by_name = AsyncMock(return_value=SimpleNamespace(id="ch", name="All Hands"))
    ward_room.create_thread = AsyncMock()

    registry = MagicMock()
    registry.all.return_value = []
    registry.count = 0

    runtime = MagicMock()
    runtime.ward_room = ward_room
    runtime._cold_start = True
    runtime.registry = registry
    runtime._started = False
    runtime._lifecycle_state = "first_boot"
    runtime._stasis_duration = 0
    runtime._previous_session = None
    runtime.event_log = AsyncMock()
    runtime.pools = {}
    runtime.red_team_agents = []
    runtime.ontology = None
    runtime.trust_network = MagicMock()
    runtime.trust_network.set_department_lookup = MagicMock()
    runtime.trust_network.set_event_callback = MagicMock()
    runtime.dream_scheduler = None
    runtime.self_mod_pipeline = None
    runtime.callsign_registry = None
    runtime.episodic_memory = None
    runtime.intent_bus = None
    runtime._knowledge_store = None
    runtime.initiative = None
    runtime._emergent_detector = None
    runtime.hebbian_router = None
    runtime.bridge_alerts = None
    runtime.behavioral_monitor = None
    runtime.acm = None
    runtime.onboarding = MagicMock()
    runtime.nats_bus = None
    runtime.deliberation_protocol = "sentinel"

    config = MagicMock()
    config.proactive_cognitive.enabled = False
    config.deliberation = DeliberationConfig(enabled=False)
    config.discovery_learning = DiscoveryLearningConfig(enabled=False)  # AD-512 wirer opt-out
    runtime.config = config

    await finalize_startup(runtime=runtime, config=config)

    assert runtime.deliberation_protocol is None
