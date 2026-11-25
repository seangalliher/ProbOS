"""AD-1358 S2 (#1750), amendment A2: the three findings of review round 1.

Contract: prompts/ad-1358-s2-lookup-claim-trace.md, section 16 (R1-1, R1-2, R1-3). Real objects: the real
projection, the real pass fold, the real metadata builder, a real IntentResult, the route's reconstruction,
the real DmSanityGate and the real pipeline. Only the intent bus is a stand-in.
"""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome, _project_tool_invocations
from probos.cognitive.cognitive_agent import (
    _accumulate_pass_invocations,
    _attach_run_provenance,
    _build_result_metadata,
)
from probos.cognitive.dm.lookup_claim import LOOKUP_DISCLOSURE, _mask_quoted, find_lookup_claim
from probos.cognitive.dm.reply_pipeline import DmReplyPipeline
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.dm_reply import ToolInvocations
from probos.types import IntentResult
from tests.test_ad1295_tool_success_ledger import (
    DISCLOSURE_FRAGMENT,
    FINDING,
    _CapturingEpisodicMemory,
    _OverridingAgent,
    _agentic_result,
    _agentic_result_with_ids,
    _make_ctx,
    _runtime,
)
from tests.test_ad1358_s2_lookup_claim import _ctx_for_turn

_LOGGER = "probos.cognitive.dm.reply_pipeline"
_CLAIM = "I searched the records and found nothing for that."
_FENCE = "`" * 3


# --- R1-1: a dispatched retry, whatever it returns ------------------------------------------------------

#: A claim and an orphaned ``[CHALLENGE`` tag: the real gate keeps the claim and asks for one retry.
_REJECTED = _CLAIM + " [CHALLENGE"
_NO_RESPONSE = object()


class _RetryBus:
    """The one stand-in: answers the retry with ``response``, or raises as a timed-out dispatch does."""

    def __init__(self, response, *, raises: bool = False) -> None:
        self.response = response
        self.raises = raises
        self.sent: list = []

    async def send(self, intent):
        self.sent.append(intent)
        if self.raises:
            raise TimeoutError("the retry timed out; its tools may have run")
        return self.response


def _ctx_with_gate(reply: str, bus: _RetryBus):
    runtime = _runtime(episodic=_CapturingEpisodicMemory())
    runtime.intent_bus = bus
    ctx = _ctx_for_turn(_agentic_result([]), reply, runtime=runtime)
    ctx.sanity_gate = DmSanityGate()
    return ctx


@pytest.mark.parametrize(("answer", "raises"), [
    pytest.param("The record I found shows it as a draw.", False, id="adopted"),
    pytest.param("", False, id="empty-text"),
    pytest.param(None, False, id="none-result"),
    pytest.param(_NO_RESPONSE, False, id="no-response"),
    pytest.param(_NO_RESPONSE, True, id="raised"),
])
def test_a_dispatched_retry_makes_the_check_abstain_whatever_it_returns(answer, raises) -> None:
    response = None if answer is _NO_RESPONSE else IntentResult(
        intent_id="i-2", agent_id="a1", success=True, result=answer,
    )
    bus = _RetryBus(response, raises=raises)
    ctx = _ctx_with_gate(_REJECTED, bus)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert len(bus.sent) == 1, "premise: the gate dispatched one retry"
    assert find_lookup_claim(ctx.pre_write_disclosure_body) is not None, "premise: the reply claims a lookup"
    assert ctx.lookup_record_incomplete is True
    assert ctx.write_disclosure_suffix is None
    assert LOOKUP_DISCLOSURE not in ctx.response_text


def test_a_reply_the_gate_accepts_dispatches_no_retry_and_is_checked() -> None:
    bus = _RetryBus(None)
    ctx = _ctx_with_gate(_CLAIM, bus)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert bus.sent == [], "premise: the gate accepted the reply"
    assert ctx.lookup_record_incomplete is False
    assert ctx.write_disclosure_suffix == LOOKUP_DISCLOSURE
    assert ctx.response_text == ctx.pre_write_disclosure_body + LOOKUP_DISCLOSURE


# --- R1-2: an unverifiable call, in any pass of the turn --------------------------------------------------

def _pass(kind: str):
    """One agentic pass of a turn, as the loop records it."""
    if kind == "empty":
        return _agentic_result([])
    if kind == "unverifiable":
        return _agentic_result_with_ids([("oracle_query", True, None)])
    if kind == "lookup":
        return _agentic_result([("oracle_query", True)])
    assert kind == "failed-write"
    return _agentic_result([(FINDING, False)])


def _ctx_for_passes(kinds: list[str], reply: str):
    """The real fold over several passes of one turn, the real metadata builder, the route's reconstruction."""
    observation: dict = {"intent": "direct_message"}
    for kind in kinds:
        outcome = WorkItemAgenticOutcome(
            final_text="done", tool_invocations=_project_tool_invocations(_pass(kind)),
        )
        _accumulate_pass_invocations(observation, outcome)
    decision = {"action": "execute", "llm_output": reply}
    _attach_run_provenance(decision, observation)
    report = asyncio.run(_OverridingAgent().act(decision))
    result = IntentResult(
        intent_id="i-1", agent_id="a1", success=True, result=reply,
        metadata=_build_result_metadata(report, decision, observation),
    )
    return _make_ctx(
        runtime=_runtime(episodic=_CapturingEpisodicMemory()),
        response_text=reply,
        tool_invocations=ToolInvocations.from_intent_result(result),
    )


@pytest.mark.parametrize(("kinds", "fires"), [
    pytest.param(["unverifiable"], False, id="unverifiable-only"),
    pytest.param(["unverifiable", "empty"], False, id="unverifiable-first"),
    pytest.param(["empty", "unverifiable"], False, id="unverifiable-last"),
    pytest.param(["empty", "unverifiable", "empty"], False, id="unverifiable-between"),
    pytest.param(["unverifiable", "failed-write", "empty"], False, id="with-known-call"),
    pytest.param(["lookup", "empty"], False, id="control-correlatable-first"),
    pytest.param(["empty", "empty"], True, id="control-two-empty-passes"),
])
def test_an_unverifiable_call_keeps_the_record_incomplete_in_every_pass_order(kinds, fires) -> None:
    ctx = _ctx_for_passes(kinds, "I searched the records: two games.")
    assert type(ctx.tool_invocations) is ToolInvocations, "premise: the route rebuilt a record"
    assert ctx.tool_invocations.incomplete is ("unverifiable" in kinds)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert (LOOKUP_DISCLOSURE in ctx.response_text) is fires


def test_a_known_write_and_the_incomplete_mark_both_survive_the_fold() -> None:
    ctx = _ctx_for_passes(["unverifiable", "failed-write", "empty"], "I searched the records first.")
    assert ctx.tool_invocations == ToolInvocations.from_names([FINDING], [], incomplete=True)
    asyncio.run(DmReplyPipeline(ctx).run())
    assert DISCLOSURE_FRAGMENT in ctx.response_text, "the write guard still reports the failed save"
    assert LOOKUP_DISCLOSURE not in ctx.response_text


@pytest.mark.parametrize(("triples", "attempted", "incomplete"), [
    pytest.param([("read_file", True, None), (FINDING, False, "c-1")], (FINDING,), True, id="sibling-kept"),
    pytest.param([("oracle_query", True, None)], (), True, id="all-unverifiable"),
    pytest.param([(FINDING, True, "same"), ("read_file", False, "same")], (), True, id="duplicate-ids"),
    pytest.param([("oracle_query", True, "c-1")], ("oracle_query",), False, id="well-formed"),
    pytest.param([], (), False, id="no-calls"),
])
def test_the_projection_marks_a_record_that_left_a_call_out(triples, attempted, incomplete) -> None:
    inv = _project_tool_invocations(_agentic_result_with_ids(triples))
    assert type(inv) is ToolInvocations
    assert inv.attempted == attempted
    assert inv.incomplete is incomplete


def test_merged_with_keeps_the_incomplete_mark_in_either_order() -> None:
    marked = ToolInvocations(incomplete=True)
    assert ToolInvocations().merged_with(marked).incomplete is True
    assert marked.merged_with(ToolInvocations()).incomplete is True
    assert ToolInvocations().merged_with(ToolInvocations()) == ToolInvocations()
    known = ToolInvocations.from_names([FINDING], [FINDING])
    assert marked.merged_with(known) == ToolInvocations.from_names([FINDING], [FINDING], incomplete=True)


def test_a_complete_record_keeps_the_ad1295_wire_shape() -> None:
    assert ToolInvocations().to_wire() == {"v": 1, "attempted": [], "succeeded": []}
    assert set(ToolInvocations.from_names([FINDING], []).to_wire()) == {"v", "attempted", "succeeded"}


def test_an_incomplete_record_round_trips_on_the_wire() -> None:
    value = ToolInvocations.from_names([FINDING], [], incomplete=True)
    payload = value.to_wire()
    assert payload == {"v": 1, "attempted": [FINDING], "succeeded": [], "incomplete": True}
    assert ToolInvocations.from_wire(payload) == value
    assert ToolInvocations.from_wire(ToolInvocations(incomplete=True).to_wire()) == ToolInvocations(incomplete=True)


@pytest.mark.parametrize("flag", [
    pytest.param(False, id="false"),
    pytest.param(1, id="one"),
    pytest.param("true", id="string"),
    pytest.param(None, id="null"),
])
def test_an_incomplete_key_that_is_not_true_reads_as_no_record(flag) -> None:
    assert ToolInvocations.from_wire({"v": 1, "attempted": [], "succeeded": [], "incomplete": flag}) is None


# --- R1-3: quoted wording over several lines --------------------------------------------------------------

_FENCED = (
    "Here is the template:\n" + _FENCE + "\nGood evening.\n\n"
    "I searched the records and found two games.\n" + _FENCE + "\nFill it in."
)
_QUOTED_OVER_LINES = (
    'Say it like this: "Good evening, Captain.\nI searched the records and found two games." That is the form.'
)
_UNQUOTED = "Here is the template:\nGood evening.\n\nI searched the records and found two games.\nFill it in."
#: Every test of this section except the timing test at its end runs with LF and with CRLF line breaks
#: (amendment A3): the masking reads both. The timing test (three cases) stays LF-only.
_EOLS = pytest.mark.parametrize("eol", [pytest.param("\n", id="lf"), pytest.param("\r\n", id="crlf")])


@_EOLS
@pytest.mark.parametrize("text", [
    pytest.param(_FENCED, id="fence-with-blank-line"),
    pytest.param("~~~\nI searched the records and found two games.\n~~~", id="tilde-fence"),
    pytest.param("~~~\nI searched the records and found two games.\n~~~\nThat was the form.",
                 id="tilde-fence-then-text"),
    pytest.param(_FENCE + "text\nThe record I found shows it as a draw.\n" + _FENCE, id="fence-info-string"),
    pytest.param(_QUOTED_OVER_LINES, id="multi-line-double-quote"),
    pytest.param("\u201cGood evening.\nI searched the records.\u201d That was the line.", id="multi-line-curly"),
    pytest.param("Use `the phrase\nI searched the records` as the test.", id="multi-line-backtick"),
])
def test_wording_quoted_over_several_lines_is_not_found(text, eol) -> None:
    assert find_lookup_claim(text.replace("\n", eol)) is None


@_EOLS
@pytest.mark.parametrize("text", [
    pytest.param(_FENCE + "\nexample\n" + _FENCE + "\nI searched the records and found two games.",
                 id="after-a-closed-fence"),
    pytest.param(_FENCE + "\nI searched the records and found two games.", id="unclosed-fence"),
    pytest.param('The board is 6" wide.\n\nI searched the records and found the "draw" entry.',
                 id="stray-quote-stops-at-blank-line"),
    pytest.param('He said "hi.\nI searched the records and found two games.', id="unpaired-quote"),
])
def test_an_unquoted_claim_beside_a_fence_or_quote_is_found(text, eol) -> None:
    found = find_lookup_claim(text.replace("\n", eol))
    assert found is not None and "i searched" in found.lower()


@_EOLS
@pytest.mark.parametrize(("reply", "fires"), [
    pytest.param(_FENCED, False, id="fenced-block"),
    pytest.param(_QUOTED_OVER_LINES, False, id="multi-line-quote"),
    pytest.param(_UNQUOTED, True, id="unquoted-control"),
])
def test_a_claim_quoted_over_several_lines_leaves_the_reply_unchanged(reply, fires, eol, caplog) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    ctx = _ctx_for_turn(_agentic_result([]), reply.replace("\n", eol))
    asyncio.run(DmReplyPipeline(ctx).run())
    assert (ctx.write_disclosure_suffix == LOOKUP_DISCLOSURE) is fires
    assert ctx.response_text == ctx.pre_write_disclosure_body + (LOOKUP_DISCLOSURE if fires else "")
    assert any("lookup-claim check" in r.getMessage() for r in caplog.records) is fires


@_EOLS
@pytest.mark.parametrize(("text", "expected"), [
    pytest.param(
        "~~~\nintro\n" + _FENCE + "\nI searched the records and found two games.\n" + _FENCE
        + "\nI checked the logs before answering.",
        "checked the logs", id="block-after-stray-opener",
    ),
    pytest.param(
        _FENCE + "`\nI searched the records and found two games.\n" + _FENCE + "\nThat was all.",
        "i searched", id="shorter-run",
    ),
    pytest.param(
        "~~~\nI searched the records and found two games.\n" + _FENCE + "\nThat was all.",
        "i searched", id="other-character",
    ),
])
def test_a_fence_ends_only_on_its_own_kind_and_length(text, expected, eol) -> None:
    """A fence ends at the first later line of the same character, at least as long; a stray opener makes no
    fenced span."""
    found = find_lookup_claim(text.replace("\n", eol))
    assert found is not None and expected in found.lower()


@_EOLS
def test_masking_keeps_length_and_line_breaks(eol) -> None:
    text = ('a "b\nc" d\n> e\n' + _FENCE + "\nf\n\ng\n" + _FENCE + "\n\u201ch\u201d `i`").replace("\n", eol)
    masked = _mask_quoted(text)
    assert len(masked) == len(text)
    assert masked == ("a   \n   d\n   \n   \n \n\n \n   \n" + " " * 7).replace("\n", eol)


@pytest.mark.parametrize("unit", [
    pytest.param(_FENCE + "a\n", id="unopened-backtick-fences"),
    pytest.param("~~~a\n", id="unopened-tilde-fences"),
    pytest.param("\u201ca ", id="unpaired-curly-quotes"),
])
def test_masking_takes_linear_time_on_unclosed_openers(unit) -> None:
    """16,000 openers that nothing ends. The linear pass took 8 to 50 ms where measured; the quadratic variants of
    the census (the first draft of A2-6, and an opener check that rescans the later lines) took 4.7 to 14 s. So the
    2 s bound is 40 times or more above the linear pass and only 2.3 to 7 times below the quadratic ones: a host
    over 2.3 times as fast could pass the weakest quadratic variant (contract sections 14.7.3, 16.10 and 17)."""
    text = unit * 16_000 + "\nI searched the records and found two games."
    began = time.perf_counter()
    found = find_lookup_claim(text)
    elapsed = time.perf_counter() - began
    assert found is not None and "i searched" in found.lower()
    assert elapsed < 2.0, f"masking took {elapsed:.2f} s on {len(text)} characters"
