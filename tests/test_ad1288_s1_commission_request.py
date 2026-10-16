"""AD-1288 S1 (M1): the commission request contracts -- identity, validation bounds and the no-authority rule.

Pure contract tests of ``probos.cognitive.elastic_commission``: ``CommissionRequest``, ``SlotReservation``,
``ReleaseRequest`` and the three result types. No store, no session, no clock; the admission rules are the M2 file
and the commission chain is the M3 file.

Two conventions hold throughout. Every refusal is paired with its accepted neighbour (the same payload with one
change), so a refusal can only come from the rule under test. A ``ValidationError`` is read through ``errors()`` as
``(location, code)``: the code is the ``ValueError`` text of a ``value_error`` (what these contracts raise) or
pydantic's own error type. Nothing matches a substring of the rendered message.

The request-reference known answer is checked against bytes written out by hand (``_KAT_CANONICAL``: RFC 8785 for a
request that holds only ASCII strings, integers and null), and the domain strings are written out here, never
imported, so a change to either one shows up as a failure.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from probos.cognitive.elastic_commission import (
    CommissionReceipt,
    CommissionRequest,
    ReleaseRequest,
    SlotReservation,
    SlotView,
    TeamView,
)
from probos.federation.ard.jcs import canonicalize
from tests.test_ad1287_execution_profile import _AUTHORITY_WORDS, _authority_named

_V1_DOMAIN = b"probos.elastic_team/commission_request/v1\x00"
_V2_DOMAIN = b"probos.elastic_team/commission_request/v2\x00"

# The RFC 8785 form of ``_kat_payload()``'s request, written by hand: keys sorted, no spaces, the evidence refs
# sorted, ``None`` as ``null``. It does not come from any canonicaliser.
_KAT_CANONICAL = (
    b'{"evidence_refs":["' + b"c" * 64 + b'","' + b"d" * 64 + b'"],'
    b'"owner_id":"owner-1","rationale":"Review the findings.",'
    b'"reservations":[{"execution_profile_ref":"' + b"b" * 64 + b'","ordinal":1,"slot_id":"review",'
    b'"supersedes_attempt_id":null}],'
    b'"schema_version":1,"session_id":"session-1","team_spec_ref":"' + b"a" * 64 + b'"}'
)

_Error = tuple[tuple[int | str, ...], str]  # (location, code)


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


def _ref(label: str) -> str:
    """A distinct, well-formed sha256 reference per label."""
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _reservation(
    slot_id: str = "review", ordinal: int = 1, profile: str = "profile-a", supersedes: str | None = None
) -> SlotReservation:
    return SlotReservation(
        slot_id=slot_id, ordinal=ordinal, execution_profile_ref=_ref(profile), supersedes_attempt_id=supersedes
    )


def _entry(**overrides: Any) -> dict[str, Any]:
    """One reservation as the plain dict a JSON caller sends; ``overrides`` replace fields."""
    entry: dict[str, Any] = {
        "slot_id": "review",
        "ordinal": 1,
        "execution_profile_ref": _ref("profile-a"),
        "supersedes_attempt_id": None,
    }
    entry.update(overrides)
    return entry


def _entry_without(key: str) -> dict[str, Any]:
    entry = _entry()
    del entry[key]
    return entry


def _distinct_reservations(count: int) -> list[SlotReservation]:
    """``count`` reservations with pairwise different ``(slot_id, ordinal)`` pairs."""
    return [_reservation(f"slot-{index:02d}", 1) for index in range(count)]


def _payload(**overrides: Any) -> dict[str, Any]:
    """A valid ``CommissionRequest`` payload; ``overrides`` replace fields."""
    payload: dict[str, Any] = {
        "schema_version": 1,
        "session_id": "session-1",
        "team_spec_ref": _ref("team-spec"),
        "owner_id": "owner-1",
        "reservations": [_reservation()],
        "rationale": "Review the analysis findings.",
        "evidence_refs": [_ref("evidence-b"), _ref("evidence-a")],
    }
    payload.update(overrides)
    return payload


def _release_payload(**overrides: Any) -> dict[str, Any]:
    """A valid ``ReleaseRequest`` payload; ``overrides`` replace fields."""
    payload: dict[str, Any] = {
        "schema_version": 1,
        "session_id": "session-1",
        "owner_id": "owner-1",
        "worker_attempt_id": "attempt-1",
    }
    payload.update(overrides)
    return payload


def _kat_payload() -> dict[str, Any]:
    """The fixed request behind ``_KAT_CANONICAL``; the evidence refs are given out of order."""
    return {
        "schema_version": 1,
        "session_id": "session-1",
        "team_spec_ref": "a" * 64,
        "owner_id": "owner-1",
        "reservations": [_entry(execution_profile_ref="b" * 64)],
        "rationale": "Review the findings.",
        "evidence_refs": ["d" * 64, "c" * 64],
    }


def _refusal(model: type[BaseModel], payload: dict[str, Any]) -> list[_Error]:
    """Validate ``payload`` expecting a refusal; every error as ``(location, code)``.

    The code is the ``ValueError`` text of a ``value_error``, else pydantic's own type (``extra_forbidden``).
    """
    with pytest.raises(ValidationError) as caught:
        model.model_validate(payload)
    return [
        (error["loc"], str(error["ctx"]["error"]) if error["type"] == "value_error" else error["type"])
        for error in caught.value.errors()
    ]


_REQUESTS: dict[str, tuple[type[BaseModel], Callable[..., dict[str, Any]]]] = {
    "commission": (CommissionRequest, _payload),
    "release": (ReleaseRequest, _release_payload),
}


# --------------------------------------------------------------------------------------
# 1-2. Identity: order never changes the request, and the reference is domain separated
# --------------------------------------------------------------------------------------

_SORTED_PAIRS = (("analyse", 2), ("review", 1), ("review", 2), ("review", 10))


def test_reservations_sort_and_order_never_changes_the_reference() -> None:
    ordered = [_reservation(slot_id, ordinal) for slot_id, ordinal in _SORTED_PAIRS]
    orders = list(itertools.permutations(ordered))

    # premises: the fixture is in the contract's (slot_id, ordinal) order; that order differs from the two plausible
    # wrong ones (ordinal first, ordinal as text); and every permutation is a different input order
    assert tuple(sorted(_SORTED_PAIRS)) == _SORTED_PAIRS
    assert tuple(sorted(_SORTED_PAIRS, key=lambda pair: (pair[1], pair[0]))) != _SORTED_PAIRS
    assert tuple(sorted(_SORTED_PAIRS, key=lambda pair: (pair[0], str(pair[1])))) != _SORTED_PAIRS
    assert len({tuple((entry.slot_id, entry.ordinal) for entry in order) for order in orders}) == len(orders) == 24

    def build(order: Sequence[SlotReservation], shape: str) -> CommissionRequest:
        entries = list(order) if shape == "objects" else [entry.model_dump() for entry in order]
        return CommissionRequest.model_validate(_payload(reservations=entries))

    baseline = build(ordered, "objects")
    assert tuple((entry.slot_id, entry.ordinal) for entry in baseline.reservations) == _SORTED_PAIRS
    for shape in ("objects", "dicts"):
        for order in orders:
            request = build(order, shape)
            assert request == baseline, (shape, order)
            assert request.content_ref() == baseline.content_ref(), (shape, order)

    # negative control: the reference follows the reservations' content, so the equalities above are not vacuous
    changed = build([*ordered[:-1], _reservation("review", 10, profile="profile-b")], "objects")
    assert changed != baseline
    assert changed.content_ref() != baseline.content_ref()


def test_request_ref_is_domain_separated_known_answer() -> None:
    request = CommissionRequest.model_validate(_kat_payload())
    canonical = canonicalize(request.model_dump(mode="json"))

    # premise: the bytes the digest covers are the hand-written RFC 8785 form of every field
    assert canonical == _KAT_CANONICAL

    expected = hashlib.sha256(_V1_DOMAIN + canonical).hexdigest()
    assert request.content_ref() == expected
    assert request.content_ref() == hashlib.sha256(_V1_DOMAIN + _KAT_CANONICAL).hexdigest()

    # negative controls: the same bytes under the v2 domain, and under no domain, give other digests
    under_v2 = hashlib.sha256(_V2_DOMAIN + canonical).hexdigest()
    assert expected != under_v2
    assert request.content_ref() != under_v2
    assert request.content_ref() != hashlib.sha256(canonical).hexdigest()


# --------------------------------------------------------------------------------------
# 3-4. The reservation sequence
# --------------------------------------------------------------------------------------

# id: () -> (reservations that repeat a (slot_id, ordinal) pair, the same number of reservations without a repeat)
_DUPLICATE_CASES: dict[str, Callable[[], tuple[list[Any], list[Any]]]] = {
    "identical": lambda: (
        [_reservation("review", 1), _reservation("review", 1)],
        [_reservation("review", 1), _reservation("review", 2)],  # the same slot with two ordinals
    ),
    "same_pair_other_profile": lambda: (
        [_reservation("review", 1, profile="profile-a"), _reservation("review", 1, profile="profile-b")],
        [_reservation("review", 1, profile="profile-a"), _reservation("analyse", 1, profile="profile-b")],
    ),
    "not_adjacent": lambda: (
        [_reservation("review", 1), _reservation("analyse", 1), _reservation("review", 1)],
        [_reservation("review", 1), _reservation("analyse", 1), _reservation("review", 2)],
    ),
    "dict_entries": lambda: ([_entry(), _entry()], [_entry(), _entry(ordinal=2)]),
}


@pytest.mark.parametrize("case", list(_DUPLICATE_CASES))
def test_duplicate_slot_ordinal_pair_is_refused(case: str) -> None:
    duplicated, neighbour = _DUPLICATE_CASES[case]()

    accepted = CommissionRequest.model_validate(_payload(reservations=neighbour))  # control: the accepted neighbour
    assert len(accepted.reservations) == len(duplicated)  # premise: only the repeated pair differs

    assert _refusal(CommissionRequest, _payload(reservations=duplicated)) == [
        (("reservations",), "commission_reservation_duplicate")
    ]


# id: () -> (a value the sequence rule refuses, the accepted neighbour that differs only in that rule, its size)
_SEQUENCE_CASES: dict[str, Callable[[], tuple[Any, Any, int]]] = {
    "empty": lambda: ([], [_reservation()], 1),
    "sixty_five": lambda: (_distinct_reservations(65), _distinct_reservations(64), 64),  # 64 is the largest accepted
    "not_a_sequence": lambda: ({_reservation()}, (_reservation(),), 1),
    "none": lambda: (None, [_reservation()], 1),
    "bool_ordinal": lambda: ([_entry(ordinal=True)], [_entry(ordinal=1)], 1),
    "missing_slot_id": lambda: ([_entry_without("slot_id")], [_entry()], 1),
    "other_type": lambda: ([("review", 1)], [_reservation()], 1),
}


@pytest.mark.parametrize("case", list(_SEQUENCE_CASES))
def test_reservation_sequence_bounds(case: str) -> None:
    refused, neighbour, neighbour_size = _SEQUENCE_CASES[case]()

    accepted = CommissionRequest.model_validate(_payload(reservations=neighbour))  # control: the accepted neighbour
    assert len(accepted.reservations) == neighbour_size  # premise: the neighbour holds the size the table names

    assert _refusal(CommissionRequest, _payload(reservations=refused)) == [
        (("reservations",), "commission_reservations_invalid")
    ]


# --------------------------------------------------------------------------------------
# 5. The rationale
# --------------------------------------------------------------------------------------

# id: () -> (a rationale the rules refuse, the accepted neighbour that differs only in the refused part)
_RATIONALE_CASES: dict[str, Callable[[], tuple[Any, str]]] = {
    "empty": lambda: ("", "x"),
    "blank": lambda: (" \t\n ", " x "),
    "over_2000": lambda: ("x" * 2001, "x" * 2000),
    "carriage_return": lambda: ("line one\r\nline two", "line one\nline two"),
    "nul": lambda: ("before\x00after", "before after"),
    "delete": lambda: ("before\x7fafter", "before~after"),
    "lone_surrogate": lambda: ("before\ud800after", "before\U0001f600after"),
    "not_a_string": lambda: (b"bytes", "bytes"),
    "none": lambda: (None, "none"),
}


@pytest.mark.parametrize("case", list(_RATIONALE_CASES))
def test_rationale_rules(case: str) -> None:
    refused, neighbour = _RATIONALE_CASES[case]()

    accepted = CommissionRequest.model_validate(_payload(rationale=neighbour))  # control: the accepted neighbour
    assert accepted.rationale == neighbour  # kept exactly as given: it is part of the request's reference

    assert _refusal(CommissionRequest, _payload(rationale=refused)) == [
        (("rationale",), "commission_rationale_invalid")
    ]


def test_rationale_accepts_tab_and_newline() -> None:
    text = "column one\tcolumn two\nsecond line"
    assert "\t" in text and "\n" in text  # premise: the text really carries both characters

    assert CommissionRequest.model_validate(_payload(rationale=text)).rationale == text


@pytest.mark.parametrize(
    ("character", "byte_length"), [pytest.param("x", 2000, id="ascii"), pytest.param("\u00e9", 4000, id="two_byte")]
)
def test_rationale_accepts_exactly_2000_characters(character: str, byte_length: int) -> None:
    text = character * 2000
    assert (len(text), len(text.encode("utf-8"))) == (2000, byte_length)  # premise: counted in characters, not bytes

    assert CommissionRequest.model_validate(_payload(rationale=text)).rationale == text
    # negative control: one character more is refused
    assert _refusal(CommissionRequest, _payload(rationale=text + character)) == [
        (("rationale",), "commission_rationale_invalid")
    ]


# --------------------------------------------------------------------------------------
# 6. Strict and closed requests
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "bad", "neighbour", "expected"),
    [
        pytest.param("commission", {"lease_id": "lease-1"}, {}, (("lease_id",), "extra_forbidden"), id="extra_field"),
        pytest.param(
            "release", {"lease_id": "lease-1"}, {}, (("lease_id",), "extra_forbidden"), id="release_extra_field"
        ),
        pytest.param(
            "commission",
            {"session_id": 7},
            {"session_id": "7"},
            (("session_id",), "elastic_team_id_invalid"),
            id="int_session_id",
        ),
        pytest.param(
            "commission",
            {"team_spec_ref": "a" * 63},
            {"team_spec_ref": "a" * 64},
            (("team_spec_ref",), "elastic_team_ref_invalid"),
            id="short_team_spec_ref",
        ),
        pytest.param(
            "commission",
            {"team_spec_ref": "a" * 65},
            {"team_spec_ref": "a" * 64},
            (("team_spec_ref",), "elastic_team_ref_invalid"),
            id="long_team_spec_ref",
        ),
        pytest.param(
            "commission",
            {"team_spec_ref": "A" * 64},
            {"team_spec_ref": "a" * 64},
            (("team_spec_ref",), "elastic_team_ref_invalid"),
            id="uppercase_team_spec_ref",
        ),
        pytest.param(
            "commission",
            {"team_spec_ref": "g" * 64},
            {"team_spec_ref": "f" * 64},
            (("team_spec_ref",), "elastic_team_ref_invalid"),
            id="non_hex_team_spec_ref",
        ),
        pytest.param(
            "commission",
            {"evidence_refs": [_ref("evidence-1"), _ref("evidence-1")]},
            {"evidence_refs": [_ref("evidence-1"), _ref("evidence-2")]},
            (("evidence_refs",), "elastic_team_ref_set_invalid"),
            id="duplicate_evidence_refs",
        ),
        pytest.param(
            "commission",
            {"evidence_refs": ["not-a-ref"]},
            {"evidence_refs": [_ref("evidence-1")]},
            (("evidence_refs",), "elastic_team_ref_invalid"),
            id="non_sha_evidence_ref",
        ),
        pytest.param(
            "commission",
            {"evidence_refs": None},
            {"evidence_refs": []},
            (("evidence_refs",), "elastic_team_ref_set_invalid"),
            id="none_evidence_refs",
        ),
        pytest.param(
            "commission",
            {"schema_version": True},
            {"schema_version": 1},
            (("schema_version",), "elastic_team_schema_version_invalid"),
            id="bool_schema_version",
        ),
        pytest.param(
            "commission",
            {"schema_version": "1"},
            {"schema_version": 1},
            (("schema_version",), "elastic_team_schema_version_invalid"),
            id="text_schema_version",
        ),
        pytest.param(
            "commission",
            {"schema_version": 2},
            {"schema_version": 1},
            (("schema_version",), "elastic_team_schema_version_invalid"),
            id="unknown_schema_version",
        ),
        pytest.param(
            "release",
            {"schema_version": True},
            {"schema_version": 1},
            (("schema_version",), "elastic_team_schema_version_invalid"),
            id="release_bool_schema_version",
        ),
    ],
)
def test_requests_are_strict_and_closed(
    kind: str, bad: dict[str, Any], neighbour: dict[str, Any], expected: _Error
) -> None:
    model, payload = _REQUESTS[kind]

    model.model_validate(payload(**neighbour))  # control: the accepted neighbour (the valid payload, one change)

    assert _refusal(model, payload(**bad)) == [expected]


def test_evidence_refs_are_sorted_and_order_never_changes_the_reference() -> None:
    refs = [_ref("evidence-1"), _ref("evidence-2"), _ref("evidence-3")]
    ascending, descending = sorted(refs), sorted(refs, reverse=True)
    assert ascending != descending  # premise: the two input orders differ

    first = CommissionRequest.model_validate(_payload(evidence_refs=descending))
    second = CommissionRequest.model_validate(_payload(evidence_refs=ascending))
    assert first.evidence_refs == tuple(ascending)
    assert first == second
    assert first.content_ref() == second.content_ref()

    # boundary: no evidence is accepted
    assert CommissionRequest.model_validate(_payload(evidence_refs=[])).evidence_refs == ()
    # negative control: a different evidence set is a different request
    other = CommissionRequest.model_validate(_payload(evidence_refs=ascending[:2]))
    assert other != first
    assert other.content_ref() != first.content_ref()


# --------------------------------------------------------------------------------------
# 7. Release request ids
# --------------------------------------------------------------------------------------

# id: (a value the id rule refuses, the accepted neighbour that differs only in that rule)
_ID_CASES: dict[str, tuple[Any, str]] = {
    "empty": ("", "a"),
    "leading_hyphen": ("-attempt", "a-ttempt"),
    "leading_underscore": ("_attempt", "a_ttempt"),
    "leading_dot": (".attempt", "a.ttempt"),
    "leading_colon": (":attempt", "a:ttempt"),
    "space": ("attempt 1", "attempt-1"),
    "slash": ("attempt/1", "attempt:1"),
    "non_ascii": ("attempt\u00e9", "attempte"),
    "over_128": ("a" * 129, "a" * 128),
    "int": (7, "7"),
    "none": (None, "none"),
    "bytes": (b"attempt", "attempt"),
}


@pytest.mark.parametrize("field", ["session_id", "owner_id", "worker_attempt_id"])
@pytest.mark.parametrize("case", list(_ID_CASES))
def test_release_request_validates_ids(field: str, case: str) -> None:
    refused, neighbour = _ID_CASES[case]

    accepted = ReleaseRequest.model_validate(_release_payload(**{field: neighbour}))  # control: the accepted neighbour
    assert accepted.model_dump()[field] == neighbour  # premise: the neighbour reached the field unchanged

    assert _refusal(ReleaseRequest, _release_payload(**{field: refused})) == [((field,), "elastic_team_id_invalid")]


# --------------------------------------------------------------------------------------
# 8. No authority
# --------------------------------------------------------------------------------------

_EXPECTED_FIELDS = (
    (
        CommissionRequest,
        frozenset(
            {"schema_version", "session_id", "team_spec_ref", "owner_id", "reservations", "rationale", "evidence_refs"}
        ),
    ),
    (SlotReservation, frozenset({"slot_id", "ordinal", "execution_profile_ref", "supersedes_attempt_id"})),
    (ReleaseRequest, frozenset({"schema_version", "session_id", "owner_id", "worker_attempt_id"})),
    (CommissionReceipt, frozenset({"request_ref", "recorded", "acknowledged"})),
    (
        SlotView,
        frozenset({"slot_id", "capacity_maximum", "max_attempts", "attempts", "outcomes", "live", "next_ordinal"}),
    ),
    (TeamView, frozenset({"session_id", "team_spec_ref", "slots"})),
)


@dataclasses.dataclass(frozen=True)
class _FakeLeasingReceipt:
    request_ref: str
    lease_id: str


class _FakeLeasingRequest(BaseModel):
    session_id: str
    lease_id: str


def _field_names(cls: type) -> set[str]:
    """The declared field names of a pydantic model or of a dataclass (the S1 result types are dataclasses)."""
    if issubclass(cls, BaseModel):
        return set(cls.model_fields)
    return {field.name for field in dataclasses.fields(cls)}


def test_types_carry_no_authority_fields() -> None:
    # premise: the vocabulary of the check is the contract's
    assert _AUTHORITY_WORDS == ("scope", "rank", "lease", "grant", "authority", "permission")

    for cls, expected in _EXPECTED_FIELDS:
        names = _field_names(cls)
        assert names == expected, cls.__name__  # premise: the walk sees exactly the fields (an empty walk would pass)
        assert _authority_named(names) == set(), cls.__name__

    # negative control: the same walk and check flag a synthetic lease_id on either kind of type
    assert _authority_named(_field_names(_FakeLeasingReceipt)) == {"lease_id"}
    assert _authority_named(_field_names(_FakeLeasingRequest)) == {"lease_id"}
