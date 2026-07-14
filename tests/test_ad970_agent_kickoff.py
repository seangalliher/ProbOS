"""AD-970 (Natural Conversation epic #882): agent-initiated kickoff.

Captain-reported bug: an agent opened a group chat with an opening message and
addressed the invited crew — but they never responded; the room sat silent. Root
cause: the opening is persisted as ``role="agent"``, and AD-914 group fan-out
only fires on ``role=="captain"``, so an agent-created room never started a
conversation until the Captain posted.

AD-970 fans an agent's opening out to the OTHER participants (the agent-initiated
analogue of a Captain turn), reusing ``group_chat_fanout`` with a new
``opener_id`` so the opener is excluded from round 0 (it just spoke). Gated on
``GroupChatConfig.agent_initiated_kickoff_enabled`` (ships OFF), bounded by all
AD-935 backstops.

Two layers, both tested:
  * ``group_chat_fanout(opener_id=...)`` — round-0 opener exclusion,
  * ``ProactiveCognitiveLoop._kickoff_group_chat`` — the gated trigger.

BF-287: real ``ChatThreadStore`` / ``IntentBus`` / ``GroupChatConfig`` and a
real-but-fake registry + scripted handlers (NOT MagicMock at the substrate
boundary).
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from probos.config import CommunicationsConfig, GroupChatConfig, SystemConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.proactive import ProactiveCognitiveLoop
from probos.routers import thread_fanout
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


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


def _make_handler(agent_id, captured, intents=None):
    async def _h(intent: IntentMessage) -> IntentResult:
        captured.append(agent_id)
        if intents is not None:
            intents.append(intent)
        return IntentResult(
            intent_id=intent.id, agent_id=agent_id, success=True, result=f"reply::{agent_id}"
        )
    return _h


def _build_env(tmp_path, *, gc, config=None):
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    agents = {"scout1": _FakeAgent("scout"), "bones1": _FakeAgent("diagnostician")}
    cfg = config or SimpleNamespace(
        group_chat=gc,
        communications=CommunicationsConfig(),
        attachments=None,
    )
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=_FakeRegistry(agents),
        ontology=None,
        callsign_registry=_FakeCallsigns(_CALLSIGNS),
        ward_room=None,
        project_store=None,
        config=cfg,
    )
    captured: list[str] = []
    intents: list[IntentMessage] = []
    for aid in agents:
        bus.subscribe(
            aid,
            _make_handler(aid, captured, intents),
            intent_names=["direct_message"],
        )
    return store, runtime, captured, intents


# ======================= 1. group_chat_fanout opener_id =======================


@pytest.mark.asyncio
async def test_opener_excluded_from_round0(tmp_path):
    # scout1 opened the room; the kickoff fans the opening to the OTHER crew.
    # scout1 must NOT be dispatched in round 0 (it just spoke); bones1 must be.
    store, runtime, captured, _intents = _build_env(
        tmp_path, gc=GroupChatConfig(agent_reactivity_enabled=False, max_speakers_per_turn=0),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    opening = store.append_message(t.id, author_id="scout1", role="agent", body="Bones, status?")
    await group_chat_fanout(
        runtime, t.id, captain_body="Bones, status?", captain_msg=opening, opener_id="scout1",
    )
    assert "bones1" in captured
    assert "scout1" not in captured


@pytest.mark.asyncio
async def test_no_opener_id_fans_to_all(tmp_path):
    # Without opener_id (a Captain turn) both crew are dispatched — byte-identical
    # to AD-914.
    store, runtime, captured, _intents = _build_env(
        tmp_path, gc=GroupChatConfig(agent_reactivity_enabled=False, max_speakers_per_turn=0),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    assert set(captured) == {"scout1", "bones1"}


# ======================= 2. the gated kickoff trigger =======================


@pytest.mark.asyncio
async def test_kickoff_fires_when_enabled(tmp_path):
    store, runtime, captured, _intents = _build_env(
        tmp_path,
        gc=GroupChatConfig(
            agent_initiated_kickoff_enabled=True,
            agent_reactivity_enabled=False,
            max_speakers_per_turn=0,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    store.append_message(t.id, author_id="scout1", role="agent", body="Bones, status?")
    loop = ProactiveCognitiveLoop(interval=60)
    loop.set_runtime(runtime)
    await loop._kickoff_group_chat(t.id, "scout1", "Bones, status?")
    # The OTHER participant (bones1) was dispatched; the opener (scout1) was not.
    assert "bones1" in captured
    assert "scout1" not in captured


@pytest.mark.asyncio
async def test_kickoff_noop_when_disabled(tmp_path):
    store, runtime, captured, _intents = _build_env(
        tmp_path,
        gc=GroupChatConfig(
            agent_initiated_kickoff_enabled=False,  # ships OFF
            agent_reactivity_enabled=False,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    store.append_message(t.id, author_id="scout1", role="agent", body="Bones, status?")
    loop = ProactiveCognitiveLoop(interval=60)
    loop.set_runtime(runtime)
    await loop._kickoff_group_chat(t.id, "scout1", "Bones, status?")
    assert captured == []  # no fan-out when the flag is off


@pytest.mark.asyncio
async def test_kickoff_honest_degrades_on_missing_store(tmp_path):
    # A runtime with no chat_thread_store must not raise into the proactive turn.
    _store, runtime, captured, _intents = _build_env(
        tmp_path, gc=GroupChatConfig(agent_initiated_kickoff_enabled=True),
    )
    runtime.chat_thread_store = None
    loop = ProactiveCognitiveLoop(interval=60)
    loop.set_runtime(runtime)
    await loop._kickoff_group_chat("nope", "scout1", "hi")  # must not raise
    assert captured == []


@pytest.mark.asyncio
async def test_agent_created_conceptual_kickoff_has_no_grounding_side_effects(
    tmp_path,
    monkeypatch,
    caplog,
):
    cfg = SystemConfig()
    cfg.group_chat.agent_initiated_kickoff_enabled = True
    cfg.group_chat.agent_reactivity_enabled = False
    cfg.group_chat.max_speakers_per_turn = 0
    cfg.grounding.referent_gate_enabled = True
    cfg.grounding.ground_before_collaborate_enabled = True
    cfg.grounding.confab_probe_enabled = True
    store, runtime, captured, intents = _build_env(
        tmp_path,
        gc=cfg.group_chat,
        config=cfg,
    )
    monkeypatch.setattr(thread_fanout, "build_default_resolvers", lambda **kw: [])
    scheduled: list[tuple[Any, str]] = []

    def _schedule(probe_factory: Any, *, name: str = "confab-probe") -> None:
        scheduled.append((probe_factory, name))
        return None

    runtime.schedule_confab_probe = _schedule
    opening_body = "Review the node identity distribution."
    thread = store.create_thread(
        title="room",
        participants=["scout1", "bones1"],
    )
    store.append_message(
        thread.id,
        author_id="scout1",
        role="agent",
        body=opening_body,
    )
    loop = ProactiveCognitiveLoop(interval=60)
    loop.set_runtime(runtime)

    with caplog.at_level(logging.WARNING):
        await loop._kickoff_group_chat(thread.id, "scout1", opening_body)

    assert captured == ["bones1"]
    assert all("grounding_cue" not in intent.params for intent in intents)
    assert scheduled == []
    assert not any("AD-1119[observe]" in r.getMessage() for r in caplog.records)
