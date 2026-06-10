"""AD-955 (Natural Conversation epic #882, weighted-trust room sense): advisory
ROOM AWARENESS.

The facilitator already ranks the room every round (recency + department +
trust + mention). AD-955 surfaces that ranking to the dispatched speaker as an
ADVISORY signal so the room can SELF-REGULATE without a director: a dominating
agent can take a lighter touch or hand off; an agent can defer to a
better-placed peer BY NAME (an AD-951 hand-off), reframed as collaboration. It
NEVER changes who is dispatched (the cap/convergence backstops own that) — it
gives the agent the AGENCY a hard cap cannot.

Three layers, all tested here:
  * pure ``build_room_signal`` (facilitator) — the per-speaker signal,
  * ``CognitiveAgent._conversational_room_awareness_protocol`` — the framing,
  * end-to-end through ``group_chat_fanout`` — the signal reaches params.

BF-287 discipline: real ``CommunicationsConfig`` / ``ChatThreadStore`` /
``IntentBus`` (NOT MagicMock).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.cognitive.chat_facilitator import build_room_signal, SpeakerScore
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.config import CommunicationsConfig, GroupChatConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult

_HOOK = CognitiveAgent._conversational_room_awareness_protocol


# ======================= 1. pure build_room_signal =======================


def _scores(*pairs):
    # pairs: (agent_id, score)
    return [SpeakerScore(agent_id=a, score=s, mentioned=False) for a, s in pairs]


def test_recent_share_counts_within_window():
    sig = build_room_signal(
        agent_id="s1", department_relevance=0.0,
        recent_authors=["s1", "s2", "s1", "s1"],
        scores=_scores(("s1", 0.9)), callsign_by_agent={},
    )
    assert sig["recent_share"] == 3
    assert sig["recent_window"] == 4


def test_window_caps_considered():
    sig = build_room_signal(
        agent_id="s1", department_relevance=0.0,
        recent_authors=["s1"] * 20, scores=_scores(("s1", 0.9)),
        callsign_by_agent={}, recent_window=6,
    )
    assert sig["recent_window"] == 6
    assert sig["recent_share"] == 6


def test_domain_threshold():
    on = build_room_signal(
        agent_id="s1", department_relevance=0.15, recent_authors=[],
        scores=[], callsign_by_agent={},
    )
    assert on is not None and on["this_is_your_area"] is True
    off = build_room_signal(
        agent_id="s1", department_relevance=0.14, recent_authors=[],
        scores=[], callsign_by_agent={},
    )
    assert off is None  # not your area, no window, no peer -> nothing salient


def test_room_would_value_is_top_other_with_callsign():
    sig = build_room_signal(
        agent_id="s1", department_relevance=0.0,
        recent_authors=["s1"], scores=_scores(("s1", 0.9), ("s2", 0.7), ("s3", 0.6)),
        callsign_by_agent={"s2": "Bones", "s3": "Ops"},
    )
    assert sig["room_would_value"] == "Bones"  # top OTHER, skips self


def test_room_would_value_skips_self_and_missing_callsign():
    # s2 outranks but has no callsign -> fall through to s3.
    sig = build_room_signal(
        agent_id="s1", department_relevance=0.0,
        recent_authors=["s1"], scores=_scores(("s1", 0.9), ("s2", 0.8), ("s3", 0.6)),
        callsign_by_agent={"s3": "Ops"},
    )
    assert sig["room_would_value"] == "Ops"


def test_returns_none_when_nothing_salient():
    assert build_room_signal(
        agent_id="x", department_relevance=0.0, recent_authors=[],
        scores=[], callsign_by_agent={},
    ) is None


def test_signal_when_only_a_peer_is_present():
    sig = build_room_signal(
        agent_id="s1", department_relevance=0.0, recent_authors=[],
        scores=_scores(("s1", 0.5), ("s2", 0.4)), callsign_by_agent={"s2": "Bones"},
    )
    assert sig is not None
    assert sig["room_would_value"] == "Bones"


# ======================= 2. the framing hook =======================


def _self(*, enabled: bool | None = None):
    if enabled is None:
        return SimpleNamespace()
    comm = CommunicationsConfig(room_awareness_enabled=enabled)
    return SimpleNamespace(_runtime=SimpleNamespace(config=SimpleNamespace(communications=comm)))


_PEER = {"recent_share": 3, "recent_window": 4, "this_is_your_area": True, "room_would_value": "Bones"}
_NOPEER = {"recent_share": 1, "recent_window": 4, "this_is_your_area": True, "room_would_value": None}


def _obs(signal, *, intent="direct_message", group=True):
    params = {}
    if group:
        params["is_group_chat"] = True
    if signal is not None:
        params["room_signal"] = signal
    return {"intent": intent, "params": params}


def _gap_clean(text: str) -> None:
    assert _CAPABILITY_GAP_RE.search(text) is None
    for banned in ("can't", "cannot", "don't have", "unable to", "not able to", "lack"):
        assert banned not in text.lower()


def test_hook_inert_off_conversational_path():
    assert _HOOK(_self(), _obs(_PEER, intent="ward_room_notification")) == ""
    assert _HOOK(_self(), _obs(_PEER, intent="proactive_think")) == ""


def test_hook_inert_in_1to1():
    # No is_group_chat -> room awareness does not apply (no room).
    assert _HOOK(_self(), _obs(_PEER, group=False)) == ""


def test_hook_inert_without_room_signal():
    assert _HOOK(_self(), _obs(None)) == ""


def test_hook_inert_when_flag_off():
    assert _HOOK(_self(enabled=False), _obs(_PEER)) == ""


def test_hook_peer_rendering_nonempty_and_gap_safe():
    out = _HOOK(_self(), _obs(_PEER))
    assert out
    _gap_clean(out)
    assert "Bones" in out
    assert "defer" in out.lower()


def test_hook_includes_share_numbers():
    out = _HOOK(_self(), _obs(_PEER))
    assert "4 contributions" in out
    assert "3 were yours" in out


def test_hook_ego_reframe_present():
    """The 'teamwork, not a shortfall' reframe is the ego-problem solver and
    must survive any future edit (regression guard)."""
    out = _HOOK(_self(), _obs(_PEER)).lower()
    assert "teamwork" in out
    assert "shortfall" in out


def test_hook_no_peer_rendering_gap_safe():
    out = _HOOK(_self(), _obs(_NOPEER))
    assert out
    _gap_clean(out)
    # No peer -> no "defer to {name}" clause, but still teaches inviting-in.
    assert "teamwork" in out.lower()


def test_hook_default_on_when_config_absent():
    assert _HOOK(_self(), _obs(_PEER))  # bare self, no _runtime -> default ON


def test_config_default_is_on():
    assert CommunicationsConfig().room_awareness_enabled is True


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


_CALLSIGNS = {"scout": "Scout", "diagnostician": "Bones"}


def _make_handler(agent_id, captured):
    async def _h(intent: IntentMessage) -> IntentResult:
        captured.append({
            "agent_id": agent_id,
            "room_signal": intent.params.get("room_signal"),
            "is_group_chat": intent.params.get("is_group_chat"),
        })
        return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True, result=f"reply::{agent_id}")
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
async def test_room_signal_reaches_dispatched_agent_params(tmp_path):
    # max_speakers=1 -> one agent dispatched in round 0; it must receive a
    # room_signal naming the OTHER crew member as the voice the room would value.
    store, runtime, captured = _build_env(
        tmp_path, gc=GroupChatConfig(max_speakers_per_turn=1, agent_reactivity_enabled=False),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status team?")
    await group_chat_fanout(runtime, t.id, captain_body="status team?", captain_msg=cap)
    dispatched = [c for c in captured if c["room_signal"] is not None]
    assert dispatched, "the dispatched agent should carry an advisory room_signal"
    sig = dispatched[0]["room_signal"]
    assert set(sig) == {"recent_share", "recent_window", "this_is_your_area", "room_would_value"}
    # The peer named is the OTHER crew member's callsign, never the speaker's own.
    speaker = dispatched[0]["agent_id"]
    own_callsign = _CALLSIGNS[runtime.registry.get(speaker).agent_type]
    assert sig["room_would_value"] != own_callsign
    assert sig["room_would_value"] in ("Scout", "Bones")


@pytest.mark.asyncio
async def test_flag_off_attaches_no_room_signal(tmp_path):
    store, runtime, captured = _build_env(
        tmp_path, gc=GroupChatConfig(max_speakers_per_turn=1, agent_reactivity_enabled=False),
    )
    runtime.config.communications = CommunicationsConfig(room_awareness_enabled=False)
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status team?")
    await group_chat_fanout(runtime, t.id, captain_body="status team?", captain_msg=cap)
    assert captured, "an agent should still be dispatched"
    assert all(c["room_signal"] is None for c in captured)
