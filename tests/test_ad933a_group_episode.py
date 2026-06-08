"""AD-933a: group-anchored episodic write for the fan-out.

Group-chat fan-out replies previously wrote NO episode (the agent safety-net
``_store_action_episode`` skips ``direct_message``+``from="hxi_profile"``
deferring to pipeline step_5, which AD-933 excluded from the group subset).
AD-933a adds a group-anchored episodic write at the END of
``group_chat_fanout``, mirroring the AD-719 @-mention fan-out (routers/chat.py)
but with group anchors (``channel="chat"``, ``trigger_type="group_fanout"``,
``session_type:"group"``, ``chat_thread_id`` set).

BF-287 discipline: real ``ChatThreadStore`` on ``tmp_path``, real
``IntentBus(SignalManager(reap_interval=1.0))``, a real-but-fake recording
``episodic_memory`` (NOT ``MagicMock``) exposing ``async def store(self,
episode)`` that appends to a list, and a real-but-fake registry/agent that
returns a canned reply via a subscribed ``direct_message`` handler.

AD-933a constructs the group-anchored ``Episode(...)`` DIRECTLY — it does NOT
route through ``dream_adapter.build_episode`` (that helper derives a dag-shaped
episode from an ``execution_result["dag"]`` the fan-out has none of, and never
sets ``anchors``, so it would silently drop the group anchor + agent_id in
production). ``test_dream_adapter_present_still_group_anchored`` proves the
stored episode stays ``channel="chat"`` even when a ``dream_adapter`` exists.
Mirrors ``tests/test_ad914_*``/``tests/test_ad915_*``.
"""
from __future__ import annotations

from types import SimpleNamespace

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


class _RecordingEpisodicMemory:
    """Real-but-fake episodic store (NOT MagicMock). Records every stored
    ``Episode`` so tests can assert anchors/outcomes directly."""

    def __init__(self) -> None:
        self.episodes: list = []

    async def store(self, episode) -> None:
        self.episodes.append(episode)


class _RaisingThenRecordingEpisodicMemory:
    """Raises on the FIRST ``store()`` call (Tier-2 degrade path), records the
    rest — proves the fan-out still returns all replies AND the second
    reply's episode still attempts to store."""

    def __init__(self) -> None:
        self.episodes: list = []
        self.calls = 0

    async def store(self, episode) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("boom::store")
        self.episodes.append(episode)


class _FakeDreamAdapter:
    """If ``build_episode`` were (wrongly) used by the fan-out, it would emit a
    dag-shaped episode that drops the group anchor. Present on the runtime in
    the regression test to PROVE AD-933a constructs the Episode directly and
    never routes through it."""

    def build_episode(self, text, execution_result, t_start, t_end):
        from probos.types import AnchorFrame, Episode
        return Episode(
            timestamp=1.0,
            user_input=text,
            dag_summary={},
            outcomes=[],
            agent_ids=[],
            anchors=AnchorFrame(channel="dag", trigger_type="dag_execution"),
        )


def _seq_clock():
    """Deterministic monotonic clock so created_at ordering (and the
    ``before=`` history filter) is exact regardless of wall-clock speed."""
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


def _make_canned_handler(received: dict, agent_id: str, text: str):
    async def _h(intent: IntentMessage) -> IntentResult:
        received[agent_id] = {"text": intent.params.get("text")}
        return IntentResult(
            intent_id=intent.id,
            agent_id=agent_id,
            success=True,
            result=text,
        )

    return _h


def _make_silent_handler(agent_id: str):
    """Empty result -> ``_send_one`` ships the ``"(no response)"`` sentinel."""

    async def _h(intent: IntentMessage) -> IntentResult:
        return IntentResult(intent_id=intent.id, agent_id=agent_id, success=True, result="")

    return _h


def _build_env(tmp_path, *, agents, callsigns=None, episodic=None, silent=None, dream_adapter=None):
    """agents: {agent_id: agent_type}. callsigns: {agent_type: callsign}.

    episodic: a recording stub assigned to ``runtime.episodic_memory`` (or
    ``None`` to leave the attr absent — the degrade case).
    silent: agent_ids whose handler returns an empty result (sentinel path).
    dream_adapter: optional stub on ``runtime.dream_adapter`` — AD-933a must
    NOT route through it (it would emit a dag-shaped episode); the regression
    test proves the stored episode stays ``channel="chat"``.
    Returns (store, runtime, received).
    """
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    registry = _FakeRegistry({aid: _FakeAgent(at) for aid, at in agents.items()})
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=registry,
        ontology=None,
        callsign_registry=_FakeCallsigns(callsigns or {}),
        project_store=None,
    )
    if episodic is not None:
        runtime.episodic_memory = episodic
    if dream_adapter is not None:
        runtime.dream_adapter = dream_adapter
    received: dict[str, dict] = {}
    silent_ids = set(silent or ())
    for aid in agents:
        handler = (
            _make_silent_handler(aid)
            if aid in silent_ids
            else _make_canned_handler(received, aid, f"reply::{aid}")
        )
        bus.subscribe(aid, handler, intent_names=["direct_message"])
    return store, runtime, received


# ---------------- AD-933a behavior ----------------


async def test_one_episode_per_crew_reply(tmp_path):
    rec = _RecordingEpisodicMemory()
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
        episodic=rec,
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    assert len(replies) == 2
    # Exactly one episode per crew reply (2 crew -> 2 episodes).
    assert len(rec.episodes) == 2
    assert {aid for ep in rec.episodes for aid in ep.agent_ids} == {"scout1", "counselor1"}


async def test_episode_is_group_anchored(tmp_path):
    rec = _RecordingEpisodicMemory()
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
        episodic=rec,
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="report")
    await group_chat_fanout(runtime, t.id, captain_body="report", captain_msg=cap)
    assert rec.episodes
    ep = rec.episodes[0]
    assert ep.anchors is not None
    assert ep.anchors.channel == "chat"
    assert ep.anchors.trigger_type == "group_fanout"
    assert ep.anchors.chat_thread_id == t.id
    assert ep.outcomes[0]["session_type"] == "group"
    assert ep.source == "group_chat_fanout"
    # NOT the 1:1/dm shape that step_5 would have mislabeled this as.
    assert ep.anchors.channel != "dm"
    assert ep.outcomes[0]["session_type"] != "1:1"


async def test_participants_include_captain_and_crew(tmp_path):
    rec = _RecordingEpisodicMemory()
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
        episodic=rec,
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="go")
    await group_chat_fanout(runtime, t.id, captain_body="go", captain_msg=cap)
    assert rec.episodes
    parts = rec.episodes[0].anchors.participants
    assert "captain" in parts
    # both crew present (callsign-or-agent_id; callsigns resolved here)
    assert "Scout" in parts
    assert "Troi" in parts


async def test_sentinel_reply_skipped(tmp_path):
    rec = _RecordingEpisodicMemory()
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
        episodic=rec,
        silent={"counselor1"},  # empty result -> "(no response)" sentinel
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    assert len(replies) == 2  # fan-out still returns both replies
    # only the non-sentinel reply produced an episode
    assert len(rec.episodes) == 1
    assert rec.episodes[0].agent_ids == ["scout1"]


async def test_episodic_memory_none_degrades(tmp_path):
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
        episodic=None,  # no episodic_memory attr at all
    )
    assert not hasattr(runtime, "episodic_memory")
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    assert len(replies) == 2  # no crash, replies still returned


async def test_store_raising_degrades_and_continues(tmp_path):
    rec = _RaisingThenRecordingEpisodicMemory()
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
        episodic=rec,
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    # Tier-2: the fan-out still returns all replies despite the first store raising.
    assert len(replies) == 2
    assert {r["agent_id"] for r in replies} == {"scout1", "counselor1"}
    # First store() raised; the SECOND reply's episode still attempted -> recorded.
    assert rec.calls == 2
    assert len(rec.episodes) == 1


async def test_dream_adapter_present_still_group_anchored(tmp_path):
    """Regression (AD-933a build fix): ``dream_adapter.build_episode`` derives a
    dag-shaped episode from an ``execution_result["dag"]`` and never sets
    anchors, so routing through it would silently drop the group anchor in
    production. With a dream_adapter present, the stored episode must STILL be
    chat-anchored — proving the fan-out constructs the Episode directly."""
    rec = _RecordingEpisodicMemory()
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
        episodic=rec,
        dream_adapter=_FakeDreamAdapter(),
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="report")
    await group_chat_fanout(runtime, t.id, captain_body="report", captain_msg=cap)
    assert rec.episodes
    ep = rec.episodes[0]
    # Direct construction won — NOT the dag-shaped build_episode output.
    assert ep.anchors.channel == "chat"
    assert ep.anchors.trigger_type == "group_fanout"
    assert ep.outcomes[0]["session_type"] == "group"
    assert ep.agent_ids and ep.agent_ids[0] in {"scout1", "counselor1"}
