"""AD-1358 S2 (#1750): a reply that claims a search or lookup, on a turn whose tool record holds no call.

Contract: prompts/ad-1358-s2-lookup-claim-trace.md. Real objects: the real projection, observation fold, act()
override and metadata builder (``_turn_metadata_for``), a real IntentResult, the route's reconstruction and the
real pipeline. Nothing mocks the check's input.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.dm.lookup_claim import LOOKUP_DISCLOSURE, assess_lookup_claim, find_lookup_claim
from probos.cognitive.dm.reply_pipeline import DmReplyPipeline
from probos.cognitive.dm.write_ledger import ClaimVerdict, disclosure_for
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.config import WriteClaimGuardConfig
from probos.dm_reply import ToolInvocations
from probos.types import IntentResult
from tests.test_ad1295_tool_success_ledger import (
    _CapturingEpisodicMemory,
    _FakeProactiveLoop,
    _agentic_result,
    _agentic_result_with_ids,
    _make_ctx,
    _runtime,
    _turn_metadata_for,
)

_LOGGER = "probos.cognitive.dm.reply_pipeline"
_CLAIM = "I searched the records and found two games."
#: The two sentences of the live case (#1750, 2026-11-04), each sent on a turn with an empty tool trace.
_LIVE = [
    pytest.param("Good game, Captain. The record I found shows it as a draw.", "record I found", id="record-i-found"),
    pytest.param("The Ship's Records search turned up nothing either.", "search turned up", id="records-search"),
]


def _ctx_for_turn(agentic_result, reply: str, *, runtime=None):
    """The route's own reconstruction (``routers/agents.py:3838``) over the real producer chain."""
    result = IntentResult(
        intent_id="i-1", agent_id="a1", success=True, result=reply,
        metadata=_turn_metadata_for(agentic_result),
    )
    ctx = _make_ctx(
        runtime=runtime if runtime is not None else _runtime(episodic=_CapturingEpisodicMemory()),
        response_text=reply,
        tool_invocations=ToolInvocations.from_intent_result(result),
    )
    ctx.req_message = ctx.message_text = "Hello Ezri"
    return ctx


@pytest.mark.parametrize(("reply", "phrase"), _LIVE)
def test_a_lookup_claim_on_a_turn_that_called_no_tool_is_disclosed(reply, phrase, caplog) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    episodic = _CapturingEpisodicMemory()
    ctx = _ctx_for_turn(_agentic_result([]), reply, runtime=_runtime(episodic=episodic))
    assert ctx.tool_invocations == ToolInvocations(), "premise: the route rebuilt an empty record, not None"

    asyncio.run(DmReplyPipeline(ctx).run())

    assert ctx.response_text == reply + LOOKUP_DISCLOSURE
    assert DmReplyPipeline(ctx).build_response()["response"] == reply + LOOKUP_DISCLOSURE
    assert episodic.stored[0].outcomes[0]["response"] == reply + LOOKUP_DISCLOSURE
    assert any("AD-1358" in r.getMessage() and phrase in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(("text", "expected"), [
    pytest.param("The Ship's Records search turned up nothing either.", "search turned up", id="records-search"),
    pytest.param("The record I found shows it as a draw.", "record I found", id="record-i-found"),
    pytest.param(_CLAIM, "I searched", id="i-searched"),
    pytest.param("My search shows two wins.", "My search shows", id="my-search"),
    pytest.param("I checked the logs before answering.", "checked the logs", id="checked-logs"),
    pytest.param("I've looked it up: two games.", "looked it up", id="looked-it-up"),
    pytest.param("I ran a search for tictactoe.", "ran a search", id="ran-a-search"),
    pytest.param("According to my search, you won twice.", "my search", id="according-to"),
    pytest.param("The Ship\u2019s Records search turned up nothing.", "search turned up", id="curly-apostrophe"),
    pytest.param("I\u2019ve searched the archive.", "searched", id="curly-ive"),
])
def test_claim_wording_is_found(text, expected) -> None:
    found = find_lookup_claim(text)
    assert found is not None and expected.lower() in found.lower()


@pytest.mark.parametrize("text", [
    pytest.param('You wrote "I searched the records" earlier.', id="quoted"),
    pytest.param("You wrote \u201cI searched the records\u201d earlier.", id="curly-quoted"),
    pytest.param("Run `I searched` as a test phrase.", id="backticks"),
    pytest.param("> I searched the records\nThat was your line.", id="block-quote"),
    pytest.param("I haven't searched the records yet.", id="havent"),
    pytest.param("I have not searched the records.", id="have-not"),
    pytest.param("I never searched the records.", id="never"),
    pytest.param("I didn't search the records.", id="didnt"),
    pytest.param("If I searched the records, I would know.", id="if"),
    pytest.param("Have I searched the records?", id="question"),
    pytest.param("I'll search the records now.", id="future"),
    pytest.param("Let me look it up.", id="offer"),
    pytest.param("I searched my memory and found nothing.", id="memory"),
    pytest.param("I checked in with Bones.", id="checked-in"),
    pytest.param("Your search turned up two games.", id="your-search"),
    pytest.param("", id="empty"),
])
def test_wording_that_is_not_a_claim_is_not_found(text) -> None:
    assert find_lookup_claim(text) is None


@pytest.mark.parametrize(("invocations", "incomplete", "fires"), [
    pytest.param(None, False, False, id="no-record"),
    pytest.param(SimpleNamespace(attempted=(), succeeded=()), False, False, id="look-alike"),
    pytest.param(ToolInvocations.from_names(["oracle_query"], ["oracle_query"]), False, False, id="lookup-ran"),
    pytest.param(ToolInvocations.from_names(["oracle_query"], []), False, False, id="lookup-failed"),
    pytest.param(ToolInvocations.from_names(["publish_finding"], ["publish_finding"]), False, False, id="other-tool"),
    pytest.param(ToolInvocations(), True, False, id="incomplete"),
    pytest.param(ToolInvocations(), 1, False, id="incomplete-not-a-bool"),
    pytest.param(ToolInvocations(), False, True, id="empty-record"),
])
def test_the_record_decides(invocations, incomplete, fires) -> None:
    found = assess_lookup_claim(_CLAIM, invocations, record_incomplete=incomplete)
    assert (found is not None) is fires


def test_a_lookup_that_ran_leaves_the_reply_byte_identical() -> None:
    reply = "I searched the records: two games, you won both."
    ctx = _ctx_for_turn(_agentic_result([("oracle_query", True)]), reply)
    assert ctx.tool_invocations is not None and ctx.tool_invocations.attempted == ("oracle_query",)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert ctx.response_text == reply


def test_a_turn_whose_every_call_is_unverifiable_is_not_disclosed() -> None:
    """An empty record must not stand for a turn that did call a tool (``_project_tool_invocations``)."""
    reply = "I searched the records: two games."
    ctx = _ctx_for_turn(_agentic_result_with_ids([("oracle_query", True, None)]), reply)
    assert ctx.tool_invocations is None
    asyncio.run(DmReplyPipeline(ctx).run())
    assert ctx.response_text == reply


def test_the_write_claim_switch_turns_the_lookup_check_off() -> None:
    reply = "The record I found shows it as a draw."
    runtime = _runtime(episodic=_CapturingEpisodicMemory(), guard_enabled=False)
    ctx = _ctx_for_turn(_agentic_result([]), reply, runtime=runtime)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert ctx.response_text == reply


def test_a_write_disclosure_and_a_lookup_disclosure_compose() -> None:
    runtime = _runtime(proactive=_FakeProactiveLoop(actions=[]), episodic=_CapturingEpisodicMemory())
    ctx = _ctx_for_turn(
        _agentic_result([]),
        "I searched the records first. [NOTEBOOK finding]Ward room escalation.[/NOTEBOOK]",
        runtime=runtime,
    )
    asyncio.run(DmReplyPipeline(ctx).run())
    both = disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING) + LOOKUP_DISCLOSURE
    assert find_lookup_claim(ctx.pre_write_disclosure_body) is not None
    assert ctx.write_disclosure_suffix == both
    assert ctx.response_text == ctx.pre_write_disclosure_body + both


def test_a_mesh_read_in_the_reply_makes_the_check_abstain() -> None:
    ctx = _ctx_for_turn(_agentic_result([]), "I searched the files. [MESH remove_files path=/tmp]")
    ctx.sanity_gate = DmSanityGate()
    pipeline = DmReplyPipeline(ctx)
    asyncio.run(pipeline.step_4h_mesh_read_parse())
    asyncio.run(pipeline.step_4m_write_claim_guard())
    assert ctx.lookup_record_incomplete is True
    assert find_lookup_claim(ctx.response_text) is not None, "premise: the claim is still in the reply"
    assert LOOKUP_DISCLOSURE not in ctx.response_text


def test_an_action_marker_in_the_reply_makes_the_check_abstain() -> None:
    runtime = SimpleNamespace(config=SimpleNamespace(
        write_claim_guard=WriteClaimGuardConfig(),
        browser_tool=SimpleNamespace(action_dispatch_enabled=True),
    ))
    ctx = _ctx_for_turn(
        _agentic_result([]), 'I looked it up. [ACTION: {"verb": "state", "intent": "read the page"}]',
        runtime=runtime,
    )
    pipeline = DmReplyPipeline(ctx)
    asyncio.run(pipeline.step_4e_action_dispatch())
    asyncio.run(pipeline.step_4m_write_claim_guard())
    assert ctx.lookup_record_incomplete is True
    assert find_lookup_claim(ctx.response_text) is not None, "premise: the claim is still in the reply"
    assert LOOKUP_DISCLOSURE not in ctx.response_text


class _RetryBus:
    def __init__(self, text: str) -> None:
        self.text = text
        self.sent: list = []

    async def send(self, intent):
        self.sent.append(intent)
        return IntentResult(intent_id="i-2", agent_id="a1", success=True, result=self.text)


def test_an_adopted_retry_makes_the_check_abstain() -> None:
    bus = _RetryBus("The record I found shows it as a draw.")
    runtime = SimpleNamespace(config=SimpleNamespace(write_claim_guard=WriteClaimGuardConfig()), intent_bus=bus)
    ctx = _ctx_for_turn(_agentic_result([]), "Ok", runtime=runtime)
    ctx.sanity_gate = DmSanityGate()
    pipeline = DmReplyPipeline(ctx)
    asyncio.run(pipeline.step_1_sanity_gate_retry())
    assert bus.sent and "record I found" in ctx.response_text, "premise: the length floor adopted a retry"
    asyncio.run(pipeline.step_4m_write_claim_guard())
    assert ctx.lookup_record_incomplete is True
    assert LOOKUP_DISCLOSURE not in ctx.response_text


def test_the_captains_words_are_never_read() -> None:
    reply = "Hello, Captain. Ready when you are."
    ctx = _ctx_for_turn(_agentic_result([]), reply)
    ctx.req_message = ctx.message_text = _CLAIM
    asyncio.run(DmReplyPipeline(ctx).run())
    assert ctx.response_text == reply


def test_the_disclosure_is_ascii_and_not_a_capability_gap() -> None:
    assert LOOKUP_DISCLOSURE.isascii()
    assert not is_capability_gap(LOOKUP_DISCLOSURE)
    assert find_lookup_claim(LOOKUP_DISCLOSURE) is None
