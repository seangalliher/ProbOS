"""AD-958 (Natural Conversation epic #882, #894): conversational trust learning
loop — convergence-only v1.

Three layers, all tested here:
  * pure ``extract_conversation_trust_outcomes`` + ``conversation_topic_tag``
    (no I/O, no consensus import) — tests 1-8,
  * the ``GroupChatConfig`` asymmetry validation — test 9,
  * end-to-end through ``group_chat_fanout`` against a REAL ``TrustNetwork`` —
    tests 10-16.

BF-287 discipline: a REAL ``TrustNetwork()`` (NOT MagicMock) so the synchronous
``record_outcome`` signature is exercised for real. Real ``ChatThreadStore`` /
``IntentBus``, mirroring ``tests/test_ad956_scale_aware_facilitation.py``.
asyncio_mode="auto": integration tests are plain ``async def`` (no marker).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from probos.cognitive.chat_facilitator import ChatFacilitator
from probos.cognitive.conversation_trust import (
    ConversationTrustOutcome,
    conversation_topic_tag,
    extract_conversation_trust_outcomes,
)
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.config import CommunicationsConfig, GroupChatConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import (
    _assemble_speaker_signals,
    group_chat_fanout,
)
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult

# Identical body across speakers -> mean pairwise Jaccard 1.0 >= 0.6 -> converged.
_CONV = "we should ship the release this sprint"
# Zero-overlap bodies -> mean pairwise Jaccard 0.0 -> never converged.
_DIVERGENT = [
    "alpha bravo charlie delta",
    "echo foxtrot golf hotel",
    "india juliet kilo lima",
    "mike november oscar papa",
    "quebec romeo sierra tango",
    "uniform victor whiskey xray",
]


def _reply(agent_id: str, text: str) -> dict[str, str]:
    return {"agent_id": agent_id, "callsign": "", "text": text}


def _facilitator() -> ChatFacilitator:
    # Default convergence params: enabled, threshold 0.6, min_messages 4, min_agents 2.
    return ChatFacilitator()


# ======================= 1-8. pure extractor / topic tag =======================


def test_extract_divergent_returns_empty():
    replies = [_reply(f"a{i}", _DIVERGENT[i]) for i in range(4)]
    out = extract_conversation_trust_outcomes(
        replies, facilitator=_facilitator(), intent_type="t",
        positive_weight=0.05, max_outcomes=4,
    )
    assert out == []


def test_extract_below_min_messages_returns_empty():
    replies = [_reply("a1", _CONV), _reply("a2", _CONV)]  # 2 msgs < min 4
    out = extract_conversation_trust_outcomes(
        replies, facilitator=_facilitator(), intent_type="t",
        positive_weight=0.05, max_outcomes=4,
    )
    assert out == []


def test_extract_single_agent_returns_empty():
    replies = [_reply("a1", _CONV) for _ in range(4)]  # 4 msgs, 1 agent
    out = extract_conversation_trust_outcomes(
        replies, facilitator=_facilitator(), intent_type="t",
        positive_weight=0.05, max_outcomes=4,
    )
    assert out == []


def test_extract_convergent_one_positive_per_distinct_agent():
    replies = [_reply(a, _CONV) for a in ("a1", "a2", "a3", "a4")]
    out = extract_conversation_trust_outcomes(
        replies, facilitator=_facilitator(), intent_type="release planning",
        positive_weight=0.05, max_outcomes=99,
    )
    assert len(out) == 4
    assert {o.agent_id for o in out} == {"a1", "a2", "a3", "a4"}
    for o in out:
        assert isinstance(o, ConversationTrustOutcome)
        assert o.success is True
        assert o.weight == 0.05
        assert o.intent_type == "release planning"


def test_extract_no_self_sourcing():
    participants = {"a1", "a2", "a3", "a4"}
    replies = [_reply(a, _CONV) for a in sorted(participants)]
    out = extract_conversation_trust_outcomes(
        replies, facilitator=_facilitator(), intent_type="t",
        positive_weight=0.05, max_outcomes=99,
    )
    assert out  # convergent
    for o in out:
        # An agent can NEVER raise its own trust: the verifier is a DIFFERENT peer.
        assert o.verifier_id != o.agent_id
        assert o.verifier_id in participants


def test_extract_bounded_to_max_outcomes():
    replies = [_reply(f"a{i}", _CONV) for i in range(6)]  # 6 distinct, converged
    out = extract_conversation_trust_outcomes(
        replies, facilitator=_facilitator(), intent_type="t",
        positive_weight=0.05, max_outcomes=4,
    )
    assert len(out) == 4  # capped
    for o in out:
        assert o.verifier_id != o.agent_id


def test_extract_zero_bounds_return_empty():
    replies = [_reply(a, _CONV) for a in ("a1", "a2", "a3", "a4")]
    assert extract_conversation_trust_outcomes(
        replies, facilitator=_facilitator(), intent_type="t",
        positive_weight=0.05, max_outcomes=0,
    ) == []
    assert extract_conversation_trust_outcomes(
        replies, facilitator=_facilitator(), intent_type="t",
        positive_weight=0.0, max_outcomes=4,
    ) == []


def test_conversation_topic_tag_cases():
    assert conversation_topic_tag("Release Planning") == "release planning"
    assert conversation_topic_tag("  Multiple   Spaces  ") == "multiple spaces"
    assert conversation_topic_tag("") == "group_chat"
    assert conversation_topic_tag("   ") == "group_chat"
    assert conversation_topic_tag(None) == "group_chat"  # type: ignore[arg-type]
    assert conversation_topic_tag("X" * 100) == "x" * 64  # lowercased + capped at 64


# ======================= 9. config asymmetry validation =======================


def test_config_asymmetry_and_defaults():
    # negative < positive violates the asymmetry invariant.
    with pytest.raises(ValidationError):
        GroupChatConfig(
            conversation_trust_positive_weight=0.2,
            conversation_trust_negative_weight=0.1,
        )
    # negative positive weight is invalid.
    with pytest.raises(ValidationError):
        GroupChatConfig(conversation_trust_positive_weight=-0.1)
    # negative outcome bound is invalid.
    with pytest.raises(ValidationError):
        GroupChatConfig(conversation_trust_max_outcomes=-1)
    gc = GroupChatConfig()
    assert gc.conversation_trust_enabled is False
    assert gc.conversation_trust_positive_weight == 0.05
    assert gc.conversation_trust_negative_weight == 0.15
    assert gc.conversation_trust_negative_weight >= gc.conversation_trust_positive_weight


# ======================= 10-16. end-to-end through group_chat_fanout =======================

_CREW_TYPES = ["scout", "diagnostician", "architect", "operations_officer", "engineering_officer", "science_officer"]


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class _FakeRegistry:
    def __init__(self, agents: dict) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)


class _FakeCallsigns:
    def __init__(self, mapping: dict) -> None:
        self._m = mapping

    def get_callsign(self, agent_type: str) -> str:
        return self._m.get(agent_type, "")


def _seq_clock():
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


def _make_handler(agent_id: str, captured: list, *, text: str):
    async def _h(intent: IntentMessage) -> IntentResult:
        captured.append(agent_id)
        return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True, result=text)
    return _h


def _build_env(tmp_path, *, gc, n: int, convergent: bool):
    """Real harness mirroring test_ad956._build_env, with a REAL ``TrustNetwork``
    on the runtime. ``convergent`` selects identical bodies (so the conversation
    converges) vs zero-overlap bodies (so it never does)."""
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    types = _CREW_TYPES[:n]
    agents = {f"{t}_{i}": _FakeAgent(t) for i, t in enumerate(types)}
    tn = TrustNetwork()
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=_FakeRegistry(agents),
        ontology=None,
        callsign_registry=_FakeCallsigns({t: t.title() for t in types}),
        project_store=None,
        trust_network=tn,
        config=SimpleNamespace(group_chat=gc, communications=CommunicationsConfig(), attachments=None),
    )
    captured: list[str] = []
    for i, aid in enumerate(agents):
        text = _CONV if convergent else _DIVERGENT[i]
        bus.subscribe(aid, _make_handler(aid, captured, text=text), intent_names=["direct_message"])
    return store, runtime, tn, list(agents)


async def _run(store, runtime, agent_ids, *, title: str = "release planning"):
    t = store.create_thread(title=title, participants=agent_ids)
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status team?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status team?", captain_msg=cap)
    return t, replies


async def test_default_off_is_byte_identical(tmp_path):
    # conversation_trust_enabled defaults False -> the trust network is untouched
    # even after a fully convergent conversation.
    store, runtime, tn, ids = _build_env(
        tmp_path, gc=GroupChatConfig(agent_reactivity_enabled=False), n=4, convergent=True,
    )
    before = {aid: tn.get_score(aid) for aid in ids}
    _t, replies = await _run(store, runtime, ids)
    assert len(replies) == 4  # all four spoke (convergent)
    after = {aid: tn.get_score(aid) for aid in ids}
    assert after == before
    assert tn.get_recent_events() == []  # nothing recorded when OFF


async def test_on_convergent_raises_trust_and_records_event(tmp_path):
    store, runtime, tn, ids = _build_env(
        tmp_path,
        gc=GroupChatConfig(conversation_trust_enabled=True, agent_reactivity_enabled=False),
        n=4, convergent=True,
    )
    before = {aid: tn.get_score(aid) for aid in ids}
    _t, replies = await _run(store, runtime, ids, title="Release Planning")
    assert len(replies) == 4
    after = {aid: tn.get_score(aid) for aid in ids}
    # Every corroborated agent's trust strictly rose above the prior.
    for aid in ids:
        assert after[aid] > before[aid]
    # A durable TrustEvent attributes the credit to a DISTINCT verifier, tagged
    # with the topic.
    for aid in ids:
        events = tn.get_events_for_agent(aid)
        assert events, f"agent {aid} should have a trust event"
        ev = events[-1]
        assert ev.success is True
        assert ev.intent_type == "release planning"  # conversation_topic_tag
        assert ev.verifier_id and ev.verifier_id != aid


async def test_on_divergent_leaves_trust_unchanged(tmp_path):
    store, runtime, tn, ids = _build_env(
        tmp_path,
        gc=GroupChatConfig(conversation_trust_enabled=True, agent_reactivity_enabled=False),
        n=4, convergent=False,
    )
    before = {aid: tn.get_score(aid) for aid in ids}
    _t, replies = await _run(store, runtime, ids)
    after = {aid: tn.get_score(aid) for aid in ids}
    assert after == before  # not converged -> no outcomes
    assert tn.get_recent_events() == []


async def test_loop_closes_raised_trust_reaches_speaker_signals(tmp_path):
    # AD-955/915 read: after a convergent ON conversation raises trust, the next
    # facilitation reads the raised score into SpeakerSignals.trust.
    store, runtime, tn, ids = _build_env(
        tmp_path,
        gc=GroupChatConfig(conversation_trust_enabled=True, agent_reactivity_enabled=False),
        n=4, convergent=True,
    )
    await _run(store, runtime, ids)
    signals = _assemble_speaker_signals(runtime, "status team?", ids, [])
    by_id = {s.agent_id: s.trust for s in signals}
    assert by_id == {aid: tn.get_score(aid) for aid in ids}
    assert all(t > 0.5 for t in by_id.values())  # all four were corroborated


def test_core_tier_immunity_record_outcome_unit():
    # CORE-tier immunity is owned by record_outcome (a focused unit test, per the
    # spec): a core agent's trust is never moved by a recorded outcome.
    from probos.substrate.agent_tier import AgentTier

    class _CoreTierReg:
        def get_tier(self, agent_id: str) -> AgentTier:
            return AgentTier.CORE_INFRASTRUCTURE

    tn = TrustNetwork()
    tn.set_tier_registry(_CoreTierReg())
    before = tn.get_score("core1")
    out = tn.record_outcome(
        "core1", success=True, weight=0.5, intent_type="release planning",
        episode_id="", verifier_id="peer", source="conversation",
    )
    assert out == before
    assert tn.get_score("core1") == before
    assert tn.get_events_for_agent("core1") == []


async def test_honest_degrade_record_failure_does_not_abort_fanout(tmp_path):
    store, runtime, tn, ids = _build_env(
        tmp_path,
        gc=GroupChatConfig(conversation_trust_enabled=True, agent_reactivity_enabled=False),
        n=4, convergent=True,
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("trust backend down")

    tn.record_outcome = _boom  # type: ignore[assignment]
    _t, replies = await _run(store, runtime, ids)
    # The fan-out result is untouched by a trust-record failure.
    assert len(replies) == 4
    assert all(r.get("text") for r in replies)


def test_no_capability_gap_phrasing_in_module():
    import probos.cognitive.conversation_trust as mod

    with open(mod.__file__, encoding="utf-8") as fh:
        source = fh.read()
    assert _CAPABILITY_GAP_RE.search(source) is None
