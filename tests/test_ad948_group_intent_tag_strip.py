"""AD-948: the group fan-out strips the AD-722a ``<intent emotion=...>``
self-tag from each reply before it is persisted + returned, so the internal
tag never leaks into the visible group transcript.

The 1:1 path strips the tag via ``apply_divergence_check``
(``routers/agents.py``); the group fan-out (``thread_fanout._send_one``) never
did, so a tag-bearing reply leaked the raw tag into the room (the Captain's
screenshot). AD-948 reuses the single-source ``strip_intent_self_tag``.

BF-287 discipline: real ``ChatThreadStore`` on ``tmp_path``, real ``IntentBus``,
real-but-fake registry/callsigns (no MagicMock at the substrate boundary).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult

pytestmark = pytest.mark.asyncio


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type  # is_crew_agent reads .agent_type


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)


class _FakeCallsigns:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._m = mapping  # agent_type -> callsign

    def get_callsign(self, agent_type: str) -> str:
        return self._m.get(agent_type, "")


def _seq_clock():
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


def _handler(agent_id: str, text: str):
    async def _h(intent: IntentMessage) -> IntentResult:
        return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True, result=text)

    return _h


def _env(tmp_path, agents, callsigns, replies_by_agent):
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    registry = _FakeRegistry({aid: _FakeAgent(at) for aid, at in agents.items()})
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=registry,
        ontology=None,
        callsign_registry=_FakeCallsigns(callsigns),
        project_store=None,
    )
    for aid in agents:
        bus.subscribe(aid, _handler(aid, replies_by_agent[aid]), intent_names=["direct_message"])
    return store, runtime


async def test_intent_self_tag_stripped_from_group_reply(tmp_path):
    """A reply trailing a quoted/unquoted ``<intent ...>`` tag is stripped in
    BOTH the returned per_agent_replies and the persisted message rows."""
    store, runtime = _env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Reed", "counselor": "Ezri"},
        replies_by_agent={
            "scout1": 'Reporting in, Captain. <intent emotion="warm">',
            "counselor1": "How are you feeling? <intent emotion=thoughtful>",
        },
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)

    texts = {r["callsign"]: r["text"] for r in replies}
    assert "<intent" not in texts["Reed"]
    assert "<intent" not in texts["Ezri"]
    assert "Reporting in, Captain." in texts["Reed"]
    assert "How are you feeling?" in texts["Ezri"]

    agent_bodies = [m.body for m in store.list_messages(t.id, limit=100) if m.role == "agent"]
    assert agent_bodies, "expected persisted agent replies"
    for body in agent_bodies:
        assert "<intent" not in body


async def test_plain_reply_unchanged(tmp_path):
    """Prose containing the WORD 'intent' is not a tag and is preserved
    verbatim (BF-603 prose-safety carries through the reuse)."""
    store, runtime = _env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Reed", "counselor": "Ezri"},
        replies_by_agent={
            "scout1": "All systems nominal.",
            "counselor1": "I am intent on warmth.",
        },
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)

    texts = {r["callsign"]: r["text"] for r in replies}
    assert texts["Ezri"] == "I am intent on warmth."
    assert texts["Reed"] == "All systems nominal."
