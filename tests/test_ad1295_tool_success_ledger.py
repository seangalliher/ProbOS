"""AD-1295 (#1087 / BF-687): a successful tool write must be NAMEABLE.

AD-1285 shipped the *marker* half of the write-claim guard. The originally
reported 22:40 turn carried no ``[NOTEBOOK]`` marker, so ``consulted`` stayed
empty and the guard abstained -- correctly, and by design. The other channel is
the AD-1065 tool loop, which runs upstream of the reply pipeline and wrote
without telling it.

Three verified reasons the record did not exist before this AD:

* ``AgenticResult.tool_calls`` / ``tool_results`` die at
  ``WorkItemAgenticOutcome`` (the BF-793 trap, stated at
  ``cognitive_agent.py:120``).
* ``ToolFailures`` structurally cannot name a SUCCESS: the value is a ``""``
  tombstone, the tool name is HASHED into ``call_signature``, and ``to_wire``
  drops the tombstones.
* Text matching is not available. AD-1285 built such a branch and deleted it --
  ``publish_finding`` is a *tool*, not a marker, and is enabled live, so a
  genuine save reached the guard with an empty ledger and the branch
  contradicted TRUTHFUL replies. The verdict here stays entirely structural.

The most important test in this file is
``test_read_only_tools_do_not_consult_the_channel``. A false positive against a
truthful reply trains the Captain to ignore the disclosure, which costs the
control itself.

BF-287 discipline and the AD-1284 lesson: REAL fixtures only. No
``MagicMock(spec=...)`` for the runtime or the pipeline -- a spec'd double
auto-mocks any new public name and makes assertions pass for the wrong reason.
Every stand-in below accepts the real signature explicitly rather than
``**kwargs``, for the same reason.
"""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace

import pytest

from probos.cognitive.agentic_dispatch import (
    WorkItemAgenticOutcome,
    _project_tool_invocations,
)
from probos.cognitive.cognitive_agent import (
    _accumulate_pass_invocations,
    _attach_run_provenance,
    _build_result_metadata,
    _PER_RUN_PROVENANCE_KEYS,
    _cacheable_decision,
)
from probos.cognitive.dm.reply_pipeline import (
    _DURABLE_WRITE_TOOLS,
    DmReplyContext,
    DmReplyPipeline,
)
from probos.cognitive.dm.write_ledger import (
    WRITE_CHANNEL_ARTIFACT,
    WRITE_CHANNEL_FINDING,
    WRITE_CHANNEL_NOTEBOOK,
    ClaimVerdict,
    WriteLedger,
    assess_write_claim,
)
from probos.cognitive.swe_harness.agentic_loop import AgenticResult
from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolCallResult
from probos.config import WriteClaimGuardConfig
from probos.dm_reply import (
    TOOL_INVOCATIONS_METADATA_KEY,
    DmReply,
    ToolInvocations,
    _MAX_TOOL_INVOCATION_NAMES,
)
from probos.types import Episode, IntentResult

#: The tool whose success constitutes a durable write today.
FINDING = "publish_finding"

#: The sentence ``step_4m`` appends when a channel ran and wrote nothing.
DISCLOSURE_FRAGMENT = "A durable write was attempted on this turn"

#: A reply carrying a notebook marker, for the mixed-channel tests.
MARKED_REPLY = "Noted. [NOTEBOOK finding]Ward room escalation.[/NOTEBOOK]"


# --------------------------------------------------------------------------- #
# BF-287 real-but-fake stubs                                                   #
# --------------------------------------------------------------------------- #


class _CapturingEpisodicMemory:
    """Records what ``step_5_episodic_store`` actually stored.

    A plain attribute object, not a spec'd mock: a ``MagicMock(spec=...)``
    would auto-mock ``self_contradicted_channels`` and make the AD-1293
    composition assertion pass for the wrong reason.
    """

    def __init__(self) -> None:
        self.stored: list[Episode] = []

    async def store(self, episode: Episode) -> None:
        self.stored.append(episode)


class _FakeProactiveLoop:
    """Stands in for ``ProactiveLoop``, with the REAL method signature.

    ``actions`` is what the notebook channel's ledger entry reads: an empty
    list means the channel ran and wrote nothing.
    """

    def __init__(self, *, actions: list | None = None) -> None:
        self._actions = list(actions or [])

    async def extract_and_execute_notebooks(self, agent, text: str):
        cleaned = (
            text.replace("[NOTEBOOK finding]", "").replace("[/NOTEBOOK]", "").strip()
        )
        return cleaned, self._actions


class _OverridingAgent:
    """An ``act()`` override that copies ONLY ``llm_output``.

    This is the hazard ``_build_result_metadata``'s docstring names: ``act()``
    is overridden by ``CounselorAgent`` and by every generated agent, and those
    overrides copy only ``llm_output``. Written out here rather than mocked so
    the test exercises the exact shape that broke the chain.
    """

    async def act(self, decision: dict) -> dict:
        return {"success": True, "result": decision.get("llm_output", "")}


def _runtime(*, proactive=None, episodic=None, guard_enabled: bool = True):
    return SimpleNamespace(
        config=SimpleNamespace(
            write_claim_guard=WriteClaimGuardConfig(enabled=guard_enabled),
        ),
        proactive_loop=proactive,
        episodic_memory=episodic,
    )


def _make_ctx(
    *,
    runtime,
    response_text: str = "I saved that finding for you.",
    tool_invocations: ToolInvocations | None = None,
) -> DmReplyContext:
    return DmReplyContext(
        runtime=runtime,
        agent=SimpleNamespace(id="a1", agent_type="yeoman"),
        agent_id="a1",
        callsign="Yeo",
        req_message="Please record that finding.",
        reply=DmReply(body=response_text),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="Please record that finding.",
        sampling_state=None,
        avatar_event_bus=None,
        chat_thread_id="t1",
        tool_invocations=tool_invocations,
    )


def _agentic_result(pairs: list[tuple[str, bool]]) -> AgenticResult:
    """A REAL ``AgenticResult`` from ``(tool_name, succeeded)`` pairs.

    Calls and results are correlated by id, exactly as the loop produces them.
    """
    calls: list[ToolCallRequest] = []
    results: list[ToolCallResult] = []
    for index, (name, ok) in enumerate(pairs):
        call_id = f"call-{index}"
        calls.append(ToolCallRequest(name=name, arguments={"i": index}, id=call_id))
        results.append(
            ToolCallResult(id=call_id, output="ok" if ok else "boom", is_error=not ok)
        )
    return AgenticResult(final_text="done", tool_calls=calls, tool_results=results)


def _turn_metadata_for(agentic_result: AgenticResult | None) -> dict:
    """Drive the REAL producer chain and return ``IntentResult.metadata``.

    ``None`` means the agentic loop did not run on this turn, so nothing is
    ever folded into the observation. Otherwise the chain is:
    projection -> outcome -> observation fold -> decision -> ``act()`` override
    -> ``_build_result_metadata``.
    """
    observation: dict = {"intent": "direct_message"}
    if agentic_result is not None:
        outcome = WorkItemAgenticOutcome(
            final_text="done",
            tool_invocations=_project_tool_invocations(agentic_result),
        )
        _accumulate_pass_invocations(observation, outcome)

    decision = {"action": "execute", "llm_output": "I saved that finding for you."}
    _attach_run_provenance(decision, observation)
    report = asyncio.run(_OverridingAgent().act(decision))
    return _build_result_metadata(report, decision, observation)


def _turn_metadata(pairs: list[tuple[str, bool]] | None) -> dict:
    """:func:`_turn_metadata_for`, keyed by ``(tool_name, succeeded)`` pairs."""
    return _turn_metadata_for(None if pairs is None else _agentic_result(pairs))


# =========================================================================== #
# 1-8. projection out of the agentic loop (Section 1)                         #
# =========================================================================== #


def test_successful_tool_call_is_nameable() -> None:
    """The whole point: ``ToolFailures`` cannot answer this question."""
    inv = _project_tool_invocations(_agentic_result([(FINDING, True)]))

    assert inv is not None
    assert inv.succeeded == (FINDING,)
    assert inv.attempted == (FINDING,)


def test_failed_tool_call_is_attempted_but_not_succeeded() -> None:
    inv = _project_tool_invocations(_agentic_result([(FINDING, False)]))

    assert inv is not None
    assert inv.attempted == (FINDING,)
    assert inv.succeeded == ()


def test_same_tool_succeeding_twice_is_one_entry() -> None:
    """De-duplicated by NAME, which is what bounds the set (BF-797)."""
    inv = _project_tool_invocations(
        _agentic_result([(FINDING, True), (FINDING, True)])
    )

    assert inv is not None
    assert inv.succeeded == (FINDING,)
    assert inv.attempted == (FINDING,)


def test_projection_is_sorted_and_stable_across_call_order() -> None:
    forward = _project_tool_invocations(
        _agentic_result([("alpha", True), ("beta", True), ("gamma", True)])
    )
    reverse = _project_tool_invocations(
        _agentic_result([("gamma", True), ("beta", True), ("alpha", True)])
    )

    assert forward is not None and reverse is not None
    assert forward.succeeded == ("alpha", "beta", "gamma")
    assert forward == reverse


def test_projection_caps_at_the_documented_bound() -> None:
    over = _MAX_TOOL_INVOCATION_NAMES + 5
    inv = _project_tool_invocations(
        _agentic_result([(f"tool_{i:04d}", True) for i in range(over)])
    )

    assert inv is not None
    assert len(inv.attempted) == _MAX_TOOL_INVOCATION_NAMES
    assert len(inv.succeeded) == _MAX_TOOL_INVOCATION_NAMES


def test_projection_carries_names_only() -> None:
    """AD-731: refs on the bus, bytes in the store. No arguments, no outputs."""
    result = _agentic_result([(FINDING, True)])
    result.tool_calls[0] = ToolCallRequest(
        name=FINDING,
        arguments={"content": "SECRET-ARGUMENT-BODY"},
        id=result.tool_calls[0].id,
    )
    result.tool_results[0] = ToolCallResult(
        id=result.tool_results[0].id, output="SECRET-OUTPUT-BODY", is_error=False
    )

    inv = _project_tool_invocations(result)

    assert inv is not None
    flat = repr(inv)
    assert "SECRET-ARGUMENT-BODY" not in flat
    assert "SECRET-OUTPUT-BODY" not in flat
    assert set(inv.attempted) | set(inv.succeeded) == {FINDING}


def test_success_is_correlated_by_id_not_by_request_position() -> None:
    """A positional pairing would turn any future ordering drift into a FALSE
    disclosure against a truthful reply -- the one failure class this guard
    must not have."""
    result = AgenticResult(
        tool_calls=[
            ToolCallRequest(name="read_file", arguments={}, id="c-1"),
            ToolCallRequest(name=FINDING, arguments={}, id="c-2"),
        ],
        # Deliberately out of request order.
        tool_results=[
            ToolCallResult(id="c-2", output="saved", is_error=False),
            ToolCallResult(id="c-1", output="boom", is_error=True),
        ],
    )

    inv = _project_tool_invocations(result)

    assert inv is not None
    assert inv.attempted == (FINDING, "read_file")
    assert inv.succeeded == (FINDING,)


def test_call_with_no_result_is_attempted_and_not_succeeded() -> None:
    result = AgenticResult(
        tool_calls=[ToolCallRequest(name=FINDING, arguments={}, id="c-1")],
        tool_results=[],
    )

    inv = _project_tool_invocations(result)

    assert inv is not None
    assert inv.attempted == (FINDING,)
    assert inv.succeeded == ()


def test_outcome_defaults_to_no_record_at_all() -> None:
    """AD-1269: an outcome nobody projected onto must not assert an empty run."""
    assert WorkItemAgenticOutcome().tool_invocations is None


def test_the_field_was_appended_without_disturbing_its_predecessors() -> None:
    """The convention every additive field on this outcome has followed, so a
    reader can tell an insertion from a reshape at a glance."""
    names = [f.name for f in dataclasses.fields(WorkItemAgenticOutcome)]

    assert names[:names.index("tool_invocations")] == [
        "final_text", "stopped_reason", "denied_tools", "tool_trace_ref",
        "total_tokens", "artifact_refs", "token_source", "tool_failures",
        "tool_defect", "tool_defect_evaluated",
    ]


# =========================================================================== #
# 9-15. the metadata hop (Section 2)                                          #
# =========================================================================== #


def test_metadata_carries_the_key_when_the_loop_ran() -> None:
    metadata = _turn_metadata([(FINDING, True)])

    assert TOOL_INVOCATIONS_METADATA_KEY in metadata
    assert metadata[TOOL_INVOCATIONS_METADATA_KEY]["succeeded"] == [FINDING]


def test_metadata_omits_the_key_when_the_loop_did_not_run() -> None:
    """AD-1269 half one: absent, NOT an empty tuple."""
    metadata = _turn_metadata(None)

    assert TOOL_INVOCATIONS_METADATA_KEY not in metadata


def test_metadata_carries_an_empty_record_when_no_tool_succeeded() -> None:
    """AD-1269 half two. Together with the test above this is the distinction:
    if one implementation could satisfy both, the distinction is not encoded."""
    metadata = _turn_metadata([])

    assert TOOL_INVOCATIONS_METADATA_KEY in metadata
    assert metadata[TOOL_INVOCATIONS_METADATA_KEY]["attempted"] == []
    assert metadata[TOOL_INVOCATIONS_METADATA_KEY]["succeeded"] == []


def test_the_two_halves_are_distinguishable_end_to_end() -> None:
    """Reconstruction preserves the distinction, not just the raw metadata."""
    ran = IntentResult(
        intent_id="i", agent_id="a1", success=True,
        metadata=_turn_metadata([]),
    )
    did_not_run = IntentResult(
        intent_id="i", agent_id="a1", success=True,
        metadata=_turn_metadata(None),
    )

    assert ToolInvocations.from_intent_result(ran) == ToolInvocations()
    assert ToolInvocations.from_intent_result(did_not_run) is None


def test_record_survives_an_act_override_that_copies_only_llm_output() -> None:
    """The ``_build_result_metadata`` docstring's stated hazard, and the reason
    the field is reconciled at the single ``IntentResult`` construction site
    rather than in any ``act()``."""
    observation: dict = {}
    _accumulate_pass_invocations(
        observation,
        WorkItemAgenticOutcome(
            tool_invocations=_project_tool_invocations(
                _agentic_result([(FINDING, True)])
            ),
        ),
    )
    decision = {"llm_output": "saved"}
    _attach_run_provenance(decision, observation)

    report = asyncio.run(_OverridingAgent().act(decision))
    assert "_dm_tool_invocations" not in report  # the override dropped it...

    metadata = _build_result_metadata(report, decision, observation)
    # ...and the observation put it back.
    assert metadata[TOOL_INVOCATIONS_METADATA_KEY]["succeeded"] == [FINDING]


def test_passes_of_one_turn_union_rather_than_supersede() -> None:
    """An AD-1164 continuation ADDS calls; a tool that succeeded on pass 1 still
    succeeded on this turn, and there is no analogous 'un-succeed'."""
    observation: dict = {}
    _accumulate_pass_invocations(
        observation,
        WorkItemAgenticOutcome(
            tool_invocations=_project_tool_invocations(
                _agentic_result([(FINDING, True)])
            ),
        ),
    )
    _accumulate_pass_invocations(
        observation,
        WorkItemAgenticOutcome(
            tool_invocations=_project_tool_invocations(
                _agentic_result([("read_file", False)])
            ),
        ),
    )

    folded = observation["_dm_tool_invocations"]
    assert folded.attempted == (FINDING, "read_file")
    assert folded.succeeded == (FINDING,)


def test_the_record_is_per_run_provenance_and_never_replayed_from_cache() -> None:
    """AD-1248's rule: a cache hit replays a previous turn's answer, and serving
    it with this turn's invocation record would let the guard judge one run
    against another run's evidence."""
    assert "_dm_tool_invocations" in _PER_RUN_PROVENANCE_KEYS

    cached = _cacheable_decision({
        "llm_output": "saved",
        "_dm_tool_invocations": ToolInvocations.from_names([FINDING], [FINDING]),
    })
    assert "_dm_tool_invocations" not in cached


# =========================================================================== #
# 16-21. the wire contract                                                    #
# =========================================================================== #


def test_wire_round_trip_preserves_both_lists() -> None:
    original = ToolInvocations.from_names([FINDING, "read_file"], [FINDING])

    assert ToolInvocations.from_wire(original.to_wire()) == original


def test_empty_record_survives_the_wire_unlike_a_failure_payload() -> None:
    """``ToolFailures.to_wire`` returns ``None`` for an empty value because an
    empty failure set has nothing to disclose. An empty INVOCATION record is a
    positive assertion and must survive."""
    payload = ToolInvocations().to_wire()

    assert payload is not None
    assert ToolInvocations.from_wire(payload) == ToolInvocations()


@pytest.mark.parametrize("payload", [
    None,
    "not-a-dict",
    {},
    {"v": 2, "attempted": [], "succeeded": []},
    {"v": True, "attempted": [], "succeeded": []},
    {"v": 1, "attempted": []},
    {"v": 1, "attempted": [], "succeeded": [], "extra": 1},
    {"v": 1, "attempted": "publish_finding", "succeeded": []},
    {"v": 1, "attempted": [{"name": FINDING}], "succeeded": []},
    {"v": 1, "attempted": ["bad name!"], "succeeded": []},
    {"v": 1, "attempted": [], "succeeded": [FINDING]},
])
def test_malformed_wire_payload_reads_as_no_record_not_an_empty_one(payload) -> None:
    """``None`` rather than an empty value, deliberately: an empty value ASSERTS
    that the loop ran and called nothing, which a malformed payload does not
    establish."""
    assert ToolInvocations.from_wire(payload) is None


def test_over_bound_wire_payload_is_rejected() -> None:
    names = [f"tool_{i:04d}" for i in range(_MAX_TOOL_INVOCATION_NAMES + 1)]

    assert ToolInvocations.from_wire(
        {"v": 1, "attempted": names, "succeeded": []}
    ) is None


def test_from_intent_result_returns_none_when_there_is_no_result() -> None:
    assert ToolInvocations.from_intent_result(None) is None


# =========================================================================== #
# 22-28. the ledger, the verdict, the reply (Sections 3-4)                    #
# =========================================================================== #


def _run_write_steps(ctx: DmReplyContext) -> None:
    """Producer then consumer, in ``_full_steps`` order."""
    pipeline = DmReplyPipeline(ctx)
    asyncio.run(pipeline.step_4n_tool_write_ledger())
    asyncio.run(pipeline.step_4m_write_claim_guard())


def test_successful_publish_finding_leaves_the_reply_byte_identical() -> None:
    """A truthful save must not be marked. This is the property that makes the
    disclosure worth reading when it does appear."""
    ctx = _make_ctx(
        runtime=_runtime(),
        tool_invocations=ToolInvocations.from_names([FINDING], [FINDING]),
    )
    before = ctx.response_text

    _run_write_steps(ctx)

    assert ctx.write_ledger.consulted == frozenset({WRITE_CHANNEL_FINDING})
    assert ctx.write_ledger.wrote == frozenset({WRITE_CHANNEL_FINDING})
    assert assess_write_claim(ctx.write_ledger) is ClaimVerdict.ABSTAIN
    assert ctx.response_text == before


def test_failed_publish_finding_is_disclosed() -> None:
    ctx = _make_ctx(
        runtime=_runtime(),
        tool_invocations=ToolInvocations.from_names([FINDING], []),
    )
    before = ctx.response_text

    _run_write_steps(ctx)

    assert ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_FINDING})
    assert assess_write_claim(ctx.write_ledger) is ClaimVerdict.MARKER_WROTE_NOTHING
    assert ctx.response_text.startswith(before)
    assert DISCLOSURE_FRAGMENT in ctx.response_text


def test_read_only_tools_do_not_consult_the_channel() -> None:
    """THE FALSE-POSITIVE GUARD, and the most important test in this file.

    Consulting on every tool-loop turn would make every read-only turn report
    ``wrote_nothing={finding}`` and append a disclosure to a TRUTHFUL reply.
    AD-1285 deleted a text-reading branch to avoid exactly this class; a loose
    admission condition would reintroduce it structurally.
    """
    ctx = _make_ctx(
        runtime=_runtime(),
        response_text="I read three files and found nothing unusual.",
        tool_invocations=ToolInvocations.from_names(
            ["read_file", "list_directory", "web_search"],
            ["read_file", "list_directory"],
        ),
    )
    before = ctx.response_text

    _run_write_steps(ctx)

    assert ctx.write_ledger.consulted == frozenset()
    assert ctx.write_ledger.evaluated is False
    assert assess_write_claim(ctx.write_ledger) is ClaimVerdict.ABSTAIN
    assert ctx.response_text == before


def test_a_turn_with_no_tool_loop_does_not_consult_the_channel() -> None:
    ctx = _make_ctx(runtime=_runtime(), tool_invocations=None)
    before = ctx.response_text

    _run_write_steps(ctx)

    assert ctx.write_ledger.consulted == frozenset()
    assert ctx.response_text == before


def test_notebook_wrote_and_finding_failed_names_only_the_finding() -> None:
    """Per-channel granularity: a ledger-wide ``if self.wrote`` would mask it
    (``write_ledger.py`` ``wrote_nothing``)."""
    ctx = _make_ctx(
        runtime=_runtime(),
        tool_invocations=ToolInvocations.from_names([FINDING], []),
    )
    ctx.write_ledger = ctx.write_ledger.consulted_with(
        WRITE_CHANNEL_NOTEBOOK, wrote=True,
    )

    _run_write_steps(ctx)

    assert ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_FINDING})
    assert DISCLOSURE_FRAGMENT in ctx.response_text


def test_both_channels_wrote_abstains() -> None:
    ctx = _make_ctx(
        runtime=_runtime(),
        tool_invocations=ToolInvocations.from_names([FINDING], [FINDING]),
    )
    ctx.write_ledger = ctx.write_ledger.consulted_with(
        WRITE_CHANNEL_ARTIFACT, wrote=True,
    )
    before = ctx.response_text

    _run_write_steps(ctx)

    assert ctx.write_ledger.consulted == frozenset(
        {WRITE_CHANNEL_FINDING, WRITE_CHANNEL_ARTIFACT}
    )
    assert ctx.write_ledger.wrote_nothing == frozenset()
    assert ctx.response_text == before


def test_the_1087_turn_stays_undetectable_and_that_is_correct() -> None:
    """The reported 22:40 turn: the agentic loop ran, ``publish_finding`` was
    never called, and no ``[NOTEBOOK]`` marker was present.

    It still abstains, and that is the RIGHT answer -- nothing durable was
    attempted, so nothing structural contradicts the claim. This test exists to
    stop a future reader "fixing" the abstention by reading the reply text.
    AD-1285 built that branch and deleted it: ``publish_finding`` is a tool, not
    a marker, and is enabled live, so a genuine save reached the guard with an
    empty ledger and the branch contradicted TRUTHFUL replies. A false positive
    here trains the Captain to ignore the signal, which costs the control.
    """
    ctx = _make_ctx(
        runtime=_runtime(),
        response_text=(
            "I wrote the finding and it's saved to my notebook under the slug "
            "ward-room-escalation-decision."
        ),
        tool_invocations=ToolInvocations.from_names(
            ["read_file", "search_files"], ["read_file", "search_files"],
        ),
    )
    before = ctx.response_text

    _run_write_steps(ctx)

    assert assess_write_claim(ctx.write_ledger) is ClaimVerdict.ABSTAIN
    assert ctx.response_text == before


def test_the_durable_write_tool_set_is_publish_finding_only() -> None:
    """Adding a name changes what the guard asserts about every turn calling it,
    so each addition needs its own evidence. Pinned so a widening is a decision
    rather than a drive-by."""
    assert _DURABLE_WRITE_TOOLS == frozenset({FINDING})


def test_the_producer_step_runs_before_its_only_consumer() -> None:
    pipeline = DmReplyPipeline.__new__(DmReplyPipeline)
    names = [s.__name__ for s in DmReplyPipeline._full_steps(pipeline)]

    assert names.index("step_4n_tool_write_ledger") < names.index(
        "step_4m_write_claim_guard"
    )
    # 1:1 only, for AD-1285's reason: the group sink is unverified (#1087).
    escalation = [s.__name__ for s in DmReplyPipeline._escalation_steps(pipeline)]
    assert "step_4n_tool_write_ledger" not in escalation


def test_the_ledger_value_itself_is_unchanged_by_the_new_channel() -> None:
    """The design's stated purpose: a new channel adds a KEY, not a shape."""
    ledger = WriteLedger().consulted_with(WRITE_CHANNEL_FINDING, wrote=False)

    assert ledger.consulted == frozenset({WRITE_CHANNEL_FINDING})
    assert ledger.wrote_nothing == frozenset({WRITE_CHANNEL_FINDING})
    assert assess_write_claim(ledger) is ClaimVerdict.MARKER_WROTE_NOTHING


# =========================================================================== #
# 29-30. composition with AD-1293, and the crossing test                      #
# =========================================================================== #


def test_finding_failure_marks_the_stored_episode_with_no_ad1293_change() -> None:
    """AD-1293 reads ``ledger.wrote_nothing`` by name and needed no edit at all.
    That is the name-keyed design proving itself."""
    episodic = _CapturingEpisodicMemory()
    ctx = _make_ctx(
        runtime=_runtime(episodic=episodic),
        tool_invocations=ToolInvocations.from_names([FINDING], []),
    )

    asyncio.run(DmReplyPipeline(ctx).step_4n_tool_write_ledger())
    asyncio.run(DmReplyPipeline(ctx).step_5_episodic_store())

    assert episodic.stored, "step_5 stored nothing -- the fixture never reached it"
    assert episodic.stored[0].self_contradicted_channels == [WRITE_CHANNEL_FINDING]
    # AD-1293's rule: ``success`` stays task-execution truth and is not overloaded.
    assert episodic.stored[0].outcomes[0]["success"] is True


def test_projection_to_metadata_to_ledger_to_verdict_to_reply() -> None:
    """THE CROSSING TEST -- one pass through every seam this AD adds.

    Three tests that each stop at a boundary is the exact evidence shape that
    let BF-793 ship: a producer firing proves the producer, not the chain. This
    runs the real loop record through the real projection, the real observation
    fold, a real ``act()`` override, the real metadata builder, a real
    ``IntentResult``, the real reconstruction, and both real pipeline steps.

    The positive case runs FIRST so the negative assertion below cannot pass
    trivially by never reaching the branch.
    """
    # --- the failed save: the whole chain, ending in a disclosure ---
    failed = IntentResult(
        intent_id="i-1", agent_id="a1", success=True,
        result="I saved that finding for you.",
        metadata=_turn_metadata([("read_file", True), (FINDING, False)]),
    )
    ctx = _make_ctx(
        runtime=_runtime(),
        tool_invocations=ToolInvocations.from_intent_result(failed),
    )
    _run_write_steps(ctx)

    assert ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_FINDING})
    assert DISCLOSURE_FRAGMENT in ctx.response_text

    # --- the truthful save: identical fixture shape, byte-identical reply ---
    saved = IntentResult(
        intent_id="i-2", agent_id="a1", success=True,
        result="I saved that finding for you.",
        metadata=_turn_metadata([("read_file", True), (FINDING, True)]),
    )
    truthful = _make_ctx(
        runtime=_runtime(),
        tool_invocations=ToolInvocations.from_intent_result(saved),
    )
    before = truthful.response_text
    _run_write_steps(truthful)

    assert truthful.write_ledger.wrote == frozenset({WRITE_CHANNEL_FINDING})
    assert truthful.response_text == before


def test_the_notebook_marker_and_the_tool_channel_compose_in_one_run() -> None:
    """Both channels through the FULL pipeline: the notebook marker writes, the
    finding tool fails, and only the finding is named."""
    episodic = _CapturingEpisodicMemory()
    ctx = _make_ctx(
        runtime=_runtime(
            proactive=_FakeProactiveLoop(actions=[{"type": "notebook_write"}]),
            episodic=episodic,
        ),
        response_text=MARKED_REPLY,
        tool_invocations=ToolInvocations.from_names([FINDING], []),
    )

    asyncio.run(DmReplyPipeline(ctx).run())

    assert ctx.write_ledger.consulted == frozenset(
        {WRITE_CHANNEL_NOTEBOOK, WRITE_CHANNEL_FINDING}
    )
    assert ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_FINDING})
    assert DISCLOSURE_FRAGMENT in ctx.response_text
    assert episodic.stored[0].self_contradicted_channels == [WRITE_CHANNEL_FINDING]


# =========================================================================== #
# 31-36. the UNCORRELATABLE-ID seam                                           #
# =========================================================================== #
#
# The highest-risk path in this AD, and the one the original 30 tests missed
# entirely. ``llm_client.py`` builds ``ToolCallRequest.id`` from
# ``tc.get("id", uuid4().hex)``, and ``dict.get`` returns the DEFAULT only when
# the key is absent -- a provider sending ``"id": null`` or ``"id": ""`` yields
# a call whose id is ``None`` / ``""``. Before the fix, such a call was recorded
# as ``attempted`` and never as ``succeeded``, so a turn whose
# ``publish_finding`` ACTUALLY LANDED had the disclosure appended to it. That is
# AD-1285's deleted text-reading branch reappearing structurally.


def _agentic_result_with_ids(triples: list[tuple[str, bool, object]]) -> AgenticResult:
    """A REAL ``AgenticResult`` from ``(tool_name, succeeded, call_id)``.

    ``call_id`` is deliberately untyped: the dataclass annotates ``id: str`` but
    does not enforce it, and neither does the provider that fills it in.
    """
    calls: list[ToolCallRequest] = []
    results: list[ToolCallResult] = []
    for name, ok, call_id in triples:
        calls.append(ToolCallRequest(name=name, arguments={}, id=call_id))  # type: ignore[arg-type]
        results.append(
            ToolCallResult(  # type: ignore[arg-type]
                id=call_id, output="saved" if ok else "boom", is_error=not ok
            )
        )
    return AgenticResult(final_text="done", tool_calls=calls, tool_results=results)


#: Every shape ``tc.get("id", ...)`` can hand back that cannot index a dict key
#: the correlation index will ever hold.
UNCORRELATABLE_IDS = [
    pytest.param(None, id="null"),
    pytest.param("", id="empty"),
    pytest.param(12345, id="non-string-int"),
    pytest.param(["c-1"], id="non-string-list"),
]


@pytest.mark.parametrize("bad_id", UNCORRELATABLE_IDS)
def test_unverifiable_call_is_omitted_from_attempted(bad_id) -> None:
    """The rule, at the seam that decides it.

    ``attempted`` without ``succeeded`` is an ASSERTION that the write did not
    land. An uncorrelatable call cannot support that assertion, so it must not
    enter either list.
    """
    inv = _project_tool_invocations(_agentic_result_with_ids([(FINDING, True, bad_id)]))

    assert inv is not None
    assert inv.attempted == ()
    assert inv.succeeded == ()


def test_uncorrelatable_call_does_not_hide_its_well_formed_sibling() -> None:
    """Dropping is per CALL, not per turn: a turn must not lose a real,
    correlatable failure because an unrelated call arrived id-less."""
    inv = _project_tool_invocations(
        _agentic_result_with_ids(
            [("read_file", True, None), (FINDING, False, "c-1")]
        )
    )

    assert inv is not None
    assert inv.attempted == (FINDING,)
    assert inv.succeeded == ()


def test_duplicate_call_ids_are_uncorrelatable() -> None:
    """The same seam, reached by a repeated id rather than a missing one.

    The correlation index is last-write-wins, so two calls sharing an id pair
    the FIRST with the SECOND's outcome. Verified reachable: a successful
    ``publish_finding`` sharing an id with a failed ``read_file`` produced
    ``attempted=('publish_finding', 'read_file'), succeeded=()`` -- a false
    accusation against a landed write, identical to the null-id case.
    """
    inv = _project_tool_invocations(
        _agentic_result_with_ids(
            [(FINDING, True, "same"), ("read_file", False, "same")]
        )
    )

    assert inv is not None
    assert inv.attempted == ()
    assert inv.succeeded == ()


def test_a_call_with_a_well_formed_id_is_still_correlated() -> None:
    """The premise the three tests above rest on. Without this, they would all
    pass against a projection that had simply stopped working."""
    inv = _project_tool_invocations(_agentic_result_with_ids([(FINDING, True, "c-1")]))

    assert inv is not None
    assert inv.attempted == (FINDING,)
    assert inv.succeeded == (FINDING,)


@pytest.mark.parametrize("bad_id", UNCORRELATABLE_IDS)
def test_successful_write_with_an_unverifiable_id_is_never_contradicted(
    bad_id,
) -> None:
    """THE REGRESSION -- the full chain, on the case that was broken.

    Reproduced against the unfixed tree: a SUCCEEDING ``publish_finding`` whose
    provider id did not survive parsing produced
    ``attempted=('publish_finding',), succeeded=()``, ``step_4n`` recorded the
    channel consulted-and-not-written, and ``step_4m`` appended
    "[A durable write was attempted on this turn and did not complete...]" to a
    reply whose write HAD landed.

    Every seam is real: the real projection, the real observation fold, a real
    ``act()`` override, the real metadata builder, a real ``IntentResult``, the
    real reconstruction, and both real pipeline steps.

    The positive arm runs FIRST so the negative assertion cannot pass trivially
    by never reaching the branch.
    """
    # --- premise: the identical fixture with a well-formed id correlates ---
    good = IntentResult(
        intent_id="i-1", agent_id="a1", success=True,
        result="I saved that finding for you.",
        metadata=_turn_metadata_for(_agentic_result_with_ids([(FINDING, True, "c-1")])),
    )
    good_inv = ToolInvocations.from_intent_result(good)
    assert good_inv is not None and good_inv.succeeded == (FINDING,), (
        "premise dead: the chain no longer correlates even a well-formed id, so "
        "the assertions below would pass for the wrong reason"
    )

    # --- the regression: the same successful save, id lost at the parser ---
    saved = IntentResult(
        intent_id="i-2", agent_id="a1", success=True,
        result="I saved that finding for you.",
        metadata=_turn_metadata_for(
            _agentic_result_with_ids([(FINDING, True, bad_id)])
        ),
    )
    ctx = _make_ctx(
        runtime=_runtime(),
        tool_invocations=ToolInvocations.from_intent_result(saved),
    )
    before = ctx.response_text

    _run_write_steps(ctx)

    assert ctx.write_ledger.consulted == frozenset()
    assert assess_write_claim(ctx.write_ledger) is ClaimVerdict.ABSTAIN
    assert DISCLOSURE_FRAGMENT not in ctx.response_text
    assert ctx.response_text == before


def test_unverifiable_id_abstains_through_the_whole_pipeline() -> None:
    """The same case through ``run()`` rather than the two steps in isolation,
    so a future reordering cannot reintroduce the accusation past this file."""
    episodic = _CapturingEpisodicMemory()
    ctx = _make_ctx(
        runtime=_runtime(episodic=episodic),
        tool_invocations=_project_tool_invocations(
            _agentic_result_with_ids([(FINDING, True, None)])
        ),
    )
    before = ctx.response_text

    asyncio.run(DmReplyPipeline(ctx).run())

    assert ctx.response_text == before
    assert episodic.stored, "step_5 stored nothing -- the fixture never reached it"
    assert episodic.stored[0].self_contradicted_channels == []

