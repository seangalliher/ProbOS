"""AD-961: cascade-extend-on-address — a directed peer hand-off is always answered.

AD-951 routes a directed address ("Ezri, ...") to that peer as the next cascade
speaker, but only WITHIN ``max_agent_rounds``. When the address lands in the
LAST normal round, the addressed peer never got a turn (the Captain had to
manually re-prompt). AD-961 grants up to ``max_address_extensions`` EXTRA rounds
PAST the cap, each consumed only by a fresh unanswered directed address, so a
hand-off is always answered — bounded so mutual hand-offs can't ping-pong.

BF-287 discipline: real ``ChatThreadStore`` on ``tmp_path``, real
``IntentBus(SignalManager(reap_interval=1.0))``, real-but-fake registry/agents
with SCRIPTED ``direct_message`` handlers (NOT MagicMock), a real
``GroupChatConfig`` toggled per test. Mirrors ``tests/test_ad951_*`` /
``tests/test_ad935_*`` — exercised end-to-end through ``group_chat_fanout``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.config import GroupChatConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


# ---------------- BF-287 real-but-fake substrate stubs ----------------


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type  # real attr; is_crew_agent reads .agent_type


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


def _make_scripted_handler(agent_id: str, scripted: list[str], dispatched: list[dict]):
    state = {"n": 0}

    async def _h(intent: IntentMessage) -> IntentResult:
        n = state["n"]
        state["n"] += 1
        text = scripted[n] if n < len(scripted) else scripted[-1]
        dispatched.append({"agent_id": agent_id, "call": n, "trigger": intent.params.get("text")})
        return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True, result=text)

    return _h


def _build_env(tmp_path, *, agents, callsigns, scripts=None, gc=None):
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
        config=SimpleNamespace(group_chat=gc or GroupChatConfig(), attachments=None),
    )
    dispatched: list[dict] = []
    scripts = scripts or {}
    for aid in agents:
        handler = _make_scripted_handler(aid, scripts.get(aid, [f"reply::{aid}"]), dispatched)
        bus.subscribe(aid, handler, intent_names=["direct_message"])
    return store, runtime, dispatched


_CALLSIGNS = {"scout": "Scout", "counselor": "Ops"}


# ======================= the AD-961 extension behavior =======================


@pytest.mark.asyncio
async def test_address_in_last_round_is_answered_via_extension(tmp_path):
    # max_agent_rounds=1: round 0 (Captain @Scout) = Scout, who addresses Ops ->
    # round 1 = Ops (the one normal round). Ops addresses Scout in that LAST
    # round; pre-AD-961 the cascade stops and Scout never answers. With
    # max_address_extensions=1, an extra round runs and Scout answers.
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "ops1": "counselor"},
        callsigns=_CALLSIGNS,
        scripts={
            "scout1": ["Ops, what's your read?", "Scout here — the variance is fine."],
            "ops1": ["Scout, what do you think?"],
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1,
            max_speakers_per_turn=1, agent_next_speaker_selection_enabled=True,
            max_address_extensions=1,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "ops1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="@Scout kick us off")
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="@Scout kick us off", captain_msg=cap
    )
    # Scout -> Ops -> Scout (the dangling hand-off is answered).
    assert [r["agent_id"] for r in replies] == ["scout1", "ops1", "scout1"]
    assert replies[2]["text"] == "Scout here — the variance is fine."


@pytest.mark.asyncio
async def test_extension_disabled_drops_the_handoff(tmp_path):
    # IDENTICAL setup, ONLY max_address_extensions=0 (pre-AD-961 behavior): the
    # cascade stops at max_agent_rounds and Scout's answer never happens.
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "ops1": "counselor"},
        callsigns=_CALLSIGNS,
        scripts={
            "scout1": ["Ops, what's your read?", "Scout here — the variance is fine."],
            "ops1": ["Scout, what do you think?"],
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1,
            max_speakers_per_turn=1, agent_next_speaker_selection_enabled=True,
            max_address_extensions=0,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "ops1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="@Scout kick us off")
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="@Scout kick us off", captain_msg=cap
    )
    assert [r["agent_id"] for r in replies] == ["scout1", "ops1"]


@pytest.mark.asyncio
async def test_mutual_handoffs_are_bounded_no_pingpong(tmp_path):
    # Every reply addresses the other peer. With max_agent_rounds=1 and
    # max_address_extensions=1 the cascade is bounded at exactly
    # max_agent_rounds + max_address_extensions = 2 cascade rounds (round 0 +
    # 2 = 3 replies total). Proves a mutual hand-off chain can't loop forever.
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "ops1": "counselor"},
        callsigns=_CALLSIGNS,
        scripts={
            "scout1": ["Ops, your read?", "Ops, and your second read?"],
            "ops1": ["Scout, what do you think?", "Scout, again?"],
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1,
            max_speakers_per_turn=1, agent_next_speaker_selection_enabled=True,
            max_address_extensions=1,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "ops1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="@Scout kick us off")
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="@Scout kick us off", captain_msg=cap
    )
    # Bounded: Scout -> Ops -> Scout, then STOP (Scout's 2nd reply still
    # addresses Ops, but the extension budget is spent).
    assert [r["agent_id"] for r in replies] == ["scout1", "ops1", "scout1"]
    assert len(replies) == 3


@pytest.mark.asyncio
async def test_extension_inert_without_next_speaker_selection(tmp_path):
    # max_address_extensions=2 but agent_next_speaker_selection_enabled=False:
    # the extension is forced to 0 (it is meaningless without rule-1a routing),
    # so the cascade is byte-identical to AD-935 (stops at max_agent_rounds).
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "ops1": "counselor"},
        callsigns=_CALLSIGNS,
        scripts={
            "scout1": ["Ops, what's your read?", "Scout here again."],
            "ops1": ["Scout, what do you think?"],
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1,
            max_speakers_per_turn=1, agent_next_speaker_selection_enabled=False,
            max_address_extensions=2,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "ops1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="@Scout kick us off")
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="@Scout kick us off", captain_msg=cap
    )
    # Round 1 falls to the default selection (the only other candidate, Ops),
    # then STOP — no extension because next-speaker selection is off.
    assert [r["agent_id"] for r in replies] == ["scout1", "ops1"]


@pytest.mark.asyncio
async def test_no_address_in_last_round_does_not_extend(tmp_path):
    # The final normal round addresses NO ONE -> no extension (the budget is
    # only ever consumed by a fresh directed address).
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "ops1": "counselor"},
        callsigns=_CALLSIGNS,
        scripts={
            "scout1": ["Ops, your read?", "(should not be reached)"],
            "ops1": ["Agreed, the variance is fine."],  # addresses no one
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1,
            max_speakers_per_turn=1, agent_next_speaker_selection_enabled=True,
            max_address_extensions=1,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "ops1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="@Scout kick us off")
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="@Scout kick us off", captain_msg=cap
    )
    assert [r["agent_id"] for r in replies] == ["scout1", "ops1"]


# ======================= config default =======================


def test_config_default_extension_is_one():
    # Default 1: a single hand-off past the cap is answered, no ping-pong. Only
    # takes effect when next-speaker selection is on (itself an operator opt-in),
    # so a zero-config boot is unaffected.
    assert GroupChatConfig().max_address_extensions == 1
