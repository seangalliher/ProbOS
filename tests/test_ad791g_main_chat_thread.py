"""AD-791g (#792): main-chat thread + Captain↔Ship's-Computer thread wiring.

The multi-mention fan-out (``routers/chat.py``) seeds a single shared
``MAIN_CHAT_THREAD_ID`` thread, stamps every dispatched intent with it, and
logs the Captain turn + each real agent reply into it. The vision /
Captain-only branch routes its turn into the fixed ``COMPUTER_THREAD_ID``
thread. Both are FLAG-LESS honest-degrade: gated only on
``runtime.chat_thread_store`` presence — with the store absent every new
behavior is byte-identical to pre-AD-791g (intents carry ``thread_id=None``,
episodes keep ``chat_thread_id=""``).

Harness convention mirrors ``test_ad791a_chat_threads_wiring.py`` (real
``ChatThreadStore(tmp_path)``) and ``test_ad720d3_vision_episode_write.py``
(real filesystem attachment store for the vision path). ``asyncio_mode=auto``
→ plain ``async def`` tests. BF-287: the leading-callsign parsers and
``CallsignRegistry.resolve`` are REAL (a real registry seeded with >=2
callsigns + a fake AgentRegistry), not MagicMock'd.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from probos.crew_profile import CallsignRegistry
from probos.routers.chat import chat
from probos.threads import COMPUTER_THREAD_ID, MAIN_CHAT_THREAD_ID, ChatThreadStore

_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


# ──────────────────────────────────────────────────────────────────
# Real CallsignRegistry + fake AgentRegistry (BF-287: no MagicMock on
# the parse/resolve path).
# ──────────────────────────────────────────────────────────────────


class _FakeAgent:
    def __init__(self, agent_id: str) -> None:
        self.id = agent_id
        self.is_alive = True


class _FakeAgentRegistry:
    def __init__(self, by_pool: dict[str, list]) -> None:
        self._by_pool = by_pool

    def get_by_pool(self, agent_type: str) -> list:
        return self._by_pool.get(agent_type, [])


def _make_callsign_registry() -> CallsignRegistry:
    reg = CallsignRegistry()
    reg.set_callsign("science_officer", "Ezri")
    reg.set_callsign("ops_officer", "Yeo")
    reg.set_callsign("chief_engineer", "Tucker")
    reg.bind_registry(
        _FakeAgentRegistry(
            {
                "science_officer": [_FakeAgent("agent-sci")],
                "ops_officer": [_FakeAgent("agent-ops")],
                "chief_engineer": [_FakeAgent("agent-eng")],
            }
        )
    )
    return reg


class _FakeDreamAdapter:
    """Returns a channel="dag" Episode with NO chat_thread_id — the exact
    shape of the real ``dream_adapter.build_episode`` (dream_adapter.py:410).
    The AD-933a regression guard: the fan-out must post-mutate the anchor
    AFTER the if/else so this branch's id is set too.
    """

    def build_episode(
        self,
        text: str,
        execution_result: dict,
        t_start: float,
        t_end: float,
    ):
        from probos.types import AnchorFrame, Episode

        return Episode(
            timestamp=time.time(),
            user_input=text,
            agent_ids=list(execution_result.get("agent_ids", [])),
            source="dag",
            anchors=AnchorFrame(channel="dag", trigger_type="dag_execution"),
        )


def _req(message: str, *, attachment_ids: list[str] | None = None):
    r = MagicMock()
    r.message = message
    r.history = []
    r.attachment_ids = attachment_ids or []
    r.thread_id = None
    return r


def _make_fanout_runtime(
    tmp_path,
    *,
    with_store: bool = True,
    reply_text: str = "Acknowledged.",
):
    """MagicMock runtime for the fan-out path: real ChatThreadStore + real
    CallsignRegistry; AsyncMock intent_bus + episodic store; dream_adapter
    forced to None so the else-branch (real Episode) runs deterministically.
    """
    runtime = MagicMock()
    runtime.callsign_registry = _make_callsign_registry()
    runtime.intent_bus.send = AsyncMock(
        return_value=SimpleNamespace(result=reply_text, error=None),
    )
    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock()
    runtime.dream_adapter = None
    runtime.chat_thread_store = (
        ChatThreadStore(tmp_path / "chat_threads.db") if with_store else None
    )
    return runtime


def _make_vision_runtime(tmp_path, *, with_store: bool = True):
    """MagicMock runtime for the vision branch. Pre-seeds the per-runtime
    attachment-store cache with a real FilesystemAttachmentStore (so the
    handler can be called directly, no FastAPI client). Returns
    (runtime, attachment_store).
    """
    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    from probos.config import AttachmentsConfig, CognitiveConfig
    import probos.routers.chat as chat_mod

    target = tmp_path / "attachments"
    target.mkdir(parents=True, exist_ok=True)

    cfg_attach = AttachmentsConfig(
        attachments_dir=str(target),
        max_attachment_bytes=10 * 1024 * 1024,
        text_extraction_max_bytes=1024,
        vision_tier="vision",
        pdf_extraction_enabled=False,
    )
    cfg_cognitive = CognitiveConfig(
        llm_base_url_vision="http://127.0.0.1:11434/v1",
        llm_model_vision="llava:34b",
    )

    llm_client = MagicMock()
    llm_client.complete = AsyncMock(
        return_value=SimpleNamespace(
            content="An orange cat on a blue background.",
            tier="vision",
            model="llava:34b",
        ),
    )
    llm_client.get_health_status = MagicMock(
        return_value={
            "tiers": {
                "fast": {"status": "operational"},
                "standard": {"status": "operational"},
                "deep": {"status": "operational"},
                "vision": {"status": "operational"},
            },
            "overall": "operational",
        },
    )

    runtime = MagicMock()
    runtime.config = SimpleNamespace(attachments=cfg_attach, cognitive=cfg_cognitive)
    runtime.llm_client = llm_client
    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock()
    runtime.chat_thread_store = (
        ChatThreadStore(tmp_path / "chat_threads.db") if with_store else None
    )

    store = FilesystemAttachmentStore(target)
    chat_mod._ATTACHMENT_STORE_CACHE[id(runtime)] = store
    return runtime, store


# ──────────────────────────────────────────────────────────────────
# Test 1 — every dispatched fan-out intent carries MAIN_CHAT_THREAD_ID
# ──────────────────────────────────────────────────────────────────


async def test_fanout_intents_carry_main_chat_thread_id(tmp_path) -> None:
    runtime = _make_fanout_runtime(tmp_path)
    resp = await chat(
        _req("@Ezri @Yeo status report"),
        runtime=runtime,
        track_task=Mock(),
        broadcast=Mock(),
        pending_designs={},
    )
    calls = runtime.intent_bus.send.call_args_list
    assert len(calls) == 2
    for c in calls:
        intent = c.args[0]
        assert intent.thread_id == MAIN_CHAT_THREAD_ID
    assert resp["thread_id"] == MAIN_CHAT_THREAD_ID


# ──────────────────────────────────────────────────────────────────
# Test 2 — ONE shared thread, not N; 1 captain + N agent messages
# ──────────────────────────────────────────────────────────────────


async def test_fanout_one_shared_thread_not_n(tmp_path) -> None:
    runtime = _make_fanout_runtime(tmp_path)
    await chat(
        _req("@Ezri @Yeo status report"),
        runtime=runtime,
        track_task=Mock(),
        broadcast=Mock(),
        pending_designs={},
    )
    store = runtime.chat_thread_store
    threads = store.list_threads()
    assert [t.id for t in threads] == [MAIN_CHAT_THREAD_ID]

    msgs = store.list_messages(MAIN_CHAT_THREAD_ID)
    roles = [m.role for m in msgs]
    assert roles.count("captain") == 1
    assert roles.count("agent") == 2
    assert len(msgs) == 3


# ──────────────────────────────────────────────────────────────────
# Test 3 — membership is fixed/implicit: participants stays [] forever
# ──────────────────────────────────────────────────────────────────


async def test_fanout_membership_fixed_implicit(tmp_path) -> None:
    runtime = _make_fanout_runtime(tmp_path)
    store = runtime.chat_thread_store
    await chat(
        _req("@Ezri @Yeo first"),
        runtime=runtime,
        track_task=Mock(),
        broadcast=Mock(),
        pending_designs={},
    )
    assert store.get_thread(MAIN_CHAT_THREAD_ID).participants == []

    # A second fan-out that introduces a NEW callsign must NOT mutate the
    # roster (append-only, no participants read-modify-write).
    await chat(
        _req("@Tucker @Ezri second"),
        runtime=runtime,
        track_task=Mock(),
        broadcast=Mock(),
        pending_designs={},
    )
    assert store.get_thread(MAIN_CHAT_THREAD_ID).participants == []


# ──────────────────────────────────────────────────────────────────
# Test 4 — THE AD-933a REGRESSION GUARD: episode anchored on BOTH the
# else-branch (dream_adapter=None) AND the build_episode branch (fake
# dream_adapter returns channel="dag", no chat_thread_id).
# ──────────────────────────────────────────────────────────────────


async def test_fanout_episode_anchored_both_branches(tmp_path) -> None:
    # else-branch: no dream_adapter → direct Episode(channel="chat").
    runtime = _make_fanout_runtime(tmp_path)
    runtime.dream_adapter = None
    await chat(
        _req("@Ezri @Yeo go"),
        runtime=runtime,
        track_task=Mock(),
        broadcast=Mock(),
        pending_designs={},
    )
    stored = [c.args[0] for c in runtime.episodic_memory.store.call_args_list]
    assert len(stored) == 2
    for ep in stored:
        assert ep.anchors is not None
        assert ep.anchors.chat_thread_id == MAIN_CHAT_THREAD_ID
        assert ep.anchors.channel == "chat"

    # build_episode branch: fake dream_adapter returns a channel="dag"
    # AnchorFrame with NO chat_thread_id. The post-mutation AFTER the
    # if/else must still set the id — augmenting only the else-branch
    # AnchorFrame would silently drop it here (AD-933a).
    runtime2 = _make_fanout_runtime(tmp_path / "b")
    runtime2.dream_adapter = _FakeDreamAdapter()
    await chat(
        _req("@Ezri @Yeo go"),
        runtime=runtime2,
        track_task=Mock(),
        broadcast=Mock(),
        pending_designs={},
    )
    stored2 = [c.args[0] for c in runtime2.episodic_memory.store.call_args_list]
    assert len(stored2) == 2
    for ep in stored2:
        assert ep.anchors is not None
        assert ep.anchors.chat_thread_id == MAIN_CHAT_THREAD_ID
        # Proves the episode came from build_episode (dag-shaped), so the
        # post-mutation reached the production branch — not just the else.
        assert ep.anchors.channel == "dag"


# ──────────────────────────────────────────────────────────────────
# Test 5 — concurrent appends to the shared thread are safe (append-only,
# no participants RMW → no write-skew); all rows present, roster unchanged.
# ──────────────────────────────────────────────────────────────────


async def test_fanout_concurrent_appends_safe(tmp_path) -> None:
    store = ChatThreadStore(tmp_path / "concurrent.db")
    store.get_or_create_system_thread(MAIN_CHAT_THREAD_ID, title="Main Chat")
    n = 10

    async def _append(i: int):
        return await asyncio.to_thread(
            store.append_message,
            MAIN_CHAT_THREAD_ID,
            author_id=f"agent-{i}",
            role="agent",
            body=f"message {i}",
            metadata={"i": i},
        )

    results = await asyncio.gather(*[_append(i) for i in range(n)])
    assert all(r is not None for r in results)

    msgs = store.list_messages(MAIN_CHAT_THREAD_ID, limit=1000)
    assert len(msgs) == n
    assert store.get_thread(MAIN_CHAT_THREAD_ID).participants == []


# ──────────────────────────────────────────────────────────────────
# Test 6 — vision / Captain-only branch routes into COMPUTER_THREAD_ID
# ──────────────────────────────────────────────────────────────────


async def test_computer_thread_routing_vision_branch(tmp_path) -> None:
    import probos.routers.chat as chat_mod

    runtime, store = _make_vision_runtime(tmp_path, with_store=True)
    blob = _PNG_HEADER + b"a" * 64
    sha = hashlib.sha256(blob).hexdigest()
    await store.write(sha, blob, "image/png")

    try:
        resp = await chat(
            _req("what is this", attachment_ids=[sha]),
            runtime=runtime,
            track_task=Mock(),
            broadcast=Mock(),
            pending_designs={},
        )
    finally:
        chat_mod._ATTACHMENT_STORE_CACHE.pop(id(runtime), None)

    assert resp["response"] == "An orange cat on a blue background."

    # Vision episode is anchored to the Computer thread.
    episode = runtime.episodic_memory.store.call_args.args[0]
    assert episode.anchors is not None
    assert episode.anchors.chat_thread_id == COMPUTER_THREAD_ID

    # Computer thread exists, is tagged system, implicit membership, and
    # carries the Captain turn + the Computer reply.
    cstore = runtime.chat_thread_store
    thread = cstore.get_thread(COMPUTER_THREAD_ID)
    assert thread is not None
    assert thread.metadata["kind"] == "system"
    assert thread.participants == []

    msgs = cstore.list_messages(COMPUTER_THREAD_ID)
    bodies = {m.role: m.body for m in msgs}
    assert bodies["captain"] == "what is this"
    assert bodies["agent"] == "An orange cat on a blue background."


# ──────────────────────────────────────────────────────────────────
# Test 7 — get_or_create_system_thread is idempotent + self-healing
# ──────────────────────────────────────────────────────────────────


def test_get_or_create_system_thread_idempotent(tmp_path) -> None:
    store = ChatThreadStore(tmp_path / "sys.db")
    t1 = store.get_or_create_system_thread(MAIN_CHAT_THREAD_ID, title="Main Chat")
    t2 = store.get_or_create_system_thread(
        MAIN_CHAT_THREAD_ID, title="Different Title"
    )
    assert t1.id == t2.id == MAIN_CHAT_THREAD_ID
    assert len(store.list_threads()) == 1

    fetched = store.get_thread(MAIN_CHAT_THREAD_ID)
    assert fetched is not None
    assert fetched.metadata["kind"] == "system"
    assert fetched.participants == []
    # Idempotent: the second call did NOT overwrite the existing row.
    assert fetched.title == "Main Chat"


# ──────────────────────────────────────────────────────────────────
# Test 8 — store absent → BYTE-IDENTICAL to pre-AD-791g (fan-out + vision)
# ──────────────────────────────────────────────────────────────────


async def test_store_absent_byte_identical(tmp_path) -> None:
    import probos.routers.chat as chat_mod

    # ---- fan-out with store absent ----
    runtime = _make_fanout_runtime(tmp_path, with_store=False)
    assert runtime.chat_thread_store is None
    resp = await chat(
        _req("@Ezri @Yeo status"),
        runtime=runtime,
        track_task=Mock(),
        broadcast=Mock(),
        pending_designs={},
    )
    # Replies still returned; no thread id surfaced.
    assert len(resp["per_agent_replies"]) == 2
    assert resp["thread_id"] is None
    # Intents carry thread_id=None.
    for c in runtime.intent_bus.send.call_args_list:
        assert c.args[0].thread_id is None
    # Fan-out episodes keep chat_thread_id="".
    stored = [c.args[0] for c in runtime.episodic_memory.store.call_args_list]
    assert len(stored) == 2
    for ep in stored:
        assert ep.anchors.chat_thread_id == ""

    # ---- vision with store absent ----
    vruntime, vstore = _make_vision_runtime(tmp_path / "v", with_store=False)
    assert vruntime.chat_thread_store is None
    blob = _PNG_HEADER + b"a" * 64
    sha = hashlib.sha256(blob).hexdigest()
    await vstore.write(sha, blob, "image/png")
    try:
        vresp = await chat(
            _req("what is this", attachment_ids=[sha]),
            runtime=vruntime,
            track_task=Mock(),
            broadcast=Mock(),
            pending_designs={},
        )
    finally:
        chat_mod._ATTACHMENT_STORE_CACHE.pop(id(vruntime), None)

    assert vresp["response"] == "An orange cat on a blue background."
    vep = vruntime.episodic_memory.store.call_args.args[0]
    assert vep.anchors.chat_thread_id == ""
