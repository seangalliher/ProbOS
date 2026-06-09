"""AD-933: the group-chat fan-out runs the channel-agnostic escalation subset.

The 1:1 chat path and the group fan-out are structurally identical up through
``runtime.intent_bus.send(intent)``; AD-933 wires the group path to the same
post-LLM escalation ladder (AD-726) the 1:1 path runs, minus the 1:1-scoped
steps (episodic / working-memory / divergence / emotion / games / avatar) that
would mislabel a multi-agent turn. So a group reply can now resolve an inline
mesh read (AD-869) or open a ``[CREATE_TASK]`` (AD-845) — not just ship a
Tier-1 reply.

BF-287 discipline: every substrate the fan-out + escalation pipeline touches is
REAL — a real ``ChatThreadStore`` on ``tmp_path``, a real
``IntentBus(SignalManager(reap_interval=1.0))`` with subscribed
``direct_message`` handlers, a real ``WorkItemStore`` (in-memory SQLite) on
``runtime.work_item_store``, a real ``DmSanityGate`` on
``runtime.dm_sanity_gate``, and a real-but-fake registry / callsign stub (NOT
``MagicMock``) at the substrate/bus boundary. Mirrors the AD-914 fan-out and
AD-845 ``[CREATE_TASK]`` harnesses already in the repo.
"""
from __future__ import annotations

from types import SimpleNamespace

from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult
from probos.workforce import WorkItemStore


# ---------------- BF-287 real-but-fake substrate stubs ----------------


class _FakeAgent:
    def __init__(self, agent_type: str, agent_id: str) -> None:
        self.agent_type = agent_type  # is_crew_agent + callsign read .agent_type
        self.id = agent_id


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)

    def get_by_pool(self, pool: str):
        # AD-869 mesh-read resolution: an empty pool makes step_4h fast-degrade
        # (no bus send, no TTL wait), so the mesh-marker test never blocks.
        return []


class _FakeCallsigns:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._m = mapping  # agent_type -> callsign

    def get_callsign(self, agent_type: str) -> str:
        return self._m.get(agent_type, "")

    def resolve(self, ref: str):
        # AD-845 specialist resolution: always miss -> the work item is created
        # unassigned (still dispatchable). No live specialist needed.
        return None


class _RecordingEpisodic:
    """Records every stored episode so the test can prove step_5 (the only
    1:1-labelled episode writer) never fires on the group path."""

    def __init__(self) -> None:
        self.stored: list[object] = []

    async def store(self, episode: object) -> None:
        self.stored.append(episode)


def _seq_clock():
    """Deterministic monotonic clock so created_at ordering (and the
    ``before=`` history filter) is exact regardless of wall-clock speed."""
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


def _canned_handler(reply: str, agent_id: str):
    async def _h(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id,
            agent_id=agent_id,
            success=True,
            result=reply,
        )

    return _h


def _build_env(
    tmp_path,
    *,
    agents: dict[str, str],
    replies: dict[str, str],
    callsigns: dict[str, str] | None = None,
    sanity_gate: bool = True,
    work_item_store: WorkItemStore | None = None,
    episodic: _RecordingEpisodic | None = None,
):
    """agents: {agent_id: agent_type}. replies: {agent_id: canned_reply}.

    Returns (store, runtime). The caller owns the ``work_item_store``
    lifecycle (``start``/``stop``).
    """
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    registry = _FakeRegistry({aid: _FakeAgent(at, aid) for aid, at in agents.items()})
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=registry,
        ontology=None,
        callsign_registry=_FakeCallsigns(callsigns or {}),
        project_store=None,
        dm_sanity_gate=DmSanityGate() if sanity_gate else None,
        work_item_store=work_item_store,
    )
    if episodic is not None:
        runtime.episodic_memory = episodic
    for aid in agents:
        bus.subscribe(aid, _canned_handler(replies[aid], aid), intent_names=["direct_message"])
    return store, runtime


def _agent_rows(store: ChatThreadStore, thread_id: str) -> dict[str, str]:
    """Persisted role='agent' message bodies keyed by author_id (ground truth)."""
    return {
        m.author_id: m.body
        for m in store.list_messages(thread_id, limit=1000)
        if m.role == "agent"
    }


# A group reply that carries an AD-845 [CREATE_TASK] tag (matches _CREATE_TASK_RE).
_CREATE_TASK_REPLY = (
    "On it, Captain. [CREATE_TASK title=Sensor sweep | "
    "instructions=Research and summarize the anomaly readings | "
    "specialist=@Bones] I'll report back when it's done."
)

# A group reply carrying an AD-869 read-only mesh marker.
_MESH_REPLY = "Let me check. [MESH list_directory path=/tmp] One moment, Captain."


# ---------------- 1. [CREATE_TASK] escalates in the group path ----------------


async def test_group_create_task_opens_dispatchable_work_item(tmp_path):
    store_wi = WorkItemStore(db_path=":memory:")
    await store_wi.start()
    try:
        store, runtime = _build_env(
            tmp_path,
            agents={"yeo1": "scout", "scout1": "counselor"},
            replies={"yeo1": _CREATE_TASK_REPLY, "scout1": "Standing by, Captain."},
            callsigns={"scout": "Yeo", "counselor": "Scout"},
            work_item_store=store_wi,
        )
        t = store.create_thread(title="room", participants=["yeo1", "scout1"])
        cap = store.append_message(t.id, author_id="captain", role="captain", body="handle it")

        await group_chat_fanout(runtime, t.id, captain_body="handle it", captain_msg=cap)

        # A single dispatchable, yeo-delegated work item was created.
        items = await store_wi.list_work_items()
        assert len(items) == 1
        item = items[0]
        assert item.title == "Sensor sweep"
        assert item.metadata.get("dispatchable") is True
        assert "yeo-delegated" in item.tags
        # The persisted group reply has the tag stripped + the task-id suffix.
        rows = _agent_rows(store, t.id)
        assert "[CREATE_TASK" not in rows["yeo1"]
        assert "On it, Captain." in rows["yeo1"]
        assert f"(Task opened: {item.id})" in rows["yeo1"]
        # The other speaker's plain reply is untouched.
        assert rows["scout1"] == "Standing by, Captain."
    finally:
        await store_wi.stop()


# ---------------- 2. plain reply is a strict no-op ----------------


async def test_group_plain_reply_no_op(tmp_path):
    store_wi = WorkItemStore(db_path=":memory:")
    await store_wi.start()
    try:
        store, runtime = _build_env(
            tmp_path,
            agents={"scout1": "scout", "counselor1": "counselor"},
            replies={
                "scout1": "All quiet on sensors, Captain.",
                "counselor1": "The crew morale is steady.",
            },
            work_item_store=store_wi,
        )
        t = store.create_thread(title="room", participants=["scout1", "counselor1"])
        cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")

        await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)

        rows = _agent_rows(store, t.id)
        # Replies persist unchanged; the escalation subset created nothing.
        assert rows["scout1"] == "All quiet on sensors, Captain."
        assert rows["counselor1"] == "The crew morale is steady."
        assert await store_wi.list_work_items() == []
    finally:
        await store_wi.stop()


# ---------------- 3. dm_sanity_gate is None -> honest-degrade ----------------


async def test_group_create_task_sanity_gate_none_honest_degrade(tmp_path):
    store_wi = WorkItemStore(db_path=":memory:")
    await store_wi.start()
    try:
        store, runtime = _build_env(
            tmp_path,
            agents={"yeo1": "scout", "scout1": "counselor"},
            replies={"yeo1": _CREATE_TASK_REPLY, "scout1": "Acknowledged."},
            sanity_gate=False,  # runtime.dm_sanity_gate = None
            work_item_store=store_wi,
        )
        t = store.create_thread(title="room", participants=["yeo1", "scout1"])
        cap = store.append_message(t.id, author_id="captain", role="captain", body="go")

        # Must not raise; step_4g early-returns when the sanity gate is None.
        replies = await group_chat_fanout(runtime, t.id, captain_body="go", captain_msg=cap)

        assert len(replies) == 2
        # No work item created; the reply still ships (tag may remain).
        assert await store_wi.list_work_items() == []
        rows = _agent_rows(store, t.id)
        assert "On it, Captain." in rows["yeo1"]
    finally:
        await store_wi.stop()


# ---------------- 4. no 1:1-labelled episode is written from the group path ----


async def test_group_path_writes_no_1to1_episode(tmp_path):
    recorder = _RecordingEpisodic()
    store, runtime = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        replies={
            "scout1": "Sensors nominal, Captain.",
            "counselor1": "Morale steady, Captain.",
        },
        episodic=recorder,
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="report")

    await group_chat_fanout(runtime, t.id, captain_body="report", captain_msg=cap)

    # AD-933a: the fan-out now writes a GROUP-anchored episode per crew reply
    # (channel="chat", trigger_type="group_fanout", session_type="group") via a
    # dedicated write — but step_5_episodic_store (the only 1:1-labelled writer,
    # which hardcodes session_type:"1:1"/channel:"dm") stays EXCLUDED from the
    # escalation subset. So episodes ARE recorded now (was [] pre-AD-933a), and
    # NONE of them are 1:1-labelled.
    assert len(recorder.stored) == 2  # one group episode per crew reply (AD-933a)
    for ep in recorder.stored:  # documents the 1:1-exclusion intent (still holds)
        for outcome in getattr(ep, "outcomes", []) or []:
            assert outcome.get("session_type") != "1:1"
        anchors = getattr(ep, "anchors", None)
        if anchors is not None:
            assert anchors.channel != "dm"


# ---------------- 5. AD-869 mesh-read marker resolves or honest-degrades ------


async def test_group_mesh_read_marker_runs_without_crash(tmp_path):
    store, runtime = _build_env(
        tmp_path,
        agents={"yeo1": "scout", "scout1": "counselor"},
        replies={"yeo1": _MESH_REPLY, "scout1": "Standing by."},
    )
    t = store.create_thread(title="room", participants=["yeo1", "scout1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="look")

    # No capable mesh agent in the pool -> step_4h honest-degrades (no hang).
    await group_chat_fanout(runtime, t.id, captain_body="look", captain_msg=cap)

    rows = _agent_rows(store, t.id)
    # The MESH marker is stripped (never leaks to the Captain) and the reply
    # still persists. We do not over-assert mesh content — only that it ran.
    assert "[MESH" not in rows["yeo1"]
    assert "Let me check." in rows["yeo1"]


# ---------------- 6. run_escalation_only() runs ONLY the 6-step subset --------


_ALL_STEPS = (
    "step_1_sanity_gate_retry",
    "step_2_challenge_parse",
    "step_3_move_parse",
    "step_4_self_check_parse",
    "step_4c_image_gen_parse",
    "step_4d_follow_up_parse",
    "step_4e_action_dispatch",
    "step_4b_dm_outbound_parse",
    "step_4i_notebook_parse",
    "step_4h_mesh_read_parse",
    "step_4f_extract_artifacts",
    "step_4g_create_task_parse",
    "step_5_episodic_store",
    "step_6_working_memory_record",
    "step_7_divergence_check",
    "step_8_mark_emitted",
    "step_9_emotion_resolve",
)

_ESCALATION_SUBSET = (
    # AD-933b: step_4c_image_gen_parse added to the channel-agnostic subset
    # (run()-order: 4c precedes 4e), so the group fan-out can generate an image.
    "step_4c_image_gen_parse",
    "step_4e_action_dispatch",
    "step_4i_notebook_parse",
    "step_4h_mesh_read_parse",
    "step_4f_extract_artifacts",
    "step_4g_create_task_parse",
)


def _bare_pipeline() -> DmReplyPipeline:
    ctx = DmReplyContext(
        runtime=SimpleNamespace(),
        agent=SimpleNamespace(id="a1", agent_type="scout"),
        agent_id="a1",
        callsign="Scout",
        req_message="hi",
        response_text="reply",
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="hi",
        sampling_state=None,
        avatar_event_bus=None,
    )
    return DmReplyPipeline(ctx)


def _install_step_spies(pipeline: DmReplyPipeline) -> list[str]:
    """Replace all 17 step methods on the instance with recording spies.

    ``_full_steps``/``_escalation_steps`` read ``self.step_X`` at call time, so
    instance-attribute spies shadow the real methods — the dispatched tuple is
    the spies, and the real runtime is never touched.
    """
    recorded: list[str] = []

    def _make(name: str):
        async def _spy() -> None:
            recorded.append(name)

        return _spy

    for name in _ALL_STEPS:
        setattr(pipeline, name, _make(name))
    return recorded


async def test_run_escalation_only_invokes_only_the_subset():
    pipeline = _bare_pipeline()
    recorded = _install_step_spies(pipeline)

    await pipeline.run_escalation_only()

    # AD-933b: exactly the 6-step subset, in run()-order; none of the other 11 fired.
    assert recorded == list(_ESCALATION_SUBSET)
    excluded = set(_ALL_STEPS) - set(_ESCALATION_SUBSET)
    assert excluded.isdisjoint(recorded)


# ---------------- 7. run() still invokes all 17 steps in order ----------------


async def test_run_invokes_all_seventeen_steps_in_order():
    pipeline = _bare_pipeline()
    recorded = _install_step_spies(pipeline)

    await pipeline.run()

    # Regression guard for the AD-933 refactor: run() behaviour is byte-identical.
    assert recorded == list(_ALL_STEPS)


# ---------------- 8. fan-out return shape preserved with mutated text ---------


async def test_fanout_return_shape_preserved_with_mutated_text(tmp_path):
    store_wi = WorkItemStore(db_path=":memory:")
    await store_wi.start()
    try:
        store, runtime = _build_env(
            tmp_path,
            agents={"yeo1": "scout", "scout1": "counselor"},
            replies={"yeo1": _CREATE_TASK_REPLY, "scout1": "Standing by, Captain."},
            callsigns={"scout": "Yeo", "counselor": "Scout"},
            work_item_store=store_wi,
        )
        t = store.create_thread(title="room", participants=["yeo1", "scout1"])
        cap = store.append_message(t.id, author_id="captain", role="captain", body="handle it")

        replies = await group_chat_fanout(
            runtime, t.id, captain_body="handle it", captain_msg=cap
        )

        # Shape {agent_id, callsign, text} preserved for every speaker.
        assert len(replies) == 2
        for r in replies:
            assert set(r.keys()) == {"agent_id", "callsign", "text"}
        by_id = {r["agent_id"]: r for r in replies}
        # The escalated reply's text is the MUTATED (tag-stripped + suffixed) text.
        assert "[CREATE_TASK" not in by_id["yeo1"]["text"]
        assert "(Task opened:" in by_id["yeo1"]["text"]
        assert by_id["yeo1"]["callsign"] == "Yeo"
        # The plain reply is carried through unchanged.
        assert by_id["scout1"]["text"] == "Standing by, Captain."
    finally:
        await store_wi.stop()
