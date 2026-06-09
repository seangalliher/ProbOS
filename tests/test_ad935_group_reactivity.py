"""AD-935: bounded synchronous agent-to-agent group-chat reactivity tests.

After the Captain round, when ``group_chat.agent_reactivity_enabled`` is True,
``group_chat_fanout`` fans the prior round's agent messages to the OTHER crew
for up to ``max_agent_rounds`` extra rounds, gated by the AD-915 convergence
gate, ``[NO_RESPONSE]`` declines, exclude-prior-speakers, and the round cap.
ALL replies across rounds return in the flat ``per_agent_replies`` list (the UI
renders it directly). The cascade is SYNCHRONOUS (awaited) because the chat
transcript has no live-refresh.

BF-287 discipline: real ``ChatThreadStore`` on ``tmp_path``, real
``IntentBus(SignalManager(reap_interval=1.0))``, real-but-fake registry/agents
whose subscribed ``direct_message`` handlers return SCRIPTED replies keyed by
per-agent call index (NOT ``MagicMock``), a real ``GroupChatConfig`` toggled per
test (mounted on ``runtime.config.group_chat``), and a recording
``episodic_memory`` stub. Mirrors ``tests/test_ad914_*`` / ``tests/test_ad915_*``
/ ``tests/test_ad933a_*``.

Agent types are real ``_WARD_ROOM_CREW`` members (``scout``/``diagnostician``/
``counselor``/``security_officer``) so the ``is_crew_agent(agent, None)`` legacy
fallback admits them; the callsigns (``Scout``/``Bones``/``Ops``/``Eng``) drive
the @-mention bypass tests.
"""
from __future__ import annotations

from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
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


class _RecordingEpisodicMemory:
    """Real-but-fake episodic store (NOT MagicMock). Records every stored
    ``Episode`` so tests can assert anchors/outcomes directly."""

    def __init__(self) -> None:
        self.episodes: list = []

    async def store(self, episode) -> None:
        self.episodes.append(episode)


def _seq_clock():
    """Deterministic monotonic clock so created_at ordering (and the
    ``before=`` history filter) is exact regardless of wall-clock speed."""
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


def _make_scripted_handler(agent_id: str, scripted: list[str], dispatched: list[dict]):
    """A subscribed ``direct_message`` handler returning SCRIPTED replies keyed
    by per-agent call index (call N -> scripted[N]; the last entry repeats once
    exhausted). Records each dispatch so tests can assert which agent spoke in
    which round."""
    state = {"n": 0}

    async def _h(intent: IntentMessage) -> IntentResult:
        n = state["n"]
        state["n"] += 1
        text = scripted[n] if n < len(scripted) else scripted[-1]
        dispatched.append({
            "agent_id": agent_id,
            "call": n,
            "trigger": intent.params.get("text"),
            "is_group_chat": intent.params.get("is_group_chat"),
        })
        return IntentResult(
            intent_id=intent.id, agent_id=agent_id, success=True, result=text,
        )

    return _h


def _build_env(tmp_path, *, agents, callsigns=None, scripts=None, episodic=None, gc=None):
    """agents: {agent_id: agent_type}. callsigns: {agent_type: callsign}.

    scripts: {agent_id: [reply_per_call, ...]} (default ["reply::<id>"]).
    episodic: a recording stub assigned to ``runtime.episodic_memory`` (or None).
    gc: a real ``GroupChatConfig`` mounted on ``runtime.config.group_chat``.
    Returns (store, runtime, dispatched).
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
        config=SimpleNamespace(group_chat=gc or GroupChatConfig(), attachments=None),
    )
    if episodic is not None:
        runtime.episodic_memory = episodic
    dispatched: list[dict] = []
    scripts = scripts or {}
    for aid in agents:
        handler = _make_scripted_handler(aid, scripts.get(aid, [f"reply::{aid}"]), dispatched)
        bus.subscribe(aid, handler, intent_names=["direct_message"])
    return store, runtime, dispatched


# Valid _WARD_ROOM_CREW agent types -> the callsigns the tests @-mention.
_CALLSIGNS = {
    "scout": "Scout",
    "diagnostician": "Bones",
    "counselor": "Ops",
    "security_officer": "Eng",
}


# ---------------- 1. flag OFF = AD-914 single round ----------------


async def test_flag_off_single_round_ad914_parity(tmp_path):
    store, runtime, dispatched = _build_env(
        tmp_path,
        agents={"scout1": "scout", "bones1": "diagnostician"},
        callsigns=_CALLSIGNS,
        gc=GroupChatConfig(agent_reactivity_enabled=False),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    # Exactly one round: both crew reply, no cascade.
    assert {r["agent_id"] for r in replies} == {"scout1", "bones1"}
    assert len(replies) == 2
    # Each agent dispatched exactly once (no extra rounds).
    assert sorted(d["agent_id"] for d in dispatched) == ["bones1", "scout1"]


# ---------------- 2. flag ON, agents converse (2 rounds) ----------------


async def test_flag_on_agents_converse_two_rounds(tmp_path):
    # max_speakers=1 -> round 0 has ONE speaker (Scout), leaving Bones for round 1.
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"scout1": "scout", "bones1": "diagnostician"},
        callsigns=_CALLSIGNS,
        scripts={"scout1": ["@Bones what do you think?"], "bones1": ["I think we proceed."]},
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1, max_speakers_per_turn=1
        ),
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="thoughts team?")
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="thoughts team?", captain_msg=cap
    )
    # Round 0: Scout speaks (max_speakers=1). Round 1: Bones (@-mentioned). In order.
    assert [r["agent_id"] for r in replies] == ["scout1", "bones1"]
    assert replies[0]["text"] == "@Bones what do you think?"
    assert replies[1]["text"] == "I think we proceed."
    # Bones' round-1 reply persisted as role="agent".
    bodies = [m.body for m in store.list_messages(t.id, limit=1000) if m.role == "agent"]
    assert "I think we proceed." in bodies


# ---------------- 3. round cap stops it ----------------


async def test_round_cap_stops_cascade(tmp_path):
    # 2 crew, max_speakers=1 -> ping-pong A->B->A; distinct replies (no
    # convergence); cap=2 stops at 1 + 2 = 3 rounds even though agents would keep
    # going (round 3 would be B).
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"a1": "scout", "b1": "diagnostician"},
        callsigns=_CALLSIGNS,
        scripts={
            "a1": ["alpha one unique", "alpha two unique", "alpha three unique"],
            "b1": ["bravo one unique", "bravo two unique", "bravo three unique"],
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=2, max_speakers_per_turn=1
        ),
    )
    t = store.create_thread(title="room", participants=["a1", "b1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="go team")
    replies = await group_chat_fanout(runtime, t.id, captain_body="go team", captain_msg=cap)
    # Round 0 (a1) + round 1 (b1) + round 2 (a1) = 3 replies; cap stops round 3.
    assert len(replies) == 3
    assert [r["agent_id"] for r in replies] == ["a1", "b1", "a1"]
    assert replies[0]["text"] == "alpha one unique"
    assert replies[1]["text"] == "bravo one unique"
    assert replies[2]["text"] == "alpha two unique"


# ---------------- 4. convergence stops it (before the cap) ----------------


async def test_convergence_stops_before_cap(tmp_path):
    # 3 crew, max_speakers=2, convergence_min_messages=2, IDENTICAL replies ->
    # round 0 emits 2 identical msgs (A, B); round 1 candidate C is suppressed by
    # the convergence gate (empty speaking_order), NOT the cap (which is 2).
    store, runtime, dispatched = _build_env(
        tmp_path,
        agents={"a1": "scout", "b1": "diagnostician", "c1": "counselor"},
        callsigns=_CALLSIGNS,
        scripts={
            "a1": ["we are fully aligned"],
            "b1": ["we are fully aligned"],
            "c1": ["we are fully aligned"],
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=2,
            max_speakers_per_turn=2, convergence_min_messages=2,
        ),
    )
    t = store.create_thread(title="room", participants=["a1", "b1", "c1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="align?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="align?", captain_msg=cap)
    # Round 0: A, B speak (max_speakers=2). Round 1 candidate C is suppressed by
    # convergence -> cascade stops BEFORE the cap. C never replies / dispatched.
    assert len(replies) == 2
    assert {r["agent_id"] for r in replies} == {"a1", "b1"}
    assert "c1" not in {r["agent_id"] for r in replies}
    assert all(d["agent_id"] != "c1" for d in dispatched)


# ---------------- 5. [NO_RESPONSE] not persisted, not propagated ----------------


async def test_no_response_not_persisted_or_propagated(tmp_path):
    # 2 crew. B declines ([NO_RESPONSE]); A replies. The decline is absent from
    # per_agent_replies AND the thread, and does not extend the cascade.
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"a1": "scout", "b1": "diagnostician"},
        callsigns=_CALLSIGNS,
        scripts={"a1": ["real reply from A"], "b1": ["[NO_RESPONSE]"]},
        gc=GroupChatConfig(agent_reactivity_enabled=True, max_agent_rounds=2),
    )
    t = store.create_thread(title="room", participants=["a1", "b1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="report")
    replies = await group_chat_fanout(runtime, t.id, captain_body="report", captain_msg=cap)
    assert [r["agent_id"] for r in replies] == ["a1"]
    assert all(r["text"] != "[NO_RESPONSE]" for r in replies)
    agent_bodies = [m.body for m in store.list_messages(t.id, limit=1000) if m.role == "agent"]
    assert agent_bodies == ["real reply from A"]
    assert "[NO_RESPONSE]" not in agent_bodies


# ---------------- 6. [NO_RESPONSE] round-0 fix (flag OFF) ----------------


async def test_no_response_round0_fix_flag_off(tmp_path):
    # Flag OFF (no cascade): a round-0 agent declines; the other's real reply
    # still returns; the decline is absent from the transcript. Proves the
    # round-0 decline filter works independently of the cascade.
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"a1": "scout", "b1": "diagnostician"},
        callsigns=_CALLSIGNS,
        scripts={"a1": ["[NO_RESPONSE]"], "b1": ["B has something to say"]},
        gc=GroupChatConfig(agent_reactivity_enabled=False),
    )
    t = store.create_thread(title="room", participants=["a1", "b1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="anyone?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="anyone?", captain_msg=cap)
    assert [r["agent_id"] for r in replies] == ["b1"]
    agent_bodies = [m.body for m in store.list_messages(t.id, limit=1000) if m.role == "agent"]
    assert agent_bodies == ["B has something to say"]
    assert "[NO_RESPONSE]" not in agent_bodies


# ---------------- 7. exclude prior-round speaker (exclude-author) ----------------


async def test_exclude_prior_round_speaker(tmp_path):
    # max_speakers=1, max_agent_rounds=1. Round 0: A speaks (even self-mentions
    # @Scout). Round 1 EXCLUDES A (prior speaker) despite the self-mention ->
    # only B is a candidate. A is not re-dispatched in round 1.
    store, runtime, dispatched = _build_env(
        tmp_path,
        agents={"a1": "scout", "b1": "diagnostician"},
        callsigns=_CALLSIGNS,
        scripts={"a1": ["note to @Scout self"], "b1": ["B reacts"]},
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1, max_speakers_per_turn=1
        ),
    )
    t = store.create_thread(title="room", participants=["a1", "b1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="go")
    replies = await group_chat_fanout(runtime, t.id, captain_body="go", captain_msg=cap)
    # Round 0: A. Round 1: B (A excluded despite the @Scout self-mention).
    assert [r["agent_id"] for r in replies] == ["a1", "b1"]
    # A dispatched exactly once (round 0); NOT re-dispatched in round 1.
    a_dispatches = [d for d in dispatched if d["agent_id"] == "a1"]
    assert len(a_dispatches) == 1


# ---------------- 8. all-decline stops the cascade ----------------


async def test_all_decline_stops_cascade(tmp_path):
    # 4 crew, max_speakers=2. Round 0: A, B speak. Round 1: candidates C, D both
    # decline -> round 1 empty -> cascade ends (no infinite loop).
    store, runtime, dispatched = _build_env(
        tmp_path,
        agents={
            "a1": "scout", "b1": "diagnostician",
            "c1": "counselor", "d1": "security_officer",
        },
        callsigns=_CALLSIGNS,
        scripts={
            "a1": ["A speaks"], "b1": ["B speaks"],
            "c1": ["[NO_RESPONSE]"], "d1": ["[NO_RESPONSE]"],
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=3, max_speakers_per_turn=2
        ),
    )
    t = store.create_thread(title="room", participants=["a1", "b1", "c1", "d1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status")
    replies = await group_chat_fanout(runtime, t.id, captain_body="status", captain_msg=cap)
    # Only A and B's replies; the all-decline round 1 ends the cascade.
    assert {r["agent_id"] for r in replies} == {"a1", "b1"}
    assert len(replies) == 2
    # C and D were dispatched (round 1) but both declined -> no further round.
    assert {d["agent_id"] for d in dispatched if d["agent_id"] in ("c1", "d1")} == {"c1", "d1"}


# ---------------- 9. @-mention bypass under the cap ----------------


async def test_mention_bypass_under_cap(tmp_path):
    # 3 crew, max_speakers_per_turn=1. Round 0: A speaks, @-mentions Ops (C).
    # Round 1 candidates {B, C} under the 1-speaker cap; C is @-mentioned -> it is
    # hard-included and speaks despite the cap.
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"a1": "scout", "b1": "diagnostician", "c1": "counselor"},
        callsigns=_CALLSIGNS,
        scripts={
            "a1": ["@Ops urgent question for you"],
            "b1": ["B reply"],
            "c1": ["Ops answers"],
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1, max_speakers_per_turn=1
        ),
    )
    t = store.create_thread(title="room", participants=["a1", "b1", "c1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="go")
    replies = await group_chat_fanout(runtime, t.id, captain_body="go", captain_msg=cap)
    # Round 1: Ops (C) is @-mentioned -> in speaking_order under the 1-cap.
    assert "c1" in {r["agent_id"] for r in replies}
    assert any(r["text"] == "Ops answers" for r in replies)


# ---------------- 10. AD-933a episode per cascade reply ----------------


async def test_episode_written_per_cascade_reply(tmp_path):
    rec = _RecordingEpisodicMemory()
    store, runtime, _ = _build_env(
        tmp_path,
        agents={"a1": "scout", "b1": "diagnostician"},
        callsigns=_CALLSIGNS,
        scripts={"a1": ["@Bones thoughts?"], "b1": ["Bones here, yes."]},
        episodic=rec,
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, max_agent_rounds=1, max_speakers_per_turn=1
        ),
    )
    t = store.create_thread(title="room", participants=["a1", "b1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="team?")
    replies = await group_chat_fanout(runtime, t.id, captain_body="team?", captain_msg=cap)
    # 2 persisted replies across 2 rounds -> 2 group-anchored episodes.
    assert len(replies) == 2
    assert len(rec.episodes) == 2
    for ep in rec.episodes:
        assert ep.anchors is not None
        assert ep.anchors.channel == "chat"
        assert ep.anchors.trigger_type == "group_fanout"
        assert ep.anchors.chat_thread_id == t.id
        assert ep.outcomes[0]["session_type"] == "group"
        assert ep.source == "group_chat_fanout"
    assert {aid for ep in rec.episodes for aid in ep.agent_ids} == {"a1", "b1"}


# ---------------- 11. teaching protocol (gap-regex-safe, group-only) ----------------


def test_group_chat_protocol_off_returns_empty():
    # No is_group_chat param -> "" (1:1 DMs are unaffected).
    assert CognitiveAgent._conversational_group_chat_protocol(SimpleNamespace(), {}) == ""
    assert CognitiveAgent._conversational_group_chat_protocol(
        SimpleNamespace(), {"params": {}}
    ) == ""


def test_group_chat_protocol_on_is_nonempty_and_gap_safe():
    obs = {"params": {"is_group_chat": True}}
    out = CognitiveAgent._conversational_group_chat_protocol(SimpleNamespace(), obs)
    assert out  # non-empty when is_group_chat is set
    assert "[NO_RESPONSE]" in out
    # Gap-regex safety (the _CAPABILITY_GAP_RE lesson): the teaching string must
    # not read like a capability-gap confession.
    assert _CAPABILITY_GAP_RE.search(out) is None
    for banned in ("can't", "cannot", "don't have", "unable to", "not able to"):
        assert banned not in out.lower()


# ---------------- 12. Tier-2 honest-degrade (a cascade round raises) ----------------


async def test_cascade_round_failure_returns_replies_so_far(tmp_path):
    # A store wrapper that raises ``list_messages`` on the SECOND call (the first
    # cascade round; round 0 is the first call). 3 crew + max_speakers=1 leaves
    # candidates for round 1, so the cascade round reaches the raising
    # list_messages -> group_chat_fanout catches it and returns the round-0
    # replies gathered so far rather than crashing the turn.
    real = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())

    class _RaiseOnSecondList:
        def __init__(self, inner) -> None:
            self._inner = inner
            self._calls = 0

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def list_messages(self, *a, **k):
            self._calls += 1
            if self._calls >= 2:
                raise RuntimeError("boom::list_messages round 1")
            return self._inner.list_messages(*a, **k)

    store = _RaiseOnSecondList(real)
    bus = IntentBus(SignalManager(reap_interval=1.0))
    agents = {"a1": "scout", "b1": "diagnostician", "c1": "counselor"}
    registry = _FakeRegistry({aid: _FakeAgent(at) for aid, at in agents.items()})
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=registry,
        ontology=None,
        callsign_registry=_FakeCallsigns(_CALLSIGNS),
        project_store=None,
        config=SimpleNamespace(
            group_chat=GroupChatConfig(
                agent_reactivity_enabled=True, max_agent_rounds=2, max_speakers_per_turn=1
            ),
            attachments=None,
        ),
    )
    dispatched: list[dict] = []
    for aid in agents:
        bus.subscribe(
            aid, _make_scripted_handler(aid, [f"reply::{aid}"], dispatched),
            intent_names=["direct_message"],
        )
    t = real.create_thread(title="room", participants=["a1", "b1", "c1"])
    cap = real.append_message(t.id, author_id="captain", role="captain", body="go")
    replies = await group_chat_fanout(runtime, t.id, captain_body="go", captain_msg=cap)
    # Round 0 (1st list_messages, succeeds) yields a1; the cascade round's
    # list_messages raises -> caught -> returns the round-0 replies so far.
    assert [r["agent_id"] for r in replies] == ["a1"]
