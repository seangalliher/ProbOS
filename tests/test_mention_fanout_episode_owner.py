"""An @-mention fan-out reply is stored as the replying agent's own episode (#1794).

``routers/chat.py`` stores one episode per genuine reply of an @-mention fan-out. With a ``DreamAdapter`` on the
runtime (``startup/finalize.py`` builds one) the route used to call ``DreamAdapter.build_episode`` with a
``response`` and an ``agent_ids`` key; that function reads only ``dag``, ``results`` and ``reflection``, so the
stored episode had no owner, none of the reply, the ``direct`` source and a ``dag`` frame, and the agent's own
recall could not return it.

These cases drive the route with a REAL ``DreamAdapter``, a REAL ``EpisodicMemory`` on a temporary path and an
identity registry double that maps slot ids to sovereign ids, and read back what was stored; one case recalls each
episode as its owner, by the words of the reply.

Synthetic fixtures only. The cases marked ``built`` failed on the base at their own assert and pass now that the
route builds the Episode itself; the marker is a no-op, kept as documentation of which cases the base fails.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.config import DmAgenticConfig
from probos.crew_profile import CallsignRegistry
from probos.dream_adapter import DreamAdapter
from probos.mesh.pre_intent_auth import IntentAuthorizationDenied
from probos.routers.chat import chat
from probos.threads import MAIN_CHAT_THREAD_ID, ChatThreadStore
from probos.types import episode_ran_in_plan_mode

def built(func):
    """The built cases pass; the marker no longer fails them."""
    return func

_CAPTAIN_TEXT = "status report please"
_LONG_REPLY = "y" * 700

# callsign -> (agent type, slot id, sovereign id or "" where the slot has no certificate, reply text)
_CREW: dict[str, tuple[str, str, str, str]] = {
    "TestAlpha": (
        "test_alpha_officer", "test_alpha_officer_test_0_aaaa0001", "sov-test-alpha-0001",
        "The coolant pump bearing reads warm on loop two.",
    ),
    "TestBravo": (
        "test_bravo_officer", "test_bravo_officer_test_0_bbbb0002", "sov-test-bravo-0002",
        "Forward array sweep returns nominal echoes.",
    ),
    "TestCharlie": (
        "test_charlie_officer", "test_charlie_officer_test_0_cccc0003", "",
        "Shuttle bay doors cycle within tolerance.",
    ),
}


def _slot(callsign: str) -> str:
    return _CREW[callsign][1]


def _owner(callsign: str) -> str:
    """The id the episode must be owned by: the sovereign id, or the slot id where the slot has no certificate."""
    _type, slot, sovereign, _reply_text = _CREW[callsign]
    return sovereign or slot


def _reply(callsign: str) -> str:
    return _CREW[callsign][3]


class _Agent:
    def __init__(self, agent_id: str) -> None:
        self.id = agent_id
        self.is_alive = True


class _AgentRegistry:
    """What ``CallsignRegistry.resolve`` asks of the agent registry: the live agents of a type."""

    def __init__(self, by_type: dict[str, list[_Agent]]) -> None:
        self._by_type = by_type

    def get_by_pool(self, agent_type: str) -> list[_Agent]:
        return self._by_type.get(agent_type, [])


class _IdentityRegistry:
    """What ``resolve_sovereign_id_from_slot`` asks of the identity registry: a slot's certificate, or None."""

    def __init__(self) -> None:
        self._sovereign_by_slot = {slot: sov for _t, slot, sov, _r in _CREW.values() if sov}

    def get_by_slot(self, slot_id: str) -> Any:
        sovereign = self._sovereign_by_slot.get(slot_id)
        return SimpleNamespace(agent_uuid=sovereign) if sovereign else None


class _Bus:
    """Answers each target with its own reply; refuses or fails the targets it is told to."""

    def __init__(self, *, deny: str = "", fail: str = "", replies: dict[str, str] | None = None) -> None:
        self._deny = deny
        self._fail = fail
        self._reply_by_slot = {slot: text for _t, slot, _s, text in _CREW.values()}
        self._reply_by_slot.update(replies or {})

    async def send(self, intent: Any, *, raise_on_denial: bool = False, **_kw: Any) -> Any:
        target = str(getattr(intent, "target_agent_id", ""))
        if target == self._deny and raise_on_denial:
            raise IntentAuthorizationDenied(intent_name="direct_message", reason="test-policy", entry_point="send")
        if target == self._fail:
            raise RuntimeError("test transport failure")
        return SimpleNamespace(result=self._reply_by_slot[target], error=None)


def _callsign_registry() -> CallsignRegistry:
    registry = CallsignRegistry()
    by_type: dict[str, list[_Agent]] = {}
    for callsign, (agent_type, slot, _sovereign, _reply_text) in _CREW.items():
        registry.set_callsign(agent_type, callsign)
        by_type[agent_type] = [_Agent(slot)]
    registry.bind_registry(_AgentRegistry(by_type))
    return registry


@pytest.fixture
async def memory(tmp_path):
    mem = EpisodicMemory(db_path=tmp_path / "episodes.db", max_episodes=100, relevance_threshold=0.3)
    await mem.start()
    yield mem
    await mem.stop()


def _runtime(
    tmp_path: Any, memory: EpisodicMemory, bus: _Bus, *,
    store_type: type[ChatThreadStore] = ChatThreadStore, modes: bool | None = None,
) -> Any:
    """Every attribute the fan-out reads, set to a real object or a double above; a REAL ``DreamAdapter``.

    ``modes`` arms the plan-mode gate (#1794 A5): ``True`` or ``False`` sets a real ``DmAgenticConfig`` with the
    loop on and agent modes on or off; ``None`` keeps the mock config, which never arms it (the flags must be an
    exact ``True``).
    """
    identity = _IdentityRegistry()
    runtime = MagicMock()
    if modes is not None:
        runtime.config.dm_agentic = DmAgenticConfig(enabled=True, agent_modes_enabled=modes)
    runtime.callsign_registry = _callsign_registry()
    runtime.intent_bus = bus
    runtime.episodic_memory = memory
    runtime.identity_registry = identity
    runtime.chat_thread_store = store_type(tmp_path / "chat_threads.db")
    runtime.dream_adapter = DreamAdapter(
        dream_scheduler=None,
        emergent_detector=None,
        episodic_memory=memory,
        knowledge_store=None,
        hebbian_router=None,
        trust_network=None,
        event_emitter=lambda *args, **kwargs: None,
        self_mod_pipeline=None,
        bridge_alerts=None,
        ward_room=None,
        registry=None,
        event_log=None,
        config=None,
        pools={},
        identity_registry=identity,
    )
    return runtime


async def _fan_out(runtime: Any) -> dict[str, Any]:
    request = MagicMock()
    request.message = " ".join(f"@{callsign}" for callsign in _CREW) + " " + _CAPTAIN_TEXT
    request.history = []
    request.attachment_ids = []
    request.thread_id = None
    return await chat(request, runtime=runtime, track_task=Mock(), broadcast=Mock(), pending_designs={})


async def _fanout_episodes(memory: EpisodicMemory) -> list[Any]:
    return [ep for ep in await memory.recent(k=50) if str(ep.source) == "multi_agent_chat"]


async def _fanout_episodes_by_owner(memory: EpisodicMemory) -> dict[str, Any]:
    return {ep.agent_ids[0]: ep for ep in await _fanout_episodes(memory) if len(ep.agent_ids) == 1}


@built
async def test_each_reply_is_stored_as_its_agents_own_episode(tmp_path, memory) -> None:
    """One episode per genuine reply, owned by the agent's sovereign id (its slot id where it has none)."""
    response = await _fan_out(_runtime(tmp_path, memory, _Bus()))
    assert [r["status"] for r in response["per_agent_replies"]] == ["", "", ""], "premise: three genuine replies"

    episodes = await _fanout_episodes(memory)
    assert sorted(ep.agent_ids for ep in episodes) == sorted([_owner(callsign)] for callsign in _CREW)


@built
async def test_each_episode_holds_the_reply_and_the_chat_frame(tmp_path, memory) -> None:
    await _fan_out(_runtime(tmp_path, memory, _Bus()))

    by_owner = await _fanout_episodes_by_owner(memory)
    assert sorted(by_owner) == sorted(_owner(callsign) for callsign in _CREW)
    for callsign in _CREW:
        episode = by_owner[_owner(callsign)]
        assert episode.user_input == f"@{callsign} {_CAPTAIN_TEXT}"
        assert episode.reflection == f"{callsign} said: {_reply(callsign)}"
        assert [outcome.get("response") for outcome in episode.outcomes] == [_reply(callsign)]
        assert episode.anchors is not None
        assert (episode.anchors.channel, episode.anchors.trigger_type) == ("chat", "at_mention_fanout")
        assert episode.anchors.chat_thread_id == MAIN_CHAT_THREAD_ID
        assert episode.anchors.participants == ["captain", callsign]


@built
async def test_the_owner_recalls_its_reply_by_its_own_words(tmp_path, memory) -> None:
    """The seam the defect broke: route, store, then the owner's own recall, queried by the reply's words."""
    await _fan_out(_runtime(tmp_path, memory, _Bus()))

    for callsign in _CREW:
        recalled = await memory.recall_for_agent(_owner(callsign), _reply(callsign), k=5)
        assert [ep.reflection for ep in recalled if str(ep.source) == "multi_agent_chat"] == [
            f"{callsign} said: {_reply(callsign)}"
        ]


@built
async def test_the_reflection_keeps_600_characters_of_a_long_reply(tmp_path, memory) -> None:
    """The reflection keeps the group fan-out's shipped cap; the outcome keeps 500, as the group fan-out's does."""
    bus = _Bus(replies={_slot("TestAlpha"): _LONG_REPLY})
    await _fan_out(_runtime(tmp_path, memory, bus))

    by_owner = await _fanout_episodes_by_owner(memory)
    assert _owner("TestAlpha") in by_owner
    episode = by_owner[_owner("TestAlpha")]
    assert episode.reflection == f"TestAlpha said: {_LONG_REPLY[:600]}"
    assert [outcome.get("response") for outcome in episode.outcomes] == [_LONG_REPLY[:500]]


async def test_a_refused_or_failed_reply_stores_no_episode(tmp_path, memory) -> None:
    """The genuine-turn gate is kept: a refused or failed recipient is never stored as having spoken (control)."""
    bus = _Bus(deny=_slot("TestBravo"), fail=_slot("TestCharlie"))
    response = await _fan_out(_runtime(tmp_path, memory, bus))

    statuses = {r["callsign"]: r["status"] for r in response["per_agent_replies"]}
    assert statuses == {"TestAlpha": "", "TestBravo": "refused", "TestCharlie": "delivery_failed"}
    assert [ep.user_input for ep in await memory.recent(k=50)] == [f"@TestAlpha {_CAPTAIN_TEXT}"]


# -- #1794 A5: plan mode (AD-1156 A-4) ------------------------------------------------------------------------


class _MainThreadUnreadable(ChatThreadStore):
    """The real store, except that reading the main-chat thread raises, so a mode read there cannot be confirmed."""

    def get_thread(self, thread_id: str) -> Any:
        if thread_id == MAIN_CHAT_THREAD_ID:
            raise RuntimeError("test: main-chat thread read failed")
        return super().get_thread(thread_id)


class _SeedFails(ChatThreadStore):
    """The real store, except that appending to the main-chat thread raises, so the route drops its main thread."""

    def append_message(self, thread_id: str, **kwargs: Any) -> Any:
        if thread_id == MAIN_CHAT_THREAD_ID:
            raise RuntimeError("test: main-chat append failed")
        return super().append_message(thread_id, **kwargs)


def _plan_on_own_thread(store: ChatThreadStore, callsign: str) -> None:
    """The Captain's ``/mode plan`` on the agent's own one-to-one thread (its default thread)."""
    thread = store.get_or_create_default_for_agent(_slot(callsign), callsign)
    store.set_agent_mode(thread.id, "plan", changed_by="captain")


async def _marked_by_owner(memory: EpisodicMemory) -> dict[str, bool]:
    return {owner: episode_ran_in_plan_mode(ep) for owner, ep in (await _fanout_episodes_by_owner(memory)).items()}


async def test_a_turn_held_on_an_unreadable_main_thread_is_marked_as_plan_modes(tmp_path, memory) -> None:
    """G1, A-9 through the route: with modes on, a main-chat thread that cannot be read holds every turn, so every
    episode carries the marker; the replies and the episodes themselves are kept."""
    response = await _fan_out(_runtime(tmp_path, memory, _Bus(), store_type=_MainThreadUnreadable, modes=True))
    assert response["thread_id"] == MAIN_CHAT_THREAD_ID, "premise: the seed held, so each turn ran on the main thread"
    assert [r["status"] for r in response["per_agent_replies"]] == ["", "", ""]

    assert await _marked_by_owner(memory) == {_owner(callsign): True for callsign in _CREW}


async def test_an_ordinary_turn_on_the_main_thread_is_not_marked(tmp_path, memory) -> None:
    """G2: with modes on, the main-chat thread carries no record (it has no participant), so no turn is marked and
    dreaming still learns from these episodes."""
    response = await _fan_out(_runtime(tmp_path, memory, _Bus(), modes=True))
    assert response["thread_id"] == MAIN_CHAT_THREAD_ID, "premise: the seed held"

    assert await _marked_by_owner(memory) == {_owner(callsign): False for callsign in _CREW}


async def test_after_a_failed_seed_each_turn_follows_its_agents_own_mode(tmp_path, memory) -> None:
    """G3: with no main thread, each agent runs its turn under its own thread's mode; only the agent whose thread
    is in plan mode has its episode marked."""
    runtime = _runtime(tmp_path, memory, _Bus(), store_type=_SeedFails, modes=True)
    _plan_on_own_thread(runtime.chat_thread_store, "TestAlpha")
    response = await _fan_out(runtime)
    assert response["thread_id"] is None, "premise: the seed failed, so each turn ran on its agent's own thread"

    assert await _marked_by_owner(memory) == {
        _owner("TestAlpha"): True, _owner("TestBravo"): False, _owner("TestCharlie"): False,
    }


async def test_with_agent_modes_off_no_turn_is_marked(tmp_path, memory) -> None:
    """G4, default-off: with agent modes off the gate never opens, even over a plan record."""
    runtime = _runtime(tmp_path, memory, _Bus(), store_type=_SeedFails, modes=False)
    _plan_on_own_thread(runtime.chat_thread_store, "TestAlpha")
    await _fan_out(runtime)

    assert await _marked_by_owner(memory) == {_owner(callsign): False for callsign in _CREW}
