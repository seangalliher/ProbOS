"""AD-1248 slice A gaps: the paths that bypass the reply pipeline.

Sinks 21-24 plus directed federation carriage. These are the Captain-visible
surfaces the first slice A landing left concealing -- and the promoted path is
where tool failures CONCENTRATE, because a promoted turn is by definition the
long one that burned through its tools.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.cognitive.dm.reply_value import (
    DM_REPLY_METADATA_KEY,
    DmReply,
    ToolFailures,
    call_signature,
    failure_key,
)
from probos.types import IntentResult

ROOT = "aaaaaaaaaaaa"


def _failures(name: str = "web_search") -> ToolFailures:
    return ToolFailures.from_mapping(
        {failure_key(ROOT, ROOT, call_signature(name, None)): name}
    )


class _RecordingStore:
    def __init__(self) -> None:
        self.appended: list[dict] = []

    def append_message(self, thread_id, *, author_id, role, body, metadata=None):
        # Mirrors the real store's exact-type validation, which a str subclass
        # fails -- the trap that silently lost a reply in the first landing.
        if type(body) is not str:
            raise ValueError("chat_thread_message_invalid")
        self.appended.append({"thread_id": thread_id, "body": body, "role": role})


# ── sinks 22-23: promoted completion ────────────────────────────────────────


def test_a_promoted_report_discloses_a_failed_tool() -> None:
    from probos.cognitive.turn_promotion import _post_report

    store = _RecordingStore()
    _post_report(
        runtime=SimpleNamespace(chat_thread_store=store),
        agent_id="ezri",
        thread_id="t-1",
        work_item_id="w-1",
        body="I finished the research.",
        tool_failures=_failures(),
    )
    assert "web_search" in store.appended[0]["body"]


def test_a_promoted_report_without_failures_is_byte_identical() -> None:
    from probos.cognitive.turn_promotion import _post_report

    store = _RecordingStore()
    _post_report(
        runtime=SimpleNamespace(chat_thread_store=store),
        agent_id="ezri", thread_id="t-1", work_item_id="w-1",
        body="All clear, Captain.",
    )
    assert store.appended[0]["body"] == "All clear, Captain."


def test_the_promoted_report_body_is_a_plain_str() -> None:
    """The render token is a str SUBCLASS and the store validates with
    ``type(body) is not str``. _RecordingStore reproduces that check."""
    from probos.cognitive.turn_promotion import _post_report

    store = _RecordingStore()
    _post_report(
        runtime=SimpleNamespace(chat_thread_store=store),
        agent_id="ezri", thread_id="t-1", work_item_id="w-1",
        body="done", tool_failures=_failures(),
    )
    assert type(store.appended[0]["body"]) is str


@pytest.mark.asyncio
async def test_the_promoted_finisher_consults_the_failures_probe() -> None:
    """The awaited task returns a plain string, so the failures cannot be
    recovered at report time -- the probe is the only route, exactly as BF-704's
    completed_probe is for the stop reason."""
    import asyncio

    from probos.cognitive.turn_promotion import _finish_promoted_turn

    store = _RecordingStore()
    runtime = SimpleNamespace(chat_thread_store=store, work_item_store=None)

    async def _work() -> str:
        return "Here is the summary."

    await _finish_promoted_turn(
        asyncio.ensure_future(_work()),
        runtime=runtime,
        agent_id="ezri",
        thread_id="t-1",
        work_item_id="w-1",
        failures_probe=lambda: _failures(),
    )
    assert "web_search" in store.appended[0]["body"]


@pytest.mark.asyncio
async def test_a_raising_failures_probe_still_delivers_the_report() -> None:
    """Losing the disclosure is bad; losing the whole report is worse."""
    import asyncio

    from probos.cognitive.turn_promotion import _finish_promoted_turn

    store = _RecordingStore()
    runtime = SimpleNamespace(chat_thread_store=store, work_item_store=None)

    async def _work() -> str:
        return "Summary."

    def _boom():
        raise RuntimeError("probe exploded")

    await _finish_promoted_turn(
        asyncio.ensure_future(_work()),
        runtime=runtime, agent_id="ezri", thread_id="t-1", work_item_id="w-1",
        failures_probe=_boom,
    )
    assert store.appended[0]["body"] == "Summary."


@pytest.mark.asyncio
async def test_the_slot_holder_forwards_the_probe_on_every_branch() -> None:
    """``_report_holding_slot`` forwards to the finisher through THREE branches
    (no slot factory, factory raised, slot acquired). Dropping the probe on any
    one of them conceals on exactly the configuration that uses it."""
    import asyncio
    import contextlib

    from probos.cognitive.turn_promotion import _report_holding_slot

    @contextlib.asynccontextmanager
    async def _slot():
        yield

    for label, factory in (
        ("no factory", None),
        ("factory raises", lambda: (_ for _ in ()).throw(RuntimeError("no slot"))),
        ("slot acquired", _slot),
    ):
        store = _RecordingStore()
        runtime = SimpleNamespace(chat_thread_store=store, work_item_store=None)

        async def _work() -> str:
            return "Summary."

        await _report_holding_slot(
            asyncio.ensure_future(_work()),
            runtime=runtime,
            agent_id="ezri",
            thread_id="t-1",
            work_item_id="w-1",
            failures_probe=lambda: _failures(),
            background_slot=factory,
        )
        assert "web_search" in store.appended[0]["body"], label


def test_the_agent_passes_a_probe_read_at_report_time() -> None:
    """Past the boundary: the probe must be a CLOSURE over the observation, not
    a snapshot -- the promoted run keeps accumulating passes after the
    acknowledgement is returned."""
    import inspect

    from probos.cognitive import cognitive_agent as ca

    source = inspect.getsource(ca.CognitiveAgent._maybe_run_conversational_agentic)
    assert 'failures_probe=lambda: observation.get("_dm_tool_failures")' in source


# ── sink 24: deferred replay ────────────────────────────────────────────────


def test_deferred_replay_composes_the_disclosure() -> None:
    """AD-1230 deferred replay bypasses the reply pipeline entirely, so it
    composes from what the result carries."""
    result = IntentResult(
        intent_id="i", agent_id="ezri", success=True, result="Answering now.",
        metadata={DM_REPLY_METADATA_KEY: _failures().to_wire()},
    )
    rendered = str(DmReply.from_intent_result(result).render())
    assert rendered.startswith("Answering now.")
    assert "web_search" in rendered


def test_the_deferred_dispatch_renders_rather_than_stringifying() -> None:
    import inspect

    from probos.startup import finalize

    source = inspect.getsource(finalize)
    assert "DmReply.from_intent_result(result).render()" in source, (
        "deferred replay must compose the disclosure, not str() the raw result"
    )


# ── sink 21: work-item dispatch ─────────────────────────────────────────────


def test_the_dispatch_sink_composes_from_the_failures_sink() -> None:
    import inspect

    from probos.cognitive import cognitive_agent as ca

    source = inspect.getsource(ca.CognitiveAgent._handle_work_item_dispatch)
    assert "failures_sink=_dispatch_failures" in source
    assert "_body = str(_composed.render())" in source
    assert "body=_body," in source


def test_the_dispatch_scope_is_the_work_item_id() -> None:
    """This path never calls perceive(), so it has no cognitive correlation id
    and would otherwise mint a fresh scope on every pass."""
    import inspect

    from probos.cognitive import cognitive_agent as ca

    source = inspect.getsource(ca.CognitiveAgent._run_agentic_dispatch)
    assert 'failure_scope=str(work_item_id or "")' in source


# ── directed federation carriage (not a sink: a transport hop) ──────────────


@pytest.mark.asyncio
async def test_a_malformed_probe_return_still_delivers_the_report(caplog) -> None:
    """The probe is typed ``Any`` and comes from a caller. A wrong shape must
    not raise inside a DETACHED reporter whose contract is 'never raises apart
    from cancellation' -- that would cost the Captain the report AND leave the
    work item unclosed.

    The composition ``try`` would already degrade honestly, but it degrades with
    a generic traceback. The type check exists so the log NAMES the wrong shape,
    which is the difference between a diagnosable defect and a mystery.
    """
    import asyncio

    from probos.cognitive.turn_promotion import _finish_promoted_turn

    store = _RecordingStore()
    runtime = SimpleNamespace(chat_thread_store=store, work_item_store=None)

    async def _work() -> str:
        return "Summary."

    with caplog.at_level("WARNING"):
        await _finish_promoted_turn(
            asyncio.ensure_future(_work()),
            runtime=runtime, agent_id="ezri", thread_id="t-1", work_item_id="w-1",
            failures_probe=lambda: {"not": "a ToolFailures"},
        )

    assert store.appended[0]["body"] == "Summary."
    assert any(
        "returned dict, not ToolFailures" in r.getMessage() for r in caplog.records
    ), "the log must name the wrong shape, not just report a generic failure"


def test_the_artifact_and_the_transcript_tell_the_same_story() -> None:
    """Sink 23. ``_post_report`` composes; the outcome artifact previously got
    the RAW body, so a promoted run's stored evidence disagreed with its own
    transcript about whether a tool failed. Render once per route, reuse."""
    from probos.cognitive.turn_promotion import _post_report

    store = _RecordingStore()
    reported = _post_report(
        runtime=SimpleNamespace(chat_thread_store=store),
        agent_id="ezri", thread_id="t-1", work_item_id="w-1",
        body="I finished the research.",
        tool_failures=_failures(),
    )
    assert reported == store.appended[0]["body"]
    assert "web_search" in reported
    assert type(reported) is str


def test_the_finisher_feeds_the_composed_text_to_the_episode() -> None:
    import inspect

    from probos.cognitive import turn_promotion

    source = inspect.getsource(turn_promotion._finish_promoted_turn)
    assert "reported = _post_report(" in source
    assert "body=reported," in source, (
        "the episode/artifact must receive the COMPOSED text, not the raw body"
    )


def test_a_report_with_no_store_still_returns_the_composed_text() -> None:
    from probos.cognitive.turn_promotion import _post_report

    reported = _post_report(
        runtime=SimpleNamespace(chat_thread_store=None),
        agent_id="ezri", thread_id="t-1", work_item_id="w-1",
        body="body", tool_failures=_failures(),
    )
    assert "web_search" in reported


# ── empty bodies: the disclosure is the only truthful content ───────────────


def test_a_failures_only_reply_is_not_discarded_by_the_dispatch_sink() -> None:
    import inspect

    from probos.cognitive import cognitive_agent as ca

    source = inspect.getsource(ca.CognitiveAgent._handle_work_item_dispatch)
    assert "and _body:" in source, (
        "the sink must gate on the COMPOSED text; gating on the raw body drops "
        "a run whose only truthful content is the disclosure"
    )
    assert 'result=_body or reply_text or "[NO_RESPONSE]"' in source


def test_a_failures_only_deferred_reply_is_not_discarded() -> None:
    import inspect

    from probos.startup import finalize

    source = inspect.getsource(finalize)
    assert "if result is not None:\n" in source, (
        "deferred replay must compose before testing emptiness"
    )


def test_an_empty_body_with_failures_still_renders_something() -> None:
    """The premise of both gates above."""
    rendered = DmReply(body="", tool_failures=_failures()).render()
    assert "web_search" in rendered


# ── directed federation carriage — LANDED, BF-799 ───────────────────────────
#
# Directed federation is a TRANSPORT HOP, not a sink: the origin reconstructs an
# IntentResult and a LOCAL sink displays it, so the payload rides across rather
# than being rendered remotely.
#
# The two blockers that deferred this in slice A are both resolved:
#   * the layer violation went away when BF-801 moved the value to the
#     foundation module, so federation/ imports probos.dm_reply (a documented
#     FOUNDATION_MODULE) and nothing from cognitive/. The issue's suggestion of
#     moving the key to types.py is therefore unnecessary — and would not work,
#     because dm_reply.py is asserted stdlib-only and so cannot import types.
#   * the AD-1123 frozen AST hash for forward_direct_message was rewritten
#     deliberately, with the previous hash and the reason recorded beside it.
#
# The round-trip test below is the one that mattered: adding the payload to the
# serializer and the accepted key set was NOT enough, because the detacher
# rebuilds the record key by key. The full two-bridge crossing lives in
# tests/test_bf799_federation_carriage.py.


def test_a_metadata_bearing_record_survives_the_full_round_trip() -> None:
    """serialize -> detach -> reconstruct, in ONE test.

    BF-799 has LANDED, so the strict xfail that guarded this gap is gone. The
    reverted implementation proved this is the test that matters: adding the
    payload to the serializer and the accepted key set was NOT enough, because
    ``_detach_serialized_directed_result`` rebuilds the record key by key and
    silently dropped anything unlisted. Two end tests both passed while the hop
    stayed dead.

    The full two-bridge crossing lives in ``test_bf799_federation_carriage.py``;
    this stays as the unit-level guard on the three module-level transforms.
    """
    from probos.federation.bridge import (
        _detach_serialized_directed_result,
        _serialize_directed_result,
    )

    origin = IntentResult(
        intent_id="i", agent_id="ezri", success=True, result="text",
        metadata={DM_REPLY_METADATA_KEY: _failures().to_wire()},
    )
    wire = _serialize_directed_result(origin)
    detached, error = _detach_serialized_directed_result(wire, malformed_error="bad")
    assert error is None and detached is not None

    reconstructed = IntentResult(
        intent_id="i", agent_id="ezri", success=True,
        result=detached["result"],
        metadata={DM_REPLY_METADATA_KEY: detached[DM_REPLY_METADATA_KEY]},
    )
    assert DmReply.from_intent_result(reconstructed).tool_failures.names() == (
        "web_search",
    )


def test_a_clean_turn_serialises_byte_identically_for_older_peers() -> None:
    """Holds today and must keep holding after BF-799: the payload is emitted
    only when non-empty, so a peer on an older build sees no change."""
    from probos.federation.bridge import _DIRECTED_RESULT_KEYS, _serialize_directed_result

    result = IntentResult(intent_id="i", agent_id="ezri", success=True, result="text")
    assert set(_serialize_directed_result(result)) == set(_DIRECTED_RESULT_KEYS)
