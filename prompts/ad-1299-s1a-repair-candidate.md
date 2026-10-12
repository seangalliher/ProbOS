# AD-1299 S1a — Repair candidate identity and evidence binding

**Pin one frozen repair candidate (base commit, candidate commit, tree, reviewed index) and bind a real canonical gate receipt and an independent review set to it: refuse evidence that contradicts the candidate in the facts S1a checks (stale tree or commit, failed gate, wrong label or schema, self-review), and record each piece of evidence's sha256. Pure, unwired.**

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-11
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-11
**Status:** Ready for builder (Amendment 2, review round 2: apply the two docstring changes in Section 1, the test-file wording in Section 3 and the new test 41 to the already-built files; Amendment 1 is already applied)
**Issue / AD:** #1352, AD-1299, slice S1a. No new AD: this is the first buildable slice of the rescoped epic (DECISIONS.md, AD-1299 "Native rescope (2026-10-11)").
**Dependencies:** none. Base: `origin/main` at `cddcb9f6`.
**Estimated tests:** 41 test functions (34 original + 6 from Amendment 1 + 1 from Amendment 2), 117 collected cases (101 original, per the PROGRESS.md entry, + 15 from Amendment 1: 4 + 3 + 4 + 2 + 1 + 1, + 1 from Amendment 2), in one new file. One existing test file gains one allowlist entry.

---

## DO NOT BUILD (read first; repeated in the body and at the end)

- No store, database, table, file I/O, clock, event, `EventType`, config field, router, or runtime wiring. The module is pure.
- No import of `probos.work_item_steps`, `probos.workforce`, `probos.cognitive.crew_session`, `scripts/` or any runtime module from the new source module. The one permitted `probos` import is the lazy, function-level `probos.federation.ard.jcs`.
- No change to `scripts/run_test_gate.py`, `scripts/wave-orchestrator.ps1`, `WorktreeManager`, `BuildDispatcher`, `routers/build.py`, `FaultReportStore`, `repair_*` modules, or any `src/` file other than the one new module.
- No call into, and no reuse of, `WorktreeManager.merge_to_main`, `WorktreeManager.remove` or the repository-root `work_dir` of `routers/build.py` (they patch the running checkout; AD-1299 must never route through them).
- No claim, in code, docstring or test, that the binding prevents a write, refuses every edit, or that a review-set digest covers more than its five projected fields. S1a **refuses** evidence that contradicts the candidate in the facts it checks and **records** a sha256 per piece of evidence (receipt: the raw bytes; review set: the candidate-bound five-field projection only); it does not authenticate the producer, does not assert that unread fields are valid, and does not exclude a same-OS-identity writer (the canonical statement in Amendment 2).
- Do not run the broad gate. The orchestrator runs `scripts/run_test_gate.py` once, after review.

---

## Amendment 1 (review round 1, 2026-10-11)

The Diff Reviewer (GPT-6.1 Sol) returned **not ready to commit** with three findings; the orchestrator reproduced each with premise-asserting probes. Decisions (in-envelope, applied here; reason codes and check order are unchanged):

- **F1 [P2] Unreadable review evidence escaped as an exception.** `_project_review` caught only `AttributeError`, so a getter raising `ValueError` escaped `bind_reviews`, contradicting "bad evidence never raises". **Fix:** the attribute-read block catches `Exception` (never `BaseException`) and raises `_Malformed("review_attribute")`, so the outcome is `unavailable` / `review_malformed`; `KeyboardInterrupt`, `SystemExit` and `asyncio.CancelledError` still propagate. Tests 35 and 36.
- **F2 [P2] Overstated claim.** The text said the binding "DETECTS a substituted, stale or edited receipt or review by refusing it". It does not: an edit to a field S1a does not read (`finished_at`, `manifest.sha256`, `collection.sha256`, `tree.staged_diff_sha256`), or a review's reviewer, assignee or attempt changed to another valid, independent value, still returns `present`, with a different `evidence_sha256`. **Fix:** every occurrence now carries the canonical statement:

  > *(Round-1 statement, superseded by Amendment 2 because it overstated what the review-set digest covers.)* S1a **refuses** a receipt or review set that contradicts the candidate in the facts it checks. It **records** the evidence's sha256, so a consumer that retained an earlier trusted digest can detect any later change to the evidence, including a change to a field S1a does not read. …

  Blanket refusal is **not** required: the API has no expected-digest input. Test 14 stays and documents the specified behaviour; test 40 documents it for reviews.
- **F3 [P3] Non-finite numbers.** `parse_constant` refused the tokens `NaN`/`Infinity`/`-Infinity`, but a numeric literal such as `1e99999` parses to infinity and passed in an unread field or in `junit.totals.time_seconds`. **Fix:** a `parse_float` callback raises `_Malformed("non_finite")` when the value is not finite, so the receipt is `unavailable` / `gate_receipt_malformed`. `1e-99999` underflows to a finite `0.0` and stays allowed. Python 3.12's 4300-digit integer limit already makes an absurd integer a `ValueError` (malformed); kept. Tests 37-39.

What the Builder changes: `src/probos/cognitive/repair_candidate.py` to match Section 1 byte for byte (the changed lines are listed under "Amendment 1 code delta" in Section 1), and `tests/test_ad1299_s1a_repair_candidate.py` (module docstring lines 16-17 and the comment at line 563 reworded per Section 3; tests 35-40 added). No other test changes.

## Amendment 2 (review round 2, 2026-10-11)

Round 2 verified F1 and F3 repaired and returned **not ready to commit** on wording plus one specification test. Decisions (documentation only; no executable line, reason code or check order changes):

- **R2-F1 [P2] The canonical statement overstated the review-set digest.** A receipt's `evidence_sha256` is SHA-256 of the supplied raw bytes; a review set's is a domain-separated SHA-256 of only the candidate-bound projection of five fields (`review_attempt_id`, `reviewer_id`, `assignee_id`, `reviewed_tree`, `accepted`; built `bind_reviews`, lines 456-472). Changing any other review attribute (for example a `ReviewedStepResult`'s `submission_digest`) leaves the digest unchanged. **The canonical statement is now:**

  > S1a **refuses** a receipt or review set that contradicts the candidate in the facts it checks (commit, tree, status, schema and reviewer independence, plus the label when one is expected). It **records** a sha256 for each piece of evidence: for a receipt, the SHA-256 of the supplied raw bytes, so any change to those bytes changes it; for a review set, a domain-separated SHA-256 of the candidate-bound projection of five review fields (attempt id, reviewer id, assignee id, reviewed tree, accepted), so a change to those five fields changes it and a change to any other review attribute does not. A consumer that retained an earlier trusted digest can therefore detect a change within what each digest covers. S1a does not authenticate the producer, does not assert that unread fields are valid, and does not exclude a writer running under ProbOS's own OS identity.

  It replaces the round-1 statement in the module docstring, the `bind_reviews` docstring (one added sentence), the test-file docstring and the test 14/40 docstrings, and every doc carrier. New **test 41** pins the five-field scope.
- **R2-F2 [P2] C10 read as a conjunction of two faults** (architecture doc and #1352 body): restated as two independent requirements (see the C10 row there).
- **R2-F3 [P3] SLSA row** (Prior Art): `resolvedDependencies` is best effort, not complete; ProbOS states its own required input coverage (C6).
- **R2-F4 [P3] Citations** (Prior Art): the uncited NixOS row is removed; the in-toto layouts row cites the in-toto specification.

What the Builder changes in round 2: the two docstrings in Section 1 (listed under "Amendment 2 code delta"), the test-file docstring and the test 14/40 docstrings per Section 3, and test 41. No executable line changes.

---

## Problem

AD-1299 (#1352) must judge a repair campaign against **one frozen candidate**: the committed tree the canonical gate tested, the index the reviewers reviewed and (in S4) the promoted bytes. Nothing in `src/` names that identity or binds evidence to it.

- The canonical gate writes a success receipt that records `tree.head`, `tree.head_tree` and `tree.index_tree` and refuses an uncommitted index (`scripts/run_test_gate.py:1659-1662`, payload `:1663-1696`). The only consumer that checks a receipt against an admitted tree is PowerShell, in the wave pipeline (`scripts/wave-orchestrator.ps1:191-247`). No Python consumer exists, so no ProbOS component can bind a receipt to a repair candidate.
- Independent review provenance exists natively as `ReviewedStepResult` (`src/probos/work_item_steps.py:506-514`), and the reviewer must differ from the assignee (`work_item_steps.py:460,609`; `workforce.py:3509`). Nothing binds a review to the tree the gate tested, so an informal review of a different tree could be relabelled.
- The design reference (c) in #1352 requires a missing link to read as **unavailable**, never inferred.

## Solution

One new pure module, `src/probos/cognitive/repair_candidate.py`:

| Name | Kind | Purpose |
|---|---|---|
| `RepairCandidate` | frozen, slotted dataclass | `base_commit`, `candidate_commit`, `tree`, `index_tree`; refuses malformed ids, mixed hash lengths, and `index_tree != tree`. `projection()`, `canonical_bytes()`, `digest()`. |
| `EvidenceLink` | frozen, slotted dataclass | `kind`, `status`, `reason`, `candidate_digest`, `evidence_sha256`; `current` property. Self-consistent by construction; a report, not an authority token. |
| `ReviewAttestation` | `typing.Protocol` | The five facts `bind_reviews` reads (Interface Segregation). |
| `verify_gate_receipt(candidate, receipt_bytes, *, expected_label=None)` | function | Binds a canonical success receipt (schema 1) to the candidate. |
| `bind_reviews(candidate, reviews, *, required_reviewers=1)` | function | Binds an independent review set to the candidate. |
| `REASON_CODES`, `REPAIR_CANDIDATE_SCHEMA_VERSION`, `GATE_RECEIPT_SCHEMA_VERSION`, `MAX_RECEIPT_BYTES`, `MAX_REVIEWS` | constants | Pinned by tests. |

**Status semantics.** `present` = bound; `refused` = readable but contradicts the candidate in a fact S1a checks (stale tree or commit, failed gate, wrong label or schema, uncommitted index, self-review, unaccepted or duplicated review, review of another tree); `unavailable` = absent, empty, oversized, malformed (including unreadable review attributes and non-finite numbers), or not enough reviewers. Only `present` is current. Wrong argument *types* are programming errors and raise (`TypeError`/`ValueError`); bad *evidence* never raises. A change to a receipt field S1a does not read still binds and shows only as a different `evidence_sha256`; a change to a review attribute outside the five projected fields still binds and does not change `evidence_sha256` at all (the canonical statement, Amendment 2).

**Design decisions pinned (the Builder decides none of these):**

1. **Frozen stdlib dataclasses, not Pydantic.** The module must not coerce (Pydantic lax mode turns `"1"` into `1` and `1` into `True` in places); every field is checked with `type(x) is T`. Stdlib-only keeps the module importable without the model stack, like `probos.federation.ard.jcs` itself.
2. **Canonical JSON = AD-1144 RFC 8785 (`probos.federation.ard.jcs.canonicalize`), imported lazily inside `_canonicalize`.** DRY with the one standards-grade canonicaliser (the AD-1286 precedent, `cognitive/elastic_team.py:56-65`). Not stdlib `json.dumps(sort_keys=True)`: `jcs.py:8-22` documents why that is only "nearly" RFC 8785. Requires one `ALLOWED_EXCEPTIONS` entry in `tests/test_layer_boundaries.py` (Section 2), as for `cognitive/elastic_team.py` at line 128.
3. **Digest = `sha256(domain + canonical_bytes).hexdigest()`**, domain `b"probos.repair_candidate/candidate/v1\x00"`. The review-set digest uses `b"probos.repair_candidate/review_set/v1\x00"`. The projection holds only ASCII strings and the integer `1`, so no float rule ever applies. The key set is fixed per `schema_version`; a new field means schema 2, never a silent re-hash.
4. **Git object ids:** `^(?:[0-9a-f]{40}|[0-9a-f]{64})$` with `re.fullmatch`, never `re.match` and `$`, which accepts a trailing newline. All four candidate ids must share one length (no mixed SHA-1/SHA-256).
5. **Agent/attempt ids** mirror `probos.work_item_steps.OwnedId` (`^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`, `work_item_steps.py:32`), so S3 can project a `ReviewedStepResult` without loss. The pattern is copied, not imported (do-not-build: no `work_item_steps` import); test #34 guards the field names.
6. **Receipt parsing:** strict UTF-8 decode (a BOM is malformed); `json.loads` with an `object_pairs_hook` refusing duplicate keys, a `parse_constant` refusing the `NaN`/`Infinity`/`-Infinity` tokens, and (Amendment 1, F3) a `parse_float` refusing any numeric literal whose value is not finite (`1e99999`, `-1e99999`); `1e-99999` underflows to `0.0` and is allowed. An integer literal over Python 3.12's 4300-digit limit raises `ValueError` and is malformed. `RecursionError` from pathological nesting is malformed. Size cap `MAX_RECEIPT_BYTES = 1_048_576`. Extra keys are tolerated within schema 1.
7. **Check order is fixed**, so a reason code proves which boundary was reached. Gate: absent → type → empty → oversized → parse → `schema_version` → full shape read → label → clean success → uncommitted index → tree → commit. Reviews: absent → container type → empty → oversized → per-record shape → duplicate attempt → reviewer equals assignee → not accepted → tree → distinct reviewers.
8. **The receipt artifact files (manifest, JUnit, collection) are not re-hashed in S1a.** S1a takes bytes, not paths. It requires their `sha256` fields to be well-formed and carries the receipt's own sha256 as `evidence_sha256`. Re-hashing the artifact files against those fields is S1's file-backed binder (later slice), mirroring `wave-orchestrator.ps1:209-220`.
9. **Refuses versus records (Amendment 1, F2).** S1a refuses only what contradicts the candidate in the facts it checks. It has no expected-digest input, so it cannot refuse an edit to an unread field or a review re-labelled to another valid, independent value; it records `evidence_sha256` so that a consumer holding an earlier trusted digest can detect a change within what that digest covers: all raw bytes of a receipt, but only the five projected fields of a review set (Amendment 2). Wording anywhere must follow the canonical statement in Amendment 2.
10. **One broad catch, at one boundary (Amendment 1, F1).** `_project_review` reads attributes of an arbitrary caller-supplied object, and an attribute read can run any code. It catches `Exception` (not `BaseException`) and turns it into `review_malformed`, so evidence defects are returned while control-flow exceptions (`KeyboardInterrupt`, `SystemExit`, `asyncio.CancelledError`) propagate. No other broad catch is permitted in the module.

### The receipt shape consumed (from `scripts/run_test_gate.py:1663-1696`, schema 1)

| Key read | Required type | Malformed when | Refused when |
|---|---|---|---|
| `schema_version` | `int` | key absent | present but not exactly `int` `1` (`2`, `"1"`, `True`, `1.0`) → `gate_receipt_schema_unsupported` |
| `label` | `str` | absent or not `str` | `expected_label` given and unequal → `gate_receipt_label_mismatch` |
| `status.wrapper_exit_code`, `status.preflight_exit_code`, `status.pytest_exit_code` | `int` (not `bool`) | absent or wrong type | any `!= 0` → `gate_receipt_not_success` |
| `status.preflight_only`, `status.tree_changed` | `bool` | absent or wrong type | either `True` → `gate_receipt_not_success` |
| `tree.head`, `tree.head_tree`, `tree.index_tree` | git object id | absent or not a git object id | `head_tree != index_tree` → `gate_receipt_uncommitted_index`; `head_tree != candidate.tree` → `gate_receipt_tree_mismatch`; `head != candidate.candidate_commit` → `gate_receipt_commit_mismatch` |
| `manifest.sha256`, `junit.sha256`, `collection.sha256` | 64 lowercase hex | absent or malformed | — |
| `junit.totals.tests`, `junit.totals.failures`, `junit.totals.errors` | `int` | absent or wrong type | `tests <= 0`, `failures != 0` or `errors != 0` → `gate_receipt_not_success` |

These are the same success predicates the wave pipeline applies (`wave-orchestrator.ps1:195-201`, `:236-247`). Not read: `finished_at`, `tree.status_sha256`, `tree.raw_status_sha256`, `tree.staged_diff_sha256`, artifact `path`s, `collection.totals`, `junit.totals.skipped`, `junit.totals.time_seconds`, `junit.totals.extra_reports`. An edit to any of them still binds (with a different `evidence_sha256`), except that a non-finite number anywhere in the receipt makes it malformed (F3).

---

## Section 1 — New module `src/probos/cognitive/repair_candidate.py` (full code)

```python
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
```

**Amendment 1 code delta** (against the built `src/probos/cognitive/repair_candidate.py`, 448 lines, staged at review round 1). Everything else in the block above is unchanged:

1. Module docstring: the paragraph "Enforced versus detected: the binding DETECTS ..." (built lines 19-23) is replaced by the "Refuses versus records" paragraph.
2. Imports: `import math` added between `import json` and `import re`.
3. New function `_refuse_non_finite(text: str) -> float` (with its two-line comment), placed after `_refuse_constant`.
4. `_parse_receipt`: `json.loads(...)` gains the argument `parse_float=_refuse_non_finite,`.
5. `verify_gate_receipt` docstring: two sentences added on unread fields.
6. `_project_review`: `except AttributeError as exc:` becomes the five-line comment plus `except Exception as exc:  # noqa: BLE001 -- see the comment above`.
7. `bind_reviews` docstring: two sentences added on re-labelled reviews.

**Amendment 2 code delta** (against the built `src/probos/cognitive/repair_candidate.py`, 473 lines, staged at review round 2). Docstrings only; no executable line changes:

1. Module docstring: the "Refuses versus records" paragraph (built lines 19-28, 10 lines) is replaced by the 14-line paragraph above (the Amendment 2 canonical statement).
2. `bind_reviews` docstring: two lines added after "independent value still binds; only ``evidence_sha256`` changes." (built line 437): "Attributes outside the five projected fields, for example a submission" / "digest, do not enter ``evidence_sha256``."

After round 2 the module is 479 lines.

Notes for the Builder:

- The regexes have no `^`/`$` because every use is `fullmatch`. Do not switch any call to `match` or `search`.
- `# noqa: BLE001` follows the repository precedent (`src/probos/approval_authority.py:115`). Do not widen the catch to `BaseException` and do not add a second broad catch anywhere else.
- `_Malformed` subclasses `ValueError`. `_parse_receipt` catches `ValueError` (covering `json.JSONDecodeError` and the hooks' `_Malformed`) and re-raises one `_Malformed`; nothing escapes as a different exception.
- The module text must contain no `.db` literal: `tests/test_ad1265_backup_coverage.py:66` scans `src/probos` for them.

## Section 2 — Layer allowlist entry: `tests/test_layer_boundaries.py`

Add one entry to `ALLOWED_EXCEPTIONS`, directly after the AD-1286 entry. Single-line anchor (CRLF tree):

SEARCH (one line):
```
    ("cognitive/elastic_team.py", "probos.federation.ard.jcs"),
```
REPLACE:
```
    ("cognitive/elastic_team.py", "probos.federation.ard.jcs"),
    # AD-1299 S1a: the repair candidate hashes its identity with AD-1144's RFC 8785
    # canonicaliser, the AD-1286 precedent above (DRY; no second canonical-JSON
    # site). Lazy, function-level (``_canonicalize``); importing ``repair_candidate``
    # never imports the federation package (tests/test_ad1299_s1a_repair_candidate.py #9).
    ("cognitive/repair_candidate.py", "probos.federation.ard.jcs"),
```

`test_no_stale_allowed_exceptions` (`tests/test_layer_boundaries.py:227`) requires the import to exist, which Section 1 provides.

## Section 3 — New test file `tests/test_ad1299_s1a_repair_candidate.py`

### Fixtures (pinned; write them exactly so)

- `SCRIPT = REPO_ROOT / "scripts" / "run_test_gate.py"`. Load it as `tests/test_run_test_gate.py:24-30` does, but under the module name `"probos_test_ad1299_run_test_gate"` (register it in `sys.modules` before `exec_module`, because the script's dataclasses need their module registered). Module-scoped fixture `gate`.
- `_git(repo, *args)`: `subprocess.run(["git", "-c", "user.name=ProbOS Tests", "-c", "user.email=tests@probos.invalid", *args], cwd=repo, check=True, capture_output=True)`.
- `_rev(repo, ref) -> str`: `git rev-parse <ref>`, stripped.
- `repo` fixture (`tmp_path`): `git init -q`; write `tracked.txt` = `"base\n"`; add and commit `"base"`; write `tracked.txt` = `"candidate\n"`; add and commit `"candidate"`. `base = _rev(repo, "HEAD~1")`.
- `_candidate(repo) -> RepairCandidate`: `RepairCandidate(base_commit=_rev(repo, "HEAD~1"), candidate_commit=_rev(repo, "HEAD"), tree=_rev(repo, "HEAD^{tree}"), index_tree=_rev(repo, "HEAD^{tree}"))`.
- `_real_receipt(gate, repo, *, label="ad1299-s1a") -> bytes` produces the receipt with the **real producer**, `gate._write_success_receipt` (`run_test_gate.py:1641`):
  ```python
  gates = repo / "logs" / "gates"
  gates.mkdir(parents=True, exist_ok=True)
  manifest = gates / f"{label}.json"; manifest.write_text("{}\n", encoding="utf-8")
  junit = gates / f"{label}.xml"; junit.write_text("<testsuites/>\n", encoding="utf-8")
  collection = gates / f"{label}.collection.json"; collection.write_text("{}\n", encoding="utf-8")
  snapshot = gate._snapshot_tree(repo)
  result = gate.GateResult(
      label=label, started_at="2026-10-11T00:00:00Z", finished_at="2026-10-11T00:00:01Z",
      elapsed_seconds=1.0, wrapper_exit_code=0, preflight_exit_code=0, pytest_exit_code=0,
      preflight_only=False, interrupted=False, error="", tree_changed=False,
      snapshot_before=snapshot, snapshot_after=snapshot, command=["pytest"], phases=[],
      sanitized_pytest_environment=[], summary="", log_path="", junit_path=str(junit),
      junit_totals=gate.JUnitTotals(tests=1, failures=0, errors=0, skipped=0, time_seconds=0.1),
      collection_path=str(collection),
      collection_totals=gate.CollectionTotals(nodes=1, workers=1, sha256="0" * 64),
  )
  receipt = gates / f"{label}.receipt.json"
  gate._write_success_receipt(
      receipt, repo_root=repo, result=result, source_snapshot=snapshot,
      manifest_path=manifest, junit_path=junit, collection_path=collection,
  )
  return receipt.read_bytes()
  ```
  The untracked `logs/` files do not change `write-tree`, so `head_tree == index_tree`. Calling the script's private helpers is the precedent of `tests/test_run_test_gate.py` (it calls `gate._sha256_file`); it is the only way to get a real receipt without running pytest inside pytest.
- `_mutate(receipt_bytes, dotted_path, value) -> bytes`: `json.loads`, set the nested key, then `json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"`.
- `_Review`: a test-local `@dataclass(frozen=True)` with `review_attempt_id`, `reviewer_id`, `assignee_id`, `reviewed_tree`, `accepted`, satisfying `ReviewAttestation`.
- `_ids(n)`: `(c * 40 for c in "abcdef")` style fixed ids for pure tests.

**Premise rule (mandatory).** Every refusal or unavailability test that mutates a real receipt first asserts that the **unmutated** receipt binds (`status == "present"`), then asserts the exact `reason`. The fixed check order (design decision 7) makes the reason code the proof of which boundary was reached. A test that asserts only `status != "present"` is not acceptable.

### Named tests

**Candidate identity**
1. `test_candidate_accepts_matching_full_object_ids`: parametrized over 40- and 64-hex ids; constructs and round-trips fields.
2. `test_candidate_refuses_index_tree_that_differs_from_tree`: `ValueError("repair_candidate_uncommitted_index")`.
3. `test_candidate_refuses_malformed_ids`: parametrize one field over `""`, `None`, `"A" * 40`, `"a" * 39`, `"a" * 41`, `"a" * 40 + "\n"`, `0`, `b"a" * 40`; `ValueError("repair_candidate_field_invalid")`.
4. `test_candidate_refuses_mixed_hash_lengths`: 40-hex commit with 64-hex tree.
5. `test_candidate_is_frozen`: assignment raises `dataclasses.FrozenInstanceError`.
6. `test_candidate_digest_is_domain_separated_sha256_of_rfc8785`: `digest() == sha256(b"probos.repair_candidate/candidate/v1\x00" + jcs.canonicalize(projection())).hexdigest()` and `!= sha256(canonical_bytes()).hexdigest()`.
7. `test_candidate_canonical_bytes_golden`: with `base="a"*40`, `commit="b"*40`, `tree=index="c"*40`, `canonical_bytes() == b'{"base_commit":"' + b"a"*40 + b'","candidate_commit":"' + b"b"*40 + b'","index_tree":"' + b"c"*40 + b'","schema_version":1,"tree":"' + b"c"*40 + b'"}'`.
8. `test_candidate_digest_changes_with_each_field`: parametrize `base_commit`, `candidate_commit`, and `tree`+`index_tree` together; the digest differs from the baseline.
9. `test_module_import_does_not_import_federation`: (a) static AST: no module-scope `probos.*` import, and `probos.federation.ard.jcs` appears only inside `_canonicalize`; (b) subprocess `python -c "import probos.cognitive.repair_candidate, sys; print('probos.federation' in sys.modules)"` prints `False` (pattern: `tests/test_ad1286_elastic_team_contract.py:998-1006`).

**Gate receipt (real producer)**
10. `test_real_receipt_binds_its_own_candidate`: the seam test. `status == "present"`, `reason == "gate_receipt_bound"`, `current is True`, `evidence_sha256 == sha256(receipt_bytes)`, `candidate_digest == candidate.digest()`; with `expected_label="ad1299-s1a"` it also binds.
11. `test_receipt_for_an_older_tree_is_refused_as_stale`: receipt produced at `HEAD`, then a third commit changes `tracked.txt`; the candidate built from the new `HEAD` gets `gate_receipt_tree_mismatch`. Premise: the receipt binds the candidate built before the third commit.
12. `test_receipt_for_same_tree_other_commit_is_refused`: after the receipt, `git commit --allow-empty -m again`; assert the premise `HEAD^{tree}` is unchanged, then the new-commit candidate gets `gate_receipt_commit_mismatch`.
13. `test_receipt_with_uncommitted_index_is_refused`: `_mutate(tree.index_tree, "d"*40)` → `gate_receipt_uncommitted_index`.
14. `test_edited_receipt_changes_evidence_digest`: any `_mutate` that still binds (for example `finished_at`) yields a different `evidence_sha256`. **Specified behaviour, not a gap** (Amendment 1, F2): S1a does not read that field, so it binds; the changed digest is what lets a consumer holding an earlier trusted digest detect the edit. Built test unchanged except its wording: give it a docstring that says so and cites the canonical statement, and replace the comment at built line 563 with `# a field S1a does not read: still binds (specified); only the recorded digest changes`. **Amendment 2:** in the built docstring (test file lines 561-566) replace the round-1 canonical paragraph with the Amendment 2 statement (text pinned under "Amendment 2 test-file wording" below); keep lines 568-569 as they are (they are true for a receipt).
15. `test_receipt_not_describing_clean_success_is_refused`: parametrize `status.wrapper_exit_code=1`, `status.preflight_exit_code=2`, `status.pytest_exit_code=1`, `status.preflight_only=True`, `status.tree_changed=True`, `junit.totals.tests=0`, `junit.totals.failures=1`, `junit.totals.errors=1` → `gate_receipt_not_success`.
16. `test_receipt_schema_version_other_than_int_one_is_refused`: parametrize `2`, `0`, `"1"`, `True`, `1.0` → `gate_receipt_schema_unsupported`.
17. `test_receipt_label_mismatch_is_refused`: `expected_label="other"` → `gate_receipt_label_mismatch`.
18. `test_receipt_absent_or_empty_is_unavailable`: `None` → `gate_receipt_absent`; `b""` → `gate_receipt_empty`; both with `evidence_sha256 == ""`.
19. `test_receipt_oversized_is_unavailable`: `b" " * (MAX_RECEIPT_BYTES + 1)` → `gate_receipt_oversized`.
20. `test_receipt_malformed_is_unavailable`: parametrize `b"not json"`; `b"[]"`; `b"\xff\xfe"`; a receipt with a duplicated top-level key (hand-written bytes); `NaN` substituted for `junit.totals.tests` in the bytes; UTF-8 BOM + the real receipt; the receipt without `tree`; `tree.head="HEAD"`; `status.wrapper_exit_code=False`; `manifest.sha256="abc"`; the receipt without `schema_version`; `b"[" * 200_000`. All → `gate_receipt_malformed`. For every mutation of the real receipt, assert the premise first.
21. `test_receipt_wrong_argument_types_raise`: receipt as `str`, `bytearray`, `memoryview` → `TypeError("gate_receipt_bytes_required")`; candidate as `dict` → `TypeError("repair_candidate_required")`; `expected_label=""` or `7` → `ValueError("gate_receipt_label_invalid")`.
22. `test_reason_codes_are_pinned`: `REASON_CODES` equals the 20-code literal set in Section 1, and every link the tests produce has `reason in REASON_CODES`.

**Review set**
23. `test_independent_accepted_reviews_bind`: two reviews (`red_team`, `system_qa`; assignee `builder`; tree = candidate tree; accepted), `required_reviewers=2` → `review_set_bound`, `current is True`, 64-hex `evidence_sha256`.
24. `test_self_review_is_refused`: one review with `reviewer_id == assignee_id` → `review_not_independent` (premise: the same review with a different reviewer binds).
25. `test_unaccepted_review_is_refused` → `review_not_accepted`.
26. `test_review_of_another_tree_is_refused`: `reviewed_tree = "e"*40` → `review_tree_mismatch`.
27. `test_duplicate_review_attempt_is_refused` → `review_attempt_duplicate`.
28. `test_too_few_distinct_reviewers_is_unavailable`: the same reviewer on two attempts, `required_reviewers=2` → `review_insufficient`, status `unavailable`.
29. `test_reviews_absent_or_empty_is_unavailable`: `None`, `[]`, `()` → `review_set_absent`.
30. `test_review_set_oversized_is_unavailable`: `MAX_REVIEWS + 1` well-formed reviews → `review_set_oversized`.
31. `test_malformed_review_is_unavailable`: parametrize `object()`, `reviewer_id=""`, `review_attempt_id="has space"`, `accepted="yes"`, `accepted=1`, `reviewed_tree="C"*40` → `review_malformed`.
32. `test_review_set_digest_is_order_independent_and_candidate_bound`: reversing the list gives the same `evidence_sha256`; a different candidate gives a different one.
33. `test_review_wrong_argument_types_raise`: `reviews="abc"`, `{}`, a generator → `TypeError("review_set_container_invalid")`; `required_reviewers` of `0`, `True`, `MAX_REVIEWS + 1` → `ValueError("review_required_invalid")`; candidate `None` → `TypeError`.
34. `test_review_attestation_fields_exist_on_owned_review_records`: a drift guard for S3. `{"reviewer_id", "review_attempt_id", "accepted"} <= set(ReviewedStepResult.model_fields)` and `"assignee_id" in OwnedStepExecutionPermit.model_fields` (import `probos.work_item_steps` in the **test** only).

**Amendment 1 tests (new; append to the built file)**
35. `test_review_getter_raising_is_unavailable`: parametrize `(attribute, exception)` over `("reviewer_id", ValueError)`, `("reviewer_id", RuntimeError)`, `("reviewer_id", KeyError)`, `("accepted", ValueError)`. A test-local class `_RaisingReview` takes the five `_Review` values plus `raising: str` and `error: type[Exception]`; each attribute is a `@property` returning the value, except `raising`, which raises `error("boom")`. **Premise:** `_RaisingReview(...)` with `raising=""` (no attribute raises) and the same values binds (`review_set_bound`), and reading the raising attribute directly raises `error` (`pytest.raises`). Then `bind_reviews(candidate, [raising_record])` returns `("unavailable", "review_malformed")`, `evidence_sha256 == ""`, and raises nothing.
36. `test_review_getter_control_flow_exception_propagates`: parametrize `KeyboardInterrupt`, `SystemExit`, `asyncio.CancelledError` (each a `BaseException`, not an `Exception`: assert `not issubclass(error, Exception)` as the premise). The same `_RaisingReview` with that error on `reviewer_id`: `pytest.raises(error)` around `bind_reviews`. Premise: the readable twin binds.
37. `test_receipt_non_finite_number_is_unavailable`: parametrize `literal` over `b"1e99999"`, `b"-1e99999"` and `location` over the unread field `finished_at` (marker `b'"finished_at": "2026-10-11T00:00:01Z"'`) and `junit.totals.time_seconds` (marker `b'"time_seconds": 0.1'`); 4 cases. **Premises:** `math.isinf(json.loads(literal))`; the unmutated receipt binds; the marker occurs exactly once, so the substitution lands (`real.count(marker) == 1`); and a lenient `json.loads(raw)` reads the substituted location as an infinity (so only the F3 rule can make this receipt malformed). Then `("unavailable", "gate_receipt_malformed")`, with `evidence_sha256 == sha256(raw)`.
38. `test_receipt_finite_underflow_number_still_binds`: `b"1e-99999"` substituted at the same two locations (2 cases). Premise: `json.loads(b"1e-99999") == 0.0`. Result: `("present", "gate_receipt_bound")`.
39. `test_receipt_oversized_integer_literal_is_unavailable`: a 5000-digit integer literal (`b"9" * 5000`) substituted for `junit.totals.time_seconds`. Premise: `json.loads(literal)` raises `ValueError` (Python 3.12's integer-string limit). Result: `gate_receipt_malformed`.
40. `test_edited_review_changes_evidence_digest`: specified behaviour (F2). Premise: `_two_independent_reviews()` binds. Replace the first review's `reviewer_id` with `"counselor"` (still valid and independent) and, separately, its `review_attempt_id` with `"attempt-9"`. Each still returns `("present", "review_set_bound")` with an `evidence_sha256` different from the original's. The docstring cites the canonical statement. **Amendment 2:** in the built docstring (test file lines 1467-1472) replace the round-1 canonical paragraph with the Amendment 2 statement; keep lines 1474-1475, and add after them one sentence: "Both edited fields are among the five the review-set digest covers, which is why the digest changes; test 41 pins that an attribute outside them does not."

**Amendment 2 test (new; append to the built file)**
41. `test_review_digest_ignores_attributes_outside_the_projection`: specified behaviour (R2-F1). Define a test-local `@dataclass(frozen=True) class _ReviewWithSubmission(_Review)` adding `submission_digest: str = "a" * 64` (the `ReviewedStepResult.submission_digest` analogue, `work_item_steps.py:508`). Build `first = _ReviewWithSubmission(review_attempt_id="attempt-1", reviewer_id="red_team", submission_digest="a" * 64)` and `second = dataclasses.replace(first, submission_digest="b" * 64)`. **Premises:** `first.submission_digest != second.submission_digest`; the five projected fields are equal (`_review_record(first) == _review_record(second)`, the existing helper at built line ~996); `bind_reviews(candidate, [first])` and `bind_reviews(candidate, [second])` each return `("present", "review_set_bound")`. **Assertion:** their `evidence_sha256` values are equal. Docstring: "Specified behaviour, not a gap (Amendment 2, R2-F1): a review-set digest covers only the candidate-bound five-field projection, so an attribute outside it (here a submission digest) does not change it." followed by the Amendment 2 canonical statement. 1 case.

**Amendment 2 test-file wording** (the Amendment 2 canonical statement, wrapped for the test docstrings; use it verbatim at test 14 and test 40, indented to the docstring):

```
The canonical statement (Amendment 2): S1a refuses a receipt or review set that contradicts the
candidate in the facts it checks (commit, tree, status, schema and reviewer independence, plus the
label when one is expected). It records a sha256 for each piece of evidence: for a receipt, the
SHA-256 of the supplied raw bytes, so any change to those bytes changes it; for a review set, a
domain-separated SHA-256 of the candidate-bound projection of five review fields (attempt id,
reviewer id, assignee id, reviewed tree, accepted), so a change to those five fields changes it
and a change to any other review attribute does not. A consumer that retained an earlier trusted
digest can therefore detect a change within what each digest covers. S1a does not authenticate
the producer, does not assert that unread fields are valid, and does not exclude a writer running
under ProbOS's own OS identity.
```

And replace the test-file module docstring lines 16-19 ("S1a refuses evidence that contradicts the candidate ... It does not authenticate the producer.") with:

```
S1a refuses evidence that contradicts the candidate in the facts it checks and
records a sha256 per piece of evidence: a receipt's covers its raw bytes, a
review set's covers only the candidate-bound five-field projection. An edit to
an unread receipt field still binds and changes the digest (test 14); a review
re-labelled within the five fields still binds and changes it (test 40); a
review attribute outside the five does not change it (test 41). It does not
authenticate the producer.
```

**Wording change in the built test file, Amendment 1** (applied in round 1; superseded by the Amendment 2 test-file wording above): replace the module-docstring lines 16-17 ("The binding DETECTS a substituted, stale or edited receipt or review by refusing the link. It does not authenticate who produced the bytes.") with: "S1a refuses evidence that contradicts the candidate in the facts it checks and records each piece of evidence's sha256; an edit to an unread field still binds and is detectable only by a consumer holding an earlier digest (tests 14 and 40). It does not authenticate the producer."

**EvidenceLink self-consistency** (fold into #22 or add as 22b): `EvidenceLink("gate_receipt", "present", "gate_receipt_not_success", "0"*64)` raises `ValueError("evidence_link_invalid")`, as does a review reason on a `gate_receipt` kind.

### Focused tests the Builder runs (no broad gate)

1. `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1299_s1a_repair_candidate.py -v -n 0`: the new file, 41 functions, 117 cases. Run it with the worktree's `src` on the path: the shared `d:/ProbOS/.venv` editable install points at `d:/ProbOS/src`, so from a worktree collection fails with `ModuleNotFoundError: probos.cognitive.repair_candidate` unless `PYTHONPATH` names this worktree's `src` (observed by the Architect on 2026-10-11).
2. `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_layer_boundaries.py -q -n 0`: the allowlist entry and the stale-exception check.
3. `git add src/probos/cognitive/repair_candidate.py` (the architecture checker sees tracked files only, `tests/test_ad1270b_architecture_fitness.py:739`), then `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1270b_architecture_fitness.py -q -n 0`: the committed baseline must still pass with the new module (`:192`).
4. `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_run_test_gate.py -q -n 0`: confirms the producer is unchanged and that loading it under a second module name interferes with nothing.
5. `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1265_backup_coverage.py -q -n 0`: the `src/` scan for `.db` literals.

The broad gate (`scripts/run_test_gate.py --label ... --receipt ...`) is run once by the orchestrator, not the Builder.

---

## What This Does NOT Change

- `scripts/run_test_gate.py` and its receipt schema; `scripts/wave-orchestrator.ps1` and its receipt verifier.
- `WorktreeManager`, `BuildDispatcher`, `routers/build.py`, `execute_approved_build`, the native harness, `CopilotBuilderAdapter`.
- `FaultReportStore` (its expected-state guard is S2), `repair_brief`, `repair_dispatch`, `repair_issue`, `repair_verification`.
- CrewSession/WorkItem stores, `work_item_steps` (only read by test #34), approvals, `ApprovalAuthorityStore`.
- AD-1315/AD-1316 (`execution/authority.py`, `execution/effect_broker.py`), which stay default OFF.
- No config, event, API or UI surface.

## Tracking

- `PROGRESS.md`: the orchestrator records "AD-1299 S1a built (#1352)" after the gate. The Builder does not edit it.
- `docs/development/roadmap.md` and `DECISIONS.md`: already updated by the rescope; Amendment 1 corrected the refuse-versus-record wording there and in the architecture doc and the #1352 body (Architect-owned; no Builder edit).
- #1352: tick nothing. S1 is complete only when the file-backed binder and backend conformance land.

## Acceptance Criteria

- [ ] `src/probos/cognitive/repair_candidate.py` matches Section 1 (names, signatures, reason codes, domains, check order).
- [ ] One `ALLOWED_EXCEPTIONS` entry added exactly as in Section 2; no other edit to `tests/test_layer_boundaries.py`.
- [ ] `tests/test_ad1299_s1a_repair_candidate.py` has tests 1-41 (41 functions, 117 cases), every mutation test asserting its premise and its exact reason code; tests 1-40 are unchanged except the wording named in Section 3.
- [ ] Amendment 2: no text in the module, the tests or the docs says a review-set digest covers more than its five projected fields; test 41 passes.
- [ ] Amendment 1: no getter exception other than a `BaseException` escapes `bind_reviews`; no non-finite number binds; no text in the module, the tests or the docs claims that S1a refuses every edit.
- [ ] Test #10 uses a receipt written by the real `_write_success_receipt`, not a hand-built dict.
- [ ] Focused runs 1-5 pass at `-n 0`.
- [ ] Only these files change: the new module, the new test file, `tests/test_layer_boundaries.py`.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-10-11)

Base `origin/main` `cddcb9f6` (`git log --oneline -3` → `cddcb9f6 Merge pull request #1503 ...`).

```
Read scripts/run_test_gate.py:1641-1706
  1641: def _write_success_receipt(
  1659:     head_tree = _git_bytes(repo_root, "rev-parse", "HEAD^{tree}").decode().strip()
  1660:     index_tree = _git_bytes(repo_root, "write-tree").decode().strip()
  1661:     if head_tree != index_tree:
  1662:         raise RuntimeError("Cannot issue a success receipt for an uncommitted index")
  1664:         "schema_version": 1,
  1667-1673: "status": {wrapper_exit_code, preflight_exit_code, pytest_exit_code, preflight_only, tree_changed}
  1674-1681: "tree": {head, head_tree, index_tree, status_sha256, raw_status_sha256, staged_diff_sha256}
  1682-1695: "manifest"/"junit"/"collection": {path, sha256[, totals]}
  1700:             json.dump(payload, handle, indent=2, sort_keys=True)
Read scripts/run_test_gate.py:112-187 (TreeSnapshot, JUnitTotals, CollectionTotals, GateResult fields)
Read scripts/run_test_gate.py:466-480
  467:     head = _git_bytes(repo_root, "rev-parse", "HEAD").decode().strip()   (tree.head is a full object id)
grep -n "def _write_[a-z_]*receipt|..." scripts/run_test_gate.py
  1641 only writer; receipt written only on success (2068: if receipt_path is not None and wrapper_exit_code == 0)
Read scripts/wave-orchestrator.ps1:191-247   (existing PowerShell receipt checks mirrored by S1a)
Read tests/test_run_test_gate.py:20-30        (SCRIPT path, importlib loader, sys.modules registration)
grep -n "_sha256_file" tests/test_run_test_gate.py
  1443: assert receipt["manifest"]["sha256"] == gate._sha256_file(manifest_path)   (private-helper precedent)
Read src/probos/federation/ard/jcs.py:1-73
  32: __all__ = ["canonicalize"]
  53: def canonicalize(value: object) -> bytes:
Read src/probos/cognitive/elastic_team.py:48-73   (domain-prefixed sha256 + lazy jcs import precedent)
Read tests/test_layer_boundaries.py:45-57,122-128,132-160
  51:     "cognitive": {"knowledge", "substrate", "mesh"},
  128:    ("cognitive/elastic_team.py", "probos.federation.ard.jcs"),
grep -n "^def test_" tests/test_layer_boundaries.py
  182: test_no_undocumented_cross_layer_imports   227: test_no_stale_allowed_exceptions
grep -n "probos.federation" tests/test_ad1286_elastic_team_contract.py
  993-1006: static + subprocess "not imported" pattern
grep -n "^def test_" tests/test_ad1270b_architecture_fitness.py
  192: test_committed_baseline_passes_check_in_a_subprocess   739: test_untracked_violation_is_invisible
grep -n "rglob" tests/test_ad1265_backup_coverage.py
  66: for path in sorted((root / "src" / "probos").rglob("*.py")):   (scans for *.db literals)
Read src/probos/work_item_steps.py:32,322-330,450-464,506-514,595-614
  32:  OwnedId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
  330:     assignee_id: OwnedId
  460:             or self.reviewer_id == self.permit.assignee_id
  506: class ReviewedStepResult(_OwnedFormat):
  512:     reviewer_id: OwnedId   513: review_attempt_id: OwnedId   514: accepted: bool
  609:             or self.reviewed_result.reviewer_id == self.assignee_id
Read src/probos/workforce.py:3500-3513
  3509:                 or reviewer_id == row.assignee_id
grep -n "class CodeReviewAgent" src/probos/cognitive/code_reviewer.py
  25: class CodeReviewAgent(CognitiveAgent):
Read src/probos/worktree_manager.py:97-169
  105: "worktree", "remove", "--force", info.path    112: ("branch", "-D", info.branch)
  143: async def merge_to_main(...)   154: ("checkout", "main")   159: ("merge", info.branch, "--no-edit")
Read src/probos/routers/build.py:52-65
  60:     work_dir = str(pathlib.Path(__file__).resolve().parent.parent.parent.parent)
```

Amendment 1 anchors (re-read 2026-10-11 against the built, staged files; no earlier anchor moved, because no production file outside the new module changed):

```
Read src/probos/cognitive/repair_candidate.py:1-448 (built, staged)
  19-23:  "Enforced versus detected: the binding DETECTS a substituted, stale or edited ..."   (F2 text)
  32-37:  imports hashlib, json, re, collections.abc.Sequence, dataclass, typing      (no math)
  259-260: def _refuse_constant(name: str) -> Any: raise _Malformed(name)
  263-274: def _parse_receipt -- json.loads(..., object_pairs_hook=..., parse_constant=...)   (no parse_float: F3)
  363-371: def _project_review -- except AttributeError as exc: raise _Malformed("review_attribute")   (F1)
Read tests/test_ad1299_s1a_repair_candidate.py (built, staged)
  16-17:  "The binding DETECTS a substituted, stale or edited receipt or review by refusing the link."
  555-570: test_edited_receipt_changes_evidence_digest; 563: "# an edit to a field the binder does not read still binds, and is still detectable"
  204-212: class _Review   231-235: _two_independent_reviews()   755-763: NaN substitution helpers (the pattern tests 37-39 follow)
  34 test functions (grep -n "^def test_"): lines 244 ... 1225
Read scripts/run_test_gate.py:1689
  1689:             "totals": asdict(result.junit_totals),   (so junit.totals carries time_seconds, skipped, extra_reports)
grep -n "BLE001" src/probos/approval_authority.py
  115:     except Exception:  # noqa: BLE001 -- no open transaction is the common case
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1299_s1a_repair_candidate.py --collect-only -q -n 0   (from this worktree)
  ModuleNotFoundError: No module named 'probos.cognitive.repair_candidate'  (shared venv's editable install -> d:/ProbOS/src)
```

Amendment 2 anchors (re-read 2026-10-11 against the built, staged files after round 1):

```
Read src/probos/cognitive/repair_candidate.py (473 lines)
  19-28:   "Refuses versus records: ... can detect any later change to the evidence, including a change to a field this module does not read."
  430-438: bind_reviews docstring ("... only ``evidence_sha256`` changes.")
  456-472: evidence = sha256(_DOMAINS["review_set"] + _canonicalize({schema_version, candidate, reviews: [five-field dicts for sorted(projected)]}))
Read tests/test_ad1299_s1a_repair_candidate.py (built, round 1)
  16-19:     module docstring, round-1 wording
  558-570:   test 14 docstring (561-566: round-1 canonical paragraph)
  996:       def _review_record(review: _Review) -> dict[str, object]
  1464-1476: test 40 docstring (1467-1472: round-1 canonical paragraph)
  41 functions after test 41 (grep -n "^def test_": 40 today, 247 ... 1464)
Read src/probos/work_item_steps.py:506-514
  508:     submission_digest: OwnedDigest   (ReviewedStepResult; not one of the five projected fields)
```

## Absence Verified (2026-10-11)

```
CLAIM: no repair-candidate identity or evidence binder exists yet
RUN:   Grep "RepairCandidate|EvidenceLink|ReviewAttestation|verify_gate_receipt|bind_reviews" (whole repo)
FOUND: no files (before this prompt was written)
HOLDS: yes

CLAIM: no Python consumer of gate receipts exists
RUN:   Grep "def [a-z_]*receipt[a-z_]*\(" scripts/      -> scripts/run_test_gate.py:1641 (_write_success_receipt, the producer)
RUN:   Grep "head_tree|index_tree" src/                 -> no files
RUN:   Grep "verify_build_receipt" (whole repo)         -> scripts/wave-orchestrator.ps1, tests/test_run_test_gate.py
HOLDS: yes -- the only consumer is the PowerShell wave pipeline

CLAIM: the target paths are free
RUN:   Glob src/probos/cognitive/repair_candidate*  -> no files
RUN:   git ls-files tests/test_ad1299*              -> empty
RUN:   Glob prompts/ad-1299*                        -> no files (before this prompt)
HOLDS: yes

CLAIM: no model-family provenance exists to bind a review to (so S1a does not try)
RUN:   Grep "model_family|provider_family|reviewer_model" src/probos -> no files
HOLDS: yes

CLAIM (Amendment 1): the overstated claim is gone from every Architect-owned carrier
RUN:   Grep "(?i)detect|substitut|refuses the link|hash binding" over this prompt, the architecture doc,
       the #1352 body draft, the AD-1299 DECISIONS block and the roadmap section
FOUND: only the canonical refuses-versus-records wording and unrelated uses ("detected where only detectable",
       "detection-only delegation", "not a substitute for isolation")
HOLDS: yes for Architect-owned files; the module and test-file wording is the Builder's per Section 1 and Section 3,
       and PROGRESS.md is the orchestrator's
```

---

## Prior Art and Blind Spots (reviewed 2026-10-11)

Bounded pass run under the standing "anything not considered, or prior work to leverage" instruction (PR #1505), after this prompt was first drafted.
S1a's code is unchanged by it (Amendment 1 is the review round, not this pass). The findings become named constraints on later slices (C1-C11, listed in `docs/development/self-maintenance-architecture.md`).
Evidence status of the external references: the in-toto DigestSet specification, the systemd boot-assessment page and the two CVE records were checked against the
primary page or an advisory summary; the others rest on search summaries and should be re-read before they are quoted elsewhere. Other projects are described only as
technical design references.

### Internal prior work

| Source | What applies | Decision |
|---|---|---|
| `DECISIONS.md` AD-1047 ("score is not trust"; JWS honest degrade: `signature_verified` is always False because no verifier-key infrastructure exists in `src/probos`) | Verification evidence is not authority, and an unverifiable signature must not raise trust. | **Absorb.** S1a already says a hash is an integrity binding, not authentication; no field implies a producer was authenticated. |
| `DECISIONS.md` AD-1144 (RFC 8785 JCS) and AD-1286 (domain-prefixed sha256, lazy import) | Canonical identity bytes. | **Absorb** (already used by `RepairCandidate.digest`). |
| `DECISIONS.md` AD-1315 ("a restart or changed effective manifest advances generation and revokes older grants") | Monotonic generation; stale grants refused. | **Adapt** for S4: the controller's activation sequence is monotonic and never reused (C1). Semantics only; the store is not reused, because the controller is out of process. |
| `Vibes/Nooplex_Final.md` section 7.10 (shadow deployment, comparative evaluation against the incumbent, cutover or rollback, recorded with provenance) | Compare the candidate with the incumbent, not only against its own tests. | **Adapt** for S3 (C11). |
| `CLAUDE.md` workflow step 5 ("a base that moves after the gate invalidates it") | Gate evidence goes stale when the base moves. | **Adapt** for S4 promotion (C10). |
| `docs/research/` (38 studies) | Searched for rollback, attestation, provenance and self-modification. The hits are in memory and knowledge studies; none covers release, promotion or attestation. | Nothing to cite. |

### External technical design references

| Reference | Design idea | Decision |
|---|---|---|
| in-toto attestation DigestSet, https://github.com/in-toto/attestation/blob/main/spec/v1/digest_set.md (read) and the Statement v1 shape, https://in-toto.io/Statement/v1 | `gitCommit` and `gitTree` are defined as lowercase-hex SHA-1 (40) or SHA-256 (64) object ids, the shapes S1a validates. A Statement binds a typed predicate (`predicateType`) to subject digests. | **Adapt.** `EvidenceLink.kind` plays the predicate-type role and `candidate_digest` the subject role; S1a's 40/64 id rule matches. **Considered, deferred:** emitting in-toto/DSSE envelopes. Without signing keys an envelope would imply an authenticity ProbOS cannot provide (AD-1047). |
| in-toto layouts, in the in-toto specification, https://github.com/in-toto/specification/blob/master/in-toto-spec.md (checked by the orchestrator) | The project owner defines the steps, who performs each and in what order; verification checks that a step was intended and done by the right actor. | **Adapt** for S1b: a required-evidence-kinds set per authority class; completion only when every required kind is `present` (C9). |
| SLSA Provenance v1, https://slsa.dev/provenance/v1 | `buildDefinition.resolvedDependencies` lists build-time dependencies with digests on a best-effort basis; the specification does not require it to be complete (at least through Build L3). | **Adapt** for S4. ProbOS states its own required input coverage rather than inheriting completeness from that field: the tracked `uv.lock` and `ui/package-lock.json` through the tree digest, plus the interpreter version and an installed-environment digest in the manifest, with the release validated in its own environment (C6). **Considered, deferred:** SLSA build levels and builder attestation. |
| TUF security model, https://theupdateframework.io/security/ | Rollback, freeze and fast-forward attacks; metadata versions must never decrease. | **Adapt** for S4: a monotonic activation sequence (C1) and base freshness (C10). **Rejected for v1:** TUF role and threshold signing, which needs keys (a secret, NEEDS CAPTAIN) and adds nothing against a writer with ProbOS's own OS identity, consistent with parked D-B2. |
| go-tuf CVE-2022-29173 (advisory GHSA-66x3-6cw3-v5gj; checked via an advisory summary) | A client did not check that the version of non-root metadata was not lower than the previously trusted one, so older but still valid metadata could be accepted. | **Absorb** as S4 C2: rollback protection applies to every state record, and an absent, unreadable or zero journal or generation fails closed rather than defaulting. |
| tough CVE-2025-2888 (advisory GHSA-76g3-38jv-wxh4; checked via an advisory summary) | Timestamp metadata was cached even though it failed the snapshot rollback check, so a later valid update could be rejected until the cache was cleared. | **Absorb** as S4 C3: verify, then persist. |
| systemd Automatic Boot Assessment, https://systemd.io/AUTOMATIC_BOOT_ASSESSMENT (read) | An entry carries a tries counter; it is marked good only once the boot is judged successful (optionally only when no service has failed), and entries whose tries are exhausted are deprioritized. | **Adapt** for S4 (C4): a release is `indeterminate` until the observation window passes, then `good` or `bad`; ProbOS never auto-selects a `bad` release. |
| OSTree / rpm-ostree (for example https://docs.fedoraproject.org/lo/iot/applying-updates-UG/) | The previous deployment is retained as a known-good rollback target; deployments are hard links into a content-addressed object store. | **Adapt** (C7): retention never deletes the active release or the rollback target, and release trees must not share hard links with any mutable path. **Rejected:** bootloader- or OS-level deployment, which is privileged and outside an application release. |

### Blind spots found (named constraints, not new scope)

- **ABA on compare-and-set (C1).** A release-identity CAS passes on A, then B, then A again. Use a monotonic activation sequence.
- **Fail-open defaults (C2) and persist-before-verify (C3)**, from the two TUF-implementation CVEs above.
- **Health that is only liveness (C5).** `/api/health` states it is "not an integration readiness gate" (`src/probos/routers/system.py:37`).
- **Tested environment is not the released environment (C6).** The gate receipt records no interpreter or installed-environment identity; it binds the tree only.
- **The review assignee is caller-supplied (C8).** `bind_reviews` checks that the reviewer differs from the assignee the record claims, not that this assignee is the campaign's builder or that every review names the same one. S1a is unwired, so nothing breaks today; S1b's binder must add `expected_assignee`.
- **Stale base (C10)** and **no incumbent comparison (C11).**
- **Recorded digest without an expected digest (from review round 1, F2).** S1a records `evidence_sha256` but takes no expected digest, so a change is detectable only by a consumer that retained an earlier trusted digest, and only within what that digest covers (a receipt's raw bytes; a review set's five projected fields, Amendment 2). S1b's persisted link store keeps the first trusted digest per evidence reference and treats a later different digest for the same reference as a change to report (not silently replace).

---

## DO NOT BUILD (repeated)

- No store, I/O, clock, event, config, router or runtime wiring; the module is pure.
- No `src/` change other than the new module; no change to `run_test_gate.py`, the wave orchestrator, `WorktreeManager`, `BuildDispatcher`, `routers/build.py`, `FaultReportStore` or the `repair_*` modules.
- Never route through `merge_to_main`, `WorktreeManager.remove` or the repository-root `work_dir`.
- No wording that claims prevention, blanket refusal, or a review-set digest wider than its five projected fields: S1a refuses what contradicts the candidate in the facts it checks and records a sha256 per piece of evidence (receipt: raw bytes; review set: the five-field projection) (the canonical statement in Amendment 2).
- No broad catch other than the one in `_project_review`, and never `BaseException`.
- No broad gate run by the Builder.
