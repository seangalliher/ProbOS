"""AD-978 (Natural Conversation epic #882): camera/video perception in GROUP chat.

Captain-reported bug: the camera->perception->describe pipeline works (the 1:1
chat preview shows scene descriptions), but in a GROUP chat the crew were blind
to the camera. Root cause: the AD-733a scene-context injection lived ONLY in the
1:1 DM path (routers/agents.py); the group fan-out (thread_fanout.py _send_one)
never pulled each agent's VisionWorkingMemory, so the visual block never reached
the dispatched agents' prompts.

AD-978 mirrors the 1:1 injection into the group fan-out:
  * ``_maybe_force_describe_frame`` freshens every observer's WM ONCE per round
    (shared camera frame -> one describe, not one per agent), and
  * ``_render_agent_scene_block`` renders THIS agent's ring and the per-agent
    scene block is prepended to ``params["text"]`` (what the LLM receives).

Gated on ``perception.enabled`` (defaults False -> byte-identical when off),
exactly like the 1:1 path. BF-294 confabulation guard: an empty ring renders a
non-empty "no visual data" sentinel, never a silent omission.

BF-287 discipline: real ``ChatThreadStore`` / ``IntentBus`` / ``PerceptionConfig``
and real ``VisionWorkingMemory`` rings (NOT MagicMock). The scripted IntentBus
handler captures the real ``params["text"]`` each agent receives, so the test
proves the scene block actually reaches the dispatched agent's prompt.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from probos.config import (
    CommunicationsConfig,
    GroupChatConfig,
    PerceptionConfig,
)
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.perception.consumer import (
    get_or_create_working_memory,
    reset_working_memories_for_tests,
)
from probos.perception.working_memory import VisionObservation
from probos.routers.thread_fanout import (
    _maybe_force_describe_frame,
    _render_agent_scene_block,
    group_chat_fanout,
)
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


# ============================ fixtures / harness ============================


@pytest.fixture(autouse=True)
def _clean_wm():
    """Each test starts and ends with empty per-agent vision rings."""
    reset_working_memories_for_tests()
    yield
    reset_working_memories_for_tests()


def _observe(agent_id: str, description: str) -> None:
    """Populate ``agent_id``'s real VisionWorkingMemory with one observation."""
    wm = get_or_create_working_memory(agent_id)
    wm.append(
        VisionObservation(
            timestamp=time.time(),
            attachment_ref="sha-" + agent_id,
            description=description,
            novelty_score=0.9,
            subject_identity="captain",
        )
    )


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


class _RecordingConsumer:
    """Records force_describe calls (proves once-per-round, not once-per-agent)."""

    def __init__(self) -> None:
        self.force_calls = 0

    async def force_describe_current_frame(self, *, timeout_s: float = 4.0) -> None:
        self.force_calls += 1


def _seq_clock():
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


_CALLSIGNS = {"scout": "Scout", "diagnostician": "Bones"}


def _make_handler(agent_id, captured):
    async def _h(intent: IntentMessage) -> IntentResult:
        captured.append({"agent_id": agent_id, "text": intent.params.get("text")})
        return IntentResult(
            intent_id=intent.id, agent_id=agent_id, success=True, result=f"reply::{agent_id}"
        )

    return _h


def _build_env(tmp_path, *, perception, consumer=None):
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
        vision_consumer=consumer,
        perception_mode_controller=None,
        perception_engagement_registry=None,
        config=SimpleNamespace(
            group_chat=GroupChatConfig(
                max_speakers_per_turn=0, agent_reactivity_enabled=False
            ),
            communications=CommunicationsConfig(),
            attachments=None,
            perception=perception,
        ),
    )
    captured: list[dict] = []
    for aid in agents:
        bus.subscribe(aid, _make_handler(aid, captured), intent_names=["direct_message"])
    return store, runtime, captured


# ===================== 1. _render_agent_scene_block helper =====================


def test_render_returns_empty_when_perception_disabled():
    rt = SimpleNamespace(config=SimpleNamespace(perception=PerceptionConfig(enabled=False)))
    _observe("scout1", "The Captain is at a desk.")
    # Even with a populated ring, a disabled subsystem injects nothing.
    assert _render_agent_scene_block(rt, "scout1") == ""


def test_render_returns_scene_when_enabled_and_ring_populated():
    rt = SimpleNamespace(
        config=SimpleNamespace(perception=PerceptionConfig(enabled=True)),
        perception_mode_controller=None,
        perception_engagement_registry=None,
    )
    _observe("scout1", "The Captain is at a desk with a coffee mug.")
    out = _render_agent_scene_block(rt, "scout1")
    assert "Current Visual Context" in out
    assert "coffee mug" in out


def test_render_returns_bf294_sentinel_when_enabled_and_ring_empty():
    # Confabulation guard: enabled + empty ring -> explicit "no data" sentinel,
    # NOT an empty string (which the agent might fill from imagination).
    rt = SimpleNamespace(
        config=SimpleNamespace(perception=PerceptionConfig(enabled=True)),
        perception_mode_controller=None,
        perception_engagement_registry=None,
    )
    out = _render_agent_scene_block(rt, "scout1")
    assert out != ""
    assert "no frames described yet" in out.lower() or "camera not active" in out.lower()
    assert "do not describe what you cannot see" in out.lower()


def test_render_is_per_agent():
    rt = SimpleNamespace(
        config=SimpleNamespace(perception=PerceptionConfig(enabled=True)),
        perception_mode_controller=None,
        perception_engagement_registry=None,
    )
    _observe("scout1", "Scout sees a red light.")
    _observe("bones1", "Bones sees a blue light.")
    assert "red light" in _render_agent_scene_block(rt, "scout1")
    assert "blue light" in _render_agent_scene_block(rt, "bones1")
    # No cross-contamination between agents' rings.
    assert "blue light" not in _render_agent_scene_block(rt, "scout1")


def test_render_degrades_when_config_missing():
    # No perception attribute at all -> "" (Tier-2), never raises.
    assert _render_agent_scene_block(SimpleNamespace(config=None), "scout1") == ""


def test_render_notes_per_agent_engagement():
    notes: list[str] = []

    class _Ctrl:
        def __init__(self, name):
            self.name = name

        def note_dm_activity(self):
            notes.append(self.name)

    class _Registry:
        def __init__(self, m):
            self._m = m

        def get(self, aid):
            return self._m.get(aid)

    rt = SimpleNamespace(
        config=SimpleNamespace(perception=PerceptionConfig(enabled=True)),
        perception_mode_controller=_Ctrl("global"),
        perception_engagement_registry=_Registry({"scout1": _Ctrl("scout1")}),
    )
    _observe("scout1", "scene")
    _render_agent_scene_block(rt, "scout1")
    # Per-agent controller preferred over the global one (AD-733c-5).
    assert notes == ["scout1"]


# ===================== 2. _maybe_force_describe_frame helper =====================


@pytest.mark.asyncio
async def test_force_describe_skipped_when_disabled():
    consumer = _RecordingConsumer()
    rt = SimpleNamespace(
        config=SimpleNamespace(perception=PerceptionConfig(enabled=False)),
        vision_consumer=consumer,
    )
    await _maybe_force_describe_frame(rt)
    assert consumer.force_calls == 0


@pytest.mark.asyncio
async def test_force_describe_called_once_when_enabled():
    consumer = _RecordingConsumer()
    rt = SimpleNamespace(
        config=SimpleNamespace(perception=PerceptionConfig(enabled=True)),
        vision_consumer=consumer,
    )
    await _maybe_force_describe_frame(rt)
    assert consumer.force_calls == 1


@pytest.mark.asyncio
async def test_force_describe_degrades_on_consumer_error():
    class _BadConsumer:
        async def force_describe_current_frame(self, *, timeout_s: float = 4.0):
            raise RuntimeError("vision down")

    rt = SimpleNamespace(
        config=SimpleNamespace(perception=PerceptionConfig(enabled=True)),
        vision_consumer=_BadConsumer(),
    )
    # Must not raise — Tier-2 honest-degrade.
    await _maybe_force_describe_frame(rt)


# ===================== 3. end-to-end through group_chat_fanout =====================


@pytest.mark.asyncio
async def test_scene_block_reaches_dispatched_agent_text(tmp_path):
    consumer = _RecordingConsumer()
    store, runtime, captured = _build_env(
        tmp_path, perception=PerceptionConfig(enabled=True), consumer=consumer
    )
    _observe("scout1", "The Captain is holding a wrench.")
    _observe("bones1", "The Captain is holding a wrench.")
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="what do you see?")
    await group_chat_fanout(runtime, t.id, captain_body="what do you see?", captain_msg=cap)
    assert captured, "agents should have been dispatched"
    # Every dispatched agent's prompt text carries the visual block + the body.
    for c in captured:
        assert "Current Visual Context" in c["text"]
        assert "wrench" in c["text"]
        assert "what do you see?" in c["text"]


@pytest.mark.asyncio
async def test_force_describe_called_once_per_round_not_per_agent(tmp_path):
    consumer = _RecordingConsumer()
    store, runtime, captured = _build_env(
        tmp_path, perception=PerceptionConfig(enabled=True), consumer=consumer
    )
    _observe("scout1", "scene")
    _observe("bones1", "scene")
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    # Two agents dispatched, but the shared frame is described exactly once.
    assert len(captured) == 2
    assert consumer.force_calls == 1


@pytest.mark.asyncio
async def test_no_scene_block_when_perception_disabled(tmp_path):
    store, runtime, captured = _build_env(
        tmp_path, perception=PerceptionConfig(enabled=False), consumer=_RecordingConsumer()
    )
    # Even with populated rings, a disabled subsystem injects nothing -> the
    # dispatched text is byte-identical to the Captain's body.
    _observe("scout1", "The Captain is holding a wrench.")
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    assert captured
    for c in captured:
        assert c["text"] == "status?"
        assert "Current Visual Context" not in c["text"]


@pytest.mark.asyncio
async def test_empty_ring_injects_sentinel_in_group(tmp_path):
    # perception enabled but no frames captured -> the BF-294 sentinel reaches
    # the agent (so it knows the camera is off), NOT a silent omission.
    store, runtime, captured = _build_env(
        tmp_path, perception=PerceptionConfig(enabled=True), consumer=_RecordingConsumer()
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    assert captured
    for c in captured:
        assert "Current Visual Context" in c["text"]
        assert "status?" in c["text"]
