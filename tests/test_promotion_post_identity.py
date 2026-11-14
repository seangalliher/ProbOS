"""Promotion posts name their author: D5-R1 of #1754 and F-529 of #1523.

``CognitiveAgent._announce_promotion_request`` (a procedure's promotion request) and ``_teach_procedure`` (a taught
procedure) post to the Ward Room, open a DM channel and subscribe its members. They used to read
``getattr(self, "_agent_id", agent_type)`` and ``getattr(self, "_callsign", agent_type)``; no agent has either
attribute, so every such post carried the agent's TYPE as its author id, as its DM channel's creator and member, and
as the id the shadow admission check was handed. These cases drive a real ``CognitiveAgent`` into a real
``WardRoomService`` on a temporary database and read back what was stored; one case hands the stored author to the
production router's target selection.

Synthetic fixtures only. The cases marked ``built`` fail on the base at their own assert and pass once the two
methods read ``self.id`` and ``self.callsign``; ``PROMOTION_POST_RUNXFAIL=1`` runs them as plain cases.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

import probos.ward_room.channels as ward_room_channels
import probos.ward_room.service as ward_room_service
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import AgentState
from probos.ward_room import WardRoomService
from probos.ward_room_router import WardRoomRouter

built = (
    (lambda func: func)
    if os.environ.get("PROMOTION_POST_RUNXFAIL") == "1"
    else pytest.mark.xfail(raises=AssertionError, strict=True)
)

_AGENT_ID = "test-id"
_AGENT_TYPE = "test-agent"
_SHORT_TYPE = "t-agent"
_CALLSIGN = "test-callsign"
_PROCEDURE_ID = "test-procedure-id"
_TARGET = "test-peer"


class _PromotingAgent(CognitiveAgent):
    """A real agent. Nothing in this file sets a private attribute on it."""

    agent_type = _AGENT_TYPE
    instructions = "Test instructions."


class _ShortTypeAgent(_PromotingAgent):
    """The same agent with a type of fewer than 8 characters (a DM channel name keeps 8 characters of each id)."""

    agent_type = _SHORT_TYPE


class _Ontology:
    """What the two methods ask of the ontology: the department of an agent type."""

    def __init__(self, department: str) -> None:
        self._department = department

    def get_agent_department(self, agent_type: str) -> str:
        return self._department


class _Trust:
    """What a teaching reads of the trust network: a score above the teaching threshold."""

    def get_score(self, agent_id: str) -> float:
        return 0.9


def _promotion_result(criticality: str) -> dict:
    return {
        "eligible": True,
        "criticality": criticality,
        "procedure_name": "test-procedure",
        "procedure_description": "A synthetic procedure.",
        "compilation_level": 4,
        "intent_types": ["test_intent"],
        "quality_metrics": {"effective_rate": 0.9, "total_completions": 12},
    }


class _ProcedureStore:
    """The procedure-store reads the two methods make."""

    def __init__(self, criticality: str) -> None:
        self._criticality = criticality

    async def request_promotion(self, procedure_id: str) -> dict:
        return _promotion_result(self._criticality)

    async def get(self, procedure_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            name="test-procedure",
            description="A synthetic procedure.",
            compilation_level=5,
            steps=[SimpleNamespace(step_number=1, action="run the first step")],
            preconditions=[],
            postconditions=[],
        )

    async def get_promotion_status(self, procedure_id: str) -> str:
        return "approved"

    async def get_quality_metrics(self, procedure_id: str) -> dict:
        return {"total_completions": 12, "effective_rate": 0.95}


@pytest_asyncio.fixture
async def room(tmp_path):
    service = WardRoomService(db_path=str(tmp_path / "ward_room.db"))
    await service.start()
    yield service
    await service.stop()


@pytest.fixture
def presented(monkeypatch):
    """The id each shadow store-write check was handed, in order: both Ward Room modules call ``check_at``."""
    seen: list[object] = []

    def record(service: object, *, effect: str, presented_id: object) -> None:
        seen.append(presented_id)

    monkeypatch.setattr(ward_room_channels, "check_at", record)
    monkeypatch.setattr(ward_room_service, "check_at", record)
    return seen


def _slot_id(agent_type: str) -> str:
    """An agent id in the production shape ``{agent_type}_{pool}_{index}_{hash8}`` (``substrate/identity.py``)."""
    return f"{agent_type}_test-pool_0_abcd1234"


def make_agent(
    room: WardRoomService,
    *,
    agent_cls: type[CognitiveAgent] = _PromotingAgent,
    agent_id: str = _AGENT_ID,
    callsign: str = _CALLSIGN,
    department: str = "",
    criticality: str = "low",
) -> CognitiveAgent:
    """A real agent, built as the spawner builds one (the pool and the agent id in the constructor) and given the
    callsign ``AgentOnboardingService.wire_agent`` sets. Its runtime holds the real Ward Room."""
    runtime = SimpleNamespace(
        ward_room=room,
        ontology=_Ontology(department) if department else None,
        trust_network=_Trust(),
        procedure_store=_ProcedureStore(criticality),
    )
    agent = agent_cls(pool="test-pool", agent_id=agent_id, runtime=runtime)
    agent.callsign = callsign
    return agent


async def _request_promotion(agent: CognitiveAgent) -> None:
    result = await agent._request_procedure_promotion(_PROCEDURE_ID)
    assert result is not None and result["eligible"] is True, "the promotion request never reached the announcement"


async def _teach(agent: CognitiveAgent) -> None:
    assert await agent._teach_procedure(_PROCEDURE_ID, _TARGET) is True, "the teaching DM was not sent"


async def _stored(room: WardRoomService) -> tuple[list, list]:
    """Every thread in the room, and its DM channels."""
    channels = await room.list_channels()
    threads = [thread for channel in channels for thread in await room.list_threads(channel.id)]
    return threads, [channel for channel in channels if channel.channel_type == "dm"]


def _router_over(agent: CognitiveAgent) -> WardRoomRouter:
    """The production router over a registry that holds just this agent; the collaborators it does not use to pick
    targets are doubles, as tests/test_ad621_channel_visibility.py builds it."""
    registry = MagicMock()
    registry.all.return_value = [agent]
    config = MagicMock()
    config.ward_room.event_coalesce_ms = 200
    return WardRoomRouter(
        ward_room=MagicMock(),
        registry=registry,
        intent_bus=MagicMock(),
        trust_network=MagicMock(),
        ontology=None,
        callsign_registry=MagicMock(),
        episodic_memory=None,
        event_emitter=MagicMock(),
        event_log=MagicMock(),
        config=config,
    )


_DRIVERS = pytest.mark.parametrize("drive", [_request_promotion, _teach], ids=["promotion-request", "teaching"])


@built
@_DRIVERS
async def test_the_posts_and_the_dm_channel_carry_the_agents_own_id(drive, room, presented):
    agent = make_agent(room)
    assert agent.id == _AGENT_ID and agent.agent_type == _AGENT_TYPE, "the premise: the agent's id is not its type"

    await drive(agent)

    threads, dms = await _stored(room)
    assert threads and len(dms) == 1, (threads, dms)
    assert {thread.author_id for thread in threads} == {agent.id}
    assert dms[0].created_by == agent.id
    assert agent.id in await room.get_channel_subscriber_ids(dms[0].id)
    assert presented and set(presented) == {agent.id}


@built
@_DRIVERS
async def test_the_posts_are_signed_with_the_agents_callsign(drive, room):
    agent = make_agent(room, callsign=_CALLSIGN)

    await drive(agent)

    threads, dms = await _stored(room)
    assert threads and len(dms) == 1, (threads, dms)
    assert {thread.author_callsign for thread in threads} == {_CALLSIGN}
    assert dms[0].description.startswith(f"DM: {_CALLSIGN} ")


@built
async def test_the_promoting_agent_is_not_its_own_dm_recipient(room):
    agent = make_agent(room, agent_id=_slot_id(_AGENT_TYPE))
    agent.state = AgentState.ACTIVE  # alive, as a started agent is

    await _request_promotion(agent)

    threads, dms = await _stored(room)
    assert len(dms) == 1, dms
    posted = [thread for thread in threads if thread.channel_id == dms[0].id]
    assert len(posted) == 1, threads
    with patch("probos.ward_room_router.is_crew_agent", return_value=True):
        targets = _router_over(agent).find_targets_for_agent(dms[0], posted[0].author_id, mentions=[])
    assert targets == [], (posted[0].author_id, targets)  # the router drops the author by id; nobody else is in the DM


@_DRIVERS
async def test_an_agent_with_no_callsign_is_signed_with_its_type(drive, room):
    agent = make_agent(room, callsign="")

    await drive(agent)

    threads, dms = await _stored(room)
    assert threads and len(dms) == 1, (threads, dms)
    assert {thread.author_callsign for thread in threads} == {agent.agent_type}
    assert dms[0].description.startswith(f"DM: {agent.agent_type} ")


@pytest.mark.parametrize(
    ("drive", "criticality", "department", "key"),
    [
        (_request_promotion, "high", "", "captain"),
        (_request_promotion, "low", "engineering", CognitiveAgent._DEPARTMENT_CHIEFS["engineering"]),
        (_teach, "low", "", _TARGET),
    ],
    ids=["captain-approver", "department-chief-approver", "teaching-target"],
)
async def test_the_second_member_of_the_dm_is_still_a_name_not_an_agent_id(drive, criticality, department, key, room):
    """The gap F-528 of #1523 records stays visible: the approver and the teaching target are names, not ids."""
    agent = make_agent(room, criticality=criticality, department=department)

    await drive(agent)

    _, dms = await _stored(room)
    assert len(dms) == 1, dms
    members = await room.get_channel_subscriber_ids(dms[0].id)
    assert key in members and len(members) == 2, (key, members)


async def test_a_dm_channel_opened_under_a_long_type_is_found_and_left_as_it_was(room):
    agent = make_agent(room, agent_id=_slot_id(_AGENT_TYPE))
    old = await room.get_or_create_dm_channel(_AGENT_TYPE, "captain")  # what the old reads opened

    await _request_promotion(agent)

    _, dms = await _stored(room)
    assert [dm.id for dm in dms] == [old.id], dms
    assert dms[0].created_by == _AGENT_TYPE
    assert await room.get_channel_subscriber_ids(old.id) == {_AGENT_TYPE, "captain"}


@built
async def test_a_dm_channel_opened_under_a_short_type_is_left_unused_and_a_new_one_opens(room):
    agent = make_agent(room, agent_cls=_ShortTypeAgent, agent_id=_slot_id(_SHORT_TYPE))
    old = await room.get_or_create_dm_channel(_SHORT_TYPE, "captain")  # what the old reads opened

    await _request_promotion(agent)

    _, dms = await _stored(room)
    assert len(dms) == 2, dms
    opened = [dm for dm in dms if dm.id != old.id]
    assert [dm.created_by for dm in opened] == [agent.id], dms
    assert await room.list_threads(old.id) == []
