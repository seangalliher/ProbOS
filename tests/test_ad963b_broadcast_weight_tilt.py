"""AD-963b (Natural Conversation epic #882): broadcast department-dominant
weight tilt — the deferred-for-live-look third of #897.

AD-963a shipped the broadcast TERMINATOR (round-robin every crew member once)
and the ``classify_broadcast`` cue detector; AD-951 the directed dispatch. The
remaining gap was MODE-AWARE WEIGHTS: in a BROADCAST the Captain wants the
DOMAIN EXPERT to frame the topic first, so AD-963b re-weights the facilitator
(department-dominant) for a broadcast turn. The whole change is gated on the
master flag ``group_chat.turn_mode_policy_enabled`` (ships OFF) — with it OFF the
classifier never runs, the terminator keys off the shipped ``classify_broadcast``,
and the facilitator uses the standard fixed weights => byte-identical AD-963a.

BF-287 discipline: real ``ChatThreadStore`` / ``IntentBus`` / real-but-fake
registry + scripted handlers (NOT MagicMock); a real ``GroupChatConfig`` toggled
per test; exercised end-to-end through ``group_chat_fanout``. Mirrors the
tests/test_ad963a_broadcast_terminator.py harness exactly.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.cognitive.chat_facilitator import ChatFacilitator, SpeakerSignals
from probos.config import GroupChatConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import classify_turn_mode, group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


# ======================= 1. pure classify_turn_mode =======================


def test_classify_turn_mode_directed_precedence():
    # A directed callsign wins even when a broadcast cue is also present —
    # AD-951's next-speaker selection owns the dispatch for a directed turn.
    assert classify_turn_mode("what do you all think?", directed_callsign="yeo") == "directed"


def test_classify_turn_mode_broadcast():
    # No directed callsign + a plural ask to the whole room -> broadcast.
    assert classify_turn_mode("what do you all think?", directed_callsign=None) == "broadcast"


def test_classify_turn_mode_discussion():
    # No directed callsign + no broadcast cue -> the default discussion mode.
    assert classify_turn_mode("let's hash this out", directed_callsign=None) == "discussion"


# ============== 2. from_config weight selection (public rank API) ==============


def _factors_for(config: object, *, broadcast: bool) -> dict[str, float]:
    """Rank a single fully-relevant, mentioned signal and return the weight
    factors actually applied (public ``rank`` API — no private-attr access).
    turns_since=0 -> recency_factor 0; trust=0 -> no trust term; so the factor
    dict isolates the mention + department WEIGHTS exactly."""
    fac = ChatFacilitator.from_config(config, broadcast=broadcast)
    scores = fac.rank([
        SpeakerSignals(
            agent_id="a", mentioned=True, department_relevance=1.0,
            trust=0.0, turns_since_last_spoke=0, order_index=0,
        )
    ])
    return scores[0].factors


def test_from_config_broadcast_policy_on_uses_department_dominant_weights():
    config = SimpleNamespace(group_chat=GroupChatConfig(turn_mode_policy_enabled=True))
    factors = _factors_for(config, broadcast=True)
    assert factors["department"] == 0.50
    assert factors["mention"] == 0.20


def test_from_config_broadcast_policy_off_is_byte_identical_standard():
    # Master flag OFF -> broadcast=True resolves to the STANDARD weights
    # (byte-identical to the pre-AD-963b facilitator).
    config = SimpleNamespace(group_chat=GroupChatConfig(turn_mode_policy_enabled=False))
    factors = _factors_for(config, broadcast=True)
    assert factors["department"] == 0.25
    assert factors["mention"] == 0.40


# ======================= 3. end-to-end through group_chat_fanout =======================


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


def _bcast_gc(policy_on: bool) -> GroupChatConfig:
    return GroupChatConfig(
        agent_reactivity_enabled=True, max_agent_rounds=1, max_speakers_per_turn=1,
        broadcast_terminator_enabled=True, turn_mode_policy_enabled=policy_on,
    )


@pytest.mark.asyncio
async def test_broadcast_policy_on_domain_expert_frames_first(tmp_path):
    # 3 crew, broadcast cue + policy ON. The Captain names a domain ("scout"),
    # so the department-dominant tilt ranks the scout FIRST (it frames the
    # topic), and the AD-963a terminator round-robins all three exactly once.
    store, runtime, dispatched = _build_env(tmp_path, gc=_bcast_gc(True))
    t = store.create_thread(title="room", participants=["scout1", "ops1", "bones1"])
    body = "everyone scout report"
    cap = store.append_message(t.id, author_id="captain", role="captain", body=body)
    replies = await group_chat_fanout(runtime, t.id, captain_body=body, captain_msg=cap)
    assert replies[0]["agent_id"] == "scout1"   # department-dominant: expert frames first
    assert sorted(r["agent_id"] for r in replies) == ["bones1", "ops1", "scout1"]
    assert len(replies) == 3                     # every crew participant once


@pytest.mark.asyncio
async def test_byte_identical_discriminator_policy_reorders_by_department(tmp_path):
    # SAME room + SAME Captain turn; only turn_mode_policy_enabled differs. A
    # prior scout turn makes the domain expert STALE (low recency) while the
    # other two are fresh. Under STANDARD weights (policy OFF) recency outweighs
    # the expert's department term -> a fresh non-expert frames first (AD-963a
    # ordering). The broadcast tilt (department 0.50, recency 0.15) FLIPS it ->
    # the stale domain expert frames first.
    body = "everyone scout report"

    async def _replies(policy_on: bool, sub: str):
        sub_dir = tmp_path / sub
        sub_dir.mkdir()
        store, runtime, _ = _build_env(sub_dir, gc=_bcast_gc(policy_on))
        t = store.create_thread(title="room", participants=["scout1", "ops1", "bones1"])
        store.append_message(t.id, author_id="scout1", role="agent", body="Scout: earlier note.")
        cap = store.append_message(t.id, author_id="captain", role="captain", body=body)
        return await group_chat_fanout(runtime, t.id, captain_body=body, captain_msg=cap)

    off = await _replies(False, "off")
    on = await _replies(True, "on")
    # Policy OFF reproduces AD-963a ordering: a fresh non-expert frames first.
    assert off[0]["agent_id"] == "ops1"
    # Policy ON reorders by department: the (stale) domain expert frames first.
    assert on[0]["agent_id"] == "scout1"
    # Both round-robin via the AD-963a terminator (every crew participant once).
    assert len(off) == 3 and len(on) == 3


@pytest.mark.asyncio
async def test_directed_wins_over_broadcast_cue_policy_on(tmp_path):
    # A leading directed address to a participant ("Scout, ...") plus a broadcast
    # cue ("everyone"), policy ON. Directed wins: the addressed agent frames
    # first, the standard weights are used (no tilt), and the broadcast
    # round-robin does NOT fire (discussion cap, NOT all-three-once).
    store, runtime, dispatched = _build_env(tmp_path, gc=_bcast_gc(True))
    t = store.create_thread(title="room", participants=["scout1", "ops1", "bones1"])
    body = "Scout, everyone what's your read?"
    cap = store.append_message(t.id, author_id="captain", role="captain", body=body)
    replies = await group_chat_fanout(runtime, t.id, captain_body=body, captain_msg=cap)
    assert replies[0]["agent_id"] == "scout1"                 # directed agent frames first
    assert len(replies) == 2                                  # capped, NOT the 3-way round-robin
    assert "bones1" not in [r["agent_id"] for r in replies]   # no forced round-robin


@pytest.mark.asyncio
async def test_discussion_policy_on_is_byte_identical(tmp_path):
    # A discussion turn (no cue, no leading callsign), policy ON vs OFF. The
    # AD-935 cascade is unaffected by the policy flag: same ordering, same count,
    # standard weights both ways.
    body = "let's hash out the cluster"

    async def _replies(policy_on: bool, sub: str):
        sub_dir = tmp_path / sub
        sub_dir.mkdir()
        store, runtime, _ = _build_env(sub_dir, gc=_bcast_gc(policy_on))
        t = store.create_thread(title="room", participants=["scout1", "ops1", "bones1"])
        cap = store.append_message(t.id, author_id="captain", role="captain", body=body)
        return await group_chat_fanout(runtime, t.id, captain_body=body, captain_msg=cap)

    off = await _replies(False, "off")
    on = await _replies(True, "on")
    assert [r["agent_id"] for r in off] == [r["agent_id"] for r in on]   # identical ordering
    assert len(off) == 2   # discussion cap (no broadcast round-robin), unchanged
