"""BF-903 (#1581) M2: the Ward Room checks a visiting officer's capability at every entry that acts for an actor id.

Real objects: a real ``AgentIdentityRegistry`` and ``WardRoomService`` in ``tmp_path``, the real
``VisitingOfficerRegistry`` with an injected clock, the real API app for the 403, and one real boot (mock LLM).
Crew act by slot id, as ``agent.id`` does, and the Captain by "captain".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient as _TestClient  # FastAPI's, not a ProbOS name
from httpx import ASGITransport as _ASGITransport  # httpx's names, not ProbOS's
from httpx import AsyncClient as _AsyncClient

from probos.api import create_app
from probos.assignment import AssignmentService
from probos.cognitive.llm_client import MockLLMClient
from probos.config import TEACHING_MIN_COMPILATION_LEVEL, AuthConfig, SystemConfig
from probos.identity import AgentIdentityRegistry
from probos.runtime import ProbOSRuntime
from probos.visiting_officers import (
    CAP_DM_RECEIVE,
    CAP_DM_SEND,
    CAP_WARD_ROOM_POST,
    CAP_WARD_ROOM_READ,
    REFUSED_CAPABILITY,
    REFUSED_EXPIRED,
    REFUSED_NO_SESSION,
    REFUSED_REGISTRY_OFF,
    VisitingOfficerRegistry,
    VisitorScopeRefused,
)
from probos.ward_room.service import WardRoomService

INSTANCE_ID = "bf903-m2-ship"
VESSEL_NAME = "Bf903m2"
CREW_SLOT = "counselor_counselor_0_67c601cb"
ALL = (CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ, CAP_DM_SEND, CAP_DM_RECEIVE)
Events = list[tuple[str, dict[str, Any]]]

#: entry -> (the capability a visitor needs there, the refusal's surface)
ENTRIES: dict[str, tuple[str, str]] = {
    "create_thread": (CAP_WARD_ROOM_POST, "ward_room.create_thread"),
    "create_post": (CAP_WARD_ROOM_POST, "ward_room.create_post"),
    "edit_post": (CAP_WARD_ROOM_POST, "ward_room.edit_post"),
    "endorse": (CAP_WARD_ROOM_POST, "ward_room.endorse"),
    "subscribe": (CAP_WARD_ROOM_READ, "ward_room.subscribe"),
    "update_last_seen": (CAP_WARD_ROOM_READ, "ward_room.update_last_seen"),
    "browse_threads": (CAP_WARD_ROOM_READ, "ward_room.browse_threads"),
    "list_channels": (CAP_WARD_ROOM_READ, "ward_room.list_channels"),
    "get_unread_counts": (CAP_WARD_ROOM_READ, "ward_room.get_unread_counts"),
    "get_unread_dms": (CAP_DM_RECEIVE, "ward_room.get_unread_dms"),
    "dm_channel_as_a": (CAP_DM_RECEIVE, "ward_room.get_or_create_dm_channel"),
    "dm_channel_as_b": (CAP_DM_RECEIVE, "ward_room.get_or_create_dm_channel"),
}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class _Rig:
    identities: AgentIdentityRegistry
    officers: VisitingOfficerRegistry
    ward_room: WardRoomService
    clock: _Clock
    events: Events
    all_hands: str
    crew_thread: str
    crew_post: str
    dm_channel: str
    dm_thread: str
    dm_post: str


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[_Rig]:
    identities = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    ward_room = WardRoomService(db_path=str(tmp_path / "wr.db"), identity_registry=identities)
    try:
        await identities.start()
        await identities.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        await ward_room.start()
        clock = _Clock()
        events: Events = []
        officers = VisitingOfficerRegistry(
            identities, instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, baseline_version="1",
            emit_event=lambda name, payload: events.append((name, payload)), clock=clock,
        )
        ward_room.attach_visiting_officers(officers)
        all_hands = await ward_room.get_channel_by_name("All Hands")
        thread = await ward_room.create_thread(all_hands.id, CREW_SLOT, "Crew thread", "crew body")
        post = await ward_room.create_post(thread.id, CREW_SLOT, "crew post")
        dm = await ward_room.get_or_create_dm_channel(CREW_SLOT, "captain")
        dm_thread = await ward_room.create_thread(dm.id, CREW_SLOT, "Crew DM", "dm body")
        dm_post = await ward_room.create_post(dm_thread.id, CREW_SLOT, "dm post")
        yield _Rig(
            identities, officers, ward_room, clock, events,
            all_hands.id, thread.id, post.id, dm.id, dm_thread.id, dm_post.id,
        )
    finally:
        await ward_room.stop()
        await identities.stop()


async def _visitor(rig: _Rig, *capabilities: str) -> str:
    session = await rig.officers.register("visitor", list(capabilities))
    return session.did


def _refusals(events: Events) -> list[dict[str, Any]]:
    return [payload for name, payload in events if name == "VISITING_OFFICER_REFUSED"]


async def _act(rig: _Rig, entry: str, actor: str, *, own: bool) -> None:
    """One call at ``entry`` as ``actor``; with ``own`` an edit targets a post the actor writes first."""
    wr = rig.ward_room
    if entry == "create_thread":
        await wr.create_thread(rig.all_hands, actor, "A visitor's thread", "body")
    elif entry == "create_post":
        await wr.create_post(rig.crew_thread, actor, "a reply")
    elif entry == "edit_post":
        target = (await wr.create_post(rig.crew_thread, actor, "mine")).id if own else rig.crew_post
        await wr.edit_post(target, actor, "edited")
    elif entry == "endorse":
        await wr.endorse(rig.crew_post, "post", actor, "up")
    elif entry == "subscribe":
        await wr.subscribe(actor, rig.all_hands)
    elif entry == "update_last_seen":
        await wr.update_last_seen(actor, rig.all_hands)
    elif entry == "browse_threads":
        await wr.browse_threads(actor)
    elif entry == "list_channels":
        await wr.list_channels(actor)
    elif entry == "get_unread_counts":
        await wr.get_unread_counts(actor)
    elif entry == "get_unread_dms":
        await wr.get_unread_dms(actor)
    elif entry == "dm_channel_as_a":
        await wr.get_or_create_dm_channel(actor, CREW_SLOT)
    elif entry == "dm_channel_as_b":
        await wr.get_or_create_dm_channel(CREW_SLOT, actor)
    else:
        raise AssertionError(f"not an entry: {entry}")


async def _write(rig: _Rig, where: str, actor: str, *, own: bool) -> None:
    wr = rig.ward_room
    if where == "post-in-ship-thread":
        await wr.create_post(rig.crew_thread, actor, "reply")
    elif where == "post-in-dm-thread":
        await wr.create_post(rig.dm_thread, actor, "reply")
    elif where == "thread-in-dm-channel":
        await wr.create_thread(rig.dm_channel, actor, "title", "body")
    elif where == "edit-in-dm-thread":
        target = (await wr.create_post(rig.dm_thread, actor, "mine")).id if own else rig.dm_post
        await wr.edit_post(target, actor, "edited")
    else:
        raise AssertionError(f"not a write: {where}")


@pytest.mark.parametrize("entry", list(ENTRIES))
async def test_a_visitor_without_the_capability_is_refused_at_each_entry(rig: _Rig, entry: str) -> None:
    """W1: each entry refuses a visitor holding every capability but the one it needs, names that capability
    and the entry, and records one refusal."""
    capability, surface = ENTRIES[entry]
    visitor = await _visitor(rig, *(c for c in ALL if c != capability))
    with pytest.raises(VisitorScopeRefused) as refused:
        await _act(rig, entry, visitor, own=False)
    assert (refused.value.did, refused.value.capability, refused.value.reason, refused.value.surface) == (
        visitor, capability, REFUSED_CAPABILITY, surface,
    )
    assert _refusals(rig.events) == [
        {"did": visitor, "capability": capability, "reason": REFUSED_CAPABILITY, "surface": surface},
    ]


@pytest.mark.parametrize("entry", list(ENTRIES))
async def test_a_visitor_with_only_that_capability_is_served_at_each_entry(rig: _Rig, entry: str) -> None:
    """W2: holding exactly the capability an entry needs is enough there."""
    capability, _surface = ENTRIES[entry]
    visitor = await _visitor(rig, capability)
    await _act(rig, entry, visitor, own=True)
    assert _refusals(rig.events) == []


@pytest.mark.parametrize(
    ("where", "granted", "needed"),
    [
        ("post-in-ship-thread", CAP_DM_SEND, CAP_WARD_ROOM_POST),
        ("post-in-dm-thread", CAP_WARD_ROOM_POST, CAP_DM_SEND),
        ("thread-in-dm-channel", CAP_WARD_ROOM_POST, CAP_DM_SEND),
        ("edit-in-dm-thread", CAP_WARD_ROOM_POST, CAP_DM_SEND),
    ],
    ids=["post-in-ship-thread", "post-in-dm-thread", "thread-in-dm-channel", "edit-in-dm-thread"],
)
async def test_a_write_needs_dm_send_in_a_dm_channel_and_ward_room_post_elsewhere(
    rig: _Rig, where: str, granted: str, needed: str,
) -> None:
    """W3: the capability a visitor's write needs follows the channel it lands in; holding it serves the write."""
    with pytest.raises(VisitorScopeRefused) as refused:
        await _write(rig, where, await _visitor(rig, granted), own=False)
    assert refused.value.capability == needed
    await _write(rig, where, await _visitor(rig, needed), own=True)


@pytest.mark.parametrize("lapse", ["expired", "deregistered", "registry-off"])
async def test_a_lapsed_or_unattached_session_is_refused_at_its_next_request(rig: _Rig, lapse: str) -> None:
    """W4: an expired session is refused before any sweep, a deregistered one at once, and with no registry a
    visitor is refused; crew post throughout."""
    session = await rig.officers.register("visitor", list(ALL), session_ttl_seconds=10.0)
    expected = {"expired": REFUSED_EXPIRED, "deregistered": REFUSED_NO_SESSION, "registry-off": REFUSED_REGISTRY_OFF}
    if lapse == "expired":
        rig.clock.now += 10.0
    elif lapse == "deregistered":
        rig.officers.deregister(session.did)
    else:
        rig.ward_room.attach_visiting_officers(None)
    with pytest.raises(VisitorScopeRefused) as refused:
        await rig.ward_room.create_post(rig.crew_thread, session.did, "late")
    assert refused.value.reason == expected[lapse]
    await rig.ward_room.create_post(rig.crew_thread, CREW_SLOT, "crew still posts")
    deregistrations = [n for n, _ in rig.events if n == "VISITING_OFFICER_DEREGISTERED"]
    assert len(deregistrations) == (1 if lapse == "deregistered" else 0)


async def test_crew_and_the_captain_are_served_as_before_without_a_lookup(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5 golden: every guarded entry serves a crew slot id and "captain", with the registry attached and not,
    and reads no certificate for them (a lookup raises here)."""
    def _no_lookup(_uuid: str) -> None:
        raise AssertionError("not expected: a crew or Captain id was looked up")

    monkeypatch.setattr(rig.identities, "get_by_uuid", _no_lookup)
    wr = rig.ward_room
    for attached in (True, False):
        wr.attach_visiting_officers(rig.officers if attached else None)
        for actor, other in ((CREW_SLOT, "captain"), ("captain", CREW_SLOT)):
            thread = await wr.create_thread(rig.all_hands, actor, "t", "b")
            post = await wr.create_post(thread.id, actor, "p")
            await wr.edit_post(post.id, actor, "edited")
            await wr.endorse(post.id, "post", other, "up")
            await wr.subscribe(actor, rig.all_hands)
            await wr.update_last_seen(actor, rig.all_hands)
            await wr.browse_threads(actor)
            await wr.list_channels(actor)
            await wr.get_unread_counts(actor)
            await wr.get_unread_dms(actor)
            await wr.get_or_create_dm_channel(actor, other)
    assert _refusals(rig.events) == []


async def test_a_crew_did_is_served(rig: _Rig) -> None:
    """W6: a crew member acting by its certificate DID is looked up, found not visiting, and served."""
    crew = await rig.identities.resolve_or_issue(
        slot_id=CREW_SLOT, agent_type="counselor", callsign="Counselor", instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME, department="medical", post_id="counselor", baseline_version="v1",
    )
    thread = await rig.ward_room.create_thread(rig.all_hands, crew.did, "t", "b")
    assert thread.author_id == crew.did
    assert _refusals(rig.events) == []


class _RefusingWardRoom:
    """Raises the real refusal from create_thread; the guard itself is W1-W4's."""

    async def create_thread(self, **_kwargs: Any) -> None:
        raise VisitorScopeRefused(
            "did:probos:ship:visitor", CAP_WARD_ROOM_POST, REFUSED_CAPABILITY, "ward_room.create_thread",
        )


def _api_runtime(ward_room: Any) -> Any:
    """The mock runtime BF-771's API test builds (tests/test_bf771_intent_authorization.py:515-534)."""
    runtime = MagicMock()
    runtime.registry = MagicMock()
    runtime.profile_store = None
    cfg = MagicMock()
    cfg.auth = AuthConfig()
    runtime.config = cfg
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = ""
    runtime.callsign_registry.resolve.return_value = None
    runtime.callsign_registry.all_callsigns.return_value = {}
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime._start_time = 0.0
    runtime.episodic_memory = None
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()
    runtime.ward_room = ward_room
    # A4: a MagicMock data directory is truthy, and create_app would create its model folders under the working
    # directory (api.py:377-389); this double has none.
    runtime._data_dir = None
    runtime.data_dir = None
    return runtime


def test_the_api_answers_a_visitor_refusal_with_403_and_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W7: a refusal from the Ward Room reaches the client as 403 with the capability, reason and surface. The app is
    built in an empty working directory and leaves it empty: the runtime double has no data directory (A4)."""
    monkeypatch.chdir(tmp_path)
    client = _TestClient(create_app(_api_runtime(_RefusingWardRoom())), raise_server_exceptions=False)
    assert list(tmp_path.iterdir()) == []
    response = client.post(
        "/api/wardroom/channels/c1/threads",
        json={"author_id": "did:probos:ship:visitor", "title": "t", "body": "b"},
    )
    assert response.status_code == 403, response.text
    assert response.json() == {
        "error": "visitor_scope_refused",
        "capability": CAP_WARD_ROOM_POST,
        "reason": REFUSED_CAPABILITY,
        "surface": "ward_room.create_thread",
    }


_SUBSCRIBE_REFUSED = {
    "error": "visitor_scope_refused",
    "capability": CAP_WARD_ROOM_READ,
    "reason": REFUSED_CAPABILITY,
    "surface": "ward_room.subscribe",
}


class _Chamber:
    """A Birth Chamber that has graduated no one, so ``AssignmentService`` defers every subscription to it (AD-486)."""

    def __init__(self) -> None:
        self.queued: list[tuple[str, str]] = []

    def is_graduated(self, agent_id: str) -> bool:
        return False

    def queue_pending_subscription(self, agent_id: str, channel_id: str, subscribe: Any) -> None:
        self.queued.append((agent_id, channel_id))


class _Procedure:
    """The members the teaching route reads from an approved Level-5 procedure."""

    name = "bf903-procedure"
    description = "a procedure fit to teach"
    compilation_level = TEACHING_MIN_COMPILATION_LEVEL
    steps: tuple[Any, ...] = ()


class _TeachingStore:
    """The three ``ProcedureStore`` reads the teaching route makes; the store is upstream of the seam under test."""

    async def get(self, procedure_id: str) -> _Procedure:
        return _Procedure()

    async def get_promotion_status(self, procedure_id: str) -> str:
        return "approved"

    async def get_quality_metrics(self, procedure_id: str) -> dict[str, Any]:
        return {"total_completions": 10, "effective_rate": 0.9}


def _client(runtime: Any) -> _AsyncClient:
    """The real API app over an in-process ASGI transport, on the test's own event loop."""
    return _AsyncClient(transport=_ASGITransport(app=create_app(runtime)), base_url="http://bf903.test")


async def test_an_assignment_naming_a_refused_visitor_changes_nothing_and_answers_403(rig: _Rig, tmp_path: Path) -> None:
    """W9 (A4): POST /api/assignments checks every member before the channel, a subscription or a row exists, so a
    request naming a visitor without ward_room.read answers 403 with the reason and leaves no assignment, channel,
    subscription or deferred subscription; a visitor holding ward_room.read joins with every member subscribed.
    Before A4 the service swallowed the refusal: 200, every member recorded, the members after the visitor not
    subscribed."""
    service = AssignmentService(db_path=str(tmp_path / "assignments.db"), ward_room=rig.ward_room)
    await service.start()
    try:
        runtime = _api_runtime(rig.ward_room)
        runtime.assignment_service = service
        refused_visitor = await _visitor(rig, CAP_DM_SEND)
        reader = await _visitor(rig, CAP_WARD_ROOM_READ)
        channels = [c.id for c in await rig.ward_room.list_channels()]
        chamber = _Chamber()
        async with _client(runtime) as client:
            refused = await client.post(
                "/api/assignments",
                json={"name": "Away", "assignment_type": "away_team", "members": [CREW_SLOT, refused_visitor, "captain"]},
            )
            assert refused.status_code == 403, refused.text
            assert refused.json() == _SUBSCRIBE_REFUSED
            service.set_birth_chamber(chamber)
            deferred = await client.post(
                "/api/assignments",
                json={"name": "Away", "assignment_type": "away_team", "members": [CREW_SLOT, refused_visitor]},
            )
            assert deferred.status_code == 403, deferred.text
            assert chamber.queued == []
            assert await service.list_assignments() == []
            assert [c.id for c in await rig.ward_room.list_channels()] == channels
            assert [p["surface"] for p in _refusals(rig.events)] == ["ward_room.subscribe", "ward_room.subscribe"]
            service.set_birth_chamber(None)
            served = await client.post(
                "/api/assignments",
                json={"name": "Away", "assignment_type": "away_team", "members": [CREW_SLOT, reader, "captain"]},
            )
        assert served.status_code == 200, served.text
        channel = served.json()["ward_room_channel_id"]
        for member in (CREW_SLOT, reader, "captain"):
            assert channel in [c.id for c in await rig.ward_room.list_channels(member)]
    finally:
        await service.stop()


async def test_adding_a_refused_visitor_to_an_assignment_writes_no_member_and_answers_403(
    rig: _Rig, tmp_path: Path,
) -> None:
    """W10 (A4): POST /api/assignments/{id}/members checks the member before its row is written, so a visitor without
    ward_room.read answers 403 and the assignment keeps its members; a visitor holding it joins and is subscribed.
    Before A4 the row was committed, the refusal swallowed and the answer 200."""
    service = AssignmentService(db_path=str(tmp_path / "assignments.db"), ward_room=rig.ward_room)
    await service.start()
    try:
        runtime = _api_runtime(rig.ward_room)
        runtime.assignment_service = service
        assignment = await service.create_assignment("Away", "away_team", "captain", [CREW_SLOT])
        refused_visitor = await _visitor(rig, CAP_DM_SEND)
        reader = await _visitor(rig, CAP_WARD_ROOM_READ)
        async with _client(runtime) as client:
            refused = await client.post(f"/api/assignments/{assignment.id}/members", json={"agent_id": refused_visitor})
            assert refused.status_code == 403, refused.text
            assert refused.json() == _SUBSCRIBE_REFUSED
            assert set((await service.get_assignment(assignment.id)).members) == {CREW_SLOT}
            served = await client.post(f"/api/assignments/{assignment.id}/members", json={"agent_id": reader})
        assert served.status_code == 200, served.text
        assert set((await service.get_assignment(assignment.id)).members) == {CREW_SLOT, reader}
        assert assignment.ward_room_channel_id in [c.id for c in await rig.ward_room.list_channels(reader)]
    finally:
        await service.stop()


async def test_the_teaching_route_answers_a_visitor_refusal_with_403(rig: _Rig) -> None:
    """W11 (A4): POST /api/procedures/teach lets a scope refusal reach the API's handler instead of answering 200 with
    an error string, so a visitor target without dm.receive answers 403 and no DM channel is opened; a crew target is
    taught as before."""
    runtime = _api_runtime(rig.ward_room)
    runtime.procedure_store = _TeachingStore()
    visitor = await _visitor(rig, CAP_DM_SEND)
    channels = [c.id for c in await rig.ward_room.list_channels()]
    async with _client(runtime) as client:
        refused = await client.post("/api/procedures/teach", json={"procedure_id": "p1", "target_callsign": visitor})
        assert refused.status_code == 403, refused.text
        assert refused.json() == {
            "error": "visitor_scope_refused",
            "capability": CAP_DM_RECEIVE,
            "reason": REFUSED_CAPABILITY,
            "surface": "ward_room.get_or_create_dm_channel",
        }
        assert [c.id for c in await rig.ward_room.list_channels()] == channels
        served = await client.post("/api/procedures/teach", json={"procedure_id": "p1", "target_callsign": CREW_SLOT})
    assert served.status_code == 200, served.text
    assert served.json()["success"] is True


async def test_a_real_boot_scopes_visitors_in_the_ward_room(tmp_path: Path) -> None:
    """W8: with AD-701 on, a booted Ward Room refuses a reader's thread for its capability and serves a poster's."""
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    config.visiting_officers.enabled = True
    config.ward_room.enabled = True  # WardRoomConfig.enabled is off by default, so runtime.ward_room is None without it
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await runtime.start()
    try:
        reader = await runtime.visiting_officers.register("boot-reader", [CAP_WARD_ROOM_READ])
        poster = await runtime.visiting_officers.register("boot-poster", [CAP_WARD_ROOM_POST])
        all_hands = await runtime.ward_room.get_channel_by_name("All Hands")
        with pytest.raises(VisitorScopeRefused) as refused:
            await runtime.ward_room.create_thread(all_hands.id, reader.did, "t", "b")
        assert refused.value.reason == REFUSED_CAPABILITY
        thread = await runtime.ward_room.create_thread(all_hands.id, poster.did, "t", "b")
        assert thread.author_id == poster.did
    finally:
        await runtime.stop()
