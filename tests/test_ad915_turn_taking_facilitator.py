"""AD-915: turn-taking facilitator tests.

Two halves:

* The pure ``ChatFacilitator`` value-class (ranking / truncation /
  convergence / @-mention override) is exercised directly — it has no I/O,
  so no fixtures are needed.
* The impure assembly helper ``_assemble_speaker_signals`` and the
  ``group_chat_fanout`` wiring follow BF-287 discipline: real
  ``ChatThreadStore`` on ``tmp_path``, real ``IntentBus(SignalManager(
  reap_interval=1.0))``, and real-but-fake registry / callsign / ontology
  stubs (NOT ``MagicMock``) at the substrate/bus boundary. The integration
  cases prove AD-914's all-at-once invariant survives (cap off, convergence
  inert) and that convergence + @-mention reshape the dispatch correctly.
"""
from __future__ import annotations

from types import SimpleNamespace

from probos.cognitive.chat_facilitator import (
    ChatFacilitator,
    FacilitationResult,
    SpeakerScore,
    SpeakerSignals,
)
from probos.config import GroupChatConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import (
    _assemble_speaker_signals,
    _build_session_history,
    group_chat_fanout,
)
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


# ============================ pure facilitator ============================


def test_rank_orders_by_relevance():
    f = ChatFacilitator()
    sigs = [
        SpeakerSignals(agent_id="a", department_relevance=0.1, order_index=0),
        SpeakerSignals(agent_id="b", department_relevance=0.9, order_index=1),
        SpeakerSignals(agent_id="c", department_relevance=0.5, order_index=2),
    ]
    ranked = f.rank(sigs)
    assert [s.agent_id for s in ranked] == ["b", "c", "a"]
    assert all(isinstance(s, SpeakerScore) for s in ranked)


def test_mentioned_speaker_ranks_first():
    # A mentioned speaker is pulled to the FRONT by facilitate() even when a
    # non-mentioned speaker has a strictly higher raw relevance score.
    f = ChatFacilitator()  # cap off
    sigs = [
        SpeakerSignals(
            agent_id="high", department_relevance=1.0, trust=1.0,
            turns_since_last_spoke=99, order_index=0,
        ),
        SpeakerSignals(
            agent_id="mention", mentioned=True, department_relevance=0.0,
            trust=0.0, turns_since_last_spoke=0, order_index=1,
        ),
    ]
    result = f.facilitate(sigs, [])
    assert result.speaking_order == ["mention", "high"]


def test_truncation_caps_non_mentioned():
    f = ChatFacilitator(max_speakers_per_turn=2)
    sigs = [
        SpeakerSignals(agent_id=f"a{i}", department_relevance=(5 - i) / 10, order_index=i)
        for i in range(5)
    ]
    result = f.facilitate(sigs, [])
    assert len(result.speaking_order) == 2
    assert result.converged is False


def test_truncation_off_by_default_returns_all():
    f = ChatFacilitator()  # cap 0 == AD-914 all-at-once
    sigs = [SpeakerSignals(agent_id=f"a{i}", order_index=i) for i in range(5)]
    result = f.facilitate(sigs, [])
    assert len(result.speaking_order) == 5


def test_mention_always_included_past_cap():
    # cap 1 + 2 mentions => both mentions survive; the cap bounds only the
    # NON-mentioned tail (remaining = max(0, 1 - 2) = 0).
    f = ChatFacilitator(max_speakers_per_turn=1)
    sigs = [
        SpeakerSignals(agent_id="m1", mentioned=True, order_index=0),
        SpeakerSignals(agent_id="m2", mentioned=True, order_index=1),
        SpeakerSignals(agent_id="n1", department_relevance=1.0, order_index=2),
    ]
    result = f.facilitate(sigs, [])
    assert "m1" in result.speaking_order and "m2" in result.speaking_order
    assert "n1" not in result.speaking_order
    assert result.speaking_order[:2] == ["m1", "m2"]


def test_convergence_suppresses_speakers():
    f = ChatFacilitator()
    msgs = [
        ("a", "status nominal all systems go"),
        ("b", "status nominal all systems go"),
        ("a", "status nominal all systems go"),
        ("b", "status nominal all systems go"),
    ]
    sigs = [
        SpeakerSignals(agent_id="a", order_index=0),
        SpeakerSignals(agent_id="b", order_index=1),
    ]
    result = f.facilitate(sigs, msgs)
    assert isinstance(result, FacilitationResult)
    assert result.converged is True
    assert result.speaking_order == []


def test_convergence_inert_below_min_messages():
    f = ChatFacilitator()
    msgs = [("a", "same words here"), ("b", "same words here")]  # only 2 < min 4
    assert f.is_converged(msgs) is False


def test_convergence_inert_single_agent():
    # 6 identical messages from ONE author is self-echo, not cross-agent
    # convergence (distinct agents 1 < min 2).
    f = ChatFacilitator()
    msgs = [("a", "echo echo echo")] * 6
    assert f.is_converged(msgs) is False


def test_convergence_inert_low_similarity():
    # >= 4 msgs from 2 agents but disjoint word sets => mean Jaccard 0 < 0.6.
    f = ChatFacilitator()
    msgs = [
        ("a", "alpha bravo charlie"),
        ("b", "delta echo foxtrot"),
        ("a", "golf hotel india"),
        ("b", "juliet kilo lima"),
    ]
    assert f.is_converged(msgs) is False


def test_mention_overrides_convergence():
    f = ChatFacilitator()
    msgs = [
        ("a", "status nominal all systems"),
        ("b", "status nominal all systems"),
        ("a", "status nominal all systems"),
        ("b", "status nominal all systems"),
    ]
    sigs = [
        SpeakerSignals(agent_id="a", order_index=0),
        SpeakerSignals(agent_id="m", mentioned=True, order_index=1),
    ]
    result = f.facilitate(sigs, msgs)
    assert result.converged is True
    assert result.speaking_order == ["m"]


def test_recency_fairness_prioritizes_quiet_agent():
    f = ChatFacilitator()
    sigs = [
        SpeakerSignals(agent_id="loud", turns_since_last_spoke=0, order_index=0),
        SpeakerSignals(agent_id="quiet", turns_since_last_spoke=10, order_index=1),
    ]
    ranked = f.rank(sigs)
    assert [s.agent_id for s in ranked] == ["quiet", "loud"]


def test_rank_deterministic_stable_tiebreak():
    # Identical scores => stable tiebreak on (order_index, agent_id). "z"
    # has the lower order_index so it precedes "a" despite alphabetic order.
    f = ChatFacilitator()
    sigs = [
        SpeakerSignals(agent_id="z", turns_since_last_spoke=5, trust=0.5, order_index=0),
        SpeakerSignals(agent_id="a", turns_since_last_spoke=5, trust=0.5, order_index=1),
    ]
    assert [s.agent_id for s in f.rank(sigs)] == ["z", "a"]
    assert [s.agent_id for s in f.rank(sigs)] == ["z", "a"]  # deterministic


def test_from_config_none_uses_defaults():
    f = ChatFacilitator.from_config(None)
    sigs = [SpeakerSignals(agent_id=f"a{i}", order_index=i) for i in range(3)]
    # cap off => all returned (AD-914 invariant)
    assert len(f.facilitate(sigs, []).speaking_order) == 3
    # convergence on => a similar window suppresses
    msgs = [
        ("a", "all nominal status"), ("b", "all nominal status"),
        ("a", "all nominal status"), ("b", "all nominal status"),
    ]
    assert f.facilitate(sigs[:2], msgs).converged is True


def test_from_config_reads_group_chat_fields():
    # Non-None branch: read cap + convergence flag from a real GroupChatConfig.
    cfg = SimpleNamespace(
        group_chat=GroupChatConfig(max_speakers_per_turn=2, convergence_enabled=False)
    )
    f = ChatFacilitator.from_config(cfg)
    sigs = [SpeakerSignals(agent_id=f"a{i}", order_index=i) for i in range(5)]
    assert len(f.facilitate(sigs, []).speaking_order) == 2  # cap applied
    msgs = [
        ("a", "same same same"), ("b", "same same same"),
        ("a", "same same same"), ("b", "same same same"),
    ]
    assert f.is_converged(msgs) is False  # convergence disabled


# ===================== BF-287 real-but-fake substrate stubs ===============


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)


class _FakeCallsigns:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._m = mapping

    def get_callsign(self, agent_type: str) -> str:
        return self._m.get(agent_type, "")


class _FakeOntology:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._m = mapping

    def get_agent_department(self, agent_type: str) -> str | None:
        return self._m.get(agent_type)


def _seq_clock():
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


# ===================== assembly helper (impure boundary) ==================


def test_assemble_detects_mention():
    runtime = SimpleNamespace(
        registry=_FakeRegistry(
            {"counselor1": _FakeAgent("counselor"), "scout1": _FakeAgent("scout")}
        ),
        callsign_registry=_FakeCallsigns({"counselor": "Troi", "scout": "Scout"}),
    )
    sigs = _assemble_speaker_signals(
        runtime, "@troi status?", ["counselor1", "scout1"], []
    )
    by_id = {s.agent_id: s for s in sigs}
    assert by_id["counselor1"].mentioned is True
    assert by_id["scout1"].mentioned is False


def test_assemble_recency_from_prior(tmp_path):
    store = ChatThreadStore(tmp_path / "t.db", clock=_seq_clock())
    t = store.create_thread(title="r", participants=["scout1", "counselor1"])
    store.append_message(t.id, author_id="scout1", role="agent", body="s0")
    store.append_message(t.id, author_id="counselor1", role="agent", body="c0")
    store.append_message(t.id, author_id="scout1", role="agent", body="s1")
    prior = store.list_messages(t.id, limit=1000)  # 3 agent rows, ASC
    runtime = SimpleNamespace(
        registry=_FakeRegistry(
            {
                "scout1": _FakeAgent("scout"),
                "counselor1": _FakeAgent("counselor"),
                "yeo1": _FakeAgent("yeoman"),
            }
        ),
        callsign_registry=_FakeCallsigns({}),
    )
    sigs = _assemble_speaker_signals(
        runtime, "report", ["scout1", "counselor1", "yeo1"], prior
    )
    by_id = {s.agent_id: s for s in sigs}
    # n_prior=3; scout1 last at idx2 => 1; counselor1 last idx1 => 2; yeo1 never.
    assert by_id["scout1"].turns_since_last_spoke == 1
    assert by_id["counselor1"].turns_since_last_spoke == 2
    assert by_id["yeo1"].turns_since_last_spoke == 9_999


def test_assemble_department_relevance_and_fallback():
    # No ontology, no trust_network: dept descriptor falls back to agent_type,
    # trust degrades to the neutral 0.5 default — no crash.
    runtime = SimpleNamespace(
        registry=_FakeRegistry({"scout1": _FakeAgent("scout")}),
        callsign_registry=_FakeCallsigns({"scout": "Scout"}),
    )
    sigs = _assemble_speaker_signals(runtime, "scout the area ahead", ["scout1"], [])
    assert sigs[0].department_relevance > 0.0  # "scout" overlaps captain words
    assert sigs[0].trust == 0.5                # trust_network absent => neutral

    # Ontology-present branch: department word participates in the descriptor.
    runtime2 = SimpleNamespace(
        registry=_FakeRegistry({"med1": _FakeAgent("doctor")}),
        callsign_registry=_FakeCallsigns({"doctor": "Bones"}),
        ontology=_FakeOntology({"doctor": "medical"}),
    )
    sigs2 = _assemble_speaker_signals(
        runtime2, "medical emergency triage", ["med1"], []
    )
    assert sigs2[0].department_relevance > 0.0  # "medical" overlaps captain words


# ===================== group_chat_fanout integration ======================


def _recording_handler(received: dict, agent_id: str):
    async def _h(intent: IntentMessage) -> IntentResult:
        received.setdefault(agent_id, []).append(intent.params.get("text"))
        return IntentResult(
            intent_id=intent.id, agent_id=agent_id, success=True,
            result=f"reply::{agent_id}",
        )

    return _h


def _build_env(tmp_path, *, agents, callsigns=None, subscribe=None):
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    registry = _FakeRegistry({aid: _FakeAgent(at) for aid, at in agents.items()})
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=registry,
        ontology=None,
        callsign_registry=_FakeCallsigns(callsigns or {}),
    )
    received: dict[str, list] = {}
    sub_ids = list(agents.keys()) if subscribe is None else list(subscribe)
    for aid in sub_ids:
        bus.subscribe(aid, _recording_handler(received, aid), intent_names=["direct_message"])
    return store, runtime, received


async def test_fanout_two_agent_unchanged_ad914(tmp_path):
    # No config on the runtime => from_config(None) => cap off + convergence
    # inert (empty prior). AD-914's all-at-once invariant must hold.
    store, runtime, received = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="status?", captain_msg=cap
    )
    assert {r["agent_id"] for r in replies} == {"scout1", "counselor1"}
    assert set(received.keys()) == {"scout1", "counselor1"}


async def test_fanout_converged_thread_suppresses(tmp_path):
    store, runtime, received = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    body = "status nominal all systems green"
    for author in ("scout1", "counselor1", "scout1", "counselor1"):
        store.append_message(t.id, author_id=author, role="agent", body=body)
    cap = store.append_message(
        t.id, author_id="captain", role="captain", body="anything else?"
    )
    pre = len([m for m in store.list_messages(t.id, limit=1000) if m.role == "agent"])
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="anything else?", captain_msg=cap
    )
    assert replies == []
    assert received == {}
    post = len([m for m in store.list_messages(t.id, limit=1000) if m.role == "agent"])
    assert post == pre  # no NEW agent rows written
    # Captain message stays persisted.
    assert any(
        m.role == "captain" and m.body == "anything else?"
        for m in store.list_messages(t.id, limit=1000)
    )


async def test_fanout_mention_in_converged_thread_only_mentioned(tmp_path):
    store, runtime, received = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    body = "status nominal all systems green"
    for author in ("scout1", "counselor1", "scout1", "counselor1"):
        store.append_message(t.id, author_id=author, role="agent", body=body)
    cap = store.append_message(
        t.id, author_id="captain", role="captain", body="@scout sitrep"
    )
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="@scout sitrep", captain_msg=cap
    )
    assert {r["agent_id"] for r in replies} == {"scout1"}
    assert set(received.keys()) == {"scout1"}
    new_rows = [
        m.body for m in store.list_messages(t.id, limit=1000)
        if m.role == "agent" and m.body == "reply::scout1"
    ]
    assert new_rows == ["reply::scout1"]  # only the mentioned agent persisted


async def test_build_session_history_backcompat_4arg(tmp_path):
    # The AD-914 4-arg call (no prior) must behave identically to the AD-915
    # 5-arg call with an explicit prefetched prior.
    store, runtime, _ = _build_env(
        tmp_path, agents={"scout1": "scout"}, callsigns={"scout": "Scout"}
    )
    t = store.create_thread(title="room", participants=["scout1"])
    for i in range(3):
        store.append_message(t.id, author_id="scout1", role="agent", body=f"turn-{i}")
    cap = store.append_message(t.id, author_id="captain", role="captain", body="now")
    four = _build_session_history(runtime, store, t.id, cap.created_at)
    prior = store.list_messages(t.id, limit=1000, before=cap.created_at)
    five = _build_session_history(runtime, store, t.id, cap.created_at, prior=prior)
    assert four == five
    assert [e["text"] for e in four] == ["turn-0", "turn-1", "turn-2"]
    assert all(e["role"] == "Scout" for e in four)
