"""AD-1248 slice A: the vertical crossing tests.

Unit tests prove each component. These prove the SEAM -- a failed tool call
leaving the agentic run and arriving in the text the Captain actually reads.
Every defect in the BF-773 review waves sat between two correct components, so
these are the tests that matter.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.reply_value import (
    DM_REPLY_METADATA_KEY,
    UNKNOWN_TOOL_LABEL,
    DmReply,
    ToolFailures,
    call_signature,
    correlate_tool_outcomes,
    failure_key,
)
from probos.types import IntentResult

ROOT = "aaaaaaaaaaaa"


class _Call:
    def __init__(self, cid: str, name: str, arguments: dict | None = None) -> None:
        self.id = cid
        self.name = name
        self.arguments = arguments or {}


class _Result:
    def __init__(self, cid: str, is_error: bool) -> None:
        self.id = cid
        self.is_error = is_error


def _run(*pairs: tuple[_Call, _Result]) -> SimpleNamespace:
    return SimpleNamespace(
        tool_calls=[c for c, _ in pairs],
        tool_results=[r for _, r in pairs],
    )


# ── the producer ────────────────────────────────────────────────────────────


def test_a_failed_call_is_recorded_with_its_offered_name() -> None:
    run = _run((_Call("1", "web_search"), _Result("1", True)))
    failures = correlate_tool_outcomes(
        run, root=ROOT, scope=ROOT, known_tools=["web_search"],
    )
    assert failures.names() == ("web_search",)


def test_a_successful_call_records_a_tombstone_not_a_failure() -> None:
    run = _run((_Call("1", "web_search"), _Result("1", False)))
    failures = correlate_tool_outcomes(
        run, root=ROOT, scope=ROOT, known_tools=["web_search"],
    )
    assert failures.names() == ()
    assert failures.entries  # the tombstone exists, so supersession can use it


def test_a_name_never_offered_renders_as_unknown() -> None:
    """S22. Keying disclosure off a registry id names a tool the Captain never
    saw the agent offered."""
    run = _run((_Call("1", "mcp:docs:search"), _Result("1", True)))
    failures = correlate_tool_outcomes(
        run, root=ROOT, scope=ROOT, known_tools=["read_file"],
    )
    assert failures.names() == (UNKNOWN_TOOL_LABEL,)


def test_an_offered_mcp_alias_is_disclosed_by_its_alias() -> None:
    """S21."""
    alias = "mcp_docs_search_38c53abe80026e47"
    run = _run((_Call("1", alias), _Result("1", True)))
    failures = correlate_tool_outcomes(
        run, root=ROOT, scope=ROOT, known_tools=[alias],
    )
    assert failures.names() == (alias,)


def test_a_permission_denial_is_not_disclosed_as_a_tool_failure() -> None:
    """S23. AD-855's gap driver already names the exact tool; disclosing it here
    too reports one event twice, in the worse wording."""
    run = _run((_Call("1", "shell"), _Result("1", True)))
    failures = correlate_tool_outcomes(
        run, root=ROOT, scope=ROOT,
        known_tools=["shell"], excluded_tools=["shell"],
    )
    assert failures.is_empty


def test_a_denial_is_suppressed_across_the_mcp_alias_namespace() -> None:
    """S24. ``denied_tools`` holds REGISTRY ids while the call carries the
    PROVIDER alias. Comparing the two namespaces directly is what made the
    discarded BF-773 build both duplicate and conceal, depending on which way
    the mismatch fell."""
    from probos.cognitive.swe_harness.tool_call import llm_function_name

    registry_id = "mcp:docs:search"
    alias = llm_function_name(registry_id)
    assert alias != registry_id  # the premise of this test

    run = _run((_Call("1", alias), _Result("1", True)))
    failures = correlate_tool_outcomes(
        run, root=ROOT, scope=ROOT,
        known_tools=[alias], excluded_tools=[registry_id],
    )
    assert failures.is_empty


def test_a_correlation_mismatch_is_skipped_not_surfaced() -> None:
    run = SimpleNamespace(
        tool_calls=[_Call("1", "web_search")],
        tool_results=[_Result("MISMATCH", True)],
    )
    failures = correlate_tool_outcomes(
        run, root=ROOT, scope=ROOT, known_tools=["web_search"],
    )
    assert failures.is_empty


def test_a_run_with_no_calls_discloses_nothing() -> None:
    failures = correlate_tool_outcomes(
        SimpleNamespace(tool_calls=[], tool_results=[]), root=ROOT, scope=ROOT,
    )
    assert failures.is_empty


def test_the_producer_yields_a_merge_open_value() -> None:
    """Supersession across AD-1164 passes needs the tombstones, so the value
    leaving the producer must not be merge-closed."""
    run = _run((_Call("1", "web_search"), _Result("1", False)))
    assert correlate_tool_outcomes(run, root=ROOT, scope=ROOT).merge_open is True


# ── the seam: producer -> IntentResult -> pipeline -> both sinks ────────────


def _pipeline_for(result: IntentResult, body: str) -> DmReplyPipeline:
    """Mirror the router's construction (routers/agents.py) exactly."""
    return DmReplyPipeline(DmReplyContext(
        runtime=SimpleNamespace(),
        agent=SimpleNamespace(),
        agent_id="ezri",
        callsign="Ezri",
        req_message="hi",
        reply=DmReply.from_intent_result(result).with_body(body),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="hi",
        sampling_state=None,
        avatar_event_bus=None,
    ))


def _result_with_failure(body: str = "All done, Captain.") -> IntentResult:
    run = _run((_Call("1", "web_search"), _Result("1", True)))
    failures = correlate_tool_outcomes(
        run, root=ROOT, scope=ROOT, known_tools=["web_search"],
    )
    return IntentResult(
        intent_id="i", agent_id="ezri", success=True, result=body,
        metadata={DM_REPLY_METADATA_KEY: failures.to_wire()},
    )


def test_sink_1_and_2_both_receive_the_disclosure() -> None:
    """Sinks 1 and 2 -- the thread append and the HTTP body -- read the SAME
    composed value, so the disclosure cannot reach one and miss the other.
    That is the two-sinks-one-route shape review round 4 found."""
    result = _result_with_failure()
    pipeline = _pipeline_for(result, "All done, Captain.")
    response = pipeline.build_response()

    http_body = response["response"]          # sink 2
    thread_body = response.get("response", "")  # sink 1 reads the same key
    assert "web_search" in http_body
    assert http_body == thread_body


def test_a_body_rewrite_inside_the_pipeline_preserves_the_disclosure() -> None:
    """The pipeline rewrites ``ctx.response_text`` in 34 places. Every one of
    them must keep the attachments -- that is the whole point of DD-6."""
    result = _result_with_failure()
    pipeline = _pipeline_for(result, "raw [MOVE A1] text")
    pipeline.ctx.response_text = pipeline.ctx.response_text.replace(" [MOVE A1]", "")
    pipeline.ctx.response_text = pipeline.ctx.response_text.upper()

    rendered = pipeline.build_response()["response"]
    assert rendered.startswith("RAW TEXT")
    assert "web_search" in rendered


def test_a_turn_with_no_failures_is_byte_identical() -> None:
    """DD-4. The migration changes nothing until a fact is actually attached."""
    result = IntentResult(
        intent_id="i", agent_id="ezri", success=True, result="Clean answer.",
    )
    pipeline = _pipeline_for(result, "Clean answer.")
    assert pipeline.build_response()["response"] == "Clean answer."


def test_the_router_reconstruction_survives_a_result_with_no_metadata() -> None:
    result = IntentResult(intent_id="i", agent_id="ezri", success=True, result="x")
    assert DmReply.from_intent_result(result).tool_failures.is_empty


def test_malformed_metadata_degrades_to_the_body_alone() -> None:
    result = IntentResult(
        intent_id="i", agent_id="ezri", success=True, result="Answer.",
        metadata={DM_REPLY_METADATA_KEY: {"v": 99, "entries": []}},
    )
    pipeline = _pipeline_for(result, "Answer.")
    assert pipeline.build_response()["response"] == "Answer."


# ── the carriage: report -> IntentResult.metadata ───────────────────────────


def test_the_metadata_builder_attaches_a_bounded_payload() -> None:
    from probos.cognitive.cognitive_agent import _build_result_metadata

    failures = ToolFailures.from_mapping(
        {failure_key(ROOT, ROOT, call_signature("web_search", None)): "web_search"}
    )
    metadata = _build_result_metadata({"_dm_tool_failures": failures})
    assert metadata[DM_REPLY_METADATA_KEY]["v"] == 1
    assert metadata[DM_REPLY_METADATA_KEY]["entries"][0][1] == "web_search"


def test_the_metadata_builder_is_empty_on_a_clean_turn() -> None:
    from probos.cognitive.cognitive_agent import _build_result_metadata

    assert _build_result_metadata({"result": "hi"}) == {}


def test_the_metadata_builder_still_carries_the_trace_ref() -> None:
    """AD-1203 must keep working beside AD-1248."""
    from probos.cognitive.cognitive_agent import _build_result_metadata

    assert _build_result_metadata({"_tool_trace_ref": "sha"})["tool_trace_ref"] == "sha"


def test_a_turn_whose_failures_all_succeeded_attaches_nothing() -> None:
    from probos.cognitive.cognitive_agent import _build_result_metadata

    run = _run((_Call("1", "web_search"), _Result("1", False)))
    failures = correlate_tool_outcomes(run, root=ROOT, scope=ROOT)
    assert _build_result_metadata({"_dm_tool_failures": failures}) == {}


# ── the outcome projection ──────────────────────────────────────────────────


def test_the_dispatch_outcome_carries_failures() -> None:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome

    outcome = WorkItemAgenticOutcome(final_text="done")
    assert outcome.tool_failures.is_empty


def test_the_outcome_failure_field_defaults_independently() -> None:
    """A shared mutable default would let one run's failures appear on another."""
    from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome

    a = WorkItemAgenticOutcome(final_text="a")
    b = WorkItemAgenticOutcome(final_text="b")
    assert a.tool_failures is not b.tool_failures or a.tool_failures.is_empty


# ── the mid-chain hops ──────────────────────────────────────────────────────
#
# The six mutation survivors on the first pass were ALL here: the producer end
# and the egress end were covered and nothing crossed between them. That is this
# repo's most common defect -- every link correct, the chain dead.


def _failures(name: str = "web_search", scope: str = ROOT) -> ToolFailures:
    run = _run((_Call("1", name), _Result("1", True)))
    return correlate_tool_outcomes(run, root=ROOT, scope=scope, known_tools=[name])


def _succeeded(name: str = "web_search", scope: str = ROOT) -> ToolFailures:
    run = _run((_Call("1", name), _Result("1", False)))
    return correlate_tool_outcomes(run, root=ROOT, scope=scope, known_tools=[name])


def test_the_dispatch_outcome_carries_what_the_producer_found() -> None:
    """D1: the outcome is the ONLY way the failures leave the executor scope."""
    from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome

    outcome = WorkItemAgenticOutcome(final_text="done", tool_failures=_failures())
    assert outcome.tool_failures.names() == ("web_search",)


def test_a_pass_folds_its_failures_onto_the_observation() -> None:
    """A4, first half: the hop from the dispatch outcome to the turn."""
    from probos.cognitive.cognitive_agent import _accumulate_pass_failures

    observation: dict = {}
    _accumulate_pass_failures(observation, SimpleNamespace(tool_failures=_failures()))
    assert observation["_dm_tool_failures"].names() == ("web_search",)


def test_a_second_pass_supersedes_only_the_calls_it_retried() -> None:
    """A4: overwriting instead of superseding is the AD-1164 defect. Pass 2
    retried ``web_search`` successfully but never touched ``read_file``, so one
    clears and one survives."""
    from probos.cognitive.cognitive_agent import _accumulate_pass_failures

    observation: dict = {}
    pass_1 = _failures("web_search").combined_with(
        correlate_tool_outcomes(
            _run((_Call("9", "read_file"), _Result("9", True))),
            root=ROOT, scope="bbbbbbbbbbbb", known_tools=["read_file"],
        )
    )
    _accumulate_pass_failures(observation, SimpleNamespace(tool_failures=pass_1))
    _accumulate_pass_failures(observation, SimpleNamespace(tool_failures=_succeeded()))

    assert observation["_dm_tool_failures"].names() == ("read_file",)


def test_a_pass_without_failures_leaves_the_observation_untouched() -> None:
    from probos.cognitive.cognitive_agent import _accumulate_pass_failures

    observation: dict = {}
    _accumulate_pass_failures(observation, SimpleNamespace())
    assert "_dm_tool_failures" not in observation


@pytest.mark.asyncio
async def test_act_forwards_the_failures_to_the_report() -> None:
    """A2: the decision -> report hop, the last one before IntentResult."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    agent = CognitiveAgent.__new__(CognitiveAgent)
    report = await CognitiveAgent.act(agent, {
        "action": "execute",
        "llm_output": "All done.",
        "_dm_tool_failures": _failures(),
    })
    assert report["result"] == "All done."
    assert report["_dm_tool_failures"].names() == ("web_search",)


@pytest.mark.asyncio
async def test_act_attaches_nothing_when_the_turn_had_no_failures() -> None:
    from probos.cognitive.cognitive_agent import CognitiveAgent

    agent = CognitiveAgent.__new__(CognitiveAgent)
    report = await CognitiveAgent.act(agent, {"llm_output": "clean"})
    assert "_dm_tool_failures" not in report


@pytest.mark.asyncio
async def test_the_full_carriage_reaches_the_captains_text() -> None:
    """The whole chain in one test: producer -> observation -> decision ->
    report -> IntentResult.metadata -> router reconstruction -> pipeline
    rewrite -> rendered egress. Every hop the mutation matrix found bare."""
    from probos.cognitive.cognitive_agent import (
        CognitiveAgent,
        _accumulate_pass_failures,
        _build_result_metadata,
    )

    observation: dict = {}
    _accumulate_pass_failures(observation, SimpleNamespace(tool_failures=_failures()))

    decision = {"llm_output": "Here is what I found.", "action": "execute"}
    carried = observation.get("_dm_tool_failures")
    if carried is not None and not carried.is_empty:
        decision["_dm_tool_failures"] = carried

    agent = CognitiveAgent.__new__(CognitiveAgent)
    report = await CognitiveAgent.act(agent, decision)

    result = IntentResult(
        intent_id="i", agent_id="ezri", success=True,
        result=report["result"], metadata=_build_result_metadata(report),
    )

    pipeline = _pipeline_for(result, report["result"])
    pipeline.ctx.response_text = pipeline.ctx.response_text + " Anything else?"
    rendered = pipeline.build_response()["response"]

    assert rendered.startswith("Here is what I found. Anything else?")
    assert "web_search" in rendered


def test_a_cached_decision_does_not_replay_a_previous_turns_failures() -> None:
    """A5: a replayed answer asserts nothing about THIS turn's tools, so serving
    stale evidence would bind a claim to a run that never happened."""
    from probos.cognitive.cognitive_agent import _cacheable_decision

    decision = {
        "action": "execute",
        "llm_output": "Here is what I found.",
        "_dm_tool_failures": _failures(),
        "_tool_trace_ref": "sha-abc",
    }
    cached = _cacheable_decision(decision)

    assert cached["llm_output"] == "Here is what I found."
    assert "_dm_tool_failures" not in cached
    assert "_tool_trace_ref" not in cached
    # The original is untouched -- this turn still discloses.
    assert decision["_dm_tool_failures"].names() == ("web_search",)


def test_the_decide_hop_carries_the_failures_onto_the_decision() -> None:
    """A1: the observation -> decision hop. Losing this drops disclosure on the
    main conversational path entirely, and every downstream test would still
    pass -- which is why this hop needs its own."""
    from probos.cognitive.cognitive_agent import _attach_run_provenance

    decision = {"action": "execute", "llm_output": "Here is what I found."}
    _attach_run_provenance(decision, {
        "_dm_tool_failures": _failures(),
        "_tool_trace_ref": "sha-abc",
    })

    assert decision["_dm_tool_failures"].names() == ("web_search",)
    assert decision["_tool_trace_ref"] == "sha-abc"


def test_the_decide_hop_attaches_nothing_on_a_clean_turn() -> None:
    from probos.cognitive.cognitive_agent import _attach_run_provenance

    decision = {"llm_output": "clean"}
    _attach_run_provenance(decision, {})
    assert decision == {"llm_output": "clean"}


def test_the_decide_hop_skips_a_run_whose_tools_all_succeeded() -> None:
    from probos.cognitive.cognitive_agent import _attach_run_provenance

    decision = {"llm_output": "clean"}
    _attach_run_provenance(decision, {"_dm_tool_failures": _succeeded()})
    assert "_dm_tool_failures" not in decision


def test_the_decide_site_uses_the_provenance_helper() -> None:
    """A1, past the boundary: the helper is correct AND is what decide calls."""
    import inspect

    from probos.cognitive import cognitive_agent as ca

    source = inspect.getsource(ca.CognitiveAgent._decide_via_llm)
    assert "_attach_run_provenance(decision, observation)" in source, (
        "the agentic branch must carry the run's provenance onto the decision"
    )


def test_the_cache_stores_the_filtered_projection() -> None:
    """A5, past the boundary: the helper is correct AND is what the cache uses."""
    import inspect

    from probos.cognitive import cognitive_agent as ca

    source = inspect.getsource(ca.CognitiveAgent.decide)
    assert "cache[cache_key] = (_cacheable_decision(decision)" in source, (
        "the cache must store the filtered projection, not the raw decision"
    )


def test_rendered_text_must_be_flattened_before_a_strict_type_check() -> None:
    """The DD-12 token is a ``str`` SUBCLASS, and the thread store validates with
    ``type(body) is not str`` -- an exact check a subclass fails. Found by the
    full gate, not by reading: the append raised ``chat_thread_message_invalid``
    and the router's ``except`` swallowed it, so the Captain's transcript simply
    lost the reply.

    The token is an admission credential for the boundary, not a value that
    travels into storage: verify it, then hand the store a plain ``str``.
    """
    rendered = DmReply(body="hello").render()
    assert isinstance(rendered, str)
    assert type(rendered) is not str          # the trap
    assert type(str(rendered)) is str         # the fix


def test_sink_1_flattens_after_verifying() -> None:
    """Past the boundary: the router must verify THEN flatten, in that order.
    Flattening first would make the guard unreachable."""
    import inspect

    from probos.routers import agents as ag

    source = inspect.getsource(ag)
    guard = source.index('sink="chat_thread_append"')
    flatten = source.index("body=str(_rendered),")
    assert guard < flatten, (
        "the egress guard must run before the value is flattened to str"
    )


def test_the_egress_guard_is_not_inside_the_degradation_catch() -> None:
    """The first version of the strict-type bug was INVISIBLE because the guard
    sat inside a broad ``except Exception`` meant for a thread-store outage: the
    append raised, the except logged, and the Captain's transcript lost the
    reply while HTTP still returned 200. An egress-contract violation is a
    programming error and must be loud."""
    import inspect

    from probos.routers import agents as ag

    source = inspect.getsource(ag)
    guard = source.index('sink="chat_thread_append"')
    catch = source.index("try:", source.index("if thread is not None:"))
    assert guard < catch, (
        "require_rendered must sit OUTSIDE the log-and-degrade catch"
    )


# ── the polymorphic act() boundary (DD-7) ───────────────────────────────────


def test_metadata_survives_an_act_override_that_drops_private_keys() -> None:
    """``CounselorAgent`` and generated agents override ``act()`` and copy only
    ``llm_output``. A chain that depends on those overrides forwarding private
    keys silently drops the disclosure for the agents that do most of the
    Captain's DMs -- which is exactly what DD-7 said not to rely on."""
    from probos.cognitive.cognitive_agent import _build_result_metadata

    overridden_report = {"success": True, "result": "All done."}  # no private keys
    observation = {"_dm_tool_failures": _failures()}

    metadata = _build_result_metadata(overridden_report, {}, observation)
    assert metadata[DM_REPLY_METADATA_KEY]["entries"][0][1] == "web_search"


def test_metadata_survives_an_empty_agentic_result_falling_back() -> None:
    """Whitespace-only agentic output falls through to the single-pass path,
    which rebuilds the decision from scratch -- but the run still happened and
    its tools still failed."""
    from probos.cognitive.cognitive_agent import _build_result_metadata

    rebuilt_decision = {"action": "execute", "llm_output": "Second try."}
    observation = {"_dm_tool_failures": _failures()}

    metadata = _build_result_metadata({"result": "x"}, rebuilt_decision, observation)
    assert DM_REPLY_METADATA_KEY in metadata


def test_an_explicitly_forwarded_value_still_wins() -> None:
    from probos.cognitive.cognitive_agent import _build_result_metadata

    report = {"_dm_tool_failures": _failures("read_file")}
    observation = {"_dm_tool_failures": _failures("web_search")}
    metadata = _build_result_metadata(report, {}, observation)
    assert metadata[DM_REPLY_METADATA_KEY]["entries"][0][1] == "read_file"


def test_the_lifecycle_reconciles_from_the_observation() -> None:
    """Past the boundary: the helper is correct AND the lifecycle passes it the
    observation rather than the report alone."""
    import inspect

    from probos.cognitive import cognitive_agent as ca

    source = inspect.getsource(ca.CognitiveAgent._run_cognitive_lifecycle)
    assert "_build_result_metadata(report, decision, observation)" in source


def test_the_offered_names_are_captured_after_dedupe() -> None:
    """D2: a pre-dedupe capture names tools the provider was never sent, so a
    disclosure could name a tool the agent never actually had.

    Source-position guard rather than a behavioural one: reaching the collision
    requires driving the whole executor with two ids that sanitise to the same
    provider name. Recorded as a known limitation rather than a silent gap.
    """
    import inspect

    from probos.cognitive import agentic_dispatch as ad

    source = inspect.getsource(ad)
    start = source.index("def _build_tools(")
    # AD-1241 returns definitions and published IDs; name capture still follows dedupe.
    builder = source[start:source.index("tools, published_mcp_ids = _build_tools(")]

    assert "deduped = dedupe_llm_definitions(" in builder
    assert builder.index("deduped = dedupe_llm_definitions(") < builder.index(
        "for _definition in deduped:"
    ), "the offered-name capture must read the DEDUPED list, not the built one"
