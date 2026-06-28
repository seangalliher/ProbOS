"""AD-1076: liveness-independent group-chat participant resolution.

The observed production failure was ``AD-966: ... suppressed ... refs=['Lyra']``
— NOT a malformed tag. The agent named its peer correctly by callsign, but
``CallsignRegistry.resolve`` only returns an ``agent_id`` for a LIVE agent
(``state in {ACTIVE, DEGRADED}``). A proactive crew is idle most of the time, so
a correctly-named but resting peer dropped, and when it was the only named peer
the single-participant room fell below the AD-966 floor and was suppressed.

AD-1076 makes ``_resolve_participant`` fall back to any registered crew agent of
the named type — group-chat membership is persistent, so a resting peer still
belongs in the room and sees it when it next runs.

BF-287 discipline: real ``ChatThreadStore`` + real ``CallsignRegistry`` + a
real-but-fake registry (NOT MagicMock). Crew ``agent_type``s (builder /
diagnostician) come from ``crew_utils._WARD_ROOM_CREW`` so ``ontology=None``
resolves crew. "Bones" -> diagnostician (per the AD-924 fixtures).
"""
from __future__ import annotations

from probos.config import GroupChatConfig
from probos.crew_profile import CallsignRegistry
from probos.threads import ChatThreadStore
from probos.threads.agent_group_chat import AgentGroupChatService


class _FakeAgent:
    def __init__(self, agent_id: str, agent_type: str, *, alive: bool = True) -> None:
        self.id = agent_id
        self.agent_type = agent_type
        self.pool = agent_type  # registry.get_by_pool filters on .pool/.agent_type
        self.is_alive = alive


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)

    def get_by_pool(self, agent_type: str):
        return [a for a in self._a.values() if a.agent_type == agent_type]


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _make(tmp_path, agents):
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    registry = _FakeRegistry(agents)
    cs = CallsignRegistry()
    cs.load_from_profiles()
    cs.bind_registry(registry)
    svc = AgentGroupChatService(
        store=store, registry=registry, callsign_registry=cs,
        config=GroupChatConfig(), ontology_provider=None, clock=_Clock(),
    )
    return svc, store, cs


def test_resting_peer_named_by_callsign_still_resolves(tmp_path):
    # Bones (diagnostician) is registered but RESTING — the common idle state.
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder", alive=True),
        "bones-1": _FakeAgent("bones-1", "diagnostician", alive=False),
    }
    svc, store, cs = _make(tmp_path, agents)
    # Sanity: the original live-only path misses for a resting agent.
    resolved = cs.resolve("Bones")
    assert resolved is not None and resolved["agent_id"] is None

    res = svc.create_group_chat(
        creator_id="forge-1", title="Sickbay Sync", participants=["Bones"],
    )
    assert res.ok, res.error
    assert set(res.thread.participants) == {"forge-1", "bones-1"}


def test_resolve_participant_unit_resting_peer(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder", alive=True),
        "bones-1": _FakeAgent("bones-1", "diagnostician", alive=False),
    }
    svc, _, _ = _make(tmp_path, agents)
    assert svc._resolve_participant("Bones") == "bones-1"


def test_live_peer_still_resolves(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder", alive=True),
        "bones-1": _FakeAgent("bones-1", "diagnostician", alive=True),
    }
    svc, store, _ = _make(tmp_path, agents)
    res = svc.create_group_chat(creator_id="forge-1", title="Y", participants=["Bones"])
    assert res.ok
    assert set(res.thread.participants) == {"forge-1", "bones-1"}


def test_unknown_callsign_still_suppressed(tmp_path):
    # The AD-966 floor + resolution still reject a genuinely unknown name.
    agents = {"forge-1": _FakeAgent("forge-1", "builder", alive=True)}
    svc, store, _ = _make(tmp_path, agents)
    res = svc.create_group_chat(creator_id="forge-1", title="X", participants=["Nobody"])
    assert not res.ok
    assert res.error == "no_participant_resolved"
    assert store.list_threads() == []
