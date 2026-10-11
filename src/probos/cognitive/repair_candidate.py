"""AD-1299 S1a (#1352): repair candidate identity and evidence binding.

A repair campaign is judged against ONE frozen candidate: the committed tree
the canonical gate tested, the index its reviewers reviewed and, in a later
slice, the bytes that get promoted. This module defines that identity and two
bindings:

* ``verify_gate_receipt`` binds a canonical ``scripts/run_test_gate.py``
  success receipt (schema 1) only when it describes a clean full-gate success
  of exactly the candidate's commit and tree.
* ``bind_reviews`` binds a review set only when every review was accepted by a
  reviewer other than the assignee and names the candidate's tree.

Each returns an :class:`EvidenceLink`: ``present`` (bound), ``refused``
(readable but contradicts the candidate) or ``unavailable`` (absent, empty,
oversized, malformed or insufficient). Only ``present`` is current; nothing is
inferred. Wrong argument types are programming errors and raise.

Refuses versus records: the binding REFUSES a receipt or review set that
contradicts the candidate in the facts it checks (commit, tree, status,
schema and reviewer independence, plus the label when one is expected). It
RECORDS a sha256 for each piece of evidence (``EvidenceLink.evidence_sha256``):
for a receipt, the SHA-256 of the supplied raw bytes, so any change to those
bytes changes it; for a review set, a domain-separated SHA-256 of the
candidate-bound projection of five review fields (attempt id, reviewer id,
assignee id, reviewed tree, accepted), so a change to those five fields
changes it and a change to any other review attribute does not. A consumer
that retained an earlier trusted digest can therefore detect a change within
what each digest covers. It does not authenticate the producer (a hash is an
integrity binding, not a signature), does not assert that unread fields are
valid, and does not exclude a writer running under ProbOS's own OS identity
(AD-1315 Boundary). Authority stays with the Captain's per-step decision.

Pure: no I/O, no clock, no runtime, no store. Identity bytes are AD-1144's
RFC 8785 canonical form, imported lazily (the AD-1286 precedent) so importing
this module never imports the federation package.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

REPAIR_CANDIDATE_SCHEMA_VERSION: Final = 1
GATE_RECEIPT_SCHEMA_VERSION: Final = 1
MAX_RECEIPT_BYTES: Final = 1_048_576
MAX_REVIEWS: Final = 32

_DOMAINS: Final[dict[str, bytes]] = {
    "candidate": b"probos.repair_candidate/candidate/v1\x00",
    "review_set": b"probos.repair_candidate/review_set/v1\x00",
}
_GIT_OBJECT_RE: Final = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
# Mirrors probos.work_item_steps.OwnedId, so a ReviewedStepResult projects without loss.
_ID_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")

EvidenceKind = Literal["gate_receipt", "review_set"]
EvidenceStatus = Literal["present", "refused", "unavailable"]

_BOUND: Final = frozenset({"gate_receipt_bound", "review_set_bound"})
_UNAVAILABLE: Final = frozenset({
    "gate_receipt_absent",
    "gate_receipt_empty",
    "gate_receipt_oversized",
    "gate_receipt_malformed",
    "review_set_absent",
    "review_set_oversized",
    "review_malformed",
    "review_insufficient",
})
_REFUSED: Final = frozenset({
    "gate_receipt_schema_unsupported",
    "gate_receipt_label_mismatch",
    "gate_receipt_not_success",
    "gate_receipt_uncommitted_index",
    "gate_receipt_tree_mismatch",
    "gate_receipt_commit_mismatch",
    "review_attempt_duplicate",
    "review_not_independent",
    "review_not_accepted",
    "review_tree_mismatch",
})
REASON_CODES: Final[frozenset[str]] = _BOUND | _UNAVAILABLE | _REFUSED


class _Malformed(ValueError):
    """Internal: evidence could not be read as its declared shape."""


def _canonicalize(value: object) -> bytes:
    """RFC 8785 bytes (AD-1144). Imported lazily: see the module docstring."""
    from probos.federation.ard.jcs import canonicalize

    return canonicalize(value)


def _is_git_object(value: object) -> bool:
    return type(value) is str and _GIT_OBJECT_RE.fullmatch(value) is not None


def _status_for(reason: str) -> EvidenceStatus:
    if reason in _BOUND:
        return "present"
    if reason in _UNAVAILABLE:
        return "unavailable"
    return "refused"


@dataclass(frozen=True, slots=True)
class RepairCandidate:
    """One frozen candidate. The reviewed index must equal the committed tree."""

    base_commit: str
    candidate_commit: str
    tree: str
    index_tree: str

    def __post_init__(self) -> None:
        values = (self.base_commit, self.candidate_commit, self.tree, self.index_tree)
        if not all(_is_git_object(value) for value in values):
            raise ValueError("repair_candidate_field_invalid")
        if len({len(value) for value in values}) != 1:
            raise ValueError("repair_candidate_field_invalid")
        if self.index_tree != self.tree:
            raise ValueError("repair_candidate_uncommitted_index")

    def projection(self) -> dict[str, object]:
        """The identity material. Fixed key set per schema version."""
        return {
            "schema_version": REPAIR_CANDIDATE_SCHEMA_VERSION,
            "base_commit": self.base_commit,
            "candidate_commit": self.candidate_commit,
            "tree": self.tree,
            "index_tree": self.index_tree,
        }

    def canonical_bytes(self) -> bytes:
        """RFC 8785 bytes of :meth:`projection` (no domain prefix)."""
        return _canonicalize(self.projection())

    def digest(self) -> str:
        """``sha256(candidate domain + canonical_bytes())`` as lowercase hex."""
        return hashlib.sha256(_DOMAINS["candidate"] + self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    """One piece of evidence judged against one candidate.

    A report, not an authority token: construction checks only that the link is
    self-consistent. A consumer that must trust a link re-derives it from the
    evidence bytes by calling the verifier, never by accepting a built instance.
    """

    kind: EvidenceKind
    status: EvidenceStatus
    reason: str
    candidate_digest: str
    evidence_sha256: str = ""

    def __post_init__(self) -> None:
        prefix = "gate_receipt_" if self.kind == "gate_receipt" else "review_"
        if (
            self.kind not in ("gate_receipt", "review_set")
            or type(self.reason) is not str
            or self.reason not in REASON_CODES
            or not self.reason.startswith(prefix)
            or self.status != _status_for(self.reason)
            or type(self.candidate_digest) is not str
            or _SHA256_RE.fullmatch(self.candidate_digest) is None
            or type(self.evidence_sha256) is not str
            or (self.evidence_sha256 and _SHA256_RE.fullmatch(self.evidence_sha256) is None)
        ):
            raise ValueError("evidence_link_invalid")

    @property
    def current(self) -> bool:
        """True only for bound evidence."""
        return self.status == "present"


def _link(kind: EvidenceKind, reason: str, candidate_digest: str, evidence_sha256: str = "") -> EvidenceLink:
    return EvidenceLink(kind, _status_for(reason), reason, candidate_digest, evidence_sha256)


class ReviewAttestation(Protocol):
    """The five facts ``bind_reviews`` reads.

    S3 projects an owned-step ``ReviewedStepResult`` onto it (``reviewer_id``,
    ``review_attempt_id``, ``accepted``, ``permit.assignee_id``) plus the tree the
    review read. This module never imports ``work_item_steps``.
    """

    @property
    def review_attempt_id(self) -> str: ...

    @property
    def reviewer_id(self) -> str: ...

    @property
    def assignee_id(self) -> str: ...

    @property
    def reviewed_tree(self) -> str: ...

    @property
    def accepted(self) -> bool: ...


# -- gate receipt -------------------------------------------------------------


def _field(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise _Malformed(key)
    return mapping[key]


def _dict_field(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = _field(mapping, key)
    if type(value) is not dict:
        raise _Malformed(key)
    return value


def _int_field(mapping: dict[str, Any], key: str) -> int:
    value = _field(mapping, key)
    if type(value) is not int:
        raise _Malformed(key)
    return value


def _bool_field(mapping: dict[str, Any], key: str) -> bool:
    value = _field(mapping, key)
    if type(value) is not bool:
        raise _Malformed(key)
    return value


def _git_field(mapping: dict[str, Any], key: str) -> str:
    value = _field(mapping, key)
    if not _is_git_object(value):
        raise _Malformed(key)
    return value


def _sha256_field(mapping: dict[str, Any], key: str) -> str:
    value = _field(mapping, key)
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise _Malformed(key)
    return value


def _refuse_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _Malformed("duplicate_key")
        result[key] = value
    return result


def _refuse_constant(name: str) -> Any:
    raise _Malformed(name)


def _refuse_non_finite(text: str) -> float:
    # ``parse_constant`` sees only the NaN/Infinity tokens; a numeric literal
    # such as ``1e99999`` overflows to infinity here instead.
    value = float(text)
    if not math.isfinite(value):
        raise _Malformed("non_finite")
    return value


def _parse_receipt(receipt_bytes: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(
            receipt_bytes.decode("utf-8"),
            object_pairs_hook=_refuse_duplicate_keys,
            parse_constant=_refuse_constant,
            parse_float=_refuse_non_finite,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise _Malformed("json") from exc
    if type(payload) is not dict:
        raise _Malformed("root")
    return payload


def _receipt_reason(
    candidate: RepairCandidate, payload: dict[str, Any], expected_label: str | None,
) -> str:
    if "schema_version" not in payload:
        raise _Malformed("schema_version")
    version = payload["schema_version"]
    if type(version) is not int or version != GATE_RECEIPT_SCHEMA_VERSION:
        return "gate_receipt_schema_unsupported"
    label = _field(payload, "label")
    if type(label) is not str:
        raise _Malformed("label")
    status = _dict_field(payload, "status")
    exit_codes = tuple(
        _int_field(status, key)
        for key in ("wrapper_exit_code", "preflight_exit_code", "pytest_exit_code")
    )
    preflight_only = _bool_field(status, "preflight_only")
    tree_changed = _bool_field(status, "tree_changed")
    tree = _dict_field(payload, "tree")
    head = _git_field(tree, "head")
    head_tree = _git_field(tree, "head_tree")
    index_tree = _git_field(tree, "index_tree")
    for artifact in ("manifest", "junit", "collection"):
        _sha256_field(_dict_field(payload, artifact), "sha256")
    totals = _dict_field(_dict_field(payload, "junit"), "totals")
    tests = _int_field(totals, "tests")
    failures = _int_field(totals, "failures")
    errors = _int_field(totals, "errors")
    # The whole shape is read before any verdict, so a malformed receipt is
    # never reported as refused for a reason it might not have.
    if expected_label is not None and label != expected_label:
        return "gate_receipt_label_mismatch"
    if (
        any(code != 0 for code in exit_codes)
        or preflight_only
        or tree_changed
        or tests <= 0
        or failures != 0
        or errors != 0
    ):
        return "gate_receipt_not_success"
    if head_tree != index_tree:
        return "gate_receipt_uncommitted_index"
    if head_tree != candidate.tree:
        return "gate_receipt_tree_mismatch"
    if head != candidate.candidate_commit:
        return "gate_receipt_commit_mismatch"
    return "gate_receipt_bound"


def verify_gate_receipt(
    candidate: RepairCandidate,
    receipt_bytes: bytes | None,
    *,
    expected_label: str | None = None,
) -> EvidenceLink:
    """Bind a canonical gate success receipt (schema 1) to ``candidate``.

    Raises ``TypeError`` for a non-``RepairCandidate`` candidate or non-``bytes``
    receipt, and ``ValueError`` for an empty or non-``str`` ``expected_label``.
    Every evidence defect is returned as a link, never raised. Fields this
    function does not read are not validated: an edit to one still binds and
    shows only as a different ``evidence_sha256``.
    """
    if type(candidate) is not RepairCandidate:
        raise TypeError("repair_candidate_required")
    if expected_label is not None and (type(expected_label) is not str or not expected_label):
        raise ValueError("gate_receipt_label_invalid")
    digest = candidate.digest()
    if receipt_bytes is None:
        return _link("gate_receipt", "gate_receipt_absent", digest)
    if type(receipt_bytes) is not bytes:
        raise TypeError("gate_receipt_bytes_required")
    if not receipt_bytes:
        return _link("gate_receipt", "gate_receipt_empty", digest)
    if len(receipt_bytes) > MAX_RECEIPT_BYTES:
        return _link("gate_receipt", "gate_receipt_oversized", digest)
    evidence = hashlib.sha256(receipt_bytes).hexdigest()
    try:
        reason = _receipt_reason(candidate, _parse_receipt(receipt_bytes), expected_label)
    except _Malformed:
        return _link("gate_receipt", "gate_receipt_malformed", digest, evidence)
    return _link("gate_receipt", reason, digest, evidence)


# -- review set ---------------------------------------------------------------


def _project_review(record: ReviewAttestation) -> tuple[str, str, str, str, bool]:
    try:
        attempt = record.review_attempt_id
        reviewer = record.reviewer_id
        assignee = record.assignee_id
        reviewed_tree = record.reviewed_tree
        accepted = record.accepted
    # A broad catch is correct at this one boundary: ``record`` is an arbitrary
    # caller-supplied object whose attribute reads may run any code, and an
    # evidence defect is returned as a link, never raised. ``Exception`` (not
    # ``BaseException``) lets KeyboardInterrupt, SystemExit and
    # asyncio.CancelledError propagate.
    except Exception as exc:  # noqa: BLE001 -- see the comment above
        raise _Malformed("review_attribute") from exc
    for value in (attempt, reviewer, assignee):
        if type(value) is not str or _ID_RE.fullmatch(value) is None:
            raise _Malformed("review_id")
    if not _is_git_object(reviewed_tree):
        raise _Malformed("reviewed_tree")
    if type(accepted) is not bool:
        raise _Malformed("accepted")
    return attempt, reviewer, assignee, reviewed_tree, accepted


def _review_reason(
    candidate: RepairCandidate,
    projected: list[tuple[str, str, str, str, bool]],
    required_reviewers: int,
) -> str:
    attempts = [attempt for attempt, _, _, _, _ in projected]
    if len(set(attempts)) != len(attempts):
        return "review_attempt_duplicate"
    if any(reviewer == assignee for _, reviewer, assignee, _, _ in projected):
        return "review_not_independent"
    if not all(accepted for _, _, _, _, accepted in projected):
        return "review_not_accepted"
    if any(reviewed_tree != candidate.tree for _, _, _, reviewed_tree, _ in projected):
        return "review_tree_mismatch"
    if len({reviewer for _, reviewer, _, _, _ in projected}) < required_reviewers:
        return "review_insufficient"
    return "review_set_bound"


def bind_reviews(
    candidate: RepairCandidate,
    reviews: Sequence[ReviewAttestation] | None,
    *,
    required_reviewers: int = 1,
) -> EvidenceLink:
    """Bind an independent review set to ``candidate``.

    ``reviews`` must be a ``list`` or ``tuple`` (or ``None``). Raises
    ``TypeError`` for a non-``RepairCandidate`` candidate or another container,
    and ``ValueError`` when ``required_reviewers`` is not an ``int`` in
    ``1..MAX_REVIEWS``. Every evidence defect is returned as a link. A review
    whose reviewer, assignee or attempt id is changed to another valid,
    independent value still binds; only ``evidence_sha256`` changes.
    Attributes outside the five projected fields, for example a submission
    digest, do not enter ``evidence_sha256``.
    """
    if type(candidate) is not RepairCandidate:
        raise TypeError("repair_candidate_required")
    if type(required_reviewers) is not int or not 1 <= required_reviewers <= MAX_REVIEWS:
        raise ValueError("review_required_invalid")
    digest = candidate.digest()
    if reviews is None:
        return _link("review_set", "review_set_absent", digest)
    if type(reviews) not in (list, tuple):
        raise TypeError("review_set_container_invalid")
    if not reviews:
        return _link("review_set", "review_set_absent", digest)
    if len(reviews) > MAX_REVIEWS:
        return _link("review_set", "review_set_oversized", digest)
    try:
        projected = [_project_review(record) for record in reviews]
    except _Malformed:
        return _link("review_set", "review_malformed", digest)
    evidence = hashlib.sha256(
        _DOMAINS["review_set"]
        + _canonicalize({
            "schema_version": REPAIR_CANDIDATE_SCHEMA_VERSION,
            "candidate": digest,
            "reviews": [
                {
                    "review_attempt_id": attempt,
                    "reviewer_id": reviewer,
                    "assignee_id": assignee,
                    "reviewed_tree": reviewed_tree,
                    "accepted": accepted,
                }
                for attempt, reviewer, assignee, reviewed_tree, accepted in sorted(projected)
            ],
        })
    ).hexdigest()
    return _link("review_set", _review_reason(candidate, projected, required_reviewers), digest, evidence)
