"""AD-951 (Natural Conversation epic #882, issue #887): agent next-speaker
selection — Conversation-Analysis turn-allocation RULE 1a ("current speaker
selects next").

When an agent in a group chat DIRECTLY ADDRESSES a peer by callsign ("@yeo ..."
or the vocative "Yeo, ..." / "Yeo: ..."), that peer is selected to speak next:
the fan-out cascade hard-includes them (``mentioned=True``) in the next round,
overriding the per-turn cap + convergence, still bounded by ``max_agent_rounds``.
This makes AD-950's "hand the floor to a named peer" mechanical. The ``@`` form
already worked incidentally via the AD-915 global ``@(\\w+)`` scan; the NEW value
is the VOCATIVE form (essential for AD-921 VOICE meetings, where you cannot say
"@") and the DELIBERATE leading-address discipline (a message ABOUT a peer is
not a hand-off).

BF-287 discipline: real ``ChatThreadStore`` on ``tmp_path``, real
``IntentBus(SignalManager(reap_interval=1.0))``, real-but-fake registry/agents
with SCRIPTED ``direct_message`` handlers (NOT ``MagicMock``), a real
``GroupChatConfig`` toggled per test. Mirrors ``tests/test_ad935_*``. The pure
``extract_directed_callsign`` helper and the ``_assemble_speaker_signals``
hard-include wiring are tested directly; the end-to-end behavior is exercised
through ``group_chat_fanout`` with a deterministic ON-vs-OFF discriminator.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.config import GroupChatConfig
from probos.crew_profile import extract_directed_callsign
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import _assemble_speaker_signals, group_chat_fanout
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


# Real _WARD_ROOM_CREW agent types -> the callsigns the tests address.
_CALLSIGNS = {
    "scout": "Scout",
    "diagnostician": "Bones",
    "counselor": "Ops",
}


# ======================= 1. the pure directed-address helper =======================


def test_helper_at_form():
    assert extract_directed_callsign("@yeo what is your read?") == "yeo"


def test_helper_vocative_comma():
    assert extract_directed_callsign("Yeo, what is your read?") == "yeo"


def test_helper_vocative_colon():
    assert extract_directed_callsign("Yeo: what is your read?") == "yeo"


def test_helper_lowercases():
    assert extract_directed_callsign("OPS, status please") == "ops"


def test_helper_at_form_end_of_string():
    assert extract_directed_callsign("@Ops") == "ops"


def test_helper_bare_leading_word_is_not_an_address():
    # A leading word with no @, comma, or colon is a subject/noun, not an address.
    assert extract_directed_callsign("Data shows the variance is high") is None


def test_helper_about_mention_is_not_a_handoff():
    # An @callsign that does NOT lead the message is referential ("about"), not
    # a hand-off ("to") — mirrors is_directed_mention / BF #467.
    assert extract_directed_callsign("I agree with @yeo on this") is None


def test_helper_empty_and_blank():
    assert extract_directed_callsign("") is None
    assert extract_directed_callsign("   ") is None


# ============ 2. _assemble_speaker_signals hard-include wiring (deterministic) ============


def _signals_runtime(tmp_path):
    return SimpleNamespace(
        registry=_FakeRegistry({
            "scout1": _FakeAgent("scout"),
            "bones1": _FakeAgent("diagnostician"),
            "ops1": _FakeAgent("counselor"),
        }),
        callsign_registry=_FakeCallsigns(_CALLSIGNS),
        ontology=None,
    )


def test_addressed_callsign_hard_includes_that_candidate(tmp_path):
    runtime = _signals_runtime(tmp_path)
    # trigger has NO @-mention, so only the addressed_callsigns set can hard-include.
    sigs = _assemble_speaker_signals(
        runtime, "Scout: Ops, your read?", ["bones1", "ops1"], [],
        addressed_callsigns={"ops"},
    )
    by_id = {s.agent_id: s.mentioned for s in sigs}
    assert by_id["ops1"] is True       # addressed -> hard-included (rule 1a)
    assert by_id["bones1"] is False    # not addressed


def test_addressed_none_means_no_hard_include(tmp_path):
    runtime = _signals_runtime(tmp_path)
    sigs = _assemble_speaker_signals(
        runtime, "Scout: Ops, your read?", ["bones1", "ops1"], [],
        addressed_callsigns=None,
    )
    # No @-mention in the trigger and no addressed set -> nobody hard-included.
    assert all(s.mentioned is False for s in sigs)


def test_addressed_non_participant_matches_no_candidate(tmp_path):
    runtime = _signals_runtime(tmp_path)
    sigs = _assemble_speaker_signals(
        runtime, "Scout: Picard, orders?", ["bones1", "ops1"], [],
        addressed_callsigns={"picard"},
    )
    assert all(s.mentioned is False for s in sigs)  # honest-degrade, no error


# ============ 3. end-to-end through group_chat_fanout (ON-vs-OFF discriminator) ============


@pytest.mark.asyncio
async def test_vocative_handoff_selects_addressed_peer_next(tmp_path):
    # Round 0: @Scout (Captain mention) speaks alone (max_speakers=1). Scout's
    # reply VOCATIVELY addresses Ops (counselor). Round 1 MUST be Ops, even
    # though tiebreak/relevance would otherwise pick Bones (lower order_index).
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "bones1": "diagnostician", "ops1": "counselor"},
        callsigns=_CALLSIGNS,
        scripts={
            "scout1": ["Ops, what's your read on the variance?"],
            "bones1": ["bones speaks"],
            "ops1": ["ops here, the variance looks fine"],
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1,
            max_speakers_per_turn=1, agent_next_speaker_selection_enabled=True,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1", "ops1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="@Scout kick us off")
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="@Scout kick us off", captain_msg=cap
    )
    assert [r["agent_id"] for r in replies] == ["scout1", "ops1"]
    assert replies[1]["text"] == "ops here, the variance looks fine"


@pytest.mark.asyncio
async def test_flag_off_does_not_force_addressed_peer(tmp_path):
    # IDENTICAL setup, ONLY agent_next_speaker_selection_enabled=False. The
    # vocative "Ops," is now inert; round 1 falls to the default selection,
    # which (equal scores, ontology=None) tiebreaks on order_index -> Bones.
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "bones1": "diagnostician", "ops1": "counselor"},
        callsigns=_CALLSIGNS,
        scripts={
            "scout1": ["Ops, what's your read on the variance?"],
            "bones1": ["bones speaks"],
            "ops1": ["ops here, the variance looks fine"],
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1,
            max_speakers_per_turn=1, agent_next_speaker_selection_enabled=False,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1", "ops1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="@Scout kick us off")
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="@Scout kick us off", captain_msg=cap
    )
    # Round 1 is Bones (the default pick), NOT the addressed Ops -> proves the
    # flag gates the behavior and AD-935 is byte-identical when it's off.
    assert [r["agent_id"] for r in replies] == ["scout1", "bones1"]


@pytest.mark.asyncio
async def test_non_participant_handoff_is_ignored(tmp_path):
    # Scout addresses "Picard" (not a thread member). Honest-degrade: no crash,
    # no phantom speaker; the cascade proceeds with the only remaining candidate.
    store, runtime, dispatched = _build_env(
        tmp_path,
        agents={"scout1": "scout", "bones1": "diagnostician"},
        callsigns=_CALLSIGNS,
        scripts={"scout1": ["Picard, your orders?"], "bones1": ["bones acknowledges"]},
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1,
            max_speakers_per_turn=1, agent_next_speaker_selection_enabled=True,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="@Scout go")
    replies = await group_chat_fanout(runtime, t.id, captain_body="@Scout go", captain_msg=cap)
    assert [r["agent_id"] for r in replies] == ["scout1", "bones1"]
    assert "picard" not in {d["agent_id"] for d in dispatched}


@pytest.mark.asyncio
async def test_no_directed_address_is_inert_when_flag_on(tmp_path):
    # Flag ON but Scout's reply addresses no one -> the addressed set is empty,
    # so round 1 is the default selection (Bones), identical to flag-off AD-935.
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "bones1": "diagnostician", "ops1": "counselor"},
        callsigns=_CALLSIGNS,
        scripts={
            "scout1": ["I think we should proceed carefully."],
            "bones1": ["bones speaks"],
            "ops1": ["ops speaks"],
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1,
            max_speakers_per_turn=1, agent_next_speaker_selection_enabled=True,
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1", "ops1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="@Scout kick us off")
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="@Scout kick us off", captain_msg=cap
    )
    assert [r["agent_id"] for r in replies] == ["scout1", "bones1"]


# ======================= 4. config default (transitional #14) =======================


def test_config_default_is_off():
    # Pydantic default ships OFF (transitional behavioral flag, convention #14);
    # system.yaml flips it on for the live system.
    assert GroupChatConfig().agent_next_speaker_selection_enabled is False
