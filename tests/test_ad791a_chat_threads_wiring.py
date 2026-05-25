"""AD-791a: chat-threads wiring tests.

Covers the four substrate-level claims and the four router-level
contracts. Heavy integration tests for the FastAPI endpoint live in
``test_distribution.py`` (see ``TestAD791aAgentChatThreads``); these
tests run against the ``ChatThreadStore`` directly + use source-level
``inspect.getsource`` assertions for the router wiring (matching the
BF-289 pattern used in this codebase).

Twelve numbered tests in the spec (Section 9). This file holds the
Python tests #1-#3, #7, #8 (cognitive side), #10. Tests #4, #5, #6,
#8 (router side), #9 are in ``test_distribution.py`` because they
need a real FastAPI app + runtime.
"""

from __future__ import annotations

import inspect
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.threads import ChatThreadStore


# ──────────────────────────────────────────────────────────────────
# Shared mock-runtime helpers (modeled on test_ad730_agent_chat_vision)
# ──────────────────────────────────────────────────────────────────

_CREW_PATCH = patch("probos.routers.agents.is_crew_agent", return_value=True)


def _make_runtime_for_ad791a(
    *,
    tmp_path,
    response_text: str = "Acknowledged.",
):
    """Mock runtime configured for AD-791a non-attachment DM tests.

    Wires a REAL ``ChatThreadStore`` (so DB-level assertions on the
    chat-thread row + message log are meaningful) and stubs every other
    runtime collaborator the agent_chat handler reads.
    """
    from probos.config import CognitiveConfig
    from probos.cognitive.dm_sanity_gate import DmSanityGate

    runtime = MagicMock()

    agent = MagicMock()
    agent.id = "test-agent"
    agent.agent_type = "science_officer"
    agent.confidence = 0.7
    runtime.registry.get.return_value = agent

    runtime.callsign_registry.get_callsign.return_value = "Ezri"
    runtime.callsign_registry.resolve.return_value = {
        "agent_id": "test-agent",
        "callsign": "Ezri",
    }

    intent_result = MagicMock()
    intent_result.result = response_text
    intent_result.error = None
    runtime.intent_bus.send = AsyncMock(return_value=intent_result)

    runtime.recreation_service = None
    runtime.ward_room = None

    runtime.config = SimpleNamespace(
        attachments=SimpleNamespace(enabled=False),
        cognitive=CognitiveConfig(),
        perception=SimpleNamespace(enabled=False, dm_force_describe_enabled=False),
        dm_targeted_lookup=SimpleNamespace(enabled=False),
    )

    runtime.llm_client = MagicMock()
    runtime.llm_client.get_health_status = MagicMock(
        return_value={"tiers": {}, "overall": "operational"},
    )

    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock()

    runtime.dm_sanity_gate = DmSanityGate()

    # AD-791a: real ChatThreadStore so we can assert on persisted rows.
    runtime.chat_thread_store = ChatThreadStore(tmp_path / "chat_threads.db")

    # Avatar sampling state + event bus optional plumbing — pipeline guards
    # both with ``is not None`` checks, so absence is safe.
    runtime.avatar_sampling_state = None
    runtime.avatar_event_bus = None
    runtime.conversation_pacing_scheduler = None
    runtime.vision_consumer = None
    runtime.perception_mode_controller = None
    runtime.perception_engagement_registry = None

    return runtime


def _req(message: str = "hello", thread_id: str | None = None):
    r = MagicMock()
    r.message = message
    r.history = []
    r.attachment_ids = []
    r.thread_id = thread_id
    return r


# ──────────────────────────────────────────────────────────────────
# Test #1 — additive migration is idempotent across reboots
# ──────────────────────────────────────────────────────────────────

def test_alter_table_idempotent(tmp_path) -> None:
    """Opening an empty DB then re-opening must not error and must yield
    the AD-791a additive columns on both tables.
    """
    db_path = tmp_path / "threads.db"
    # First open: bare schema + AD-791a additive columns applied via
    # ``_migrate_v2``.
    store1 = ChatThreadStore(db_path)
    # Second open: idempotent — migration must detect existing columns
    # and skip them, not raise "duplicate column" errors.
    store2 = ChatThreadStore(db_path)

    with store2._connect() as conn:
        threads_cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_threads)")}
        messages_cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_thread_messages)")}

    assert "preprompt" in threads_cols
    assert "model" in threads_cols
    assert "metadata" in threads_cols
    assert "parent_message_id" in messages_cols
    assert "branch_ordinal" in messages_cols
    assert "score" in messages_cols
    assert "interrupted" in messages_cols
    # Sanity-touch both stores so neither is unused.
    assert store1.list_threads() == []
    assert store2.list_threads() == []


# ──────────────────────────────────────────────────────────────────
# Test #2 — get_or_create_default returns the same thread on second call
# ──────────────────────────────────────────────────────────────────

def test_get_or_create_default_creates_one_thread(tmp_path) -> None:
    """First call creates; second call returns the same row."""
    store = ChatThreadStore(tmp_path / "threads.db")

    t1 = store.get_or_create_default_for_agent("agent-ezri", "Ezri")
    t2 = store.get_or_create_default_for_agent("agent-ezri", "Ezri")

    assert t1.id == t2.id
    assert t1.participants == ["agent-ezri"]
    assert t1.title == "Ezri"
    assert t1.metadata.get("is_default") is True
    # Exactly one row in the table.
    assert len(store.list_threads()) == 1


# ──────────────────────────────────────────────────────────────────
# Test #3 — concurrent first-turn requests insert exactly one thread
# ──────────────────────────────────────────────────────────────────

def test_concurrent_first_turn_creates_one_thread(tmp_path) -> None:
    """Two threads racing on the same agent_id must serialize via
    ``BEGIN IMMEDIATE`` and end with exactly one row.
    """
    store = ChatThreadStore(tmp_path / "threads.db")
    results: list[str] = []
    errors: list[BaseException] = []

    def _race() -> None:
        try:
            t = store.get_or_create_default_for_agent("agent-worf", "Worf")
            results.append(t.id)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=_race) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=5.0)

    assert not errors, f"Concurrent get_or_create raised: {errors}"
    assert len(results) == 2
    assert results[0] == results[1], "Both racers must observe the same thread.id"
    assert len(store.list_threads()) == 1


# ──────────────────────────────────────────────────────────────────
# Test #7 — explicit non-default thread still resolves cleanly
# ──────────────────────────────────────────────────────────────────

def test_find_default_returns_none_when_no_default_exists(tmp_path) -> None:
    """``find_default_for_agent`` must not lazy-create. If no default
    exists, it returns None; only ``get_or_create_default_for_agent``
    inserts. This keeps the read-only path honest for AD-792 listing.
    """
    store = ChatThreadStore(tmp_path / "threads.db")
    assert store.find_default_for_agent("agent-cold") is None
    # Creating an UNRELATED thread (different agent) must NOT make the
    # original lookup return a sibling.
    store.create_thread(title="Stranger", participants=["agent-other"])
    assert store.find_default_for_agent("agent-cold") is None


# ──────────────────────────────────────────────────────────────────
# Test #8 (cognitive side) — chat_thread_id flows through DmReplyContext
# ──────────────────────────────────────────────────────────────────

def test_dm_reply_context_has_chat_thread_id_field() -> None:
    """DmReplyContext must carry ``chat_thread_id`` so the cognitive
    layer's AnchorFrame writes can tag episodes with their originating
    chat thread.
    """
    from probos.cognitive.dm.reply_pipeline import DmReplyContext

    # The dataclass field must exist with a string default of "".
    fields = {f.name: f for f in DmReplyContext.__dataclass_fields__.values()}
    assert "chat_thread_id" in fields, (
        "AD-791a: DmReplyContext must expose chat_thread_id so reply_pipeline "
        "AnchorFrame sites can populate AnchorFrame.chat_thread_id."
    )
    # Annotation should be ``str`` and default should be the empty string
    # so existing test fixtures that don't set it continue to pass.
    assert fields["chat_thread_id"].default == ""


def test_reply_pipeline_anchor_frames_propagate_chat_thread_id() -> None:
    """Both AnchorFrame sites in reply_pipeline.py must thread
    ``chat_thread_id=self.ctx.chat_thread_id`` through. Source-level
    assertion (matches BF-289 pattern) to avoid spinning up the full
    pipeline in this unit test.
    """
    from probos.cognitive.dm import reply_pipeline as rp_module

    src = inspect.getsource(rp_module)

    # AD-791a augments BOTH AnchorFrame sites. Search for the kwarg in
    # the source — two occurrences expected (action-dispatch + DM
    # episode).
    occurrences = src.count("chat_thread_id=self.ctx.chat_thread_id")
    assert occurrences >= 2, (
        f"AD-791a: expected >=2 AnchorFrame sites to propagate "
        f"chat_thread_id=self.ctx.chat_thread_id; found {occurrences}. "
        "Both the L658 action-dispatch and L757 DM AnchorFrame must be "
        "augmented (Section 5.6 of the spec)."
    )


# ──────────────────────────────────────────────────────────────────
# Test #10 — IntentMessage carries thread_id as a first-class field
# ──────────────────────────────────────────────────────────────────

def test_intent_message_carries_thread_id() -> None:
    """``IntentMessage.thread_id`` must be a real field with ``None``
    default, NOT buried in ``params`` (Section 1 of the spec).
    """
    from probos.types import IntentMessage

    fields = {f.name: f for f in IntentMessage.__dataclass_fields__.values()}
    assert "thread_id" in fields, (
        "AD-791a: IntentMessage must expose thread_id as a first-class "
        "field, not hidden inside params (Section 1)."
    )
    assert fields["thread_id"].default is None

    # Construct one to confirm runtime behavior.
    msg_no_thread = IntentMessage(intent="ping", params={})
    assert msg_no_thread.thread_id is None

    msg_with_thread = IntentMessage(
        intent="direct_message", params={}, thread_id="thread-abc"
    )
    assert msg_with_thread.thread_id == "thread-abc"


# ──────────────────────────────────────────────────────────────────
# Test #2-bis — anchor_frame.chat_thread_id is namespace-separate
# ──────────────────────────────────────────────────────────────────

def test_anchor_frame_chat_thread_id_is_separate_from_ward_room_thread_id() -> None:
    """The chat-thread namespace must NOT alias the Ward Room
    ``thread_id`` field. Section 2 of the spec is explicit about this:
    merging them would silently conflate two distinct ID spaces.
    """
    from probos.types import AnchorFrame

    fields = {f.name: f for f in AnchorFrame.__dataclass_fields__.values()}
    assert "thread_id" in fields, "AD-791a: Ward Room thread_id must remain present."
    assert "chat_thread_id" in fields, (
        "AD-791a: AnchorFrame must expose a SEPARATE chat_thread_id field; "
        "see Section 2 of the spec for the namespace rationale."
    )
    # Defaults must be the empty string (not None) so existing
    # AnchorFrame call-sites continue to work without modification.
    assert fields["chat_thread_id"].default == ""

    # Confirm construction with each field independently.
    af = AnchorFrame(thread_id="ward-room-abc", chat_thread_id="chat-xyz")
    assert af.thread_id == "ward-room-abc"
    assert af.chat_thread_id == "chat-xyz"


# ──────────────────────────────────────────────────────────────────
# Test #5 (delete cascade) — episodes survive thread delete
# ──────────────────────────────────────────────────────────────────

def test_thread_delete_preserves_episode_layer_semantics(tmp_path) -> None:
    """Deleting a thread must wipe its messages but leave the AnchorFrame
    namespace alone — episodes are agent-scoped memory, not thread-scoped
    (Section 0). The store has no episode foreign key, so this test is
    a contract check: ``delete_thread`` removes messages + thread, and
    leaves the rest of the data model untouched.
    """
    store = ChatThreadStore(tmp_path / "threads.db")
    t = store.get_or_create_default_for_agent("agent-keiko", "Keiko")
    store.append_message(t.id, author_id="captain", role="captain", body="Hi")
    store.append_message(t.id, author_id="agent-keiko", role="agent", body="Hello")
    assert len(store.list_messages(t.id)) == 2

    assert store.delete_thread(t.id) is True
    assert store.get_thread(t.id) is None
    assert store.list_messages(t.id) == []
    # Episodes are NOT touched by the store — that's the cascading
    # contract: delete the meeting log, not the relationship. The
    # ``AnchorFrame.chat_thread_id`` value can outlive the thread row,
    # which is exactly how the substrate-level "agent retains memory of
    # Captain" property of AD-791a Section 0 is preserved.


# ──────────────────────────────────────────────────────────────────
# Misleading-docstring fix audit (Section 1 closeout)
# ──────────────────────────────────────────────────────────────────

def test_threads_module_docstring_no_longer_misattributes_thread_id_origin() -> None:
    """Section 1 of the spec requires the misleading reference to
    ``activation/task_event.py`` be removed from the threads module
    docstring. ``IntentMessage.thread_id`` is AD-791a's responsibility.
    """
    import probos.threads as threads_pkg

    doc = (threads_pkg.__doc__ or "")
    # The misleading claim "IntentMessage.thread_id already exists
    # (activation/task_event.py)" must be gone. A historical parenthetical
    # mentioning that the EARLIER docstring referenced that file is fine
    # and even useful — it documents the rationale.
    assert "already exists (activation/task_event.py)" not in doc, (
        "AD-791a Section 1: the threads/__init__.py module docstring "
        "must no longer claim IntentMessage.thread_id already exists "
        "via activation/task_event.py — that was a different "
        "TaskEvent.thread_id namespace. AD-791a added the field on "
        "IntentMessage itself."
    )
    assert "AD-791a" in doc, (
        "Module docstring should reference AD-791a to point future "
        "contributors at the right history."
    )


# ──────────────────────────────────────────────────────────────────
# Router-side wiring assertions (no full app required)
# ──────────────────────────────────────────────────────────────────

def test_agent_chat_handler_wires_thread_store() -> None:
    """``routers/agents.py::agent_chat`` must reference the chat-thread
    store (``get_or_create_default_for_agent``) and propagate the
    thread ID through both IntentMessage and DmReplyContext.
    """
    from probos.routers import agents as agents_module

    src = inspect.getsource(agents_module.agent_chat)

    assert "get_or_create_default_for_agent" in src, (
        "AD-791a: agent_chat must resolve the default 1:1 thread for the "
        "addressed agent before dispatch."
    )
    assert "chat_thread_id=thread.id" in src, (
        "AD-791a: DmReplyContext must receive chat_thread_id=thread.id at "
        "construction time (Section 5.6)."
    )
    assert "thread_id=thread.id" in src, (
        "AD-791a: IntentMessage must carry thread_id=thread.id when "
        "dispatched from the chat router (Section 5.5)."
    )
    assert "append_message" in src, (
        "AD-791a: agent_chat must append both captain and agent messages "
        "to the chat-thread message log."
    )
    assert "AD-791a" in src, (
        "AD-791a wiring must be self-documenting in the handler."
    )


def test_chat_router_inline_callsign_wires_thread_store() -> None:
    """``routers/chat.py``'s inline-callsign branch must wire the
    thread store for parity with the 1:1 endpoint, populating
    ``IntentMessage.thread_id`` on dispatch.
    """
    from probos.routers import chat as chat_module

    src = inspect.getsource(chat_module)

    # Two distinct sites in chat.py: inline-callsign branch + vision
    # AnchorFrame. Both must carry AD-791a markers.
    assert src.count("AD-791a") >= 2, (
        "AD-791a: expected at least two AD-791a markers in chat.py "
        "(inline-callsign branch + vision-path AnchorFrame)."
    )
    assert "get_or_create_default_for_agent" in src, (
        "AD-791a: chat.py's inline-callsign branch must resolve the "
        "default thread for the addressed agent."
    )


# ──────────────────────────────────────────────────────────────────
# End-to-end tests using mock-runtime + real ChatThreadStore
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_chat_creates_default_thread_on_first_turn(tmp_path) -> None:
    """First POST to /api/agent/{id}/chat creates the implicit default
    thread, logs both captain + agent messages, and surfaces thread_id
    in the response dict.
    """
    from probos.routers.agents import agent_chat

    runtime = _make_runtime_for_ad791a(tmp_path=tmp_path)
    req = _req(message="Status report.")

    with _CREW_PATCH:
        result = await agent_chat("test-agent", req, runtime)

    threads = runtime.chat_thread_store.list_threads()
    assert len(threads) == 1
    thread = threads[0]
    assert thread.participants == ["test-agent"]
    assert thread.metadata.get("is_default") is True

    # Response carries thread_id.
    assert result.get("thread_id") == thread.id

    # Captain + agent messages both logged.
    msgs = runtime.chat_thread_store.list_messages(thread.id)
    assert len(msgs) == 2
    assert msgs[0].role == "captain"
    assert msgs[0].body == "Status report."
    assert msgs[1].role == "agent"


@pytest.mark.asyncio
async def test_agent_chat_reuses_default_thread_on_second_turn(tmp_path) -> None:
    """Two consecutive turns must land in the same thread; the store
    must not accumulate phantom rows.
    """
    from probos.routers.agents import agent_chat

    runtime = _make_runtime_for_ad791a(tmp_path=tmp_path)

    with _CREW_PATCH:
        first = await agent_chat("test-agent", _req(message="Turn one"), runtime)
        second = await agent_chat("test-agent", _req(message="Turn two"), runtime)

    assert first["thread_id"] == second["thread_id"]
    threads = runtime.chat_thread_store.list_threads()
    assert len(threads) == 1
    msgs = runtime.chat_thread_store.list_messages(threads[0].id)
    # Two turns × (captain + agent) = 4 messages.
    assert len(msgs) == 4


@pytest.mark.asyncio
async def test_agent_chat_explicit_thread_id_routes_correctly(tmp_path) -> None:
    """When the client passes an explicit thread_id that includes this
    agent in its participants, the turn lands in THAT thread (not the
    implicit default).
    """
    from probos.routers.agents import agent_chat

    runtime = _make_runtime_for_ad791a(tmp_path=tmp_path)
    explicit = runtime.chat_thread_store.create_thread(
        title="Alt thread",
        participants=["test-agent"],
    )

    req = _req(message="To the alt thread", thread_id=explicit.id)
    with _CREW_PATCH:
        result = await agent_chat("test-agent", req, runtime)

    assert result["thread_id"] == explicit.id
    msgs = runtime.chat_thread_store.list_messages(explicit.id)
    assert len(msgs) == 2
    assert msgs[0].body == "To the alt thread"


@pytest.mark.asyncio
async def test_agent_chat_invalid_thread_id_returns_400(tmp_path) -> None:
    """Bogus thread_id (no row, or row missing this agent from
    participants) must produce HTTPException 400, not silent fallback
    to default.
    """
    from fastapi import HTTPException

    from probos.routers.agents import agent_chat

    runtime = _make_runtime_for_ad791a(tmp_path=tmp_path)

    # (a) thread_id that does not exist
    req = _req(message="x", thread_id="thread-does-not-exist")
    with _CREW_PATCH:
        with pytest.raises(HTTPException) as ei:
            await agent_chat("test-agent", req, runtime)
    assert ei.value.status_code == 400

    # (b) thread that exists but is for a different agent
    other = runtime.chat_thread_store.create_thread(
        title="Other agent", participants=["different-agent"]
    )
    req2 = _req(message="x", thread_id=other.id)
    with _CREW_PATCH:
        with pytest.raises(HTTPException) as ei2:
            await agent_chat("test-agent", req2, runtime)
    assert ei2.value.status_code == 400


@pytest.mark.asyncio
async def test_agent_chat_dispatched_intent_carries_thread_id(tmp_path) -> None:
    """The IntentMessage that ``agent_chat`` dispatches must carry
    ``thread_id`` set to the resolved thread's ID.
    """
    from probos.routers.agents import agent_chat

    runtime = _make_runtime_for_ad791a(tmp_path=tmp_path)
    with _CREW_PATCH:
        await agent_chat("test-agent", _req(message="With thread"), runtime)

    sent_intent = runtime.intent_bus.send.call_args.args[0]
    assert sent_intent.intent == "direct_message"
    assert sent_intent.target_agent_id == "test-agent"
    assert sent_intent.thread_id is not None
    assert sent_intent.thread_id != ""
    threads = runtime.chat_thread_store.list_threads()
    assert sent_intent.thread_id == threads[0].id
