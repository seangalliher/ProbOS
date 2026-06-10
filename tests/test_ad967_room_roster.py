"""AD-967 (Natural Conversation epic #882): present-participant ROOM ROSTER.

Captain-reported bug: in a group chat the agents had no idea who was actually
in the room. They addressed peers who were never invited (asking "Sentinel" a
question in a room Sentinel was not in), and assumed a peer they named in prose
had been added. The conversation got stuck waiting on an absent member.

AD-967 injects a roster of PRESENT participants into each dispatched agent's
group-chat prompt (extending the AD-935 hook) and teaches: address only present
members; to bring in anyone else, ask the Captain to add them. The roster rides
the fan-out param ``room_roster``.

Two layers, both tested:
  * ``CognitiveAgent._conversational_group_chat_protocol`` — the rendering,
  * end-to-end through ``group_chat_fanout`` — the roster reaches params.

BF-287 discipline: real ``ChatThreadStore`` / ``IntentBus`` / config (NOT
MagicMock).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.config import CommunicationsConfig, GroupChatConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult

_HOOK = CognitiveAgent._conversational_group_chat_protocol


# ======================= 1. the rendering hook =======================


def test_no_roster_is_backward_compatible():
    # is_group_chat but no room_roster -> base AD-935 decline text only.
    out = _HOOK(SimpleNamespace(), {"params": {"is_group_chat": True}})
    assert "[NO_RESPONSE]" in out
    assert "Present in this room" not in out


def test_not_group_chat_returns_empty():
    assert _HOOK(SimpleNamespace(), {"params": {"room_roster": ["Atlas"]}}) == ""
    assert _HOOK(SimpleNamespace(), {}) == ""


def test_roster_single_name():
    out = _HOOK(SimpleNamespace(), {"params": {"is_group_chat": True, "room_roster": ["Atlas"]}})
    assert "Present in this room: Atlas." in out
    assert "[NO_RESPONSE]" in out


def test_roster_two_names_uses_and():
    out = _HOOK(
        SimpleNamespace(),
        {"params": {"is_group_chat": True, "room_roster": ["Atlas", "Wesley"]}},
    )
    assert "Present in this room: Atlas and Wesley." in out


def test_roster_three_names_oxford_list():
    out = _HOOK(
        SimpleNamespace(),
        {"params": {"is_group_chat": True, "room_roster": ["Atlas", "Wesley", "Lyra"]}},
    )
    assert "Present in this room: Atlas, Wesley, and Lyra." in out


def test_roster_teaches_address_only_present_and_ask_captain():
    out = _HOOK(
        SimpleNamespace(),
        {"params": {"is_group_chat": True, "room_roster": ["Atlas", "Wesley"]}},
    )
    # Address only present members; bring others in via the Captain (the fix for
    # agents addressing an absent peer like Sentinel).
    assert "present in the room" in out.lower()
    assert "ask the Captain to add" in out


def test_roster_rendering_is_gap_regex_safe():
    out = _HOOK(
        SimpleNamespace(),
        {"params": {"is_group_chat": True, "room_roster": ["Atlas", "Wesley", "Lyra"]}},
    )
    assert _CAPABILITY_GAP_RE.search(out) is None
    for banned in ("can't", "cannot", "don't have", "unable to", "not able to", "lack"):
        assert banned not in out.lower()


def test_roster_ignores_blank_entries():
    out = _HOOK(
        SimpleNamespace(),
        {"params": {"is_group_chat": True, "room_roster": ["", "  ", "Atlas"]}},
    )
    assert "Present in this room: Atlas." in out


def test_empty_roster_list_falls_back_to_base():
    out = _HOOK(SimpleNamespace(), {"params": {"is_group_chat": True, "room_roster": []}})
    assert "Present in this room" not in out
    assert "[NO_RESPONSE]" in out


# ======================= 2. end-to-end through group_chat_fanout =======================


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class _FakeRegistry:
    def __init__(self, agents):
        self._a = agents

    def get(self, agent_id):
        return self._a.get(agent_id)


class _FakeCallsigns:
    def __init__(self, mapping):
        self._m = mapping

    def get_callsign(self, agent_type):
        return self._m.get(agent_type, "")


def _seq_clock():
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


_CALLSIGNS = {"scout": "Scout", "diagnostician": "Bones"}


def _make_handler(agent_id, captured):
    async def _h(intent: IntentMessage) -> IntentResult:
        captured.append({
            "agent_id": agent_id,
            "room_roster": intent.params.get("room_roster"),
            "is_group_chat": intent.params.get("is_group_chat"),
        })
        return IntentResult(
            intent_id=intent.id, agent_id=agent_id, success=True, result=f"reply::{agent_id}"
        )
    return _h


def _build_env(tmp_path, *, gc):
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    agents = {"scout1": _FakeAgent("scout"), "bones1": _FakeAgent("diagnostician")}
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=_FakeRegistry(agents),
        ontology=None,
        callsign_registry=_FakeCallsigns(_CALLSIGNS),
        project_store=None,
        config=SimpleNamespace(group_chat=gc, communications=CommunicationsConfig(), attachments=None),
    )
    captured: list[dict] = []
    for aid in agents:
        bus.subscribe(aid, _make_handler(aid, captured), intent_names=["direct_message"])
    return store, runtime, captured


@pytest.mark.asyncio
async def test_roster_reaches_dispatched_agent_params(tmp_path):
    store, runtime, captured = _build_env(
        tmp_path, gc=GroupChatConfig(max_speakers_per_turn=1, agent_reactivity_enabled=False),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status team?")
    await group_chat_fanout(runtime, t.id, captain_body="status team?", captain_msg=cap)
    dispatched = [c for c in captured if c["room_roster"] is not None]
    assert dispatched, "the dispatched agent should carry a room_roster"
    roster = dispatched[0]["room_roster"]
    # Both crew callsigns are present in the roster (the full room).
    assert set(roster) >= {"Scout", "Bones"}


@pytest.mark.asyncio
async def test_roster_includes_captain_when_joined(tmp_path):
    store, runtime, captured = _build_env(
        tmp_path, gc=GroupChatConfig(max_speakers_per_turn=1, agent_reactivity_enabled=False),
    )
    # Captain is a participant (AD-968 auto-join) -> roster names "the Captain".
    t = store.create_thread(title="room", participants=["captain", "scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status team?")
    await group_chat_fanout(runtime, t.id, captain_body="status team?", captain_msg=cap)
    dispatched = [c for c in captured if c["room_roster"] is not None]
    assert dispatched
    assert "the Captain" in dispatched[0]["room_roster"]


@pytest.mark.asyncio
async def test_roster_excludes_captain_when_not_joined(tmp_path):
    store, runtime, captured = _build_env(
        tmp_path, gc=GroupChatConfig(max_speakers_per_turn=1, agent_reactivity_enabled=False),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status team?")
    await group_chat_fanout(runtime, t.id, captain_body="status team?", captain_msg=cap)
    dispatched = [c for c in captured if c["room_roster"] is not None]
    assert dispatched
    assert "the Captain" not in dispatched[0]["room_roster"]
