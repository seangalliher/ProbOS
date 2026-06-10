"""AD-966: ≥2-participant floor for agent-initiated group chats.

Bug: a crew agent emitted a [GROUP_CHAT title="..." @peer] tag where no named
ref resolved to a crew peer (the peer was addressed only in prose, or the
callsign was unknown/hallucinated). ``create_group_chat`` minted a room with
ONLY the creator — an incoherent 1-participant "group chat" talking to an
absent peer (the Captain-reported "started a chat but didn't invite them").

AD-966 adds a floor at the service (the chokepoint for all three callers:
proactive AD-924, crew_executor AD-925 task rooms, and the bus handle_intent):
when fewer than 2 participants resolve, suppress with ``no_participant_resolved``
instead of creating the room.

BF-287 discipline: real ``ChatThreadStore`` on ``tmp_path``, a real-but-fake
registry / callsign stub (NOT ``MagicMock``), and a deterministic clock so the
rate gate never flakes. Crew ``agent_type``s are drawn from the legacy
``crew_utils._WARD_ROOM_CREW`` set so ``ontology_provider=None`` resolves crew.
"""
from __future__ import annotations

from probos.config import GroupChatConfig
from probos.threads import ChatThreadStore
from probos.threads.agent_group_chat import AgentGroupChatService


# ---------------- BF-287 real-but-fake substrate stubs ----------------


class _FakeAgent:
    def __init__(self, agent_id: str, agent_type: str) -> None:
        self.id = agent_id
        self.agent_type = agent_type  # is_crew_agent reads .agent_type
        self.is_alive = True


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)

    def get_by_pool(self, agent_type: str):
        return [a for a in self._a.values() if a.agent_type == agent_type]


class _NoCallsigns:
    """Callsign registry stub whose resolve always misses (agent_id path only)."""

    def resolve(self, callsign: str):
        return None


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _make_service(tmp_path, *, agents):
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    svc = AgentGroupChatService(
        store=store,
        registry=_FakeRegistry(agents),
        callsign_registry=_NoCallsigns(),
        config=GroupChatConfig(),
        ontology_provider=None,
        clock=_Clock(),
    )
    return svc, store


# ---------------- the floor: suppress 1-participant rooms ----------------


def test_no_participants_suppressed(tmp_path):
    # No named refs at all -> only the creator -> below the floor -> suppressed.
    svc, store = _make_service(
        tmp_path, agents={"forge-1": _FakeAgent("forge-1", "builder")}
    )
    res = svc.create_group_chat(creator_id="forge-1", title="Solo")
    assert res.ok is False
    assert res.error == "no_participant_resolved"
    assert res.thread is None
    assert store.list_threads() == []


def test_empty_participant_list_suppressed(tmp_path):
    svc, store = _make_service(
        tmp_path, agents={"forge-1": _FakeAgent("forge-1", "builder")}
    )
    res = svc.create_group_chat(creator_id="forge-1", title="Solo", participants=[])
    assert res.ok is False
    assert res.error == "no_participant_resolved"
    assert store.list_threads() == []


def test_only_unresolvable_refs_suppressed(tmp_path):
    # A peer addressed in prose but named with an unknown callsign never
    # resolves -> only the creator remains -> suppressed (the Vance bug class).
    svc, store = _make_service(
        tmp_path, agents={"forge-1": _FakeAgent("forge-1", "builder")}
    )
    res = svc.create_group_chat(
        creator_id="forge-1", title="Ghost", participants=["nobody", "alsonobody"]
    )
    assert res.ok is False
    assert res.error == "no_participant_resolved"
    assert store.list_threads() == []


def test_only_non_crew_refs_suppressed(tmp_path):
    # A non-crew ref is dropped by resolution; with nothing else, the room
    # falls below the floor and is suppressed (not minted creator-only).
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "civ-1": _FakeAgent("civ-1", "captain"),  # not in _WARD_ROOM_CREW
    }
    svc, store = _make_service(tmp_path, agents=agents)
    res = svc.create_group_chat(
        creator_id="forge-1", title="Mixed", participants=["civ-1"]
    )
    assert res.ok is False
    assert res.error == "no_participant_resolved"
    assert store.list_threads() == []


def test_creator_named_in_refs_still_suppressed(tmp_path):
    # Naming ONLY the creator (deduped away) still leaves 1 participant.
    svc, store = _make_service(
        tmp_path, agents={"forge-1": _FakeAgent("forge-1", "builder")}
    )
    res = svc.create_group_chat(
        creator_id="forge-1", title="SelfOnly", participants=["forge-1"]
    )
    assert res.ok is False
    assert res.error == "no_participant_resolved"
    assert store.list_threads() == []


# ---------------- the floor lets a real 2-party room through ----------------


def test_one_resolved_peer_creates_normally(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
    }
    svc, store = _make_service(tmp_path, agents=agents)
    res = svc.create_group_chat(
        creator_id="forge-1", title="Pair", participants=["bones-1"]
    )
    assert res.ok
    assert res.thread is not None
    assert res.participants_added == ["forge-1", "bones-1"]
    assert len(store.list_threads()) == 1


def test_non_crew_dropped_but_crew_peer_keeps_room(tmp_path):
    # The non-crew ref is filtered, but a real crew peer keeps the room above
    # the floor -> created with only the crew members.
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
        "civ-1": _FakeAgent("civ-1", "captain"),
    }
    svc, store = _make_service(tmp_path, agents=agents)
    res = svc.create_group_chat(
        creator_id="forge-1", title="Mostly crew", participants=["civ-1", "bones-1"]
    )
    assert res.ok
    assert res.thread.participants == ["forge-1", "bones-1"]


def test_suppressed_create_posts_no_first_message(tmp_path):
    # A suppressed create must not persist the would-be first message anywhere
    # (no thread exists to hold it).
    svc, store = _make_service(
        tmp_path, agents={"forge-1": _FakeAgent("forge-1", "builder")}
    )
    res = svc.create_group_chat(
        creator_id="forge-1",
        title="Ghost",
        participants=["nobody"],
        first_message="Vance, the spec is ready.",
    )
    assert res.ok is False
    assert store.list_threads() == []
