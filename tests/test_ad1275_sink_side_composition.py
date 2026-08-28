"""AD-1275 (BF-806, #1270): composition belongs to the agent-role sink.

Model-authored bodies were reaching stored, Captain-visible transcript rows with
the ``<intent emotion=NAME>`` self-tag and ``[A2UI]{json}[/A2UI]`` markers
intact, because only two of eleven writer modules called
``compose_bypass_reply``. Per-path fixing had already failed three times
(BF-702, BF-791, BF-792), so the composition moved to the one place every row
passes through: ``ChatThreadStore.append_message_once``, the sole
``INSERT INTO chat_thread_messages`` in the tree.

The discriminator is ``role``, which is a required, closed-set, sink-validated
argument -- so the store reads the author's role and never sniffs the body. That
is what makes the rule safe rather than clever, and T2/T3 are the tests that
hold it there: marker-shaped text on a ``captain`` or ``system`` row is stored
byte-identically, because a marker-shaped string is not evidence of provenance.

One row cannot be reached that way and is composed at its producer instead:
``cognitive_agent`` posts a work-item title/description -- which agents author --
as ``role="captain"``. T12 pins it.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.dm.a2ui_extractor import build_a2ui_stub
from probos.cognitive.dm.bypass_egress import (
    EMPTY_AFTER_COMPOSITION_NOTE,
    compose_bypass_reply,
)
from probos.threads import ChatThreadStore
from probos.types import AgentMeta, AgentState, IntentMessage, IntentResult

_EMOTION = "<intent emotion=warm>"
_CHOICE = json.dumps({
    "kind": "choice",
    "prompt": "Which deploy target?",
    "options": ["staging", "production"],
})


def _a2ui(body: str) -> str:
    return f"[A2UI]{body}[/A2UI]"


#: Both markers on one body -- the shape #1270 measured reaching the transcript.
_DIRTY = f"Deploy is ready. {_EMOTION}\n" + _a2ui(_CHOICE)


def _store(tmp_path) -> ChatThreadStore:
    return ChatThreadStore(tmp_path / "threads.db")


def _thread(store: ChatThreadStore, agent_id: str = "counselor-001") -> Any:
    return store.get_or_create_default_for_agent(agent_id, "Ezri")


def _markers_present(text: str) -> bool:
    return _EMOTION in text and "[A2UI]" in text.upper()


# ── the sink ────────────────────────────────────────────────────────────────


def test_an_agent_row_is_composed(tmp_path) -> None:
    """T4: the rule itself, at the entry point most producers use."""
    store = _store(tmp_path)
    thread = _thread(store)

    assert _markers_present(_DIRTY), "fixture carries neither marker"

    store.append_message(
        thread.id, author_id="counselor-001", role="agent", body=_DIRTY
    )

    stored = store.list_messages(thread.id)[-1].body
    assert _EMOTION not in stored
    assert "[A2UI]" not in stored.upper()
    assert "Deploy is ready." in stored
    assert "Which deploy target?" in stored


def test_a_captain_row_is_stored_byte_identical(tmp_path) -> None:
    """T2: the corruption guard, and the reason the rule keys on role.

    If the Captain literally types ``[A2UI]{...}[/A2UI]`` or an emotion tag, it
    is his text and it is stored verbatim. A marker-shaped string is not
    evidence of provenance; the sink reads the role and never sniffs the body.
    """
    store = _store(tmp_path)
    thread = _thread(store)

    store.append_message(
        thread.id, author_id="captain", role="captain", body=_DIRTY
    )

    assert store.list_messages(thread.id)[-1].body == _DIRTY


def test_a_system_row_is_stored_byte_identical(tmp_path) -> None:
    """T3: exactly one role is composed, so system rows pass through too."""
    store = _store(tmp_path)
    thread = _thread(store)

    store.append_message(
        thread.id, author_id="system", role="system", body=_DIRTY
    )

    assert store.list_messages(thread.id)[-1].body == _DIRTY


def test_an_agent_row_of_only_markers_gets_the_note_not_a_blank(
    tmp_path, caplog
) -> None:
    """T5: the empty-after-composition policy.

    A blank bubble is not an acceptable outcome, and returning ``None`` is
    worse -- ``crew_executor`` reads that as a missing thread and reports a
    false error.
    """
    store = _store(tmp_path)
    thread = _thread(store)
    # A body that composes to nothing. NOT an unparseable [A2UI] block -- that
    # is replaced by UNRENDERABLE_NOTE and never reaches this branch.
    only_markers = f"  {_EMOTION}  "

    assert compose_bypass_reply(only_markers) == "", "fixture is not marker-only"

    with caplog.at_level(logging.WARNING, logger="probos.threads"):
        store.append_message(
            thread.id, author_id="counselor-001", role="agent", body=only_markers
        )

    assert store.list_messages(thread.id)[-1].body == EMPTY_AFTER_COMPOSITION_NOTE
    assert any("AD-1275" in r.getMessage() for r in caplog.records)


def test_an_already_empty_agent_body_is_not_substituted(tmp_path) -> None:
    """T6: the carve-out the row above could otherwise absorb.

    An empty body is the caller's own choice, not a body that composition
    consumed, so it stays byte-identical.
    """
    store = _store(tmp_path)
    thread = _thread(store)

    store.append_message(thread.id, author_id="counselor-001", role="agent", body="")

    assert store.list_messages(thread.id)[-1].body == ""


def test_the_a2ui_stub_survives_the_sink_byte_identical(tmp_path) -> None:
    """T7: the shipped interactive widget is not damaged.

    ``replace_a2ui_with_stubs`` leaves ``[A2UI: name vN - kind]``, which the HXI
    renders as a widget; ``_MARKER_PROBE`` requires the literal ``[A2UI]``. The
    raw-block half is the premise check -- without it, a probe where BOTH came
    back unchanged would read as a pass while proving nothing.
    """
    store = _store(tmp_path)
    thread = _thread(store)
    stub_body = f"Pick one.\n{build_a2ui_stub('a2ui-choice-1.json', 1, 'choice')}"

    store.append_message(
        thread.id, author_id="counselor-001", role="agent", body=stub_body
    )
    store.append_message(
        thread.id, author_id="counselor-001", role="agent", body="Raw: " + _a2ui(_CHOICE)
    )

    stored_stub, stored_raw = (m.body for m in store.list_messages(thread.id)[-2:])
    assert stored_stub == stub_body
    assert stored_raw != "Raw: " + _a2ui(_CHOICE)
    assert "[A2UI]" not in stored_raw.upper()


def test_append_message_once_stays_idempotent_under_composition(tmp_path) -> None:
    """T8: pins the ordering constraint in A1.

    Composition has to land BEFORE the ``current.body == body`` comparison, or
    a re-offer of the same message compares a composed row against a raw
    argument and raises ``chat_thread_message_conflict``.
    """
    store = _store(tmp_path)
    thread = _thread(store)
    kwargs = dict(
        message_id="msg-ad1275",
        author_id="counselor-001",
        role="agent",
        body=_DIRTY,
        created_at=1000.0,
    )

    first = store.append_message_once(thread.id, **kwargs)
    second = store.append_message_once(thread.id, **kwargs)

    assert first is not None and second is not None
    assert second.id == first.id
    assert second.body == first.body
    assert _EMOTION not in second.body
    assert len(store.list_messages(thread.id)) == 1


def test_the_crew_child_result_row_is_composed(tmp_path) -> None:
    """T9: the other entry point. ``crew_executor`` calls ``_once`` directly."""
    from probos.cognitive.crew_executor import CrewTaskExecutor

    store = _store(tmp_path)
    thread = _thread(store)
    executor = SimpleNamespace(
        _runtime=SimpleNamespace(chat_thread_store=store),
    )

    CrewTaskExecutor._append_crew_session_child_result(
        executor,
        parent_id="wi-parent",
        child=SimpleNamespace(id="wi-child", assigned_to="counselor-001"),
        thread_id=thread.id,
        output=_DIRTY,
        content_hash="a" * 64,
        finished_at=1000.0,
    )

    messages = store.list_messages(thread.id)
    assert len(messages) == 1, "the crew path stored nothing -- it degraded"
    assert _EMOTION not in messages[0].body
    assert "[A2UI]" not in messages[0].body.upper()


def test_the_live_refresh_callback_sees_the_composed_body(tmp_path) -> None:
    """T10: the HXI reads the same object the store inserted."""
    store = _store(tmp_path)
    thread = _thread(store)
    seen: list[str] = []
    store.set_message_committed_callback(lambda m: seen.append(m.body))

    store.append_message(
        thread.id, author_id="counselor-001", role="agent", body=_DIRTY
    )

    assert seen, "the commit callback never fired"
    assert _EMOTION not in seen[0]
    assert "[A2UI]" not in seen[0].upper()


def test_a_non_str_body_still_raises_before_composition(tmp_path) -> None:
    """T11: composition did not move ahead of the type validation."""
    store = _store(tmp_path)
    thread = _thread(store)

    with pytest.raises(ValueError, match="chat_thread_message_invalid"):
        store.append_message(
            thread.id, author_id="counselor-001", role="agent", body=b"x"  # type: ignore[arg-type]
        )


# ── producer -> stored body, across the seam (#1270's acceptance) ────────────


def _make_agent(runtime: Any) -> Any:
    """Minimal real ``CognitiveAgent``; mirrors ``tests/test_ad839_...``."""
    from probos.cognitive.cognitive_agent import _DECISION_CACHES, CognitiveAgent

    _DECISION_CACHES.pop("counselor", None)

    class _TestCognitiveAgent(CognitiveAgent):
        _handled_intents = {"test_intent"}

    agent = object.__new__(_TestCognitiveAgent)
    agent.instructions = "Test instructions."
    agent.agent_type = "counselor"
    agent.id = "counselor-001"
    agent.callsign = "Ezri"
    agent.confidence = 0.5
    agent.meta = AgentMeta()
    agent.state = AgentState.ACTIVE
    agent.trust_score = 0.5
    agent._llm_client = AsyncMock()
    agent._runtime = runtime
    agent._skills = {}
    agent._strategy_advisor = None
    agent._last_fallback_info = None
    return agent


def _dispatch_runtime(store: ChatThreadStore) -> Any:
    rt = MagicMock()
    rt.chat_thread_store = store
    rt.work_item_store = None
    # AD-856 gate off -> the single-shot direct-message fallback runs.
    rt.config.agentic_dispatch.enabled = False
    return rt


def _dispatch_intent(title: str, description: str) -> IntentMessage:
    return IntentMessage(
        intent="work_item_dispatched",
        params={
            "work_item_id": "wi-1",
            "title": title,
            "description": description,
        },
        target_agent_id="counselor-001",
    )


@pytest.mark.asyncio
async def test_the_work_item_acknowledgement_reaches_the_store_clean(
    tmp_path,
) -> None:
    """T1: #1270's acceptance criterion, and it crosses the whole seam.

    Real ``_handle_work_item_dispatch``, real ``ChatThreadStore`` on tmp_path,
    row read back with ``list_messages``. A test that asserts the producer
    called the composer, plus a separate test that the composer strips markers,
    is half-chain evidence -- every link correct and the chain dead -- which is
    this repo's most common defect shape.
    """
    from probos.dm_reply import DmReply

    store = _store(tmp_path)
    # Idempotent: the producer's own get_or_create returns this same thread.
    thread = _thread(store)
    agent = _make_agent(_dispatch_runtime(store))
    llm_output = f"On it, Captain. {_EMOTION}\n" + _a2ui(_CHOICE)
    result = IntentResult(
        intent_id="dm",
        agent_id=agent.id,
        success=True,
        result=llm_output,
        confidence=0.5,
    )
    agent.handle_intent = AsyncMock(return_value=result)

    # Premise: the body this producer builds DOES carry both markers, built the
    # same two ways production builds it. Without this, a marker-free fixture
    # would satisfy the strip assertion below while proving nothing.
    raw_body = str(DmReply.from_intent_result(result).render())
    assert _markers_present(raw_body), "the unfixed producer body is already clean"
    assert compose_bypass_reply(raw_body) != raw_body

    await agent._handle_work_item_dispatch(
        _dispatch_intent("Summarize crew morale", "Review the recent logs.")
    )

    agent_rows = [
        m for m in store.list_messages(thread.id) if m.role == "agent"
    ]
    assert agent_rows, "the acknowledgement never reached the store"
    stored = agent_rows[-1].body
    assert _EMOTION not in stored
    assert "[A2UI]" not in stored.upper()
    assert "On it, Captain." in stored
    assert "Which deploy target?" in stored


@pytest.mark.asyncio
async def test_the_dispatch_task_message_is_composed_at_the_producer(
    tmp_path,
) -> None:
    """T12: the one producer-side obligation, and why it cannot be the sink's.

    ``title``/``description`` come from the work item, and agents create work
    items -- so this body is model-reachable while wearing ``role="captain"``.
    The sink cannot distinguish it from a message the Captain typed (T2 is the
    test that requires the sink to leave such rows alone), so the producer owes
    the composition.
    """
    store = _store(tmp_path)
    thread = _thread(store)
    agent = _make_agent(_dispatch_runtime(store))
    agent.handle_intent = AsyncMock(return_value=None)
    dirty_description = f"Review the logs. {_EMOTION}\n" + _a2ui(_CHOICE)

    assert _markers_present(dirty_description), "fixture carries neither marker"

    await agent._handle_work_item_dispatch(
        _dispatch_intent("Summarize crew morale", dirty_description)
    )

    captain_rows = [
        m for m in store.list_messages(thread.id) if m.role == "captain"
    ]
    assert captain_rows, "the task message never reached the store"
    stored = captain_rows[-1].body
    assert _EMOTION not in stored
    assert "[A2UI]" not in stored.upper()
    assert "Summarize crew morale" in stored
    assert "Which deploy target?" in stored


@pytest.mark.asyncio
async def test_the_producer_composes_captain_authored_work_items_too(
    tmp_path,
) -> None:
    """T14: the scope this AD does NOT protect, pinned so the claim stays honest.

    Review measured it: the Captain can create work items too
    (``routers/workforce.py`` -> ``work_item_router``), and ``title`` and
    ``description`` reach here identically whoever authored them. So marker-
    shaped text a Captain typed INTO A WORK ITEM is composed, and only Captain
    CHAT input is byte-identical -- that is T2's job, and the sink never touches
    those rows.

    Distinguishing the two needs work-item provenance that does not exist yet.
    This test exists so the limitation is a recorded decision rather than an
    unnoticed overclaim: if provenance ever lands, this is the test that should
    fail and be rewritten.
    """
    store = _store(tmp_path)
    thread = _thread(store)
    agent = _make_agent(_dispatch_runtime(store))
    agent.handle_intent = AsyncMock(return_value=None)
    captain_typed = f"Ship it. {_EMOTION}"

    # PREMISE: the fixture carries a marker, or the assertion below is vacuous.
    assert _EMOTION in captain_typed

    await agent._handle_work_item_dispatch(
        _dispatch_intent("Captain's own item", captain_typed)
    )

    captain_rows = [
        m for m in store.list_messages(thread.id) if m.role == "captain"
    ]
    assert captain_rows, "the task message never reached the store"
    assert _EMOTION not in captain_rows[-1].body, (
        "the documented scope changed: this path now preserves Captain-typed "
        "work-item text. Update the comment at cognitive_agent.py Slice B."
    )
