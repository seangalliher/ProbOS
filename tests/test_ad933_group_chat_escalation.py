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

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult
from probos.workforce import WorkItemStore
from probos.cognitive.dm.reply_value import DmReply  # AD-1248


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


async def test_group_failed_notebook_write_discloses_and_marks_episode(tmp_path) -> None:
    import inspect
    from pathlib import Path

    from probos.cognitive.dm.write_ledger import (
        WRITE_CHANNEL_NOTEBOOK,
        ClaimVerdict,
        disclosure_for,
    )
    from tests.test_ad1285_write_claim_guard import (
        _FakeProactiveLoop,
        _make_ctx,
        _runtime,
    )

    root = Path(__file__).resolve().parents[1]
    for symbol, relative_path in (
        (DmReplyPipeline, "src/probos/cognitive/dm/reply_pipeline.py"),
        (group_chat_fanout, "src/probos/routers/thread_fanout.py"),
        (IntentBus, "src/probos/mesh/intent.py"),
        (ChatThreadStore, "src/probos/threads/__init__.py"),
        (_FakeProactiveLoop, "tests/test_ad1285_write_claim_guard.py"),
    ):
        assert Path(inspect.getfile(symbol)).resolve() == root / relative_path

    marked_reply = "Saved the finding. [NOTEBOOK finding]Review-probe finding.[/NOTEBOOK]"
    peer_text = "The crew morale is steady."
    disclosure = disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
    assert disclosure.strip()
    dm_producer = _FakeProactiveLoop(actions=[])
    dm_ctx = _make_ctx(
        runtime=_runtime(proactive=dm_producer), response_text=marked_reply,
    )
    dm_pipeline = DmReplyPipeline(dm_ctx)
    await dm_pipeline.run()

    assert dm_producer.calls == [marked_reply]
    assert dm_ctx.write_ledger.evaluated is True
    assert dm_ctx.write_ledger.consulted == frozenset({WRITE_CHANNEL_NOTEBOOK})
    assert dm_ctx.write_ledger.wrote == frozenset()
    assert dm_ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_NOTEBOOK})
    assert dm_ctx.response_text.count(disclosure) == 1
    assert dm_pipeline.build_response()["response"].count(disclosure) == 1
    assert "[NOTEBOOK" not in dm_ctx.response_text

    recorder = _RecordingEpisodic()
    producer = _FakeProactiveLoop(actions=[])
    store, runtime = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        replies={"scout1": marked_reply, "counselor1": peer_text},
        episodic=recorder,
    )
    runtime.proactive_loop = producer
    thread = store.create_thread(
        title="room", participants=["scout1", "counselor1"],
    )
    captain = store.append_message(
        thread.id, author_id="captain", role="captain", body="Save the finding.",
    )

    replies = await group_chat_fanout(
        runtime, thread.id, captain_body="Save the finding.", captain_msg=captain,
    )

    assert producer.calls == [marked_reply]
    agent_messages = [
        message for message in store.list_messages(thread.id, limit=1000)
        if message.role == "agent"
    ]
    assert len(agent_messages) == 2
    assert sorted(message.author_id for message in agent_messages) == [
        "counselor1", "scout1",
    ]
    rows = _agent_rows(store, thread.id)
    assert len(replies) == 2
    writer_replies = [reply for reply in replies if reply["agent_id"] == "scout1"]
    peer_replies = [reply for reply in replies if reply["agent_id"] == "counselor1"]
    assert len(writer_replies) == 1
    assert len(peer_replies) == 1
    assert len(recorder.stored) == 2
    writer_episodes = [
        episode for episode in recorder.stored if episode.agent_ids == ["scout1"]
    ]
    peer_episodes = [
        episode for episode in recorder.stored if episode.agent_ids == ["counselor1"]
    ]
    assert len(writer_episodes) == 1
    assert len(peer_episodes) == 1
    for episode in recorder.stored:
        assert episode.source == "group_chat_fanout"
        assert episode.anchors.chat_thread_id == thread.id
        assert episode.anchors.channel == "chat"
        assert episode.anchors.trigger_type == "group_fanout"
        assert len(episode.outcomes) == 1
        assert episode.outcomes[0]["session_type"] == "group"
        assert episode.outcomes[0]["success"] is True
    assert rows["counselor1"] == peer_text
    assert peer_replies[0]["text"] == peer_text
    assert peer_episodes[0].outcomes[0]["response"] == peer_text
    assert peer_episodes[0].self_contradicted_channels == []
    assert "[NOTEBOOK" not in rows["scout1"]
    assert "Saved the finding." in rows["scout1"]

    assert rows["scout1"].count(disclosure) == 1
    assert writer_replies[0]["text"].count(disclosure) == 1
    assert writer_episodes[0].outcomes[0]["response"].count(disclosure) == 1
    assert writer_episodes[0].self_contradicted_channels == [WRITE_CHANNEL_NOTEBOOK]


async def test_group_tag_only_failed_write_remains_declined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect

    from tests.test_ad1285_write_claim_guard import _FakeProactiveLoop

    root = Path(__file__).resolve().parents[1]
    for symbol, relative_path in (
        (DmReplyPipeline, "src/probos/cognitive/dm/reply_pipeline.py"),
        (group_chat_fanout, "src/probos/routers/thread_fanout.py"),
        (IntentBus, "src/probos/mesh/intent.py"),
        (ChatThreadStore, "src/probos/threads/__init__.py"),
        (_FakeProactiveLoop, "tests/test_ad1285_write_claim_guard.py"),
    ):
        assert Path(inspect.getfile(symbol)).resolve() == root / relative_path

    marked_reply = '<intent emotion="focused"/>[NOTEBOOK finding][/NOTEBOOK]'
    peer_text = "The crew morale is steady."
    recorder = _RecordingEpisodic()
    producer = _FakeProactiveLoop(actions=[])
    store, runtime = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        replies={"scout1": marked_reply, "counselor1": peer_text},
        episodic=recorder,
    )
    runtime.proactive_loop = producer
    contexts: list[DmReplyContext] = []
    escalate = DmReplyPipeline.run_escalation_only

    async def record_escalation(pipeline: DmReplyPipeline) -> None:
        await escalate(pipeline)
        contexts.append(pipeline.ctx)

    monkeypatch.setattr(DmReplyPipeline, "run_escalation_only", record_escalation)
    thread = store.create_thread(
        title="declined write", participants=["scout1", "counselor1"],
    )
    captain = store.append_message(
        thread.id, author_id="captain", role="captain", body="Save the finding.",
    )

    replies = await group_chat_fanout(
        runtime, thread.id, captain_body=captain.body, captain_msg=captain,
    )

    assert producer.calls == [marked_reply]
    assert sorted(ctx.agent_id for ctx in contexts) == ["counselor1", "scout1"]
    writer_contexts = [ctx for ctx in contexts if ctx.agent_id == "scout1"]
    assert len(writer_contexts) == 1
    ledger = writer_contexts[0].write_ledger
    assert ledger.evaluated is True
    assert ledger.consulted == frozenset({"notebook"})
    assert ledger.wrote == frozenset()
    assert ledger.wrote_nothing == frozenset({"notebook"})
    agent_messages = [
        message for message in store.list_messages(thread.id, limit=1000)
        if message.role == "agent"
    ]
    peer_replies = [reply for reply in replies if reply["agent_id"] == "counselor1"]
    peer_messages = [message for message in agent_messages if message.author_id == "counselor1"]
    peer_episodes = [
        episode for episode in recorder.stored if episode.agent_ids == ["counselor1"]
    ]
    assert len(peer_replies) == len(peer_messages) == len(peer_episodes) == 1
    assert peer_replies[0]["text"] == peer_text
    assert peer_messages[0].body == _agent_rows(store, thread.id)["counselor1"] == peer_text
    assert peer_episodes[0].outcomes[0]["response"] == peer_text
    assert peer_episodes[0].self_contradicted_channels == []
    assert peer_episodes[0].source == "group_chat_fanout"
    assert peer_episodes[0].anchors.chat_thread_id == thread.id
    assert peer_episodes[0].outcomes[0]["session_type"] == "group"

    assert len(replies) == 1
    assert replies == peer_replies
    assert len(agent_messages) == 1
    assert agent_messages == peer_messages
    assert len(recorder.stored) == 1
    assert recorder.stored == peer_episodes


@pytest.mark.parametrize("guard_enabled", [True, False], ids=["guard-on", "guard-off"])
async def test_group_late_escalation_failure_preserves_known_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, guard_enabled: bool,
) -> None:
    import inspect

    from probos.cognitive.dm.write_ledger import ClaimVerdict, disclosure_for
    from probos.config import WriteClaimGuardConfig
    from tests.test_ad1285_write_claim_guard import _FakeProactiveLoop

    root = Path(__file__).resolve().parents[1]
    for symbol, relative_path in (
        (DmReplyPipeline, "src/probos/cognitive/dm/reply_pipeline.py"),
        (group_chat_fanout, "src/probos/routers/thread_fanout.py"),
        (IntentBus, "src/probos/mesh/intent.py"),
        (ChatThreadStore, "src/probos/threads/__init__.py"),
        (_FakeProactiveLoop, "tests/test_ad1285_write_claim_guard.py"),
    ):
        assert Path(inspect.getfile(symbol)).resolve() == root / relative_path

    raw_fallback = "Saved the finding. [NOTEBOOK finding]Review-probe finding.[/NOTEBOOK]"
    marked_reply = '<intent emotion="focused"/>' + raw_fallback
    peer_text = "The crew morale is steady."
    disclosure = disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
    assert disclosure.strip()
    recorder = _RecordingEpisodic()
    producer = _FakeProactiveLoop(actions=[])
    store, runtime = _build_env(
        tmp_path,
        agents={"scout1": "scout", "counselor1": "counselor"},
        replies={"scout1": marked_reply, "counselor1": peer_text},
        episodic=recorder,
    )
    runtime.proactive_loop = producer
    runtime.config = SimpleNamespace(
        write_claim_guard=WriteClaimGuardConfig(enabled=guard_enabled),
    )
    contexts: list[DmReplyContext] = []
    failed_agents: list[str] = []
    escalate = DmReplyPipeline.run_escalation_only

    async def fail_after_escalation(pipeline: DmReplyPipeline) -> None:
        await escalate(pipeline)
        contexts.append(pipeline.ctx)
        if pipeline.ctx.agent_id == "scout1":
            assert pipeline.ctx.write_ledger.wrote_nothing == frozenset({"notebook"})
            failed_agents.append(pipeline.ctx.agent_id)
            raise RuntimeError("Injected outer failure after completed writer escalation")

    monkeypatch.setattr(DmReplyPipeline, "run_escalation_only", fail_after_escalation)
    thread = store.create_thread(
        title="late escalation failure", participants=["scout1", "counselor1"],
    )
    captain = store.append_message(
        thread.id, author_id="captain", role="captain", body="Save the finding.",
    )

    replies = await group_chat_fanout(
        runtime, thread.id, captain_body=captain.body, captain_msg=captain,
    )

    assert producer.calls == [marked_reply]
    assert failed_agents == ["scout1"]
    assert sorted(ctx.agent_id for ctx in contexts) == ["counselor1", "scout1"]
    writer_contexts = [ctx for ctx in contexts if ctx.agent_id == "scout1"]
    assert len(writer_contexts) == 1
    ledger = writer_contexts[0].write_ledger
    assert ledger.evaluated is True
    assert ledger.consulted == frozenset({"notebook"})
    assert ledger.wrote == frozenset()
    assert ledger.wrote_nothing == frozenset({"notebook"})
    assert writer_contexts[0].response_text.count(disclosure) == int(guard_enabled)
    assert "[NOTEBOOK" not in writer_contexts[0].response_text
    agent_messages = [
        message for message in store.list_messages(thread.id, limit=1000)
        if message.role == "agent"
    ]
    assert len(replies) == len(agent_messages) == len(recorder.stored) == 2
    assert sorted(message.author_id for message in agent_messages) == ["counselor1", "scout1"]
    writer_replies = [reply for reply in replies if reply["agent_id"] == "scout1"]
    peer_replies = [reply for reply in replies if reply["agent_id"] == "counselor1"]
    writer_episodes = [
        episode for episode in recorder.stored if episode.agent_ids == ["scout1"]
    ]
    peer_episodes = [
        episode for episode in recorder.stored if episode.agent_ids == ["counselor1"]
    ]
    assert len(writer_replies) == len(peer_replies) == len(writer_episodes) == len(peer_episodes) == 1
    rows = _agent_rows(store, thread.id)
    assert writer_replies[0]["text"] == rows["scout1"] == raw_fallback
    assert writer_episodes[0].outcomes[0]["response"] == raw_fallback
    assert disclosure not in raw_fallback
    assert peer_replies[0]["text"] == rows["counselor1"] == peer_text
    assert peer_episodes[0].outcomes[0]["response"] == peer_text
    assert peer_episodes[0].self_contradicted_channels == []
    for episode in recorder.stored:
        assert episode.source == "group_chat_fanout"
        assert episode.anchors.chat_thread_id == thread.id
        assert episode.anchors.channel == "chat"
        assert episode.anchors.trigger_type == "group_fanout"
        assert len(episode.outcomes) == 1
        assert episode.outcomes[0]["session_type"] == "group"
        assert episode.outcomes[0]["success"] is True

    assert writer_episodes[0].self_contradicted_channels == ["notebook"]


@pytest.mark.parametrize("guard_enabled", [True, False])
@pytest.mark.parametrize("case", [
    "tag-only", "tag-whitespace", "embedded-decline", "substantive",
    "notice-prose", "partial-notice-prose", "empty-processed", "uncaptured",
    "late-tag-only",
])
async def test_group_write_disclosure_does_not_decide_eligibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, guard_enabled: bool, case: str,
) -> None:
    from probos.avatars.divergence_detector import strip_intent_self_tag
    from probos.cognitive.dm.write_ledger import ClaimVerdict, disclosure_for
    from probos.config import WriteClaimGuardConfig
    from tests.test_ad1285_write_claim_guard import _FakeProactiveLoop

    notice = disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
    partial_notice = disclosure_for(ClaimVerdict.MARKER_WROTE_PARTIALLY)
    prefix = {
        "tag-only": '<intent emotion="focused"/>',
        "tag-whitespace": ' \t<intent emotion="focused"/> \n ',
        "embedded-decline": '<intent emotion="focused"/>Deferring [nO_rEsPoNsE] today. ',
        "substantive": '<intent emotion="focused"/>Saved the finding. ',
        "notice-prose": notice.strip(),
        "partial-notice-prose": partial_notice.strip(),
        "empty-processed": "",
        "uncaptured": '<intent emotion="focused"/>',
        "late-tag-only": '<intent emotion="focused"/>',
    }[case]
    marked_reply = prefix + "[NOTEBOOK finding][/NOTEBOOK]"
    peer_text = "The crew morale is steady."
    producer = _FakeProactiveLoop(actions=[])
    recorder = _RecordingEpisodic()
    store, runtime = _build_env(
        tmp_path, agents={"scout1": "scout", "counselor1": "counselor"},
        replies={"scout1": marked_reply, "counselor1": peer_text}, episodic=recorder,
    )
    runtime.proactive_loop = producer
    runtime.config = SimpleNamespace(
        write_claim_guard=WriteClaimGuardConfig(enabled=guard_enabled),
    )
    contexts: list[DmReplyContext] = []
    escalate = DmReplyPipeline.run_escalation_only

    async def record_escalation(pipeline: DmReplyPipeline) -> None:
        await escalate(pipeline)
        contexts.append(pipeline.ctx)
        if case == "late-tag-only" and pipeline.ctx.agent_id == "scout1":
            assert pipeline.ctx.write_ledger.wrote_nothing == frozenset({"notebook"})
            raise RuntimeError("Injected late failure with a discarded tag-only body")

    async def skip_guard(pipeline: DmReplyPipeline) -> None:
        assert pipeline.ctx.pre_write_disclosure_body is None

    monkeypatch.setattr(DmReplyPipeline, "run_escalation_only", record_escalation)
    if case == "uncaptured":
        monkeypatch.setattr(DmReplyPipeline, "step_4m_write_claim_guard", skip_guard)
    thread = store.create_thread(title="eligibility boundary", participants=["scout1", "counselor1"])
    captain = store.append_message(thread.id, author_id="captain", role="captain", body="Report.")

    replies = await group_chat_fanout(runtime, thread.id, captain_body=captain.body, captain_msg=captain)

    assert producer.calls == [marked_reply.strip()]
    writer_contexts = [ctx for ctx in contexts if ctx.agent_id == "scout1"]
    assert len(writer_contexts) == 1
    ctx = writer_contexts[0]
    assert ctx.write_ledger.wrote_nothing == frozenset({"notebook"})
    assert ctx.pre_write_disclosure_body == (None if case == "uncaptured" else prefix.strip())
    if case == "empty-processed":
        assert ctx.response_text == ""
    eligible = case in {
        "substantive", "notice-prose", "partial-notice-prose", "empty-processed", "late-tag-only",
    }
    messages = [message for message in store.list_messages(thread.id, limit=1000) if message.role == "agent"]
    assert len(replies) == len(messages) == len(recorder.stored) == 1 + int(eligible)
    peer_replies = [reply for reply in replies if reply["agent_id"] == "counselor1"]
    peer_messages = [message for message in messages if message.author_id == "counselor1"]
    peer_episodes = [episode for episode in recorder.stored if episode.agent_ids == ["counselor1"]]
    assert len(peer_replies) == len(peer_messages) == len(peer_episodes) == 1
    assert peer_replies[0]["text"] == peer_messages[0].body == peer_text
    assert peer_episodes[0].outcomes[0]["response"] == peer_text
    assert peer_episodes[0].self_contradicted_channels == []
    writer_replies = [reply for reply in replies if reply["agent_id"] == "scout1"]
    writer_messages = [message for message in messages if message.author_id == "scout1"]
    writer_episodes = [episode for episode in recorder.stored if episode.agent_ids == ["scout1"]]
    assert len(writer_replies) == len(writer_messages) == len(writer_episodes) == int(eligible)
    if eligible:
        expected = strip_intent_self_tag(
            marked_reply if case in {"empty-processed", "late-tag-only"} else
            prefix.strip() + (notice if guard_enabled else "")
        )
        assert writer_replies[0]["text"] == writer_messages[0].body == expected
        assert writer_episodes[0].outcomes[0]["response"] == expected
        assert writer_episodes[0].self_contradicted_channels == ["notebook"]
        assert writer_episodes[0].outcomes[0]["success"] is True
        assert set(writer_replies[0]) == {"agent_id", "callsign", "text"}


@pytest.mark.parametrize("failure_stage", ["reply", "context", "pipeline", "before-producer"])
async def test_group_failure_before_write_facts_does_not_invent_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str,
) -> None:
    from probos.routers import thread_fanout
    from tests.test_ad1285_write_claim_guard import _FakeProactiveLoop

    raw_fallback = "Saved the finding. [NOTEBOOK finding]Review-probe finding.[/NOTEBOOK]"
    marked_reply = '<intent emotion="focused"/>' + raw_fallback
    peer_text = "The crew morale is steady."
    producer = _FakeProactiveLoop(actions=[])
    recorder = _RecordingEpisodic()
    store, runtime = _build_env(
        tmp_path, agents={"scout1": "scout", "counselor1": "counselor"},
        replies={"scout1": marked_reply, "counselor1": peer_text}, episodic=recorder,
    )
    runtime.proactive_loop = producer
    failures: list[str] = []
    contexts: list[DmReplyContext] = []
    original_reply = thread_fanout.DmReply
    original_context = thread_fanout.DmReplyContext
    original_pipeline = thread_fanout.DmReplyPipeline
    escalate = DmReplyPipeline.run_escalation_only

    def construct_reply(*, body: str) -> DmReply:
        if body == marked_reply and failure_stage == "reply":
            failures.append(failure_stage)
            raise RuntimeError("Injected reply construction failure")
        return original_reply(body=body)

    def construct_context(**kwargs: Any) -> DmReplyContext:
        if kwargs["agent_id"] == "scout1" and failure_stage == "context":
            failures.append(failure_stage)
            raise RuntimeError("Injected context construction failure")
        context = original_context(**kwargs)
        contexts.append(context)
        return context

    def construct_pipeline(context: DmReplyContext) -> DmReplyPipeline:
        if context.agent_id == "scout1" and failure_stage == "pipeline":
            failures.append(failure_stage)
            raise RuntimeError("Injected pipeline construction failure")
        return original_pipeline(context)

    async def fail_before_producer(pipeline: DmReplyPipeline) -> None:
        if pipeline.ctx.agent_id == "scout1":
            assert pipeline.ctx.write_ledger.evaluated is False
            failures.append(failure_stage)
            raise RuntimeError("Injected orchestration failure before producers")
        await escalate(pipeline)

    monkeypatch.setattr(thread_fanout, "DmReply", construct_reply)
    monkeypatch.setattr(thread_fanout, "DmReplyContext", construct_context)
    monkeypatch.setattr(thread_fanout, "DmReplyPipeline", construct_pipeline)
    if failure_stage == "before-producer":
        monkeypatch.setattr(DmReplyPipeline, "run_escalation_only", fail_before_producer)
    thread = store.create_thread(title="unestablished ledger", participants=["scout1", "counselor1"])
    captain = store.append_message(thread.id, author_id="captain", role="captain", body="Report.")

    replies = await group_chat_fanout(runtime, thread.id, captain_body=captain.body, captain_msg=captain)

    assert failures == [failure_stage]
    assert producer.calls == []
    writer_contexts = [ctx for ctx in contexts if ctx.agent_id == "scout1"]
    assert len(writer_contexts) == int(failure_stage in {"pipeline", "before-producer"})
    assert all(ctx.write_ledger.evaluated is False for ctx in contexts)
    assert all(ctx.pre_write_disclosure_body is None for ctx in writer_contexts)
    messages = [message for message in store.list_messages(thread.id, limit=1000) if message.role == "agent"]
    assert len(replies) == len(messages) == len(recorder.stored) == 2
    for agent_id, expected in (("scout1", raw_fallback), ("counselor1", peer_text)):
        agent_replies = [reply for reply in replies if reply["agent_id"] == agent_id]
        agent_messages = [message for message in messages if message.author_id == agent_id]
        episodes = [episode for episode in recorder.stored if episode.agent_ids == [agent_id]]
        assert len(agent_replies) == len(agent_messages) == len(episodes) == 1
        assert agent_replies[0]["text"] == agent_messages[0].body == expected
        assert episodes[0].outcomes[0]["response"] == expected
        assert episodes[0].self_contradicted_channels == []
        assert episodes[0].outcomes[0]["success"] is True


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


# ---------------- 6. run_escalation_only() runs ONLY the shared subset --------


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
    "step_4k_extract_a2ui",
    "step_4g_create_task_parse",
    "step_4l_extract_todos",
    "step_4j_deliberate_parse",  # AD-934
    "step_4n_tool_write_ledger",
    "step_4m_write_claim_guard",
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
    "step_4k_extract_a2ui",
    "step_4g_create_task_parse",
    "step_4l_extract_todos",
    "step_4j_deliberate_parse",
    "step_4m_write_claim_guard",
)


def _bare_pipeline() -> DmReplyPipeline:
    ctx = DmReplyContext(
        runtime=SimpleNamespace(),
        agent=SimpleNamespace(id="a1", agent_type="scout"),
        agent_id="a1",
        callsign="Scout",
        req_message="hi",
        reply=DmReply(body="reply"),
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
    """Replace all full-chain step methods on the instance with recording spies.

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

    # AD-1305: the shared guard runs last; no excluded 1:1 step fires.
    assert recorded == list(_ESCALATION_SUBSET)
    excluded = set(_ALL_STEPS) - set(_ESCALATION_SUBSET)
    assert excluded.isdisjoint(recorded)


# ---------------- 7. run() still invokes the full chain in order -------------


async def test_run_invokes_all_steps_in_order():
    pipeline = _bare_pipeline()
    recorded = _install_step_spies(pipeline)

    await pipeline.run()

    # Regression guard: run() invokes every step in the full-chain order.
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


@pytest.mark.parametrize("case", [
    "empty", "plain", "unwired-notebook", "missing-notebook-method",
    "unrecognized-action", "producer-error", "unwired-artifacts",
    "missing-attachment-store", "passive-fence",
])
async def test_group_unknown_and_no_marker_outcomes_preserve_peer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    from probos.cognitive.dm.write_ledger import ClaimVerdict, WriteLedger, disclosure_for
    from probos.config import WriteClaimGuardConfig
    from tests.test_ad1285_write_claim_guard import CLEANED_REPLY, MARKED_REPLY, _FakeProactiveLoop
    from tests.test_bf866_artifact_channel_seams import _SelectivelyFailingStore, _long_fence, _two_tags

    text = MARKED_REPLY
    if case == "empty":
        text = ""
    elif case == "plain":
        text = "The finding is worth considering."
    elif case in {"unwired-artifacts", "missing-attachment-store"}:
        text = _two_tags()
    elif case == "passive-fence":
        text = _long_fence(lang="markdown")
    recorder = _RecordingEpisodic()
    producer = _FakeProactiveLoop(
        actions=[None, {}, {"type": "notebook_queued"}], raises=case == "producer-error",
    )
    store, runtime = _build_env(
        tmp_path, agents={"scout1": "scout", "counselor1": "counselor"},
        replies={"scout1": text, "counselor1": "Morale steady."}, episodic=recorder,
    )
    runtime.config = SimpleNamespace(
        write_claim_guard=WriteClaimGuardConfig(enabled=True),
        cognitive=SimpleNamespace(artifact_fenced_threshold_lines=40),
    )
    runtime.proactive_loop = (
        None if case == "unwired-notebook" else
        SimpleNamespace() if case == "missing-notebook-method" else producer
    )
    artifacts = _SelectivelyFailingStore(tmp_path / "artifacts.db", set())
    attachments = FilesystemAttachmentStore(tmp_path / "attachments")
    runtime.artifact_store = None if case == "unwired-artifacts" else artifacts
    runtime.attachment_store = None if case == "missing-attachment-store" else attachments
    contexts: list[DmReplyContext] = []
    escalate = DmReplyPipeline.run_escalation_only

    async def record_escalation(pipeline: DmReplyPipeline) -> None:
        await escalate(pipeline)
        contexts.append(pipeline.ctx)

    monkeypatch.setattr(DmReplyPipeline, "run_escalation_only", record_escalation)
    thread = store.create_thread(title="outcome boundary", participants=["scout1", "counselor1"])
    captain = store.append_message(thread.id, author_id="captain", role="captain", body="Report.")
    replies = await group_chat_fanout(runtime, thread.id, captain_body=captain.body, captain_msg=captain)

    expected_count = 1 if case == "empty" else 2
    rows = _agent_rows(store, thread.id)
    messages = [message for message in store.list_messages(thread.id, limit=1000) if message.role == "agent"]
    assert len(replies) == len(messages) == len(recorder.stored) == expected_count
    assert rows == {reply["agent_id"]: reply["text"] for reply in replies}
    assert rows["counselor1"] == "Morale steady."
    peer = [episode for episode in recorder.stored if episode.agent_ids == ["counselor1"]]
    assert len(peer) == 1
    assert peer[0].self_contradicted_channels == []
    assert peer[0].outcomes[0]["response"] == "Morale steady."
    known_failure = case in {"unrecognized-action", "producer-error"}
    assert producer.calls == ([MARKED_REPLY] if known_failure else [])
    assert all(ctx.tool_invocations is None for ctx in contexts)
    writer_contexts = [ctx for ctx in contexts if ctx.agent_id == "scout1"]
    if case == "empty":
        assert writer_contexts == []
        assert "scout1" not in rows
    else:
        assert len(writer_contexts) == 1
        ledger = writer_contexts[0].write_ledger
        assert ledger == (
            WriteLedger().consulted_with("notebook", wrote=False) if known_failure else
            WriteLedger().consulted_with("artifact", wrote=True) if case == "passive-fence" else
            WriteLedger()
        )
        writer = [episode for episode in recorder.stored if episode.agent_ids == ["scout1"]]
        assert len(writer) == 1
        assert writer[0].self_contradicted_channels == (["notebook"] if known_failure else [])
        assert writer[0].outcomes[0]["success"] is True
        assert rows["scout1"].count(disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)) == int(known_failure)
        if known_failure or case in {"unwired-notebook", "missing-notebook-method"}:
            assert rows["scout1"] == CLEANED_REPLY + (
                disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING) if known_failure else ""
            )
        elif case != "passive-fence":
            assert rows["scout1"] == text
    assert artifacts.attempted == (["artifact-1.md"] if case == "passive-fence" else [])
    persisted = artifacts.list_thread_latest(thread.id)
    assert len(persisted) == int(case == "passive-fence")
    if persisted:
        assert persisted[0].version == 1
        assert await attachments.read(persisted[0].content_hash) == "\n".join(
            f"x = {index}" for index in range(60)
        ).encode()
        assert "[Artifact: artifact-1.md v1" in rows["scout1"]


@pytest.mark.parametrize("denied", [False, True], ids=["addressed-empty-retry", "denied-no-retry"])
async def test_group_addressed_write_reply_keeps_retry_and_denial_contract(
    tmp_path: Path, denied: bool,
) -> None:
    from probos.cognitive.dm.write_ledger import ClaimVerdict, disclosure_for
    from probos.extensions import overlay
    from tests.test_ad1285_write_claim_guard import MARKED_REPLY, _FakeProactiveLoop
    from tests.test_bf790_fanout_denial_not_retried import _HANDOFF, _build_env as denial_env, _run

    overlay.reset_for_tests()
    try:
        store, runtime, attempts = denial_env(
            tmp_path, bones_replies=["", MARKED_REPLY], deny_bones=denied,
        )
        producer = _FakeProactiveLoop(actions=[])
        recorder = _RecordingEpisodic()
        runtime.proactive_loop = producer
        runtime.episodic_memory = recorder
        thread_id, replies = await _run(store, runtime)

        assert [text for target, text in attempts if target == "bones1"] == [_HANDOFF] * (1 if denied else 2)
        assert len([target for target, _text in attempts if target == "scout1"]) == 1
        assert producer.calls == ([] if denied else [MARKED_REPLY])
        messages = [message for message in store.list_messages(thread_id, limit=1000) if message.role == "agent"]
        assert len(messages) == len(replies) == len(recorder.stored) == (1 if denied else 2)
        assert [reply["agent_id"] for reply in replies] == (["scout1"] if denied else ["scout1", "bones1"])
        assert replies[0]["text"] == "@Bones your read?"
        assert recorder.stored[0].self_contradicted_channels == []
        if not denied:
            notice = disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
            assert replies[1]["text"].count(notice) == 1
            assert _agent_rows(store, thread_id)["bones1"] == replies[1]["text"]
            assert recorder.stored[1].agent_ids == ["bones1"]
            assert recorder.stored[1].self_contradicted_channels == ["notebook"]
            assert recorder.stored[1].outcomes[0]["success"] is True
            assert recorder.stored[1].outcomes[0]["response"].count(notice) == 1
    finally:
        overlay.reset_for_tests()


async def test_group_write_marker_is_isolated_across_rounds_and_calls(tmp_path: Path) -> None:
    from probos.cognitive.dm.write_ledger import ClaimVerdict, disclosure_for
    from probos.config import GroupChatConfig
    from tests.test_ad1285_write_claim_guard import MARKED_REPLY, _FakeProactiveLoop
    from tests.test_bf636_empty_result_thinning import _build_env as scripted_env, _scripted_handler

    dispatches: list[dict[str, Any]] = []
    marked_handoff = "@Bones your read? " + MARKED_REPLY
    store, runtime = scripted_env(
        tmp_path, agents={"scout1": "scout", "bones1": "diagnostician"},
        handlers={
            "scout1": _scripted_handler("scout1", [marked_handoff, "Sensors nominal."], dispatches),
            "bones1": _scripted_handler("bones1", ["Medical status steady."], dispatches),
        },
        gc=GroupChatConfig(
            agent_reactivity_enabled=True, agent_next_speaker_selection_enabled=True,
            max_agent_rounds=1, max_speakers_per_turn=1,
        ),
    )
    recorder = _RecordingEpisodic()
    producer = _FakeProactiveLoop(actions=[])
    runtime.episodic_memory = recorder
    runtime.proactive_loop = producer
    thread = store.create_thread(title="round isolation", participants=["scout1", "bones1"])
    captain = store.append_message(thread.id, author_id="captain", role="captain", body="thoughts team?")
    first = await group_chat_fanout(runtime, thread.id, captain_body=captain.body, captain_msg=captain)
    assert [reply["agent_id"] for reply in first] == ["scout1", "bones1"]
    assert [dispatch["agent_id"] for dispatch in dispatches] == ["scout1", "bones1"]
    assert len(recorder.stored) == 2
    assert recorder.stored[0].self_contradicted_channels == ["notebook"]
    assert recorder.stored[1].self_contradicted_channels == []
    assert first[1]["text"] == "Medical status steady."
    runtime.config.group_chat = GroupChatConfig(agent_reactivity_enabled=False)
    second_captain = store.append_message(thread.id, author_id="captain", role="captain", body="Fresh status report.")
    second = await group_chat_fanout(
        runtime, thread.id, captain_body=second_captain.body, captain_msg=second_captain,
    )
    assert len(second) == 2
    assert {reply["text"] for reply in second} == {"Sensors nominal.", "Medical status steady."}
    assert producer.calls == [marked_handoff]
    assert len(dispatches) == 4
    assert len(recorder.stored) == 4
    assert all(episode.self_contradicted_channels == [] for episode in recorder.stored[2:])
    assert all(episode.outcomes[0]["success"] is True for episode in recorder.stored)
    messages = [message for message in store.list_messages(thread.id, limit=1000) if message.role == "agent"]
    assert len(messages) == 4
    notice = disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
    assert sum(message.body.count(notice) for message in messages) == 1
    assert sum(reply["text"].count(notice) for reply in first + second) == 1
    assert sum(episode.outcomes[0]["response"].count(notice) for episode in recorder.stored) == 1


async def test_group_cancellation_during_notebook_producer_does_not_publish_writer(
    tmp_path: Path,
) -> None:
    from tests.test_ad1285_write_claim_guard import MARKED_REPLY

    entered = asyncio.Event()
    finished = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    class _AwaitingNotebookProducer:
        async def extract_and_execute_notebooks(
            self, agent: Any, text: str,
        ) -> tuple[str, list[dict[str, Any]]]:
            calls.append(text)
            entered.set()
            try:
                await release.wait()
                return text, []
            finally:
                finished.set()

    recorder = _RecordingEpisodic()
    store, runtime = _build_env(
        tmp_path, agents={"scout1": "scout", "counselor1": "counselor"},
        replies={"scout1": MARKED_REPLY, "counselor1": "Morale steady."}, episodic=recorder,
    )
    runtime.proactive_loop = _AwaitingNotebookProducer()
    thread = store.create_thread(title="cancelled write", participants=["scout1", "counselor1"])
    captain = store.append_message(thread.id, author_id="captain", role="captain", body="Report.")
    pending = asyncio.create_task(group_chat_fanout(
        runtime, thread.id, captain_body=captain.body, captain_msg=captain,
    ))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5.0)
        assert calls == [MARKED_REPLY]
        assert not finished.is_set()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert finished.is_set()
        assert recorder.stored == []
        messages = [message for message in store.list_messages(thread.id, limit=1000) if message.role == "agent"]
        assert len(messages) <= 1
        assert all(message.author_id == "counselor1" and message.body == "Morale steady." for message in messages)
        assert calls == [MARKED_REPLY]
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
