"""AD-809: personality registry + slash-command tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import inspect
import pytest

from probos.cognitive.commands.personality_command import (
    handle_personality_command,
    is_personality_command,
)
from probos.cognitive.personality_registry import (
    list_personalities,
    resolve_personality_text,
)
from probos.threads import ChatThreadStore


# ----------- registry -----------

def test_personality_registry_lookup_hit_miss_and_list() -> None:
    """Spec test #1 — three sub-checks rolled into one."""
    # Hit (case-insensitive + leading/trailing whitespace tolerant).
    text = resolve_personality_text("Concise")
    assert text is not None
    assert "short answers" in text

    # Whitespace + casing.
    assert resolve_personality_text("  formal  ") is not None

    # Miss.
    assert resolve_personality_text("wibble") is None

    # List returns sorted names, all present.
    names = list_personalities()
    assert set(names) == {"casual", "concise", "expert", "formal", "socratic"}
    assert names == sorted(names)


# ----------- /personality command parser + handler -----------

def test_is_personality_command_recognises_slash() -> None:
    assert is_personality_command("/personality formal")
    assert is_personality_command("  /personality concise  ")
    assert is_personality_command("/personality")
    # Anything else is NOT a /personality command.
    assert not is_personality_command("hello")
    assert not is_personality_command("/remind me tomorrow")


@pytest.fixture
def _store(tmp_path) -> ChatThreadStore:
    return ChatThreadStore(tmp_path / "threads.db")


def _make_thread(store: ChatThreadStore, agent_id: str = "agent-ezri") -> str:
    return store.get_or_create_default_for_agent(agent_id, "Ezri").id


def test_handle_personality_command_set(_store) -> None:
    """Spec test #2 — `/personality concise` sets the override."""
    thread_id = _make_thread(_store)

    result = handle_personality_command(
        "/personality concise", thread_id=thread_id, store=_store,
    )
    assert result["applied"] == "concise"
    assert "concise" in result["system_reply"].lower()
    assert "concise" in result["available"]

    # Override persisted.
    thread = _store.get_thread(thread_id)
    assert thread is not None
    assert thread.personality_override is not None
    assert "short answers" in thread.personality_override


def test_handle_personality_command_clear(_store) -> None:
    """Spec test #3 — `/personality clear` removes the override."""
    thread_id = _make_thread(_store)
    _store.set_personality_override(thread_id, override="something")
    assert _store.get_thread(thread_id).personality_override == "something"

    result = handle_personality_command(
        "/personality clear", thread_id=thread_id, store=_store,
    )
    assert result["applied"] is None
    assert _store.get_thread(thread_id).personality_override is None


def test_handle_personality_command_list(_store) -> None:
    """Spec test #4 — `/personality` and `/personality list` return registry."""
    thread_id = _make_thread(_store)

    for cmd in ("/personality", "/personality list"):
        result = handle_personality_command(
            cmd, thread_id=thread_id, store=_store,
        )
        assert result["applied"] is None
        assert "Available personalities" in result["system_reply"]
        assert set(result["available"]) == {
            "casual", "concise", "expert", "formal", "socratic",
        }
    # State unchanged.
    assert _store.get_thread(thread_id).personality_override is None


def test_handle_personality_command_unknown(_store) -> None:
    """Spec test #5 — `/personality wibble` returns error + available list."""
    thread_id = _make_thread(_store)

    result = handle_personality_command(
        "/personality wibble", thread_id=thread_id, store=_store,
    )
    assert result["applied"] is None
    assert "Unknown personality" in result["system_reply"]
    assert "wibble" in result["system_reply"]
    # State unchanged.
    assert _store.get_thread(thread_id).personality_override is None


# ----------- store-level: set_personality_override persists -----------

def test_set_personality_override_persists_across_reopens(tmp_path) -> None:
    """Spec test #12 — direct store call; reopen store; verify column."""
    db_path = tmp_path / "threads.db"
    store = ChatThreadStore(db_path)
    thread_id = _make_thread(store)
    store.set_personality_override(thread_id, override="custom register")

    # Reopen — separate SQLite connection.
    store2 = ChatThreadStore(db_path)
    thread = store2.get_thread(thread_id)
    assert thread is not None
    assert thread.personality_override == "custom register"

    # Clear via None.
    store2.set_personality_override(thread_id, override=None)
    assert store2.get_thread(thread_id).personality_override is None


# ----------- agent_chat: /personality short-circuits the agent turn -----------

_CREW_PATCH = patch("probos.routers.agents.is_crew_agent", return_value=True)


def _make_runtime(*, tmp_path):
    """Mock runtime configured for AD-809 chat-handler tests."""
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
    return r


@pytest.mark.asyncio
async def test_agent_chat_personality_slash_command_does_not_dispatch_intent(tmp_path) -> None:
    """Spec test #6 — POST /api/agent/{id}/chat with /personality short-circuits."""
    from probos.routers.agents import agent_chat

    runtime = _make_runtime(tmp_path=tmp_path)

    # Pre-create thread so /personality has a target.
    thread = runtime.chat_thread_store.get_or_create_default_for_agent(
        "test-agent", "Ezri",
    )

    with _CREW_PATCH:
        result = await agent_chat(
            "test-agent", _req("/personality formal"), runtime,
        )

    # IntentBus.send must NOT be called — early-return short-circuits.
    runtime.intent_bus.send.assert_not_called()

    assert result["system"] is True
    assert result["thread_id"] == thread.id
    assert "formal" in result["response"].lower()
    assert result["applied"] == "formal"

    # Override persisted.
    updated = runtime.chat_thread_store.get_thread(thread.id)
    assert updated.personality_override is not None
    assert "formal register" in updated.personality_override

    # Both captain command + system reply logged.
    msgs = runtime.chat_thread_store.list_messages(thread.id)
    assert len(msgs) == 2
    assert msgs[0].role == "captain"
    assert msgs[0].body == "/personality formal"
    assert msgs[1].role == "system"
    assert "formal" in msgs[1].body.lower()


# ----------- personality overlay flows into the system prompt -----------

def test_personality_overlay_appended_to_composed_via_inspect() -> None:
    """Spec test #10 — verify the consumption site in cognitive_agent.py.

    Source-level check (matches BF-289 / AD-791a pattern): the
    decide() body must (a) read observation["thread_id"], (b) call
    resolve_personality(), and (c) append the result to ``composed``
    before LLMRequest construction.
    """
    from probos.cognitive import cognitive_agent

    src = inspect.getsource(cognitive_agent)
    # The AD-809 overlay block appears in decide().
    assert "resolve_personality" in src, (
        "AD-809: decide() must call resolve_personality(thread, default='')."
    )
    assert "_ad809_thread_id" in src, (
        "AD-809: decide() must read thread_id from observation."
    )
    assert "AD-809" in src and "composed" in src, (
        "AD-809: overlay must append to the composed system-prompt string."
    )
    # The perceive() change populates thread_id on the observation.
    assert "\"thread_id\": getattr(intent" in src, (
        "AD-809: perceive() must lift IntentMessage.thread_id onto observation."
    )


def test_personality_overlay_text_resolves_from_store(tmp_path) -> None:
    """End-to-end: setting personality on a thread + calling
    resolve_personality returns the override text. This is the wire
    that decide() consumes — exercising it directly is the cleanest
    cross-check that the substrate + naming helper agree.
    """
    from probos.threads.naming import resolve_personality

    store = ChatThreadStore(tmp_path / "threads.db")
    thread_id = _make_thread(store)
    store.set_personality_override(thread_id, override="be concise")

    thread = store.get_thread(thread_id)
    overlay = resolve_personality(thread, default="")
    assert overlay == "be concise"

    # Default applies when no override is set.
    store.set_personality_override(thread_id, override=None)
    thread2 = store.get_thread(thread_id)
    assert resolve_personality(thread2, default="") == ""
    assert resolve_personality(thread2, default="base") == "base"
