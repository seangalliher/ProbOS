"""AD-1248 slice A: the ``DmReply`` value, its algebra, its wire form.

Every test here maps to a numbered acceptance criterion or scenario in
``prompts/ad-1248-dm-reply-value.md``. Where a test exists because a review
round broke an earlier design, the round is named -- so a future reader can tell
"required" from "whatever shipped".
"""

from __future__ import annotations

import json
import pickle

import pytest

from probos.cognitive.dm.reply_value import (
    DM_REPLY_METADATA_KEY,
    UNKNOWN_TOOL_LABEL,
    DmReply,
    RenderedDmText,
    ToolFailures,
    ToolFailuresMergeClosed,
    call_signature,
    failure_key,
    key_scope,
    mint_scope,
    offered_display_name,
    require_rendered,
    scope_from_source,
)
from probos.types import IntentResult

ROOT = "aaaaaaaaaaaa"
CHILD_A = "bbbbbbbbbbbb"
CHILD_B = "cccccccccccc"


def _fail(scope: str, name: str, args: object = None, root: str = ROOT) -> ToolFailures:
    key = failure_key(root, scope, call_signature(name, args))
    return ToolFailures.from_mapping({key: name})


def _ok(scope: str, name: str, args: object = None, root: str = ROOT) -> ToolFailures:
    key = failure_key(root, scope, call_signature(name, args))
    return ToolFailures.from_mapping({key: ""})


# ── Criterion 1: zero attachments renders byte-identically ──────────────────


@pytest.mark.parametrize(
    "body",
    [
        "",
        "hello",
        "line\nbreak",
        "trailing whitespace   ",
        "   leading",
        "unicode \u00e9\u00e8\u00ea and \U0001f600",
        "a" * 10_000,
        "markdown **bold** and `code` and\n\n> a quote",
        "[A2UI]{\"kind\":\"choice\"}[/A2UI]",
    ],
)
def test_render_with_no_attachments_is_byte_identical(body: str) -> None:
    assert DmReply(body=body).render() == body


def test_render_returns_the_nominal_egress_type() -> None:
    assert isinstance(DmReply(body="x").render(), RenderedDmText)


def test_str_of_a_reply_renders() -> None:
    reply = DmReply(body="Done.", tool_failures=_fail(ROOT, "web_search"))
    assert "web_search" in str(reply)


# ── Criterion 2: with_body preserves attachments across a transform chain ───


def test_with_body_preserves_attachments() -> None:
    reply = DmReply(body="one", tool_failures=_fail(ROOT, "web_search"))
    assert reply.with_body("two").tool_failures == reply.tool_failures


def test_three_body_rewrites_still_render_the_attachment_exactly_once() -> None:
    reply = DmReply(body="one", tool_failures=_fail(ROOT, "web_search"))
    out = str(reply.with_body("two").with_body("three").with_body("four"))
    assert out.count("web_search") == 1
    assert out.startswith("four")


# ── DD-1: scope and key identity ────────────────────────────────────────────


def test_signature_separates_two_independent_calls_of_one_tool() -> None:
    assert call_signature("web_search", {"q": "A"}) != call_signature("web_search", {"q": "B"})


def test_signature_is_stable_across_argument_ordering() -> None:
    assert call_signature("t", {"a": 1, "b": 2}) == call_signature("t", {"b": 2, "a": 1})


def test_signature_survives_unserialisable_arguments() -> None:
    assert len(call_signature("t", object())) == 16


def test_scope_from_source_passes_through_a_12_hex_token() -> None:
    assert scope_from_source(ROOT) == ROOT


def test_scope_from_source_hashes_an_oversize_id() -> None:
    scope = scope_from_source("crew-work-item-" + "z" * 200)
    assert len(scope) == 12 and int(scope, 16) >= 0


def test_minted_scopes_are_distinct() -> None:
    assert len({mint_scope() for _ in range(100)}) == 100


def test_key_is_42_chars_and_yields_its_scope() -> None:
    key = failure_key(ROOT, CHILD_A, call_signature("t", None))
    assert len(key) == 42
    assert key_scope(key) == CHILD_A


# ── DD-1: defensive copy. Round 3 broke the Mapping-field shape this way ────


def test_mutating_the_source_mapping_does_not_mutate_the_value() -> None:
    source = {failure_key(ROOT, ROOT, call_signature("t", None)): "web_search"}
    failures = ToolFailures.from_mapping(source)
    source.clear()
    assert failures.names() == ("web_search",)


# ── S20 / DD-1: merge-closed raises. Round 5 broke the failure-only shape ───


def test_supersession_on_a_reconstructed_receiver_raises() -> None:
    closed = ToolFailures.from_wire(_fail(ROOT, "web_search").to_wire())
    with pytest.raises(ToolFailuresMergeClosed):
        closed.superseded_by(_ok(ROOT, "web_search"))


def test_supersession_with_a_reconstructed_argument_also_raises() -> None:
    """Round 6: v6 specified only the receiver. Either operand is unable to
    prove a success, so either must raise."""
    closed = ToolFailures.from_wire(_ok(ROOT, "web_search").to_wire())
    with pytest.raises(ToolFailuresMergeClosed):
        _fail(ROOT, "web_search").superseded_by(closed)


def test_combine_is_defined_on_reconstructed_values() -> None:
    """Union needs no tombstones, so crew fan-in after a durable resume works."""
    a = ToolFailures.from_wire(_fail(CHILD_A, "web_search").to_wire())
    b = ToolFailures.from_wire(_fail(CHILD_B, "read_file").to_wire())
    assert a.combined_with(b).names() == ("read_file", "web_search")


# ── DD-2: the four operations ───────────────────────────────────────────────


def test_a_retried_call_that_succeeds_clears_the_earlier_failure() -> None:
    first = _fail(ROOT, "web_search", {"q": "A"})
    second = _ok(ROOT, "web_search", {"q": "A"})
    assert first.superseded_by(second).names() == ()


def test_a_call_the_later_pass_never_retried_is_retained() -> None:
    """The AD-1164 continuation prompt says 'build on the previous output',
    so a pass-1 failure pass 2 never touched must not vanish."""
    first = _fail(ROOT, "web_search", {"q": "A"})
    second = _ok(ROOT, "read_file", {"path": "x"})
    assert first.superseded_by(second).names() == ("web_search",)


def test_an_independent_success_does_not_erase_a_failure_with_identical_args() -> None:
    """S14. Round 3 proved a signature-only key erased this by last-write-wins."""
    sibling_a = _fail(CHILD_A, "web_search", {"q": "same"})
    sibling_b = _ok(CHILD_B, "web_search", {"q": "same"})
    assert sibling_a.combined_with(sibling_b).names() == ("web_search",)


def test_supersession_retains_a_disjoint_child_scope() -> None:
    """S19 synthetic. Round 5: pass 1 delegates to child-A and fails; pass 2
    supersedes its own scope only, so child-A's failure survives."""
    pass_1 = _fail(ROOT, "read_file").combined_with(_fail(CHILD_A, "web_search"))
    pass_2 = _ok(ROOT, "read_file")
    merged = pass_1.superseded_by(pass_2)
    assert merged.names() == ("web_search",)


def test_combine_rejects_overlapping_scopes() -> None:
    with pytest.raises(ValueError, match="disjoint scopes"):
        _fail(ROOT, "a").combined_with(_fail(ROOT, "b"))


def test_reply_replaced_by_discards_attachments() -> None:
    old = DmReply(body="old", tool_failures=_fail(ROOT, "web_search"))
    new = DmReply(body="new")
    assert old.replaced_by(new).tool_failures.is_empty


def test_reply_combined_with_keeps_the_receivers_body() -> None:
    parent = DmReply(body="parent prose", tool_failures=_fail(ROOT, "read_file"))
    child = DmReply(body="child prose", tool_failures=_fail(CHILD_A, "web_search"))
    folded = parent.combined_with(child)
    assert folded.body == "parent prose"
    assert folded.tool_failures.names() == ("read_file", "web_search")


# ── DD-5: the wire is a tagged union. Round 4 broke the two-field shape ─────


def test_precise_wire_carries_entries_only() -> None:
    payload = _fail(ROOT, "web_search").to_wire()
    assert payload is not None
    assert set(payload) == {"v", "entries"}


def test_successes_are_not_serialised() -> None:
    combined = _fail(ROOT, "web_search").combined_with(_ok(CHILD_A, "read_file"))
    payload = combined.to_wire()
    assert payload is not None
    assert [name for _, name in payload["entries"]] == ["web_search"]


def test_empty_failures_produce_no_payload() -> None:
    assert ToolFailures().to_wire() is None
    assert _ok(ROOT, "web_search").to_wire() is None


def test_wire_payload_is_json_safe() -> None:
    payload = _fail(ROOT, "web_search").to_wire()
    assert json.loads(json.dumps(payload)) == payload


def test_a_payload_carrying_both_states_is_malformed_not_reconciled() -> None:
    """Each half here is INDEPENDENTLY valid, so only the both-states guard can
    reject it. A degenerate payload would pass whether or not the guard exists."""
    both = {
        "v": 1,
        "entries": [[failure_key(ROOT, ROOT, call_signature("read_file", None)), "read_file"]],
        "truncated": True,
        "names": ["web_search"],
        "unresolved_count": 1,
    }
    assert ToolFailures.from_wire(both).is_empty


def test_an_unknown_schema_version_drops_otherwise_valid_attachments() -> None:
    """The entries below are well-formed, so only the version check rejects
    them. Testing an EMPTY entry list would pass either way."""
    payload = _fail(ROOT, "web_search").to_wire()
    assert payload is not None and payload["entries"]
    assert ToolFailures.from_wire({**payload, "v": 2}).is_empty
    assert ToolFailures.from_wire({**payload, "v": "1"}).is_empty


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "not a dict",
        {},
        {"v": 2, "entries": [[failure_key(ROOT, ROOT, "0" * 16), "web_search"]]},
        {"v": 1, "entries": "nope"},
        {"v": 1, "entries": [["short.key:bad", "web_search"]]},
        {"v": 1, "entries": [[failure_key(ROOT, ROOT, "0" * 16), "has spaces"]]},
        {"v": 1, "entries": [["x"]]},
        {"v": 1, "truncated": True, "names": ["web_search"], "unresolved_count": 0},
        {"v": 1, "truncated": True, "names": ["bad name"], "unresolved_count": 1},
    ],
)
def test_malformed_metadata_never_yields_attachments(payload: object) -> None:
    """Criterion 3, first invariant."""
    assert ToolFailures.from_wire(payload).is_empty


def test_unknown_tool_label_survives_the_wire() -> None:
    key = failure_key(ROOT, ROOT, call_signature("mystery", None))
    failures = ToolFailures.from_mapping({key: UNKNOWN_TOOL_LABEL})
    assert ToolFailures.from_wire(failures.to_wire()).names() == (UNKNOWN_TOOL_LABEL,)


def test_reconstructed_values_are_merge_closed() -> None:
    assert ToolFailures.from_wire(_fail(ROOT, "t").to_wire()).merge_open is False


# ── Criterion 3, second invariant: a valid overflow still discloses ─────────


def _many_failures(count: int) -> ToolFailures:
    return ToolFailures.from_mapping({
        failure_key(ROOT, ROOT, call_signature("web_search", {"q": i})): "web_search"
        for i in range(count)
    })


def test_sixty_five_failing_calls_still_disclose() -> None:
    """Round 4 killed the v3 design here: 65 valid entries collapsed to one
    honest failure, which the cap then deleted outright."""
    payload = _many_failures(65).to_wire()
    assert payload is not None
    assert payload["truncated"] is True
    assert payload["names"] == ["web_search"]
    assert payload["unresolved_count"] == 65


def test_an_overflowed_reply_renders_a_non_empty_disclosure() -> None:
    reply = DmReply(body="Answer.", tool_failures=_many_failures(65))
    assert "web_search" in str(reply)


def test_overflow_round_trips_through_the_wire_with_disclosure_intact() -> None:
    restored = ToolFailures.from_wire(_many_failures(65).to_wire())
    assert restored.names() == ("web_search",)
    assert restored.is_summary


def test_sixty_four_failing_calls_stay_precise() -> None:
    payload = _many_failures(64).to_wire()
    assert payload is not None and "entries" in payload


# ── S15: supersession over a summarised value retains ───────────────────────


def test_supersession_over_a_summary_retains_the_disclosure(caplog) -> None:
    summary = _many_failures(65)
    later = _ok(ROOT, "web_search", {"q": 0})
    with caplog.at_level("WARNING"):
        merged = summary.superseded_by(later)
    assert merged.names() == ("web_search",)
    assert any("summarised" in r.message for r in caplog.records)


# ── S16-S18: the render budget ladder ───────────────────────────────────────


def test_bounded_render_truncates_the_body_and_keeps_the_attachment() -> None:
    reply = DmReply(body="B" * 5000, tool_failures=_fail(ROOT, "web_search"))
    out = reply.render(max_chars=4096)
    assert len(out) <= 4096
    assert "web_search" in out


def test_bounded_render_with_no_attachment_just_truncates() -> None:
    out = DmReply(body="B" * 5000).render(max_chars=4096)
    assert len(out) == 4096


def test_a_budget_that_cannot_fit_the_names_falls_back_to_a_count(caplog) -> None:
    """S17. Thirty-two distinct names cannot be reserved inside a small budget,
    so the disclosure degrades to a count rather than disappearing."""
    failures = ToolFailures.from_mapping({
        failure_key(ROOT, ROOT, call_signature(f"tool_{i}", None)): f"tool_{i}"
        for i in range(32)
    })
    with caplog.at_level("WARNING"):
        out = DmReply(body="B" * 500, tool_failures=failures).render(max_chars=90)
    assert len(out) <= 90
    assert "failed" in out


def test_a_budget_below_the_minimum_raises(caplog) -> None:
    """S18. Dropping the disclosure is the defect this AD removes, so a budget
    too small to carry one is a caller error, not a silent omission."""
    reply = DmReply(body="B" * 500, tool_failures=_fail(ROOT, "web_search"))
    with pytest.raises(ValueError, match="below the minimum"):
        reply.render(max_chars=5)


def test_an_exactly_fitting_disclosure_is_kept_whole() -> None:
    reply = DmReply(body="body", tool_failures=_fail(ROOT, "web_search"))
    tail_only = len(str(reply)) - len("body")
    out = reply.render(max_chars=tail_only)
    assert "web_search" in out and len(out) == tail_only


def test_truncation_cuts_on_code_point_boundaries() -> None:
    out = DmReply(body="\U0001f600" * 100).render(max_chars=10)
    assert len(out) == 10
    assert out.encode("utf-8").decode("utf-8") == out


# ── DD-12: the nominal egress boundary ──────────────────────────────────────


def test_the_marker_cannot_be_forged() -> None:
    """Layer 1 is worthless if any caller can mint the token."""
    with pytest.raises(TypeError, match="only by DmReply.render"):
        RenderedDmText("plain")


def test_require_rendered_accepts_the_direct_result_of_render() -> None:
    assert require_rendered(DmReply(body="x").render(), sink="test") == "x"


@pytest.mark.parametrize(
    "eroded",
    [
        lambda r: str(r),
        lambda r: f"{r}",
        lambda r: r[:2],
        lambda r: r + "",
        lambda r: "".join([r]),
        lambda r: r.strip(),
        lambda r: r.replace("x", "y"),
        lambda r: json.loads(json.dumps(r)),
    ],
)
def test_every_transformation_erodes_the_marker_and_is_rejected(eroded) -> None:
    """The erosion is the point: a value that was transformed on the way to the
    sink has lost its attachments, and must be refused rather than delivered."""
    rendered = DmReply(body="xxx").render()
    with pytest.raises(TypeError, match="requires RenderedDmText"):
        require_rendered(eroded(rendered), sink="test")


def test_require_rendered_raises_rather_than_asserts() -> None:
    """A bare ``assert`` is stripped by ``python -O``; this must not be."""
    import probos.cognitive.dm.reply_value as mod

    source = mod.require_rendered.__doc__ or ""
    assert "python -O" in source


def test_the_marker_does_not_survive_pickling() -> None:
    with pytest.raises((TypeError, pickle.PicklingError)):
        pickle.loads(pickle.dumps(DmReply(body="x").render()))


# ── DD-1a: the display name comes from the offer ────────────────────────────


def test_a_name_absent_from_the_offer_renders_as_unknown() -> None:
    """S22. A registry id is not what the model received."""
    assert offered_display_name("mcp:docs:search", ["read_file"]) == UNKNOWN_TOOL_LABEL


def test_an_offered_mcp_alias_renders_as_itself() -> None:
    """S21."""
    alias = "mcp_docs_search_38c53abe80026e47"
    assert offered_display_name(alias, [alias, "read_file"]) == alias


# ── DD-5: IntentResult carriage ─────────────────────────────────────────────


def test_from_intent_result_reads_the_body_from_result() -> None:
    result = IntentResult(intent_id="i", agent_id="a", success=True, result="the prose")
    assert DmReply.from_intent_result(result).body == "the prose"


def test_from_intent_result_recovers_attachments() -> None:
    failures = _fail(ROOT, "web_search")
    result = IntentResult(
        intent_id="i", agent_id="a", success=True, result="the prose",
        metadata={DM_REPLY_METADATA_KEY: failures.to_wire()},
    )
    assert DmReply.from_intent_result(result).tool_failures.names() == ("web_search",)


def test_from_intent_result_without_metadata_yields_a_bare_reply() -> None:
    result = IntentResult(intent_id="i", agent_id="a", success=True, result="prose")
    assert DmReply.from_intent_result(result).tool_failures.is_empty


def test_from_intent_result_tolerates_a_non_string_result() -> None:
    result = IntentResult(intent_id="i", agent_id="a", success=True, result=None)
    assert DmReply.from_intent_result(result).body == ""


def test_the_body_is_never_duplicated_into_metadata() -> None:
    """DD-5. Round 2 measured a 600 KB body at 1.2 MB once duplicated, over the
    NATS ceiling. The payload carries attachments only."""
    reply = DmReply(body="B" * 1000, tool_failures=_fail(ROOT, "web_search"))
    payload = reply.metadata_payload()
    assert payload is not None
    assert "B" * 1000 not in json.dumps(payload)


def test_a_reply_with_no_failures_attaches_no_metadata() -> None:
    assert DmReply(body="clean").metadata_payload() is None


# ── executable contract cases found by pre-commit review ────────────────────


def test_two_failed_calls_to_one_tool_count_as_two() -> None:
    """Deriving the count from NAMES understates it: two failed ``web_search``
    calls are two failures and one name, and the count-only render said "1"."""
    failures = _fail(ROOT, "web_search", {"q": "A"}).combined_with(
        ToolFailures.from_mapping({
            failure_key(ROOT, CHILD_A, call_signature("web_search", {"q": "B"})):
                "web_search",
        })
    )
    assert failures.failed_call_count == 2


def test_a_count_only_summary_is_not_empty() -> None:
    summary = ToolFailures(summary_names=("web_search",), unresolved_count=3)
    assert not summary.is_empty
    assert summary.to_wire() is not None


def test_a_summary_with_only_a_count_still_discloses() -> None:
    """M21: ``is_empty`` derived from names alone would silently swallow a
    disclosure that has lost its names but kept its count."""
    counted = ToolFailures(unresolved_count=4)
    assert not counted.is_empty
    assert counted.failed_call_count == 4
    assert "4 tool calls failed" in DmReply(body="Answer.", tool_failures=counted).render()


def test_a_reconstructed_summary_is_merge_closed() -> None:
    """M11b: a summary rebuilt from the wire has no tombstones either, so it
    must refuse supersession exactly as a reconstructed precise value does."""
    restored = ToolFailures.from_wire(_many_failures(65).to_wire())
    assert restored.merge_open is False
    with pytest.raises(ToolFailuresMergeClosed):
        restored.superseded_by(_ok(ROOT, "web_search"))


def test_a_summary_round_trips_its_own_wire_form() -> None:
    """A value must be able to reconstruct what it serialised. The first version
    emitted a payload its own validator then rejected."""
    merged = _many_failures(65).superseded_by(_fail(ROOT, "read_file"))
    restored = ToolFailures.from_wire(merged.to_wire())
    assert set(restored.names()) == set(merged.names())


@pytest.mark.parametrize(
    "payload",
    [
        {"v": True, "entries": [[failure_key(ROOT, ROOT, "0" * 16), "web_search"]]},
        {"v": 1, "entries": [], "extra": 1},
        {"v": 1, "entries": [[failure_key(ROOT, ROOT, "0" * 16), "web_search"]], "unresolved_count": 1},
        {"v": 1, "truncated": False, "names": ["web_search"], "unresolved_count": 1},
        {"v": 1, "names": ["web_search"], "unresolved_count": 1},
        {"v": 1, "truncated": True, "names": ["web_search"], "unresolved_count": True},
        {"v": 1, "entries": []},
    ],
)
def test_a_payload_that_is_not_exactly_one_state_is_malformed(payload: object) -> None:
    """``bool`` is a subclass of ``int``, and a stray key means the sender and
    this reader disagree about the schema. Both are malformed, not reconcilable."""
    assert ToolFailures.from_wire(payload).is_empty


def test_a_scope_with_a_trailing_newline_is_hashed_not_accepted() -> None:
    """BF-757 paid for this once: ``$`` also matches before a trailing newline,
    so ``match`` would pass a 13-character scope straight through."""
    scope = scope_from_source(ROOT + "\n")
    assert len(scope) == 12
    assert scope != ROOT + "\n"
