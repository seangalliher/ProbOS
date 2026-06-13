"""AD-986a + AD-987: group-episode enrichment (speaker attribution + reflection
fidelity) and visual<->conversational binding at capture.

Both default-OFF -> byte-identical group episodes until the config flags are set.

BF-287 discipline: real ``ChatThreadStore`` + real ``IntentBus`` + real
``VisionWorkingMemory`` rings (via the production ``get_or_create_working_memory``)
+ a hand-written recording ``store`` stub (NOT MagicMock) at the episodic-store
boundary so the constructed ``Episode`` is asserted directly. ``_prepare_document``
is exercised as the real static method.
"""
from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

from probos.cognitive.episodic import EpisodicMemory
from probos.config import MemoryConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.perception.consumer import (
    get_or_create_working_memory,
    reset_working_memories_for_tests,
)
from probos.perception.working_memory import VisionObservation
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import AnchorFrame, Episode, IntentMessage, IntentResult


SCOUT = "scout1"
# A reply long enough to straddle the 240 (off) vs 600 (on) reflection caps.
_LONG_REPLY = ("A" * 250) + "MARKER_AT_250" + ("B" * 400)


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


class _RecordingEM:
    """Real-but-fake episodic store: records the Episode objects handed to
    ``store`` so the write-construction logic is asserted directly."""

    def __init__(self) -> None:
        self.stored: list[Episode] = []

    async def store(self, episode: Episode) -> None:
        self.stored.append(episode)


def _seq_clock():
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


def _long_reply_handler(agent_id: str):
    async def _h(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id, agent_id=agent_id, success=True, result=_LONG_REPLY,
        )

    return _h


def _build(tmp_path, *, mem_cfg=None):
    """One-agent group room with a real store/bus + recording EM. ``mem_cfg`` is
    attached as ``runtime.config.memory`` (None -> no config -> features off)."""
    reset_working_memories_for_tests()
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    registry = _FakeRegistry({SCOUT: _FakeAgent("scout"), "counselor1": _FakeAgent("counselor")})
    em = _RecordingEM()
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=registry,
        ontology=None,
        callsign_registry=_FakeCallsigns({"scout": "Scout", "counselor": "Troi"}),
        project_store=None,
        episodic_memory=em,
        config=SimpleNamespace(memory=mem_cfg) if mem_cfg is not None else None,
    )
    bus.subscribe(SCOUT, _long_reply_handler(SCOUT), intent_names=["direct_message"])
    bus.subscribe("counselor1", _long_reply_handler("counselor1"), intent_names=["direct_message"])
    return store, runtime, em


def _scout_episode(em: _RecordingEM) -> Episode:
    return next(e for e in em.stored if e.agent_ids == [SCOUT])


def _enrich_cfg(**over):
    base = dict(
        group_episode_enrichment_enabled=False,
        group_reflection_max_chars=600,
        episode_visual_binding_enabled=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# config defaults
# ---------------------------------------------------------------------------


def test_config_defaults_off():
    c = MemoryConfig()
    assert c.group_episode_enrichment_enabled is False
    assert c.group_reflection_max_chars == 600
    assert c.episode_visual_binding_enabled is False


# ---------------------------------------------------------------------------
# OFF -> byte-identical group episode
# ---------------------------------------------------------------------------


async def test_disabled_is_byte_identical(tmp_path):
    store, runtime, em = _build(tmp_path, mem_cfg=None)  # no config at all
    t = store.create_thread(title="room", participants=[SCOUT, "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="hi")
    await group_chat_fanout(runtime, t.id, captain_body="hi", captain_msg=cap)

    ep = _scout_episode(em)
    assert ep.user_input == "[group chat] hi"                 # no speaker prefix
    assert ep.reflection == f"Scout said in group chat: {_LONG_REPLY[:240]}"
    assert "MARKER_AT_250" not in ep.reflection               # capped at 240
    assert ep.anchors.trigger_agent == ""                     # AD-986a not applied
    assert ep.anchors.visual_attachment_ref == ""             # AD-987 not applied
    assert ep.anchors.visual_description == ""


# ---------------------------------------------------------------------------
# AD-986a: speaker attribution + reflection fidelity
# ---------------------------------------------------------------------------


async def test_enrichment_labels_captain_and_sets_trigger_agent(tmp_path):
    store, runtime, em = _build(tmp_path, mem_cfg=_enrich_cfg(group_episode_enrichment_enabled=True))
    t = store.create_thread(title="room", participants=[SCOUT, "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)

    ep = _scout_episode(em)
    assert ep.user_input == "[group chat] Captain: status?"   # AD-986a speaker prefix
    assert ep.anchors.trigger_agent == "Captain"              # AD-986a SOCIAL slot set


async def test_enrichment_raises_reflection_cap(tmp_path):
    store, runtime, em = _build(
        tmp_path,
        mem_cfg=_enrich_cfg(group_episode_enrichment_enabled=True, group_reflection_max_chars=600),
    )
    t = store.create_thread(title="room", participants=[SCOUT, "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="go")
    await group_chat_fanout(runtime, t.id, captain_body="go", captain_msg=cap)

    ep = _scout_episode(em)
    # The substantive payload past char 240 is now indexed (findable by content).
    assert "MARKER_AT_250" in ep.reflection
    assert ep.reflection == f"Scout said in group chat: {_LONG_REPLY[:600]}"


# ---------------------------------------------------------------------------
# AD-987: visual<->conversational binding
# ---------------------------------------------------------------------------


async def test_visual_binding_captures_current_frame(tmp_path):
    store, runtime, em = _build(tmp_path, mem_cfg=_enrich_cfg(episode_visual_binding_enabled=True))
    # Seed the replying agent's vision ring with a current frame.
    get_or_create_working_memory(SCOUT).append(
        VisionObservation(
            timestamp=123.0, attachment_ref="sha-plaid",
            description="a plaid shirt and glasses", novelty_score=0.9,
        )
    )
    t = store.create_thread(title="room", participants=[SCOUT, "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="what do you see")
    await group_chat_fanout(runtime, t.id, captain_body="what do you see", captain_msg=cap)

    ep = _scout_episode(em)
    assert ep.anchors.visual_attachment_ref == "sha-plaid"
    assert ep.anchors.visual_description == "a plaid shirt and glasses"


async def test_visual_binding_honest_degrade_no_frame(tmp_path):
    store, runtime, em = _build(tmp_path, mem_cfg=_enrich_cfg(episode_visual_binding_enabled=True))
    # No frame seeded -> empty ring -> binding must honest-degrade to "".
    t = store.create_thread(title="room", participants=[SCOUT, "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="hello")
    await group_chat_fanout(runtime, t.id, captain_body="hello", captain_msg=cap)

    ep = _scout_episode(em)
    assert ep.anchors.visual_attachment_ref == ""
    assert ep.anchors.visual_description == ""


async def test_visual_binding_disabled_ignores_frame(tmp_path):
    # A frame is present, but binding is OFF -> must NOT be captured.
    store, runtime, em = _build(tmp_path, mem_cfg=_enrich_cfg(episode_visual_binding_enabled=False))
    get_or_create_working_memory(SCOUT).append(
        VisionObservation(timestamp=1.0, attachment_ref="sha-x", description="d", novelty_score=0.5)
    )
    t = store.create_thread(title="room", participants=[SCOUT, "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="hi")
    await group_chat_fanout(runtime, t.id, captain_body="hi", captain_msg=cap)

    ep = _scout_episode(em)
    assert ep.anchors.visual_attachment_ref == ""


# ---------------------------------------------------------------------------
# AD-987: _prepare_document integrated recall
# ---------------------------------------------------------------------------


def test_prepare_document_indexes_visual_description():
    ep = Episode(
        user_input="[group chat] Captain: what do you see",
        reflection="Scout said in group chat: the plaid shirt",
        anchors=AnchorFrame(
            channel="chat", trigger_type="group_fanout",
            visual_description="a plaid shirt and glasses",
        ),
    )
    doc = EpisodicMemory._prepare_document(ep)
    assert "[saw: a plaid shirt and glasses]" in doc


def test_prepare_document_no_visual_when_absent():
    ep = Episode(
        user_input="[group chat] Captain: status?",
        reflection="Scout said in group chat: green across the board",
        anchors=AnchorFrame(channel="chat", trigger_type="group_fanout"),
    )
    doc = EpisodicMemory._prepare_document(ep)
    assert "[saw:" not in doc


# ---------------------------------------------------------------------------
# AnchorFrame serialization round-trip (the asdict <-> AnchorFrame(**...) path)
# ---------------------------------------------------------------------------


def test_anchorframe_visual_fields_round_trip():
    af = AnchorFrame(
        channel="chat", trigger_type="group_fanout", trigger_agent="Captain",
        visual_attachment_ref="sha-plaid", visual_description="a plaid shirt",
    )
    restored = AnchorFrame(**json.loads(json.dumps(dataclasses.asdict(af))))
    assert restored.trigger_agent == "Captain"
    assert restored.visual_attachment_ref == "sha-plaid"
    assert restored.visual_description == "a plaid shirt"


def test_anchorframe_back_compat_missing_visual_keys():
    # A pre-AD-987 anchors_json (no visual keys) must still hydrate.
    legacy = {"channel": "chat", "trigger_type": "group_fanout", "participants": ["captain"]}
    restored = AnchorFrame(**legacy)
    assert restored.visual_attachment_ref == ""
    assert restored.visual_description == ""
