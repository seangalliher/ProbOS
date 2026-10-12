"""AD-1299 S1b (#1352) M1: C8 (expected assignee) and C9 (evidence completion).

Pins the pure contract S1b adds to ``src/probos/cognitive/repair_candidate.py``:

* C8: ``bind_reviews`` requires the campaign's builder as ``expected_assignee`` and refuses a
  review set that names any other assignee (``review_assignee_mismatch``) without changing the
  review-set digest.
* C9: ``evaluate_completion`` says whether the links supplied for one candidate cover every
  evidence kind its authority class requires, and ``EvidenceCompleteness`` refuses an
  inconsistent report.

Premise rule (as in the S1a file): every refusal test first asserts that the UNMODIFIED premise
binds or completes, then asserts the exact reason, so the reason proves which rule was reached.

``evaluate_completion`` judges links, so its tests build ``EvidenceLink`` instances directly; the
one test that crosses the producer -> consumer seam feeds real ``bind_reviews`` output into it.
This file imports the module's real ``bind_reviews``. The S1a test module's ``bind_reviews`` is an
adapter that supplies ``expected_assignee="builder"``; C8 must never be tested through it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect

import pytest

from probos.cognitive.repair_candidate import (
    AUTHORITY_CLASSES,
    COMPLETION_REASONS,
    REASON_CODES,
    REQUIRED_EVIDENCE_KINDS,
    AuthorityClass,
    EvidenceCompleteness,
    EvidenceLink,
    RepairCandidate,
    bind_reviews,
    evaluate_completion,
    is_evidence_ref,
    is_sha256_hex,
)
from probos.federation.ard.jcs import canonicalize as jcs_canonicalize
from tests.test_ad1299_s1a_repair_candidate import _pure_candidate, _Review

REVIEW_SET_DOMAIN = b"probos.repair_candidate/review_set/v1\x00"
_CLASSES = ("repair", "maintenance", "enhancement")


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


class _StrSubclass(str):
    """A ``str`` that is not exactly ``str``: every validator here checks ``type(x) is str``."""


class _FakeCandidate:
    """Duck-types ``RepairCandidate.digest``; ``evaluate_completion`` must still refuse it."""

    def digest(self) -> str:
        return "0" * 64


class _FakeLink:
    """Carries every ``EvidenceLink`` attribute ``evaluate_completion`` reads, but is not one."""

    kind = "review_set"
    current = True
    candidate_digest = "0" * 64


def _other_candidate() -> RepairCandidate:
    """The same commits against another tree: a different candidate identity."""
    return RepairCandidate("a" * 40, "b" * 40, "e" * 40, "e" * 40)


def _present_gate(digest: str, evidence: str = "1" * 64) -> EvidenceLink:
    return EvidenceLink("gate_receipt", "present", "gate_receipt_bound", digest, evidence)


def _present_review(digest: str, evidence: str = "2" * 64) -> EvidenceLink:
    return EvidenceLink("review_set", "present", "review_set_bound", digest, evidence)


def _refused_gate(digest: str) -> EvidenceLink:
    return EvidenceLink("gate_receipt", "refused", "gate_receipt_tree_mismatch", digest, "3" * 64)


def _unavailable_review(digest: str) -> EvidenceLink:
    return EvidenceLink("review_set", "unavailable", "review_set_absent", digest)


def _assert_refused(error: type[Exception], message: str, *args: object) -> None:
    """``evaluate_completion(*args)`` raises exactly ``error`` with exactly ``(message,)``."""
    try:
        evaluate_completion(*args)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 -- the assertion below names exactly what must be raised
        assert type(exc) is error and exc.args == (message,), (type(exc), exc.args, args)
    else:
        pytest.fail(f"evaluate_completion did not raise {error.__name__}({message!r}) for {args!r}")


# ---------------------------------------------------------------------------
# C8: expected assignee
# ---------------------------------------------------------------------------


def test_bind_reviews_expected_assignee_is_required_keyword_only() -> None:
    parameter = inspect.signature(bind_reviews).parameters["expected_assignee"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty
    candidate = _pure_candidate()
    # premise: the same call binds once the keyword is supplied
    premise = bind_reviews(candidate, [_Review()], expected_assignee="builder")
    assert (premise.status, premise.reason) == ("present", "review_set_bound")

    with pytest.raises(TypeError) as excinfo:
        bind_reviews(candidate, [_Review()])  # type: ignore[call-arg]

    assert "expected_assignee" in str(excinfo.value)


@pytest.mark.parametrize("with_reviews", [True, False], ids=["one-review", "no-reviews"])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="none"),
        pytest.param("", id="empty"),
        pytest.param("-x", id="leading-dash"),
        pytest.param("a b", id="space"),
        pytest.param("a" * 129, id="129-chars"),
        pytest.param(5, id="int"),
        pytest.param(_StrSubclass("builder"), id="str-subclass"),
    ],
)
def test_bind_reviews_invalid_expected_assignee_raises(value: object, with_reviews: bool) -> None:
    candidate = _pure_candidate()
    reviews = [_Review()] if with_reviews else None
    # premise: a valid expected assignee does not raise for the same reviews
    premise = bind_reviews(candidate, reviews, expected_assignee="builder")
    assert premise.reason == ("review_set_bound" if with_reviews else "review_set_absent")

    with pytest.raises(ValueError) as excinfo:
        bind_reviews(candidate, reviews, expected_assignee=value)  # type: ignore[arg-type]

    assert excinfo.value.args == ("review_expected_assignee_invalid",)


def test_review_naming_another_assignee_is_refused() -> None:
    candidate = _pure_candidate()
    review = _Review()
    assert review.assignee_id == "builder"
    # premise: a review naming the campaign's builder binds
    premise = bind_reviews(candidate, [review], expected_assignee="builder")
    assert (premise.status, premise.reason) == ("present", "review_set_bound")

    link = bind_reviews(
        candidate, [dataclasses.replace(review, assignee_id="someone_else")], expected_assignee="builder",
    )

    assert (link.status, link.reason) == ("refused", "review_assignee_mismatch")
    assert link.current is False
    assert link.candidate_digest == candidate.digest()
    assert len(link.evidence_sha256) == 64  # the set was readable: a refusal, not unavailability


def test_builder_self_review_relabelled_is_refused() -> None:
    candidate = _pure_candidate()
    relabelled = _Review(reviewer_id="builder", assignee_id="decoy")
    # S1a independence alone accepts it: the reviewer differs from the (decoy) assignee it names
    premise = bind_reviews(candidate, [relabelled], expected_assignee="decoy")
    assert (premise.status, premise.reason) == ("present", "review_set_bound")

    link = bind_reviews(candidate, [relabelled], expected_assignee="builder")

    assert (link.status, link.reason) == ("refused", "review_assignee_mismatch")


@pytest.mark.parametrize("mismatched", [0, 1], ids=["first-mismatched", "last-mismatched"])
def test_mixed_assignees_are_refused(mismatched: int) -> None:
    candidate = _pure_candidate()
    reviews = [
        _Review(review_attempt_id="attempt-1", reviewer_id="red_team"),
        _Review(review_attempt_id="attempt-2", reviewer_id="system_qa"),
    ]
    # premise: both naming the builder, from two distinct reviewers, bind
    premise = bind_reviews(candidate, reviews, expected_assignee="builder", required_reviewers=2)
    assert (premise.status, premise.reason) == ("present", "review_set_bound")
    reviews[mismatched] = dataclasses.replace(reviews[mismatched], assignee_id="other")

    link = bind_reviews(candidate, reviews, expected_assignee="builder", required_reviewers=2)

    assert (link.status, link.reason) == ("refused", "review_assignee_mismatch")


def test_reviewer_equal_to_expected_assignee_is_not_independent() -> None:
    candidate = _pure_candidate()
    # premise: a different reviewer of the builder's work binds
    premise = bind_reviews(candidate, [_Review(reviewer_id="red_team")], expected_assignee="builder")
    assert (premise.status, premise.reason) == ("present", "review_set_bound")

    link = bind_reviews(
        candidate, [_Review(reviewer_id="builder", assignee_id="builder")], expected_assignee="builder",
    )

    assert (link.status, link.reason) == ("refused", "review_not_independent")


def test_assignee_check_order() -> None:
    candidate = _pure_candidate()
    first = _Review(review_attempt_id="attempt-1", reviewer_id="red_team")
    second = _Review(review_attempt_id="attempt-2", reviewer_id="system_qa")
    # premise: the two reviews bind
    premise = bind_reviews(candidate, [first, second], expected_assignee="builder", required_reviewers=2)
    assert (premise.status, premise.reason) == ("present", "review_set_bound")

    # a duplicate attempt id is judged before the assignee ...
    mismatched = dataclasses.replace(second, assignee_id="someone_else")
    assert bind_reviews(
        candidate, [first, mismatched], expected_assignee="builder", required_reviewers=2,
    ).reason == "review_assignee_mismatch"  # attribution: without the duplicate this is the mismatch
    duplicated = dataclasses.replace(mismatched, review_attempt_id="attempt-1")
    link = bind_reviews(candidate, [first, duplicated], expected_assignee="builder", required_reviewers=2)
    assert link.reason == "review_attempt_duplicate"

    # ... and the assignee is judged before independence
    self_reviewed = _Review(reviewer_id="someone_else", assignee_id="someone_else")
    assert bind_reviews(
        candidate, [self_reviewed], expected_assignee="someone_else",
    ).reason == "review_not_independent"  # attribution: under a matching assignee it is a self review
    link = bind_reviews(candidate, [self_reviewed], expected_assignee="builder")
    assert link.reason == "review_assignee_mismatch"


def test_review_set_digest_unchanged_by_c8() -> None:
    candidate = _pure_candidate()
    first = _Review(review_attempt_id="attempt-1", reviewer_id="red_team")
    second = _Review(review_attempt_id="attempt-2", reviewer_id="system_qa")

    # supplied out of order: the digest orders the reviews by attempt id
    link = bind_reviews(candidate, [second, first], expected_assignee="builder", required_reviewers=2)

    assert (link.status, link.reason) == ("present", "review_set_bound")
    expected = hashlib.sha256(
        REVIEW_SET_DOMAIN
        + jcs_canonicalize({
            "schema_version": 1,
            "candidate": candidate.digest(),
            "reviews": [
                {
                    "review_attempt_id": review.review_attempt_id,
                    "reviewer_id": review.reviewer_id,
                    "assignee_id": review.assignee_id,
                    "reviewed_tree": review.reviewed_tree,
                    "accepted": review.accepted,
                }
                for review in (first, second)
            ],
        })
    ).hexdigest()
    assert link.evidence_sha256 == expected
    # the expected assignee is a verdict input, not digest material: the same set refused under
    # another expected assignee records the same digest
    refused = bind_reviews(candidate, [second, first], expected_assignee="someone_else", required_reviewers=2)
    assert (refused.status, refused.reason) == ("refused", "review_assignee_mismatch")
    assert refused.evidence_sha256 == link.evidence_sha256


def test_assignee_mismatch_is_a_refused_reason() -> None:
    candidate = _pure_candidate()
    assert "review_assignee_mismatch" in REASON_CODES

    link = bind_reviews(
        candidate, [_Review(assignee_id="someone_else")], expected_assignee="builder",
    )

    assert link.reason == "review_assignee_mismatch"
    assert link.status == "refused"
    assert link.current is False
    # a link may carry the reason only as a refusal
    assert EvidenceLink("review_set", "refused", "review_assignee_mismatch", candidate.digest()).status == "refused"
    with pytest.raises(ValueError) as excinfo:
        EvidenceLink("review_set", "unavailable", "review_assignee_mismatch", candidate.digest())
    assert excinfo.value.args == ("evidence_link_invalid",)


# ---------------------------------------------------------------------------
# C9: required evidence per authority class
# ---------------------------------------------------------------------------


def test_required_evidence_kinds_table_is_pinned_and_read_only() -> None:
    assert type(AUTHORITY_CLASSES) is frozenset
    assert AUTHORITY_CLASSES == frozenset({"repair", "maintenance", "enhancement"})
    assert set(REQUIRED_EVIDENCE_KINDS) == AUTHORITY_CLASSES
    for authority_class, kinds in REQUIRED_EVIDENCE_KINDS.items():
        assert kinds == frozenset({"gate_receipt", "review_set"}), authority_class
        assert type(kinds) is frozenset, authority_class

    with pytest.raises(TypeError):
        REQUIRED_EVIDENCE_KINDS["repair"] = frozenset()  # type: ignore[index]
    with pytest.raises(TypeError):
        del REQUIRED_EVIDENCE_KINDS["repair"]  # type: ignore[attr-defined]
    assert REQUIRED_EVIDENCE_KINDS["repair"] == frozenset({"gate_receipt", "review_set"})


def test_completion_reads_the_requirement_of_the_named_class(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every class requires the same kinds today, so which table entry is read is invisible through
    # the real table (only its pin above sees a change). Give each class a different requirement to
    # prove the verdict is judged against the NAMED class's entry, as S2's per-class growth needs.
    monkeypatch.setattr(
        "probos.cognitive.repair_candidate.REQUIRED_EVIDENCE_KINDS",
        {
            "repair": frozenset({"gate_receipt", "review_set"}),
            "maintenance": frozenset({"gate_receipt"}),
            "enhancement": frozenset({"review_set"}),
        },
    )
    candidate = _pure_candidate()
    digest = candidate.digest()
    gate = _present_gate(digest)
    review = _present_review(digest)
    cases = [
        ("repair", [gate], False, ("review_set",)),
        ("repair", [review], False, ("gate_receipt",)),
        ("repair", [gate, review], True, ()),
        ("maintenance", [gate], True, ()),
        ("maintenance", [review], False, ("gate_receipt",)),
        ("enhancement", [gate], False, ("review_set",)),
        ("enhancement", [review], True, ()),
    ]

    for authority_class, links, complete, missing in cases:
        result = evaluate_completion(candidate, authority_class, links)  # type: ignore[arg-type]

        assert (result.complete, result.missing_kinds) == (complete, missing), (
            authority_class, [link.kind for link in links],
        )


@pytest.mark.parametrize("authority_class", _CLASSES)
def test_completion_complete_for_every_class(authority_class: AuthorityClass) -> None:
    candidate = _pure_candidate()
    digest = candidate.digest()
    gate = _present_gate(digest)
    review = _present_review(digest)

    result = evaluate_completion(candidate, authority_class, [gate, review])

    assert result.complete is True
    assert result.reason == "evidence_complete"
    assert result.missing_kinds == ()
    assert result.authority_class == authority_class
    assert result.candidate_digest == digest
    # the verdict is a property of the set of links: neither the container type nor the order changes it
    assert evaluate_completion(candidate, authority_class, (gate, review)) == result
    assert evaluate_completion(candidate, authority_class, [review, gate]) == result


@pytest.mark.parametrize("empty", [list, tuple], ids=["list", "tuple"])
def test_completion_with_no_links_is_kind_missing(empty: type) -> None:
    candidate = _pure_candidate()

    result = evaluate_completion(candidate, "repair", empty())

    assert result.complete is False
    assert result.reason == "evidence_kind_missing"
    assert result.missing_kinds == ("gate_receipt", "review_set")
    assert result.candidate_digest == candidate.digest()


def test_extra_links_never_substitute_for_a_missing_kind() -> None:
    candidate = _pure_candidate()
    digest = candidate.digest()
    gates = [_present_gate(digest, "1" * 64), _present_gate(digest, "4" * 64)]
    # premise: the same links plus the review complete the evidence
    assert evaluate_completion(candidate, "repair", [*gates, _present_review(digest)]).complete is True

    result = evaluate_completion(candidate, "repair", gates)

    assert result.complete is False
    assert result.reason == "evidence_kind_missing"
    assert result.missing_kinds == ("review_set",)


def test_link_for_another_candidate_blocks_and_does_not_count() -> None:
    candidate = _pure_candidate()
    digest = candidate.digest()
    other_digest = _other_candidate().digest()
    assert other_digest != digest
    # premise: the review for THIS candidate completes the evidence
    assert evaluate_completion(
        candidate, "repair", [_present_gate(digest), _present_review(digest)],
    ).complete is True

    result = evaluate_completion(
        candidate, "repair", [_present_gate(digest), _present_review(other_digest)],
    )

    assert result.complete is False
    assert result.reason == "evidence_candidate_mismatch"
    assert result.missing_kinds == ("review_set",)


def test_non_present_link_blocks_even_when_all_kinds_present() -> None:
    candidate = _pure_candidate()
    digest = candidate.digest()
    present = [_present_gate(digest), _present_review(digest)]
    assert evaluate_completion(candidate, "repair", present).complete is True  # premise

    result = evaluate_completion(candidate, "repair", [*present, _refused_gate(digest)])

    assert result.complete is False
    assert result.reason == "evidence_not_present"
    assert result.missing_kinds == ()


def test_unavailable_required_kind_blocks() -> None:
    candidate = _pure_candidate()
    digest = candidate.digest()
    # premise: with a present review in its place the evidence is complete
    assert evaluate_completion(
        candidate, "repair", [_present_gate(digest), _present_review(digest)],
    ).complete is True

    result = evaluate_completion(
        candidate, "repair", [_present_gate(digest), _unavailable_review(digest)],
    )

    assert result.complete is False
    assert result.reason == "evidence_not_present"
    assert result.missing_kinds == ("review_set",)


def test_completion_reason_precedence() -> None:
    candidate = _pure_candidate()
    digest = candidate.digest()
    gate = _present_gate(digest)
    unavailable = _unavailable_review(digest)  # blocks as not present
    elsewhere = _present_review(_other_candidate().digest())  # blocks as another candidate's
    # premises: each defect alone yields its own reason
    assert evaluate_completion(candidate, "repair", [gate, unavailable]).reason == "evidence_not_present"
    assert evaluate_completion(
        candidate, "repair", [gate, _present_review(digest), elsewhere],
    ).reason == "evidence_candidate_mismatch"

    for links in ([gate, unavailable, elsewhere], [elsewhere, unavailable, gate]):
        result = evaluate_completion(candidate, "repair", links)

        assert result.complete is False
        assert result.reason == "evidence_candidate_mismatch"
        assert result.missing_kinds == ("review_set",)


def test_evaluate_completion_argument_errors() -> None:
    candidate = _pure_candidate()
    digest = candidate.digest()
    links = [_present_gate(digest), _present_review(digest)]
    assert evaluate_completion(candidate, "repair", links).complete is True  # premise: valid arguments

    # the candidate must be exactly a RepairCandidate, not None, an object or a duck-typed stand-in
    for bad_candidate in (None, object(), _FakeCandidate()):
        _assert_refused(TypeError, "repair_candidate_required", bad_candidate, "repair", links)
    # the class must be exactly one of the pinned strings
    for bad_class in ("Repair", "other", None, "", _StrSubclass("repair")):
        _assert_refused(ValueError, "authority_class_invalid", candidate, bad_class, links)
    # the container must be exactly a list or a tuple: a set or generator is refused, never consumed
    bad_containers = [set(links), (link for link in links), None, "gate_receipt", {0: links[0]}]
    for bad_container in bad_containers:
        _assert_refused(TypeError, "evidence_links_container_invalid", candidate, "repair", bad_container)
    # every element must be exactly an EvidenceLink: no None, no object, no duck-typed stand-in
    for bad_element in (None, object(), "gate_receipt", _FakeLink()):
        _assert_refused(TypeError, "evidence_link_required", candidate, "repair", [links[0], bad_element])
        _assert_refused(TypeError, "evidence_link_required", candidate, "repair", (bad_element,))


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"reason": "evidence_complete"}, id="complete-with-missing-kinds"),
        pytest.param({"missing_kinds": ()}, id="kind-missing-with-none"),
        pytest.param({"reason": "evidence_unknown"}, id="unknown-reason"),
        pytest.param({"authority_class": "other"}, id="unknown-class"),
        pytest.param({"candidate_digest": "A" * 64}, id="bad-digest"),
        pytest.param({"missing_kinds": ("captain_approval",)}, id="missing-kind-outside-table"),
        pytest.param({"missing_kinds": ["review_set"]}, id="list-instead-of-tuple"),
        pytest.param({"authority_class": _StrSubclass("repair")}, id="class-str-subclass"),
        pytest.param({"reason": _StrSubclass("evidence_kind_missing")}, id="reason-str-subclass"),
    ],
)
def test_evidence_completeness_rejects_inconsistent_construction(change: dict[str, object]) -> None:
    digest = _pure_candidate().digest()
    consistent: dict[str, object] = {
        "authority_class": "repair",
        "candidate_digest": digest,
        "reason": "evidence_kind_missing",
        "missing_kinds": ("review_set",),
    }
    # premise: the unmodified report constructs, and so does the complete one
    assert EvidenceCompleteness(**consistent).missing_kinds == ("review_set",)  # type: ignore[arg-type]
    assert EvidenceCompleteness("repair", digest, "evidence_complete").complete is True

    with pytest.raises(ValueError) as excinfo:
        EvidenceCompleteness(**{**consistent, **change})  # type: ignore[arg-type]

    assert excinfo.value.args == ("evidence_completeness_invalid",)


def test_evidence_completeness_refuses_a_non_string_missing_kind() -> None:
    """A1: an unhashable or non-``str`` missing kind is the stable ``ValueError``, not a raw
    ``TypeError`` from the table lookup (the contract's failure tiers, D6)."""
    digest = _pure_candidate().digest()
    # premise: the same report with a valid kind constructs, so only the kind below is at fault
    assert EvidenceCompleteness(
        authority_class="repair", candidate_digest=digest, reason="evidence_kind_missing",
        missing_kinds=("review_set",),
    ).missing_kinds == ("review_set",)

    for bad_kind in ([], 1):
        with pytest.raises(ValueError) as excinfo:
            EvidenceCompleteness(
                authority_class="repair", candidate_digest=digest, reason="evidence_kind_missing",
                missing_kinds=(bad_kind,),  # type: ignore[arg-type]
            )

        assert excinfo.value.args == ("evidence_completeness_invalid",), bad_kind


def test_completion_reasons_are_pinned_and_each_constructs() -> None:
    digest = _pure_candidate().digest()
    assert COMPLETION_REASONS == frozenset({
        "evidence_complete",
        "evidence_candidate_mismatch",
        "evidence_not_present",
        "evidence_kind_missing",
        "evidence_changed",
    })

    for reason in sorted(COMPLETION_REASONS):
        missing = ("review_set",) if reason == "evidence_kind_missing" else ()
        report = EvidenceCompleteness("repair", digest, reason, missing)
        assert report.reason == reason
        assert report.complete is (reason == "evidence_complete"), reason


def test_shape_helpers() -> None:
    for value in ("0" * 64, "f" * 64, "0123456789abcdef" * 4):
        assert is_sha256_hex(value) is True, value
    for value in ("A" * 64, "0" * 63, "0" * 65, "0" * 64 + "\n", "g" * 64, "", None, 5, b"0" * 64,
                  _StrSubclass("0" * 64)):
        assert is_sha256_hex(value) is False, value

    for value in ("a", "red.team:v2-x", "a" * 128):
        assert is_evidence_ref(value) is True, value
    for value in ("", "-x", "a/b", "a" * 129, "a\n", "a b", None, 5, _StrSubclass("a")):
        assert is_evidence_ref(value) is False, value


# ---------------------------------------------------------------------------
# The producer -> consumer seam
# ---------------------------------------------------------------------------


def test_bind_reviews_links_cross_into_evaluate_completion() -> None:
    candidate = _pure_candidate()
    digest = candidate.digest()
    # The gate half is hand-built: its real producer, verify_gate_receipt, needs a receipt written by
    # scripts/run_test_gate.py in a real repository, which S1a already crosses.
    gate = _present_gate(digest)

    bound = bind_reviews(candidate, [_Review()], expected_assignee="builder")
    complete = evaluate_completion(candidate, "repair", [gate, bound])
    assert (bound.status, bound.reason) == ("present", "review_set_bound")
    assert (complete.complete, complete.reason, complete.missing_kinds) == (True, "evidence_complete", ())

    # C8: a set naming another assignee is refused by the binder and is then never the review kind
    refused = bind_reviews(candidate, [_Review(assignee_id="someone_else")], expected_assignee="builder")
    verdict = evaluate_completion(candidate, "repair", [gate, refused])
    assert (refused.status, refused.reason) == ("refused", "review_assignee_mismatch")
    assert (verdict.complete, verdict.reason, verdict.missing_kinds) == (
        False, "evidence_not_present", ("review_set",),
    )

    # an absent set is unavailable: not present, so the review kind is reported missing
    absent = bind_reviews(candidate, None, expected_assignee="builder")
    verdict = evaluate_completion(candidate, "repair", [gate, absent])
    assert (absent.status, absent.reason) == ("unavailable", "review_set_absent")
    assert (verdict.complete, verdict.reason, verdict.missing_kinds) == (
        False, "evidence_not_present", ("review_set",),
    )

    # a set bound to ANOTHER candidate names that candidate's digest: it blocks and does not count
    other = _other_candidate()
    elsewhere = bind_reviews(other, [_Review(reviewed_tree=other.tree)], expected_assignee="builder")
    verdict = evaluate_completion(candidate, "repair", [gate, elsewhere])
    assert (elsewhere.status, elsewhere.candidate_digest) == ("present", other.digest())
    assert other.digest() != digest
    assert (verdict.complete, verdict.reason, verdict.missing_kinds) == (
        False, "evidence_candidate_mismatch", ("review_set",),
    )
