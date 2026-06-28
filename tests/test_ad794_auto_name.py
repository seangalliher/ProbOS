"""AD-794: thread auto-naming tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.threads import ChatThreadStore


_CREW_PATCH = patch("probos.routers.agents.is_crew_agent", return_value=True)


def _make_runtime(*, tmp_path):
    from probos.config import CognitiveConfig
    from probos.cognitive.dm_sanity_gate import DmSanityGate
    from types import SimpleNamespace

    runtime = MagicMock()
    agent = MagicMock()
    agent.id = "test-agent"
    agent.agent_type = "science_officer"
    agent.confidence = 0.7
    runtime.registry.get.return_value = agent

    runtime.callsign_registry.get_callsign.return_value = "Ezri"
    intent_result = MagicMock()
    intent_result.result = "Acknowledged."
    intent_result.error = None
    runtime.intent_bus.send = AsyncMock(return_value=intent_result)

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
    runtime.chat_thread_store = ChatThreadStore(tmp_path / "chat_threads.db")
    runtime.avatar_sampling_state = None
    runtime.avatar_event_bus = None
    runtime.conversation_pacing_scheduler = None
    runtime.vision_consumer = None
    runtime.perception_mode_controller = None
    runtime.perception_engagement_registry = None
    runtime.recreation_service = None
    runtime.ward_room = None
    return runtime


def _req(message: str, thread_id: str | None = None):
    r = MagicMock()
    r.message = message
    r.history = []
    r.attachment_ids = []
    r.thread_id = thread_id
    # AD-1062: explicit False — the new system_trigger gate must not read a
    # truthy MagicMock proxy (would skip the auto-name this file asserts).
    r.system_trigger = False
    return r


# ----------- store-level: maybe_auto_name -----------

def test_maybe_auto_name_renames_default_thread_on_first_turn(tmp_path) -> None:
    store = ChatThreadStore(tmp_path / "threads.db")
    thread = store.get_or_create_default_for_agent("agent-ezri", "Ezri")
    assert thread.title == "Ezri"

    renamed = store.maybe_auto_name(
        thread.id, "Help me investigate the failed warp coil simulation.",
    )
    assert renamed is not None
    assert renamed.title != "Ezri"
    assert "warp coil" in renamed.title.lower() or "investigate" in renamed.title.lower()


def test_maybe_auto_name_returns_none_when_title_locked(tmp_path) -> None:
    """Spec test #8 partial — locked titles never auto-rename."""
    store = ChatThreadStore(tmp_path / "threads.db")
    thread = store.get_or_create_default_for_agent("agent-ezri", "Ezri")
    store.set_title(thread.id, "Captain's Chosen Name", lock=True)
    assert store.is_title_locked(thread.id) is True

    result = store.maybe_auto_name(thread.id, "Something new to discuss.")
    assert result is None
    # Title unchanged.
    assert store.get_thread(thread.id).title == "Captain's Chosen Name"


def test_maybe_auto_name_returns_none_when_thread_has_messages(tmp_path) -> None:
    """force=False skips threads that already have messages — the
    first-turn signal is "no prior activity", which the agent_chat
    flow relies on (captain message is appended AFTER auto-name)."""
    store = ChatThreadStore(tmp_path / "threads.db")
    thread = store.get_or_create_default_for_agent("agent-ezri", "Ezri")
    store.append_message(
        thread.id, author_id="captain", role="captain", body="first turn",
    )

    # Default mode: any prior message blocks auto-name.
    result = store.maybe_auto_name(thread.id, "Now a different topic.")
    assert result is None
    assert store.get_thread(thread.id).title == "Ezri"


def test_maybe_auto_name_force_true_overrides_renamed_state(tmp_path) -> None:
    """force=True (used by POST /auto-name) ignores pre-conditions
    except for the title_locked flag — preserves the endpoint's pre-
    AD-794 always-rename behavior."""
    store = ChatThreadStore(tmp_path / "threads.db")
    thread = store.get_or_create_default_for_agent("agent-ezri", "Ezri")
    store.set_title(thread.id, "Old topic", lock=False)

    result = store.maybe_auto_name(
        thread.id, "Investigate the warp coil issue.", force=True,
    )
    assert result is not None
    assert result.title != "Old topic"
    assert result.title != "Ezri"


def test_maybe_auto_name_force_true_still_respects_lock(tmp_path) -> None:
    """force=True does NOT override the lock — manual rename always wins."""
    store = ChatThreadStore(tmp_path / "threads.db")
    thread = store.get_or_create_default_for_agent("agent-ezri", "Ezri")
    store.set_title(thread.id, "Locked Title", lock=True)

    result = store.maybe_auto_name(
        thread.id, "Some other topic.", force=True,
    )
    assert result is None
    assert store.get_thread(thread.id).title == "Locked Title"


def test_set_title_lock_writes_metadata_title_locked(tmp_path) -> None:
    """is_title_locked reads the metadata.title_locked flag set by
    set_title(lock=True)."""
    store = ChatThreadStore(tmp_path / "threads.db")
    thread = store.get_or_create_default_for_agent("agent-ezri", "Ezri")

    # Unlocked by default.
    assert store.is_title_locked(thread.id) is False

    store.set_title(thread.id, "Locked Name", lock=True)
    assert store.is_title_locked(thread.id) is True
    assert store.get_thread(thread.id).title == "Locked Name"

    # Setting again with lock=False does NOT clear the flag (lock is
    # one-way; clearing requires manual metadata edit). Title still
    # updates though.
    store.set_title(thread.id, "Locked Name v2", lock=False)
    assert store.is_title_locked(thread.id) is True
    assert store.get_thread(thread.id).title == "Locked Name v2"


def test_is_title_locked_returns_false_on_malformed_metadata(tmp_path) -> None:
    """Defensive: malformed JSON in metadata degrades to False rather
    than raising — auto-name will be a no-op instead of crashing the
    chat turn."""
    store = ChatThreadStore(tmp_path / "threads.db")
    thread = store.get_or_create_default_for_agent("agent-ezri", "Ezri")

    # Corrupt the metadata via raw SQL.
    with store._connect() as conn:
        conn.execute(
            "UPDATE chat_threads SET metadata = ? WHERE id = ?",
            ("not-valid-json{{", thread.id),
        )

    # Must not raise.
    assert store.is_title_locked(thread.id) is False


# ----------- agent_chat: auto-name fires on first turn -----------

@pytest.mark.asyncio
async def test_agent_chat_auto_names_thread_on_first_turn(tmp_path) -> None:
    """Spec test #7 — fresh agent, first turn, title goes from
    callsign to derived heuristic."""
    from probos.routers.agents import agent_chat

    runtime = _make_runtime(tmp_path=tmp_path)
    req = _req("Help me debug the dilithium chamber resonance.")

    with _CREW_PATCH:
        result = await agent_chat("test-agent", req, runtime)

    threads = runtime.chat_thread_store.list_threads()
    assert len(threads) == 1
    thread = threads[0]
    # Title was renamed from the default callsign.
    assert thread.title != "Ezri"
    assert "dilithium" in thread.title.lower() or "debug" in thread.title.lower()

    # Response carries the renamed title.
    assert result.get("thread_id") == thread.id
    assert result.get("title") == thread.title


@pytest.mark.asyncio
async def test_agent_chat_does_not_rename_after_lock(tmp_path) -> None:
    """Spec test #8 — PATCH to lock the title, then chat: title unchanged."""
    from probos.routers.agents import agent_chat

    runtime = _make_runtime(tmp_path=tmp_path)
    # Seed the default thread + lock the title via the store API
    # (equivalent to a PATCH ... title_locked=true round-trip).
    thread = runtime.chat_thread_store.get_or_create_default_for_agent(
        "test-agent", "Ezri",
    )
    runtime.chat_thread_store.set_title(
        thread.id, "Captain's Choice", lock=True,
    )

    req = _req("Tell me about the warp coil.")
    with _CREW_PATCH:
        result = await agent_chat("test-agent", req, runtime)

    assert result.get("thread_id") == thread.id
    final = runtime.chat_thread_store.get_thread(thread.id)
    assert final.title == "Captain's Choice"


@pytest.mark.asyncio
async def test_agent_chat_does_not_rename_on_second_turn(tmp_path) -> None:
    """Spec test #9 — two turns; title only set after first."""
    from probos.routers.agents import agent_chat

    runtime = _make_runtime(tmp_path=tmp_path)

    with _CREW_PATCH:
        first = await agent_chat(
            "test-agent",
            _req("Help me investigate the failed coil sim."),
            runtime,
        )
        first_title = first.get("title")
        # Different topic on second turn.
        second = await agent_chat(
            "test-agent",
            _req("What's the engineering status report?"),
            runtime,
        )
        second_title = second.get("title")

    assert first_title is not None
    assert first_title != "Ezri"
    # Second turn: title must NOT have drifted to the second body.
    assert second_title == first_title


# ----------- PATCH endpoint locks the title -----------

@pytest.mark.asyncio
async def test_rename_thread_endpoint_locks_title(tmp_path) -> None:
    """Spec test #11 — PATCH /api/threads/{id} with title_locked=true
    persists the lock flag."""
    from probos.routers.threads import UpdateThreadRequest, update_thread

    store = ChatThreadStore(tmp_path / "threads.db")
    thread = store.get_or_create_default_for_agent("agent-ezri", "Ezri")

    runtime = MagicMock()
    runtime.chat_thread_store = store

    body = UpdateThreadRequest(title="Renamed by hand", title_locked=True)
    result = await update_thread(thread.id, body, runtime)
    assert result["title"] == "Renamed by hand"

    assert store.is_title_locked(thread.id) is True
    assert store.get_thread(thread.id).title == "Renamed by hand"


@pytest.mark.asyncio
async def test_update_thread_without_title_locked_preserves_existing_behavior(tmp_path) -> None:
    """Existing PATCH behavior unchanged when title_locked is omitted."""
    from probos.routers.threads import UpdateThreadRequest, update_thread

    store = ChatThreadStore(tmp_path / "threads.db")
    thread = store.get_or_create_default_for_agent("agent-ezri", "Ezri")

    runtime = MagicMock()
    runtime.chat_thread_store = store

    body = UpdateThreadRequest(title="Soft rename")
    result = await update_thread(thread.id, body, runtime)
    assert result["title"] == "Soft rename"
    # No lock written when title_locked is not True.
    assert store.is_title_locked(thread.id) is False
