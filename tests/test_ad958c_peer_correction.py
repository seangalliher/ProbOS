"""AD-958c (Natural Conversation epic #882, #894): peer-corrects-peer
DETECT-AND-OBSERVE-ONLY.

v1 DETECTS an explicit peer-correction (corrector ``C`` asserts a PRIOR peer
``B``'s claim was factually WRONG) and OBSERVES it as a structured log — it
writes NOTHING to the trust network. The actual negative ``record_outcome`` is
deferred to AD-958d so the detector's precision can be measured on live
transcripts first.

Two layers, all tested here:
  * the pure ``detect_conversation_corrections`` + ``_CORRECTION_CUE_RE`` (no
    I/O, no consensus import) — tests 1-8, 12 (incl. the critical
    false-positive guard: mere DISAGREEMENT must NOT fire),
  * the observe wiring through ``group_chat_fanout`` against a REAL
    ``TrustNetwork`` — tests 9-11 (OFF byte-identical / ON logs-but-writes-
    nothing / ON-no-correction-no-log).

BF-287 discipline: a REAL ``TrustNetwork()`` (NOT MagicMock) so an accidental
write would be caught for real. Real ``ChatThreadStore`` / ``IntentBus``,
mirroring ``tests/test_ad958_conversation_trust.py``. asyncio_mode="auto": the
integration tests are plain ``async def`` (no marker).
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from probos.cognitive.conversation_trust import (
    ConversationCorrectionSignal,
    detect_conversation_corrections,
)
from probos.config import CommunicationsConfig, GroupChatConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


def _reply(agent_id: str, text: str, callsign: str = "") -> dict[str, str]:
    # AD-958c attribution resolves a directed @callsign to the PRIOR speaker via
    # each reply's ``callsign`` — so the helper POPULATES it (the AD-958 helper
    # left it blank because the convergence extractor keys off agent_id only).
    return {"agent_id": agent_id, "callsign": callsign, "text": text}


# ======================= 1-8, 12. pure detector =======================


def test_fires_on_explicit_directed_correction():
    replies = [
        _reply("yeo_id", "the gate threshold is 0.6", callsign="Yeo"),
        _reply("ezri_id", "@yeo that's not right, it's 0.7", callsign="Ezri"),
    ]
    out = detect_conversation_corrections(replies, intent_type="release", max_signals=4)
    assert len(out) == 1
    sig = out[0]
    assert isinstance(sig, ConversationCorrectionSignal)
    assert sig.corrected_agent_id == "yeo_id"
    assert sig.corrector_id == "ezri_id"
    assert sig.cue  # non-empty cue
    assert sig.intent_type == "release"


@pytest.mark.parametrize(
    "text",
    [
        "@yeo I disagree",
        "@yeo I'd weigh it differently",
        "@yeo from my vantage, the risk is higher",
        "@yeo I'm not sure",
        "@yeo not necessarily",
        "@yeo I see it differently",
    ],
)
def test_disagreement_is_not_a_correction(text):
    # The critical precision guard: a directed DISAGREEMENT (not an assertion that
    # the prior claim is factually WRONG) must NOT fire.
    replies = [
        _reply("yeo_id", "the gate threshold is 0.6", callsign="Yeo"),
        _reply("ezri_id", text, callsign="Ezri"),
    ]
    assert detect_conversation_corrections(replies, intent_type="t", max_signals=4) == []


def test_no_self_sourcing():
    # A directed correction whose callsign resolves to the corrector's OWN id is
    # not a peer-correction (an agent cannot correct itself into a signal).
    replies = [
        _reply("ezri_id", "the gate threshold is 0.6", callsign="Ezri"),
        _reply("ezri_id", "@ezri that's wrong", callsign="Ezri"),
    ]
    assert detect_conversation_corrections(replies, intent_type="t", max_signals=4) == []


def test_requires_a_directed_address():
    # A correction cue with NO leading @callsign address is ambiguous (who is
    # being corrected?) -> no signal.
    replies = [
        _reply("yeo_id", "the gate threshold is 0.6", callsign="Yeo"),
        _reply("ezri_id", "that's not right at all", callsign="Ezri"),
    ]
    assert detect_conversation_corrections(replies, intent_type="t", max_signals=4) == []


def test_corrected_must_have_spoken_earlier():
    # Addressing a callsign that never spoke (no prior claim to be wrong) -> [].
    replies = [
        _reply("yeo_id", "the gate threshold is 0.6", callsign="Yeo"),
        _reply("ezri_id", "@ghost that's wrong", callsign="Ezri"),
    ]
    assert detect_conversation_corrections(replies, intent_type="t", max_signals=4) == []


def test_correction_before_target_speaks():
    # The address points at a callsign that appears only LATER -> no prior claim
    # at the moment of the cue -> [].
    replies = [
        _reply("ezri_id", "@yeo that's not right", callsign="Ezri"),
        _reply("yeo_id", "the gate threshold is 0.6", callsign="Yeo"),
    ]
    assert detect_conversation_corrections(replies, intent_type="t", max_signals=4) == []


def test_bounded_and_deduped():
    # Repeated C->B corrections collapse to ONE signal.
    dup = [
        _reply("b_id", "the figure is 10", callsign="Bee"),
        _reply("c_id", "@bee that's wrong", callsign="Cee"),
        _reply("c_id", "@bee that's not right either", callsign="Cee"),
    ]
    assert len(detect_conversation_corrections(dup, intent_type="t", max_signals=4)) == 1
    # max_signals=0 -> [].
    assert detect_conversation_corrections(dup, intent_type="t", max_signals=0) == []
    # Two distinct pairs, capped at max_signals.
    two = [
        _reply("b_id", "x", callsign="Bee"),
        _reply("d_id", "y", callsign="Dee"),
        _reply("c_id", "@bee that's wrong", callsign="Cee"),
        _reply("e_id", "@dee that's incorrect", callsign="Eee"),
    ]
    assert len(detect_conversation_corrections(two, intent_type="t", max_signals=4)) == 2
    assert len(detect_conversation_corrections(two, intent_type="t", max_signals=1)) == 1


def test_pure_determinism():
    replies = [
        _reply("b_id", "x", callsign="Bee"),
        _reply("d_id", "y", callsign="Dee"),
        _reply("c_id", "@bee that's wrong", callsign="Cee"),
        _reply("e_id", "@dee that's incorrect", callsign="Eee"),
    ]
    out1 = detect_conversation_corrections(replies, intent_type="t", max_signals=4)
    out2 = detect_conversation_corrections(replies, intent_type="t", max_signals=4)
    assert out1 == out2  # frozen dataclass value equality
    assert len(out1) == 2


def test_tier_agnostic_pure_detector():
    # The PURE detector does NOT know about tiers: it emits a signal even when the
    # corrected agent is a CORE-tier id. CORE immunity is the FUTURE write's
    # concern (record_outcome, AD-958d), not the detector's.
    replies = [
        _reply("system_heartbeat", "load is nominal", callsign="System"),
        _reply("ezri_id", "@system that's wrong, load is high", callsign="Ezri"),
    ]
    out = detect_conversation_corrections(replies, intent_type="t", max_signals=4)
    assert len(out) == 1
    assert out[0].corrected_agent_id == "system_heartbeat"
    assert out[0].corrector_id == "ezri_id"


# ======================= 9-11. observe wiring through group_chat_fanout =======================

_CREW_TYPES = ["scout", "diagnostician", "architect", "operations_officer"]
# Mutual correction: each agent corrects the OTHER, so exactly ONE signal fires
# (the SECOND speaker correcting the FIRST) regardless of facilitation order.
_CORR_TEXTS = [
    "@diagnostician that's not right, recheck the figure",  # scout_0 -> diagnostician_1
    "@scout that's wrong, the math is off",                 # diagnostician_1 -> scout_0
]


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


def _build_corr_env(tmp_path, *, gc, texts: list[str]):
    """Real harness mirroring test_ad958._build_env, with a REAL ``TrustNetwork``
    on the runtime and per-agent custom ``texts`` (so a corrector can address a
    peer by callsign). ``callsign = agent_type.title()`` => "@scout" addresses
    ``scout_0``."""
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    types = _CREW_TYPES[: len(texts)]
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
        bus.subscribe(aid, _make_handler(aid, captured, text=texts[i]), intent_names=["direct_message"])
    return store, runtime, tn, list(agents)


async def _run(store, runtime, agent_ids, *, title: str = "release planning"):
    t = store.create_thread(title=title, participants=agent_ids)
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status team?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status team?", captain_msg=cap)
    return t, replies


async def test_observe_off_is_byte_identical(tmp_path):
    # conversation_trust_correction_observe_enabled defaults False -> the detector
    # never runs even on a directed-correction transcript: replies returned, trust
    # untouched.
    store, runtime, tn, ids = _build_corr_env(
        tmp_path, gc=GroupChatConfig(agent_reactivity_enabled=False), texts=_CORR_TEXTS,
    )
    before = {a: tn.get_score(a) for a in ids}
    _t, replies = await _run(store, runtime, ids)
    assert len(replies) == 2  # both crew spoke
    after = {a: tn.get_score(a) for a in ids}
    assert after == before
    assert tn.get_recent_events() == []  # nothing recorded


async def test_observe_on_logs_but_does_not_write(tmp_path, caplog):
    # observe ON (positive path still OFF): a directed correction emits a
    # structured "AD-958c[observe]" log naming corrector + corrected, but writes
    # NOTHING to the trust network.
    store, runtime, tn, ids = _build_corr_env(
        tmp_path,
        gc=GroupChatConfig(
            conversation_trust_correction_observe_enabled=True,
            agent_reactivity_enabled=False,
        ),
        texts=_CORR_TEXTS,
    )
    before = {a: tn.get_score(a) for a in ids}
    with caplog.at_level(logging.INFO, logger="probos.routers.thread_fanout"):
        _t, replies = await _run(store, runtime, ids)
    assert len(replies) == 2  # both spoke -> the second corrects the first
    assert "AD-958c[observe]" in caplog.text
    # the single signal's log line names BOTH agents (one corrector, one corrected)
    assert "scout_0" in caplog.text and "diagnostician_1" in caplog.text
    after = {a: tn.get_score(a) for a in ids}
    assert after == before  # OBSERVE-ONLY: no trust write
    assert tn.get_recent_events() == []


async def test_observe_on_no_correction_no_log(tmp_path, caplog):
    # observe ON but a benign transcript (no correction cue) -> no log, trust
    # unchanged.
    store, runtime, tn, ids = _build_corr_env(
        tmp_path,
        gc=GroupChatConfig(
            conversation_trust_correction_observe_enabled=True,
            agent_reactivity_enabled=False,
        ),
        texts=["all looks good to me", "agreed, ship it"],
    )
    before = {a: tn.get_score(a) for a in ids}
    with caplog.at_level(logging.INFO, logger="probos.routers.thread_fanout"):
        _t, replies = await _run(store, runtime, ids)
    assert "AD-958c[observe]" not in caplog.text
    after = {a: tn.get_score(a) for a in ids}
    assert after == before
