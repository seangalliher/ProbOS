"""AD-963a (Natural Conversation epic #882): broadcast turn-mode terminator.

The AD-935 cascade stops at ``max_agent_rounds`` or the convergence gate — right
for a DISCUSSION, but wrong for a BROADCAST ("what do you ALL think?") where the
Captain wants EACH crew member to answer once. AD-963a classifies a plural ask
to the whole room as a broadcast and round-robins every crew participant exactly
once (cumulative exclude, bounded by participant count), instead of the
discussion cap. A non-broadcast turn (the default) is byte-identical.

BF-287 discipline: real ``ChatThreadStore`` / ``IntentBus`` / real-but-fake
registry + scripted handlers (NOT MagicMock); a real ``GroupChatConfig`` toggled
per test; exercised end-to-end through ``group_chat_fanout``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.config import GroupChatConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import classify_broadcast, group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


# ======================= 1. pure classifier =======================


def test_broadcast_cues_match():
    for t in [
        "What do you all think?",
        "Everyone, weigh in please.",
        "I'd like each of you to respond.",
        "All of you — give me your read.",
        "Thoughts from the whole team?",
        "Both of you, status?",
        "y'all have anything to add?",
    ]:
        assert classify_broadcast(t) is True, t


def test_non_broadcast_is_discussion():
    for t in [
        "Yeo, what's your read?",        # directed (AD-951 handles it)
        "Can you look at the variance?",  # singular
        "Status report.",
        "Let's hash out the cooperation cluster.",
        "",
        "I'll tell the team later.",      # 'the team' bare is NOT a cue (conservative)
    ]:
        assert classify_broadcast(t) is False, t


def test_classifier_handles_non_string():
    assert classify_broadcast(None) is False  # type: ignore[arg-type]
    assert classify_broadcast(123) is False    # type: ignore[arg-type]


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


def _make_handler(agent_id: str, text: str, dispatched: list[str]):
    async def _h(intent: IntentMessage) -> IntentResult:
        dispatched.append(agent_id)
        return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True, result=text)
    return _h


_CALLSIGNS = {"scout": "Scout", "counselor": "Ops", "diagnostician": "Bones"}


def _build_env(tmp_path, *, gc):
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    agents = {"scout1": "scout", "ops1": "counselor", "bones1": "diagnostician"}
    registry = _FakeRegistry({aid: _FakeAgent(at) for aid, at in agents.items()})
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=registry,
        ontology=None,
        callsign_registry=_FakeCallsigns(_CALLSIGNS),
        project_store=None,
        config=SimpleNamespace(group_chat=gc, communications=None, attachments=None),
    )
    dispatched: list[str] = []
    # Distinct replies so the convergence gate (>=4 similar msgs) never fires.
    texts = {"scout1": "Scout: the variance is bounded.",
             "ops1": "Ops: morale reads steady.",
             "bones1": "Bones: vitals nominal."}
    for aid in agents:
        bus.subscribe(aid, _make_handler(aid, texts[aid], dispatched), intent_names=["direct_message"])
    return store, runtime, dispatched


@pytest.mark.asyncio
async def test_broadcast_lets_every_crew_speak_once(tmp_path):
    # 3 crew, max_speakers_per_turn=1, broadcast cue + flag on. The cascade
    # round-robins all three (each exactly once), bounded by participant count —
    # NOT capped at max_agent_rounds=1.
    store, runtime, dispatched = _build_env(
        tmp_path,
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1, max_speakers_per_turn=1,
            broadcast_terminator_enabled=True,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "ops1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="What do you all think?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="What do you all think?", captain_msg=cap)
    # Every crew participant spoke exactly once.
    assert sorted(dispatched) == ["bones1", "ops1", "scout1"]
    assert len(dispatched) == len(set(dispatched))  # no agent twice
    assert len(replies) == 3


@pytest.mark.asyncio
async def test_discussion_default_is_capped(tmp_path):
    # Same room, NO broadcast cue -> discussion mode -> capped at
    # max_agent_rounds=1 (round 0 + 1 cascade round = 2 replies), NOT all three.
    store, runtime, dispatched = _build_env(
        tmp_path,
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1, max_speakers_per_turn=1,
            broadcast_terminator_enabled=True,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "ops1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="Let's review the cluster.")
    replies = await group_chat_fanout(runtime, t.id, captain_body="Let's review the cluster.", captain_msg=cap)
    assert len(replies) == 2  # discussion cap, not the full round-robin


@pytest.mark.asyncio
async def test_broadcast_flag_off_is_byte_identical_to_discussion(tmp_path):
    # Broadcast CUE present but the flag is OFF -> the cascade behaves exactly
    # like the AD-935/961 discussion cascade (capped at max_agent_rounds=1).
    store, runtime, dispatched = _build_env(
        tmp_path,
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1, max_speakers_per_turn=1,
            broadcast_terminator_enabled=False,  # ships OFF
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "ops1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="What do you all think?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="What do you all think?", captain_msg=cap)
    assert len(replies) == 2  # capped — broadcast terminator inert when flag off
