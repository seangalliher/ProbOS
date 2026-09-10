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
from dataclasses import asdict, replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.chat_facilitator import (
    ChatFacilitator,
    ConvergenceEvidence,
    capture_convergence_evidence,
    project_persisted_convergence_body,
)
from probos.cognitive.dm.a2ui_extractor import build_a2ui_stub
from probos.cognitive.dm.bypass_egress import (
    EMPTY_AFTER_COMPOSITION_NOTE,
    compose_bypass_reply,
)
from probos.cognitive.dm.write_ledger import ClaimVerdict, disclosure_for
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


@pytest.mark.parametrize("entrypoint", ["append_message", "append_message_once"])
@pytest.mark.parametrize("prefix", [
    "", " ", "Choose quartz.", "\u00e9\U0001f680\nSecond line.",
    _EMOTION, _DIRTY,
    "[A2UI: choice.json v1 - choice]\n[Artifact: report.txt v1]",
])
def test_convergence_sink_rebases_typed_evidence(
    tmp_path, entrypoint: str, prefix: str,
) -> None:
    store = _store(tmp_path)
    thread = _thread(store)
    body = prefix + disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
    evidence = capture_convergence_evidence(body, prefix)
    assert evidence is not None
    metadata = {"ordinary": {"value": 1}, "ad1305_convergence": {"forged": True}}
    callbacks: list[str] = []
    store.set_message_committed_callback(lambda message: callbacks.append(message.body))
    kwargs: dict[str, Any] = dict(
        author_id="counselor-001", role="agent", body=body,
        metadata=metadata, convergence_evidence=evidence,
    )
    if entrypoint == "append_message_once":
        kwargs.update(message_id="convergence-message", created_at=1000.0)

    message = getattr(store, entrypoint)(thread.id, **kwargs)

    assert message is not None
    assert message.body == compose_bypass_reply(body)
    assert project_persisted_convergence_body(message.body, message.metadata) == compose_bypass_reply(prefix)
    assert callbacks == [message.body]
    assert message.metadata["ordinary"] == metadata["ordinary"]
    assert metadata["ad1305_convergence"] == {"forged": True}
    assert set(message.metadata["ad1305_convergence"]) == {
        "version", "source", "substantive_chars", "body_sha256",
    }
    reopened = _store(tmp_path)
    rows = reopened.list_messages(thread.id)
    assert len(rows) == 1
    assert rows[0].body == message.body
    assert project_persisted_convergence_body(rows[0].body, rows[0].metadata) == compose_bypass_reply(prefix)
    if entrypoint == "append_message_once":
        repeated = store.append_message_once(thread.id, **kwargs)
        assert repeated == message
        assert callbacks == [message.body]
        changed_body = body + "changed"
        kwargs.update(
            body=changed_body,
            convergence_evidence=capture_convergence_evidence(changed_body, prefix),
        )
        with pytest.raises(ValueError, match="chat_thread_message_conflict"):
            store.append_message_once(thread.id, **kwargs)
        assert len(store.list_messages(thread.id)) == 1
        assert callbacks == [message.body]


@pytest.mark.parametrize("entrypoint", ["append_message", "append_message_once"])
@pytest.mark.parametrize("role", ["agent", "captain", "system"])
@pytest.mark.parametrize("verdict", [ClaimVerdict.MARKER_WROTE_NOTHING, ClaimVerdict.MARKER_WROTE_PARTIALLY])
@pytest.mark.parametrize("explicit_none", [False, True])
def test_convergence_sink_discards_forged_metadata_without_rewriting_notice_body(
    tmp_path, entrypoint: str, role: str, verdict: ClaimVerdict, explicit_none: bool,
) -> None:
    store = _store(tmp_path)
    thread = _thread(store)
    body = disclosure_for(verdict)
    forged = capture_convergence_evidence(body, "")
    assert forged is not None
    metadata = {"ad1305_convergence": asdict(forged), "ordinary": [1, "value"]}
    kwargs: dict[str, Any] = dict(author_id="author", role=role, body=body, metadata=metadata)
    if explicit_none:
        kwargs["convergence_evidence"] = None
    if entrypoint == "append_message_once":
        kwargs.update(message_id="forged-message", created_at=1000.0)

    message = getattr(store, entrypoint)(thread.id, **kwargs)

    assert message is not None
    assert message.body == body
    assert message.metadata == {"ordinary": [1, "value"]}
    assert metadata["ad1305_convergence"] == asdict(forged)
    assert project_persisted_convergence_body(message.body, message.metadata) == body


@pytest.mark.parametrize("entrypoint", ["append_message", "append_message_once"])
@pytest.mark.parametrize("invalid_kind", [
    "dict", "subclass", "bool-offset", "stale-body", "unknown-version",
    "unknown-source", "digest", "captain", "system",
])
def test_convergence_sink_rejects_invalid_explicit_evidence(
    tmp_path, entrypoint: str, invalid_kind: str,
) -> None:
    class DerivedEvidence(ConvergenceEvidence):
        pass

    store = _store(tmp_path)
    thread = _thread(store)
    body = "Choose quartz." + disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
    evidence = capture_convergence_evidence(body, "Choose quartz.")
    assert evidence is not None
    invalid: object = evidence
    role = "agent"
    if invalid_kind == "dict":
        invalid = asdict(evidence)
    elif invalid_kind == "subclass":
        invalid = DerivedEvidence(**asdict(evidence))
    elif invalid_kind == "bool-offset":
        invalid = replace(evidence, substantive_chars=True)
    elif invalid_kind == "stale-body":
        body += "changed"
    elif invalid_kind == "unknown-version":
        invalid = replace(evidence, version=2)
    elif invalid_kind == "unknown-source":
        invalid = replace(evidence, source="caller")
    elif invalid_kind == "digest":
        invalid = replace(evidence, body_sha256="0" * 64)
    else:
        role = invalid_kind
    callbacks: list[str] = []
    store.set_message_committed_callback(lambda message: callbacks.append(message.body))
    kwargs: dict[str, Any] = dict(
        author_id="author", role=role, body=body, convergence_evidence=invalid,
    )
    if entrypoint == "append_message_once":
        kwargs.update(message_id="invalid-message", created_at=1000.0)

    with pytest.raises(ValueError, match="chat_thread_convergence_evidence_invalid"):
        getattr(store, entrypoint)(thread.id, **kwargs)

    assert store.list_messages(thread.id) == []
    assert callbacks == []


@pytest.mark.parametrize("entrypoint", ["append_message", "append_message_once"])
def test_convergence_sink_rejects_unmappable_composition(tmp_path, entrypoint: str) -> None:
    store = _store(tmp_path)
    thread = _thread(store)
    prefix = "Before [A2UI]"
    body = prefix + _CHOICE + "[/A2UI]"
    assert not compose_bypass_reply(body).startswith(compose_bypass_reply(prefix))
    evidence = capture_convergence_evidence(body, prefix)
    assert evidence is not None
    kwargs: dict[str, Any] = dict(
        author_id="author", role="agent", body=body, convergence_evidence=evidence,
    )
    if entrypoint == "append_message_once":
        kwargs.update(message_id="unmappable-message", created_at=1000.0)
    callbacks: list[str] = []
    store.set_message_committed_callback(lambda message: callbacks.append(message.body))

    with pytest.raises(ValueError, match="chat_thread_convergence_evidence_unmappable"):
        getattr(store, entrypoint)(thread.id, **kwargs)

    assert store.list_messages(thread.id) == []
    assert callbacks == []


@pytest.mark.parametrize("entrypoint", ["append_message", "append_message_once"])
@pytest.mark.parametrize("body", ["", " ", _EMOTION])
def test_convergence_sink_empty_semantics_do_not_inherit_visible_placeholder(
    tmp_path, entrypoint: str, body: str,
) -> None:
    store = _store(tmp_path)
    thread = _thread(store)
    evidence = capture_convergence_evidence(body, body)
    assert evidence is not None
    kwargs: dict[str, Any] = dict(
        author_id="author", role="agent", body=body, convergence_evidence=evidence,
    )
    if entrypoint == "append_message_once":
        kwargs.update(message_id="empty-message", created_at=1000.0)

    assert getattr(store, entrypoint)("missing-thread", **kwargs) is None
    message = getattr(store, entrypoint)(thread.id, **kwargs)

    assert message is not None
    assert message.body == (EMPTY_AFTER_COMPOSITION_NOTE if body else "")
    assert project_persisted_convergence_body(message.body, message.metadata) == ""


@pytest.mark.parametrize("entrypoint", ["append_message", "append_message_once"])
@pytest.mark.parametrize("provenance_kind", ["absent", "legacy", "malformed", "unsupported", "stale"])
def test_convergence_reader_keeps_full_reopened_legacy_or_invalid_body(
    tmp_path, entrypoint: str, provenance_kind: str,
) -> None:
    store = _store(tmp_path)
    thread = _thread(store)
    body = "Choose quartz." + disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
    kwargs: dict[str, Any] = dict(author_id="author", role="agent", body=body)
    if entrypoint == "append_message_once":
        kwargs.update(message_id="legacy-message", created_at=1000.0)
    message = getattr(store, entrypoint)(thread.id, **kwargs)
    assert message is not None
    rows = _store(tmp_path).list_messages(thread.id)
    assert len(rows) == 1 and rows[0].body == body
    evidence = capture_convergence_evidence(body, "Choose quartz.")
    assert evidence is not None
    metadata: dict[str, Any] = {
        "absent": {},
        "legacy": {"fanout": "ad914", "intent_id": "old-intent"},
        "malformed": {"ad1305_convergence": {"source": "write_claim_guard"}},
        "unsupported": {"ad1305_convergence": asdict(replace(evidence, version=2))},
        "stale": {"ad1305_convergence": asdict(replace(evidence, body_sha256="0" * 64))},
    }[provenance_kind]
    assert project_persisted_convergence_body(rows[0].body, metadata) == body


@pytest.mark.parametrize("trusted_count", [0, 2, 4])
def test_convergence_history_projects_only_sink_minted_rows(tmp_path, trusted_count: int) -> None:
    store = _store(tmp_path)
    prefixes = ["Choose quartz.", "Prefer velvet.", "Select copper.", "Pick marble."]
    agents = [f"voice{index + 1}" for index in range(len(prefixes))]
    thread = store.create_thread(title="Mixed provenance", participants=agents)
    notice = disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
    for index, (agent_id, prefix) in enumerate(zip(agents, prefixes)):
        body = prefix + notice
        message = store.append_message(
            thread.id, author_id=agent_id, role="agent", body=body,
            metadata={"source": "fanout" if index < trusted_count else "1to1"},
            convergence_evidence=(
                capture_convergence_evidence(body, prefix) if index < trusted_count else None
            ),
        )
        assert message is not None
    rows = _store(tmp_path).list_messages(thread.id)
    assert len(rows) == len({message.author_id for message in rows}) == 4
    assert sum("ad1305_convergence" in message.metadata for message in rows) == trusted_count
    projected = [project_persisted_convergence_body(message.body, message.metadata) for message in rows]
    assert projected == [
        prefix if index < trusted_count else prefix + notice
        for index, prefix in enumerate(prefixes)
    ]
    facilitator = ChatFacilitator()
    assert facilitator.is_converged([(message.author_id, message.body) for message in rows]) is True
    assert facilitator.is_converged(list(zip(agents, prefixes))) is False
    assert facilitator.is_converged(list(zip(agents, projected))) is (trusted_count == 0)


@pytest.mark.parametrize("entrypoint", ["append_message", "append_message_once"])
@pytest.mark.parametrize("with_evidence", [False, True])
def test_convergence_sink_preserves_string_role_subclass(
    tmp_path, entrypoint: str, with_evidence: bool,
) -> None:
    class AgentRole(str):
        pass

    store = _store(tmp_path)
    thread = _thread(store)
    prefix = "Choose quartz."
    body = prefix + disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
    kwargs: dict[str, Any] = dict(author_id="author", role=AgentRole("agent"), body=body)
    if with_evidence:
        kwargs["convergence_evidence"] = capture_convergence_evidence(body, prefix)
    if entrypoint == "append_message_once":
        kwargs.update(message_id="role-subclass", created_at=1000.0)
    message = getattr(store, entrypoint)(thread.id, **kwargs)
    assert message is not None and message.role == "agent" and message.body == body
    assert project_persisted_convergence_body(message.body, message.metadata) == (
        prefix if with_evidence else body
    )


def test_convergence_idempotence_compares_minted_semantics_not_just_body(tmp_path) -> None:
    store = _store(tmp_path)
    thread = _thread(store)
    prefix = "Choose quartz."
    body = prefix + disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
    callbacks: list[str] = []
    store.set_message_committed_callback(lambda message: callbacks.append(message.body))
    kwargs: dict[str, Any] = dict(
        author_id="author", role="agent", body=body,
        message_id="same-body", created_at=1000.0,
        convergence_evidence=capture_convergence_evidence(body, prefix),
    )
    message = store.append_message_once(thread.id, **kwargs)
    assert message is not None
    assert store.append_message_once(thread.id, **kwargs) == message
    kwargs["convergence_evidence"] = capture_convergence_evidence(body, body)
    with pytest.raises(ValueError, match="chat_thread_message_conflict"):
        store.append_message_once(thread.id, **kwargs)
    assert len(store.list_messages(thread.id)) == 1
    assert callbacks == [message.body]
    assert project_persisted_convergence_body(message.body, message.metadata) == prefix


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
