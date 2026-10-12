# AD-1299 S1b (#1352): expected assignee (C8), required evidence per authority class (C9), first-trusted-digest ledger

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-12

**One line.** Close the three S1a carry-forwards: the review binder must be told who the campaign's builder is (C8); evidence is complete only when every kind required for the authority class is `present` for the same candidate (C9); and an insert-only, persisted ledger keeps the first trusted digest per evidence reference and reports a later different digest as a change (S1a review round 1, F2). One in-slice consumer, `assess_candidate_evidence`, crosses verifier -> ledger -> completion so the chain is not half-built.

| | |
|---|---|
| Status | Build-ready (split workflow: Copilot orchestrator builds). Amended 2026-10-12 after review rounds 1, 2 and 3 (see the "Review round N amendments" records). |
| Epic / AD | #1352 / AD-1299 slice S1b. **No new AD or BF number**: S1b is an already-versioned slice of AD-1299 (`docs/development/self-maintenance-architecture.md:430-431`). |
| Base | `origin/main` `712daa05`, branch `feat/ad1299-s1b-20261012-712daa05` |
| Depends on | S1a, shipped (PR #1508, merge `1a7a3fef`) |
| D-B2 | Not touched. S1b works under option (a) (execute-after-approval) and depends on no D-B2 outcome. Nothing here claims containment. |
| Estimated tests | ~22 new pure tests (M1), ~17 new store/consumer tests (M2), 4 edits in the S1a test file |
| Milestones | M1 pure contract (max effort), M2 ledger + consumer + mutation campaign (max effort), M3 trackers (high) |

---

## Problem

1. **C8, caller-supplied assignee.** `bind_reviews` (`src/probos/cognitive/repair_candidate.py:428-479`) refuses a review whose reviewer equals the assignee *the record claims* (`:417-418`). Nothing checks that the claimed assignee is the campaign's builder. A builder that reviews its own work and labels the record with any other assignee passes the independence check.
2. **C9, no completion rule.** S1a returns one `EvidenceLink` per kind (`EvidenceKind = Literal["gate_receipt", "review_set"]`, `:63`). Nothing states which kinds a campaign of a given authority class needs, so "complete" is undefined and an extra link of one kind could be miscounted as coverage of another.
3. **F2, recorded digest without an expected digest.** S1a records `evidence_sha256` (`:165`, `:374`, `:462-478`) but takes no expected digest. A change is detectable only by "a consumer that retained an earlier trusted digest" (S1a prompt `:974`, architecture doc `:233-235`). No such consumer or store exists (Absence Verified, below).

## Solution overview

| Piece | Where | Pure? |
|---|---|---|
| C8: required keyword-only `expected_assignee`; new refused reason `review_assignee_mismatch` | `repair_candidate.py` (edit) | yes |
| C9: `AuthorityClass`, `AUTHORITY_CLASSES`, read-only `REQUIRED_EVIDENCE_KINDS`, `EvidenceCompleteness`, `evaluate_completion` | `repair_candidate.py` (edit) | yes |
| Two public shape helpers, `is_sha256_hex`, `is_evidence_ref` (DRY: the ledger reuses S1a's regexes rather than copying them) | `repair_candidate.py` (edit) | yes |
| Ledger: `RepairEvidenceLinkStore` (insert-only, `ConnectionFactory`-injected, DB triggers) | `src/probos/cognitive/repair_evidence_store.py` (new) | no |
| In-slice consumer: `assess_candidate_evidence` (derives both links itself, records present ones, evaluates C9, blocks on a change) | same new module | no |
| Store declaration `cognitive.repair-evidence` | `src/probos/cognitive/storage_declarations.py` (edit) | data |

**Runtime wiring: none.** Nothing under `src/probos/` constructs or starts the store; S2 does that when admission exists. The chain is still exercised end to end by the M2 milestone test (real `run_test_gate.py` receipt -> verifier -> ledger on a real SQLite file -> restart -> tampered receipt -> `evidence_changed`).

---

## Decisions and ranked options

Ranked on correctness, safety, compatibility, architectural fit, reversibility and validation cost. All chosen options are inside the Delegated AD Execution envelope: each adds or keeps a control, touches no persisted schema in use, and rolls back with Git.

### D1. C8 shape

| Rank | Option | Verdict |
|---|---|---|
| 1 | Required keyword-only `expected_assignee: str` (owned-id shape), checked right after the duplicate-attempt check: any review whose `assignee_id != expected_assignee` -> `refused` / `review_assignee_mismatch`. The review-set digest is unchanged (the bound assignee already sits in the five-field projection and now equals the expected one). | **Chosen.** Exactly C8; no digest or golden-vector churn. |
| 2 | Optional `expected_assignee=None` meaning "skip". | Rejected: a silent skip is the defect C8 names. |
| 3 | Add the expected assignee to the digest projection. | Rejected: changes the S1a domain and digests for no detection gain. |

**Compatibility.** Making the keyword required breaks the S1a call shape. Absence Verified below shows that at base `712daa05` `bind_reviews` had no caller outside its own module and tests; this slice adds exactly one production caller, `assess_candidate_evidence` (`repair_evidence_store.py`, Section 4), which passes `expected_assignee` through as a required keyword. So no existing consumer breaks; the S1a test file gets a documented adapter (Section 3). This is in-envelope: not a published API, no persisted schema, reversible.

### D2. C9 shape

| Rank | Option | Verdict |
|---|---|---|
| 1 | A fixed, read-only module table: every class (`repair`, `maintenance`, `enhancement`) requires `{"gate_receipt", "review_set"}`, the two kinds S1 can verify. Completion counts **kinds**, not links; any supplied link for another candidate or not `present` blocks. S2 adds `captain_approval` to every class when its binder exists (strengthening only). | **Chosen.** Testable today, fail-closed, cannot be weakened by a caller. |
| 2 | Declare `captain_approval` now with no verifier. | Rejected: completion becomes unreachable and tests would have to hand-build approval links, which S1a's "re-derive, never accept a built link" rule forbids. |
| 3 | Caller-injected policy. | Rejected: the architecture doc (`:199-201`) says no agent, Builder or backend may change completion criteria or accepted evidence. |
| 4 | Per-class differences now (for example two reviewers for enhancement). | Considered, deferred: invents policy beyond C9. |

`EvidenceCompleteness.complete` is **evidence completeness only**. It is not the Captain's approval, not promotion and not campaign closure; every docstring says so.

### D3. Ledger semantics

| Rank | Option | Verdict |
|---|---|---|
| 1 | Key = `(candidate_digest, evidence_kind, evidence_ref)`. First `present` digest is inserted once and never replaced. The first **different** digest is recorded once in a change table; from then on the reference reports `changed`, even if the bytes return to the first digest (ABA). New evidence (a gate rerun, a new review round) uses a new reference. | **Chosen.** Detects change, bounded (at most two rows per reference), audit-preserving. |
| 2 | Report a change without recording it. | Rejected: an A -> B -> A revert would read `unchanged` and nothing durable would say a change was seen. |
| 3 | Record every distinct changed digest. | Rejected: unbounded per reference. |
| 4 | Key without the candidate digest. | Rejected: reusing a gate label for a new candidate would read as tampering. |

### D4. Connection model

| Rank | Option | Verdict |
|---|---|---|
| 1 | One connection per operation, opened through the injected `ConnectionFactory` and closed in `finally`; `BEGIN IMMEDIATE`; no explicit `ROLLBACK`. A write that fails or is cancelled **before its COMMIT is queued** leaves nothing: its uncommitted rows die with their connection (#10, #11). A write cancelled **after** its COMMIT is queued may have been recorded, and the caller is not told which (#20; aiosqlite runs queued calls on the connection's worker thread, `core.py:48-75`, `:150-160`). The cancellation contract is D4a N1-N5; when `CancelledError` arrives relative to the connection's cleanup is an implementation detail (D4a note), not a promise. One `asyncio.Lock` serialises in-process calls while they run; `busy_timeout` bounds waits on other connections' locks. | **Chosen.** Simplest correct shape; no SQLite-specific error classification. |
| 2 | One long-lived connection with `BEGIN`/`ROLLBACK` bookkeeping (the `ActionApprovalStore` shape plus transactions). | Rejected: a cancelled `BEGIN` or failed `ROLLBACK` can leave a transaction open on the shared connection, and telling a benign rollback error apart needs `sqlite3`-specific checks. |
| 3 | Copy `ElasticTeamStore`'s tracked-close machinery. | Considered, deferred: ~100 duplicated lines for two short transactions. If a third store needs it, extract a shared helper then. |

### D4a. Cancellation at the commit point (review rounds 1-3: B1, R2-1, R3-2)

| Rank | Option | Verdict |
|---|---|---|
| 1 | Propagate without a shield. State only what S2 needs as the normative contract (N1-N5, below) and keep the mechanics in a labelled, non-normative implementation note. | **Chosen.** Cancellation is not swallowed and no shield is added. |
| 2 | Shield the commit and await it before re-raising `CancelledError`. | Rejected: the caller still receives `CancelledError` without the result, so the outcome is no better known; it adds a re-cancellation path (`uncancel`, a second `cancel()` during the wait) and can lengthen the wait by up to `busy_timeout`. |
| 3 | Shield the whole write. | Rejected: lengthens the wait through `BEGIN IMMEDIATE`'s 5 s busy wait for no gain. |

**Normative contract (what S2 may rely on), for `check_and_record` and `assess_candidate_evidence`:**

- **N1.** `CancelledError` propagates; the store does not swallow it (#11, #20 `task.cancelled()`; T3).
- **N2.** `CancelledError` means the outcome is unknown: the observation may or may not have been recorded (#11 records nothing; #20 records).
- **N3.** A retry with identical evidence (same reference, same link) is safe: it answers the same for completion whether or not the cancelled call recorded. A first observation reads `first_recorded` (not recorded, #11) or `unchanged` (recorded, #20 `first`); a digest that differs from a recorded first reads `changed` either way (#20 `change`).
- **N4.** An abandoned observation of different evidence may leave the reference `changed`: its digest may have become the first digest or the recorded change (#20 `change`: record A, abandon B after its COMMIT is queued, a later A reads `changed`). Such a record can move a later answer only to `changed`, which blocks completion: the ledger is insert-only (#8) and `changed` is sticky (#4).
- **N5.** No promise is made about when `CancelledError` arrives relative to the connection's cleanup, the release of the in-process lock, or the queued COMMIT.

**Implementation note (NOT normative; observed with aiosqlite 0.22.1, the version in this venv):**

- A cancel that lands before the COMMIT is queued records nothing: the uncommitted rows die with the connection (#11).
- **Under a single cancellation**, `_open`'s `finally` awaits `close()`, which aiosqlite queues behind the COMMIT on the connection's FIFO worker (`core.py:48-75`, `:199-214`), so `CancelledError` reached the caller after the COMMIT and the close had run, with the store's lock held until then (#20 asserts `task in pending` 0.2 s after one cancel with the worker held; X1). The R2-1 probe measured 0.204 s with the worker held 0.2 s. `busy_timeout=5000` bounds a COMMIT that waits on another connection's lock.
- **Under repeated cancellation** (observed by the orchestrator's probe `probe_s1b_r3`, 2026-10-12; not a test): cancels 1 and 2 left the call pending, the lock held, no row; cancel 3 ended the call and released the lock while the queued COMMIT was still pending; after the worker was released the row was durable. aiosqlite's `close()` awaits `stop()` in its `finally` (`core.py:205-214`), so a second cancel interrupts the close wait and a third the `stop()` wait. This is why N5 makes no timing promise.

<details><summary>Superseded round-2 wording of option 1 (kept as audit trail)</summary>

Propagate without a shield and state the contract. **Before** the COMMIT is queued: nothing recorded. **After**: the COMMIT runs on the worker and the caller is not told whether the observation was recorded (outcome unknown). **Propagation waits for awaited cleanup:** `_open`'s `finally` awaits `close()`, which is queued behind the COMMIT on the same FIFO worker, so `CancelledError` reaches the caller after the COMMIT and the close have run. The wait is bounded by the work queued on this operation's own connection (its COMMIT and close; no other operation shares it) and by `busy_timeout` (5 s) for any lock the COMMIT waits on (R2-1 probe: 0.204 s with the worker held 0.2 s). The lock is held through that close, so the outcome is settled before the next in-process call starts, unless the caller is cancelled again during the cleanup; the cleanup can then be cut short and the queued COMMIT runs on the worker after the lock is released. **What a later call reads.** (a) A retry with identical evidence (same reference, same link) answers the same for completion either way: a first observation reads `first_recorded` if the cancelled call did not record and `unchanged` if it did (completion treats both alike); a different digest after a recorded first reads `changed` either way. (b) An observation of **different** evidence after an abandoned call can read `changed` because of that call: the abandoned digest may have become the reference's first digest or its recorded change (reproduced: record A, abandon B after its COMMIT is queued, a later A reads `changed`). The ledger is insert-only, so an unreported record can only turn a later answer into `changed`, which blocks completion; it cannot turn `changed` back, and cannot complete evidence that would otherwise be blocked. (R3-2: "propagation waits for awaited cleanup" holds only under a single cancellation; superseded by N5 and the implementation note.)

</details>

S2 consumer (named constraint): treat `CancelledError` from `assess_candidate_evidence` or `check_and_record` as **outcome unknown** (N2), not as "nothing recorded". To learn the outcome, retry with the identical evidence under the same reference (N3); otherwise abandon that reference and present new evidence under a new reference (reference discipline, below). A `changed` read on a reference whose earlier call was abandoned may come from that call itself (N4): it still blocks completion (the conservative direction), and S2 must not report it as tampering without recording the abandoned call. S2 must not infer from the arrival of `CancelledError` that the connection is closed, the lock released, or the queued COMMIT run or not run (N5).

### D5. Wiring

| Rank | Option | Verdict |
|---|---|---|
| 1 | Runtime-unwired store plus the in-slice consumer `assess_candidate_evidence`, which derives both links from the evidence itself, records only `present` ones and blocks completion on `changed`. One test crosses the full seam including a restart. | **Chosen.** No half-chain, no inert runtime file. |
| 2 | Construct and start the store at boot. | Rejected: no producer exists before S2; it would create an empty `repair_evidence.db` on every boot (the AD-1286 wiring tests pin the opposite). |
| 3 | Store only; consumer in S2. | Rejected: half-built chain. |

### D6. Failure tiers

| Condition | Tier | Behaviour |
|---|---|---|
| Wrong argument type or shape (candidate, class, container, ref, assignee, untrusted link) | Propagate | `TypeError` / `ValueError` with a stable code, before any write |
| Store not started, stopped, or clock not finite | Propagate | `RepairEvidenceStoreUnavailable` |
| Stored row fails validation (schema version, digest shape, change equal to first) | Propagate (data integrity) | `logger.error`, then `RepairEvidenceIntegrityError("repair_evidence_integrity")`; nothing recorded |
| Backend error during a write, before or at COMMIT | Propagate | Connection closed without a successful commit; nothing visible to later operations |
| Cancelled (`CancelledError`) | Propagate; not swallowed, no shield | Normative (D4a N1-N5): outcome unknown; a retry with identical evidence is safe; an abandoned observation of different evidence may leave the reference `changed`; no promise about when the error arrives relative to the connection's cleanup. Implementation (D4a note): a cancel before the COMMIT is queued records nothing (#11) |
| A stored value that fails the validators' rules for the stored text, bound by a raw writer to one of the four string-valued columns of either table (candidate digest, kind, reference, the table's digest) | Refused by the engine | `sqlite3.IntegrityError` (#21): the column's named `CHECK` (an integer or a finite or infinite real bound to a reference column included: it has no declared type, so no affinity converts it first), or the column's `NOT NULL` for NaN, which SQLite binds as NULL. `schema_version` and the two timestamp columns admit numbers by design (D7). The Python object type is outside what SQLite can see: a `str` subclass carrying valid text is stored as that text and is not refused (#22). The exact-`str` rule that `is_evidence_ref` and `is_sha256_hex` apply to references and digests is applied by `check_and_record` and `EvidenceLink` before any write (#9); the kind column's rule is membership of the two literals, which a `str` subclass equal to a literal satisfies, in production as in the engine (#22) |
| Connection close fails | Log-and-degrade | `logger.warning`; the operation's own result or error stands |
| Any exception inside `assess_candidate_evidence` | Propagate | Nothing ever returns complete on an error |

### D7. Location, schema, versioning, bounds

- Module `probos.cognitive.repair_evidence_store`, beside `repair_candidate`; declared in `probos.cognitive.storage_declarations` as `cognitive.repair-evidence`, `canonical_path="repair_evidence.db"`, `FEATURE_GATED`, `lifecycle_owner="unowned"` (the `UNOWNED_LIFECYCLE` sentinel value: nothing calls `start()`/`stop()` in production yet), `UNBOUNDED` with a note.
- Two `WITHOUT ROWID` tables, per-row `schema_version` with `CHECK (schema_version = 1)` (the AD-1286 precedent), and six triggers (three per table) refusing UPDATE, DELETE and replacing INSERT. A future schema 2 is its own slice with a migration.
- **For the four string-valued columns of each table (candidate digest, kind, reference, the table's digest), the engine admits only stored values that meet the validators' rules for the stored text (review rounds 1-4: B2, R2-2, R3-3, R4-2; #21 enumerates the refused classes; the exact-`str` type rule is not visible to SQLite, #22).** Four named table `CHECK`s per table, the key checks mirrored on the change table (with foreign keys off, as on any raw `sqlite3` connection, its foreign key is not enforced): `typeof(x) = 'text'` (no BLOB); `length(CAST(x AS BLOB)) = length(x)` or `= 64` (SQLite's `length()` and `GLOB` stop at the first NUL, so byte length equal to character length refuses NUL and, with the ASCII charset, any multi-byte character; the database is created in the default UTF-8 encoding); digests 64 lowercase hex; kind one of two literals; reference 1-128 characters, first character `[A-Za-z0-9]`, rest `[A-Za-z0-9_.:-]` (S1a `_ID_RE`). Constraint names are unique lines, so the failure message names the rule and every mutant has a single-line anchor. `STRICT` tables were considered and not used: they still admit NUL and leading punctuation, so the `CHECK`s are needed anyway.
- **Reference columns have no declared type (review round 2, R2-2).** A column declared `TEXT` has TEXT affinity, which converts a bound INTEGER or REAL to text before the `CHECK`s run: a raw integer `9` was stored as `('9', 'text')`, passed `typeof(...) = 'text'`, and collided with the string key `"9"`, while `is_evidence_ref(9)` is False. `evidence_ref` is therefore declared with no type in both tables (no affinity: a value keeps the storage class it was bound with), so the `typeof` `CHECK` refuses by name an integer or a finite or infinite real bound there (#21 numeric cases); a NaN binds as NULL and the column's `NOT NULL` refuses it (#21 NaN cases, R3-3). Each declaration line carries a table-specific SQL comment, so each is a unique mutation anchor (L14, L15). **The other columns keep their types, and no coercion yields a valid-looking value:** TEXT affinity converts only INTEGER and REAL values (NULL and BLOB are untouched; BLOB fails `typeof`); a 64-bit integer renders in at most 20 characters and a REAL in fewer than 30 (sign, at most 17 significant digits, `.`, exponent; infinity renders as a short token; NaN binds as NULL, which `NOT NULL` refuses), so no number satisfies `length(...) = 64` for the candidate or digest columns, and none equals a kind literal (both contain `_`, which no numeric rendering does). TEXT affinity never converts text to a number. **Numbers are admitted by design outside those four columns:** `schema_version` (INTEGER affinity, `CHECK (schema_version = 1)`) stores `True` and text `'1'` as integer `1`, the value the reader accepts (R3-3 probe); `recorded_at` / `observed_at` admit numbers, carry no `CHECK`, and no decision reads them. **Key consequences:** primary-key, trigger and foreign-key comparisons on an untyped column use the stored storage class with BINARY collation; the `CHECK` admits only TEXT, so every stored key is text and every comparison is text-to-text, as before. The store binds `str` only (`is_evidence_ref` runs before any write). Parent and child reference columns are both untyped, so the foreign key compares like with like; with foreign keys on, a refused value still fails its named `CHECK`, which SQLite evaluates per row before the statement-end foreign-key check (M2 #21 asserts the name in both modes).
- **Schema version stays 1.** No database written by the round-0 or round-1 DDL can exist outside test temp directories: the module has never been on a branch (`git log --all -- src/probos/cognitive/repair_evidence_store.py` shows only the unbranched review snapshots `a9b2431a` and `d8af3ac8`; `git branch --list --all --contains` is empty for both), nothing under `src/` constructs the store (M2 #19; Grep `RepairEvidenceLinkStore` in `src/` hits only its module and the declaration), and the live data directory has no `repair_evidence*` file (Glob, 2026-10-12).
- Bounds: reference 1-128 chars (owned-id shape), kind closed to two values, at most one first row and one change row per reference, no list or scan API.
- `db_path` must be a non-empty file path; `""` and `":memory:"` are refused (a ledger that forgets on restart defeats its purpose, and per-operation connections would see a fresh empty `:memory:` database every time).

---

## Section 0: Event types

None. S1b adds no `EventType`.

## Section 1 (M1): C8 and C9 in `src/probos/cognitive/repair_candidate.py`

All anchors are single lines from the live file (CRLF on disk; keep CRLF).

**1a. Module docstring** (`:11-12`). SEARCH:

```
* ``bind_reviews`` binds a review set only when every review was accepted by a
  reviewer other than the assignee and names the candidate's tree.
```
REPLACE:
```
* ``bind_reviews`` binds a review set only when every review names the
  campaign's builder as its assignee (``expected_assignee``, C8), was accepted
  by a reviewer other than that assignee and names the candidate's tree.

S1b adds C9: ``evaluate_completion`` says whether the links supplied for one
candidate cover every evidence kind its authority class requires. Complete
evidence is not authority: the Captain's approval is separate (S2).
```

**1b. Imports** (`:45`). SEARCH `from collections.abc import Sequence` REPLACE:
```python
from collections.abc import Mapping, Sequence
```
and after `from dataclasses import dataclass` (`:46`) add the line `from types import MappingProxyType`. Keep the stdlib order (`types` after `dataclasses`). No `probos` import at module scope (S1a test `test_module_import_does_not_import_federation` pins this).

**1c. Authority class type** — after `EvidenceStatus = Literal["present", "refused", "unavailable"]` (`:64`) add:
```python
AuthorityClass = Literal["repair", "maintenance", "enhancement"]
```

**1d. New refused reason** — in `_REFUSED` after `    "review_attempt_duplicate",` (`:84`) add:
```python
    "review_assignee_mismatch",
```

**1e. C9 constants** — after `REASON_CODES: Final[frozenset[str]] = _BOUND | _UNAVAILABLE | _REFUSED` (`:89`) add:
```python

AUTHORITY_CLASSES: Final[frozenset[str]] = frozenset({"repair", "maintenance", "enhancement"})
# C9: the evidence kinds whose ``present`` links complete one candidate's evidence, per authority class.
# Every class requires both kinds S1 can verify. S2 adds ``captain_approval`` to every class when its
# binder exists; a change may only add kinds, never remove one. Completion is not authority.
REQUIRED_EVIDENCE_KINDS: Final[Mapping[str, frozenset[str]]] = MappingProxyType({
    "repair": frozenset({"gate_receipt", "review_set"}),
    "maintenance": frozenset({"gate_receipt", "review_set"}),
    "enhancement": frozenset({"gate_receipt", "review_set"}),
})
_COMPLETE: Final = "evidence_complete"
COMPLETION_REASONS: Final[frozenset[str]] = frozenset({
    _COMPLETE,
    "evidence_candidate_mismatch",
    "evidence_not_present",
    "evidence_kind_missing",
    "evidence_changed",
})
```

**1f. Public shape helpers** — after `_is_git_object` (`:103-104`) add:
```python


def is_sha256_hex(value: object) -> bool:
    """True for a 64-character lowercase-hex SHA-256 digest, the shape of every digest here."""
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def is_evidence_ref(value: object) -> bool:
    """True for a valid evidence reference: the owned-step id shape that review ids use."""
    return type(value) is str and _ID_RE.fullmatch(value) is not None
```

**1g. `_review_reason`** (`:409-420`). SEARCH:
```python
    required_reviewers: int,
) -> str:
    attempts = [attempt for attempt, _, _, _, _ in projected]
    if len(set(attempts)) != len(attempts):
        return "review_attempt_duplicate"
    if any(reviewer == assignee for _, reviewer, assignee, _, _ in projected):
```
REPLACE:
```python
    required_reviewers: int,
    expected_assignee: str,
) -> str:
    attempts = [attempt for attempt, _, _, _, _ in projected]
    if len(set(attempts)) != len(attempts):
        return "review_attempt_duplicate"
    if any(assignee != expected_assignee for _, _, assignee, _, _ in projected):
        return "review_assignee_mismatch"
    if any(reviewer == assignee for _, reviewer, assignee, _, _ in projected):
```

**1h. `bind_reviews` signature and argument checks** (`:428-448`). SEARCH:
```python
    reviews: Sequence[ReviewAttestation] | None,
    *,
    required_reviewers: int = 1,
) -> EvidenceLink:
```
REPLACE:
```python
    reviews: Sequence[ReviewAttestation] | None,
    *,
    expected_assignee: str,
    required_reviewers: int = 1,
) -> EvidenceLink:
```
In the docstring, after the sentence ending `` ``1..MAX_REVIEWS``. `` (`:439`) add: ``Raises ``ValueError`` when ``expected_assignee`` (the campaign's builder, C8) is not an owned-id string; a review naming any other assignee is refused as ``review_assignee_mismatch``.`` (Review round 1, A1) Also replace the S1a sentence ``A review whose reviewer, assignee or attempt id is changed to another valid, independent value still binds; only ``evidence_sha256`` changes.`` with ``A review whose reviewer or attempt id is changed to another valid, independent value still binds, and only ``evidence_sha256`` changes; a changed assignee binds only if it still equals ``expected_assignee``, and otherwise is refused as ``review_assignee_mismatch``.`` Then SEARCH:
```python
        raise ValueError("review_required_invalid")
    digest = candidate.digest()
```
REPLACE:
```python
        raise ValueError("review_required_invalid")
    if type(expected_assignee) is not str or _ID_RE.fullmatch(expected_assignee) is None:
        raise ValueError("review_expected_assignee_invalid")
    digest = candidate.digest()
```
and replace the last line (`:479`):
```python
    return _link("review_set", _review_reason(candidate, projected, required_reviewers), digest, evidence)
```
with
```python
    return _link(
        "review_set",
        _review_reason(candidate, projected, required_reviewers, expected_assignee),
        digest,
        evidence,
    )
```
The digest block (`:462-478`) is **not** changed.

**1i. C9 completion** — append at end of module:
```python


# -- completion (C9) ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceCompleteness:
    """Whether one candidate's evidence is complete for one authority class (C9).

    A report, not authority: ``complete`` never means approved, promoted or closed.
    """

    authority_class: str
    candidate_digest: str
    reason: str
    missing_kinds: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.authority_class) is not str
            or self.authority_class not in AUTHORITY_CLASSES
            or not is_sha256_hex(self.candidate_digest)
            or type(self.reason) is not str
            or self.reason not in COMPLETION_REASONS
            or type(self.missing_kinds) is not tuple
            or any(type(kind) is not str or kind not in REQUIRED_EVIDENCE_KINDS[self.authority_class] for kind in self.missing_kinds)
            or (self.reason == _COMPLETE and self.missing_kinds)
            or (self.reason == "evidence_kind_missing" and not self.missing_kinds)
        ):
            raise ValueError("evidence_completeness_invalid")

    @property
    def complete(self) -> bool:
        """True only when every required kind is present for this candidate and nothing blocks."""
        return self.reason == _COMPLETE


def evaluate_completion(
    candidate: RepairCandidate,
    authority_class: AuthorityClass,
    links: Sequence[EvidenceLink],
) -> EvidenceCompleteness:
    """C9: complete only when every kind required for ``authority_class`` has a ``present`` link for
    ``candidate`` and every supplied link is ``present`` and names ``candidate``.

    Completion counts kinds, not links, so an extra link never substitutes for a missing kind.
    Precedence when several apply: ``evidence_candidate_mismatch``, then ``evidence_not_present``, then
    ``evidence_kind_missing``. ``missing_kinds`` lists the required kinds with no ``present`` link for
    this candidate, whatever the reason. Raises ``TypeError`` for a non-``RepairCandidate`` candidate, a
    container other than ``list``/``tuple`` or an element that is not an ``EvidenceLink``, and
    ``ValueError`` for an unknown authority class. Complete evidence is not authority.
    """
    if type(candidate) is not RepairCandidate:
        raise TypeError("repair_candidate_required")
    if type(authority_class) is not str or authority_class not in AUTHORITY_CLASSES:
        raise ValueError("authority_class_invalid")
    if type(links) not in (list, tuple):
        raise TypeError("evidence_links_container_invalid")
    if any(type(link) is not EvidenceLink for link in links):
        raise TypeError("evidence_link_required")
    digest = candidate.digest()
    required = REQUIRED_EVIDENCE_KINDS[authority_class]
    present = {link.kind for link in links if link.current and link.candidate_digest == digest}
    missing = tuple(sorted(required - present))
    if any(link.candidate_digest != digest for link in links):
        reason = "evidence_candidate_mismatch"
    elif any(not link.current for link in links):
        reason = "evidence_not_present"
    elif missing:
        reason = "evidence_kind_missing"
    else:
        reason = _COMPLETE
    return EvidenceCompleteness(authority_class, digest, reason, missing)
```

## Section 2 (M1): `tests/test_ad1299_s1b_evidence_completion.py` (new)

Pure tests; build `EvidenceLink`s directly where the function under test is `evaluate_completion` (it judges links; the "re-derive" rule binds *consumers*, and M2's consumer does re-derive). Reuse `_Review` and `_pure_candidate` by importing them from `tests.test_ad1299_s1a_repair_candidate` (precedent: `tests/test_ad1077_group_chat_coaching.py:22`). Import `bind_reviews` from `probos.cognitive.repair_candidate`, **not** from the S1a test module (whose name is the adapter). Every refusal test first asserts the unmodified premise binds.

| # | Test | Asserts |
|---|---|---|
| 1 | `test_bind_reviews_expected_assignee_is_required_keyword_only` | `inspect.signature(bind_reviews).parameters["expected_assignee"]` is `KEYWORD_ONLY` with `default is inspect.Parameter.empty`; calling without it raises `TypeError` |
| 2 | `test_bind_reviews_invalid_expected_assignee_raises` (parametrize `None`, `""`, `"-x"`, `"a b"`, `"a"*129`, `5`) | `ValueError` args `("review_expected_assignee_invalid",)`, also when `reviews is None` |
| 3 | `test_review_naming_another_assignee_is_refused` | premise `expected_assignee="builder"` binds; `assignee_id="someone_else"` -> `("refused", "review_assignee_mismatch")` |
| 4 | `test_builder_self_review_relabelled_is_refused` | review `reviewer_id="builder", assignee_id="decoy"`: with `expected_assignee="decoy"` it binds (S1a independence alone accepts it); with `"builder"` -> `review_assignee_mismatch` |
| 5 | `test_mixed_assignees_are_refused` | two reviews, one `"builder"`, one `"other"`, `required_reviewers=2` -> `review_assignee_mismatch` |
| 6 | `test_reviewer_equal_to_expected_assignee_is_not_independent` | reviewer and assignee both `"builder"` -> `review_not_independent` |
| 7 | `test_assignee_check_order` | duplicate attempt + mismatch -> `review_attempt_duplicate`; mismatch + self review -> `review_assignee_mismatch` |
| 8 | `test_review_set_digest_unchanged_by_c8` | bound digest equals `sha256(REVIEW_SET_DOMAIN + jcs(projection))` recomputed independently (S1a test `:63-64` constants and `:1003-1010` projection shape) |
| 9 | `test_assignee_mismatch_is_a_refused_reason` | in `REASON_CODES`; link `status == "refused"`, `current is False` |
| 10 | `test_required_evidence_kinds_table_is_pinned_and_read_only` | `AUTHORITY_CLASSES == {"repair","maintenance","enhancement"}`; `set(REQUIRED_EVIDENCE_KINDS) == AUTHORITY_CLASSES`; every value `== frozenset({"gate_receipt","review_set"})` and `type is frozenset`; item assignment raises `TypeError` |
| 11 | `test_completion_complete_for_every_class` (parametrize classes) | one present gate + one present review for the candidate -> `complete`, `missing_kinds == ()` |
| 12 | `test_completion_with_no_links_is_kind_missing` | `[]` and `()` -> `evidence_kind_missing`, missing `("gate_receipt","review_set")` |
| 13 | `test_extra_links_never_substitute_for_a_missing_kind` | two present gate links (different `evidence_sha256`) -> `evidence_kind_missing`, missing `("review_set",)` |
| 14 | `test_link_for_another_candidate_blocks_and_does_not_count` | present gate (this) + present review (other digest) -> `evidence_candidate_mismatch`, missing `("review_set",)` |
| 15 | `test_non_present_link_blocks_even_when_all_kinds_present` | present gate + present review + refused gate -> `evidence_not_present`, missing `()` |
| 16 | `test_unavailable_required_kind_blocks` | present gate + unavailable review -> `evidence_not_present`, missing `("review_set",)` |
| 17 | `test_completion_reason_precedence` | mismatch and not-present together -> `evidence_candidate_mismatch` |
| 18 | `test_evaluate_completion_argument_errors` | non-candidate `TypeError("repair_candidate_required")`; class `"Repair"`, `"other"`, `None` -> `ValueError("authority_class_invalid")`; `set`/generator -> `TypeError("evidence_links_container_invalid")`; non-link element -> `TypeError("evidence_link_required")` |
| 19 | `test_evidence_completeness_rejects_inconsistent_construction` | each one-defect construction raises `ValueError("evidence_completeness_invalid")`: complete with missing kinds, kind-missing with none, unknown reason, unknown class, bad digest, missing kind outside the table, list instead of tuple; premise: a consistent one constructs |
| 20 | `test_shape_helpers` | `is_sha256_hex`: `"0"*64` True; `"A"*64`, `"0"*63`, `"0"*64+"\n"`, `None` False. `is_evidence_ref`: `"a"`, `"red.team:v2-x"`, `"a"*128` True; `""`, `"-x"`, `"a/b"`, `"a"*129`, `5` False |

## Section 3 (M1): S1a test file, four edits (`tests/test_ad1299_s1a_repair_candidate.py`)

1. Import (`:53`): `    bind_reviews,` -> `    bind_reviews as _module_bind_reviews,`.
2. After `_two_independent_reviews` (`:237-241`) add the adapter:
```python
def bind_reviews(
    candidate: RepairCandidate,
    reviews: object,
    *,
    required_reviewers: int = 1,
    expected_assignee: str = "builder",
) -> EvidenceLink:
    """S1b (C8) adapter. The real binder requires ``expected_assignee``; this adapter supplies the
    campaign builder ``builder`` (the ``_Review.assignee_id`` default) unless a case passes another.
    The S1a assignee probes vary ``assignee_id`` on purpose and now see ``review_assignee_mismatch``
    for a valid non-``builder`` value. C8 itself is pinned in
    tests/test_ad1299_s1b_evidence_completion.py, never through this adapter."""
    return _module_bind_reviews(
        candidate, reviews,  # type: ignore[arg-type]
        expected_assignee=expected_assignee, required_reviewers=required_reviewers,
    )
```
3. `_EXPECTED_REASON_CODES` (`:881-902`): add `"review_assignee_mismatch",` after `"review_attempt_duplicate",`.
4. `test_reason_codes_are_pinned`: both `20` (`:948`, `:959`) -> `21`; in `_links_for_every_reason` (`:943`) append `bind_reviews(pure, [dataclasses.replace(first, assignee_id="someone_else")]),` as the last list element.

Why the S1a `assignee_id` probe test (`:1278-1283`) still holds: a valid non-`builder` assignee now yields `review_assignee_mismatch`, which is still not `review_malformed`, so `(reason != malformed) == owned_accepts(value)` is unchanged.

## Section 4 (M2): `src/probos/cognitive/repair_evidence_store.py` (new, full file)

```python
"""AD-1299 S1b (#1352): the persisted first-trusted-digest ledger for repair evidence.

S1a records a sha256 per piece of evidence but takes no expected digest, so a
change is detectable only by a consumer that kept an earlier trusted digest
(S1a review round 1, F2). This store is that memory. For each evidence
reference -- ``(candidate digest, evidence kind, evidence ref)`` -- it keeps the
FIRST digest of a ``present`` link and reports a later, different digest for
the same reference as a change. It never replaces the first digest, and once a
change is observed the reference stays ``changed`` even if the bytes later
return to the first digest. New evidence (a gate rerun, a new review round) is
recorded under a new reference.

The database enforces immutability as well as this class (the AD-1286
precedent): triggers abort every UPDATE, every DELETE and every replacing
INSERT on both tables, which are ``WITHOUT ROWID``, and named ``CHECK``
constraints on the four string-valued columns admit only stored values that meet
the Python validators' rules for the stored text (TEXT storage class, no NUL,
ASCII, owned-id references; reference columns have no declared type, so no
affinity turns a bound number into text first; a NaN binds as NULL, which
``NOT NULL`` refuses). SQLite sees storage classes, not Python types: a ``str``
subclass is stored as the plain text it contains; the exact-``str`` rule the
validators apply to references and digests is ``check_and_record``'s, applied
before any write, not the engine's. Every operation opens its own
connection through the injected ``ConnectionFactory`` and closes it in
``finally``; one lock serialises in-process calls. A write that fails, or is
cancelled, before its COMMIT is queued leaves nothing: its uncommitted rows die
with their connection. Otherwise a cancelled call's outcome is unknown to the
caller: it may have been recorded (``check_and_record`` states the contract).

Detection, not prevention: the file lives under ProbOS's own OS identity, so a
writer with that identity can delete or rewrite it (D-B2). Nothing here
authenticates a producer, claims containment or grants authority.
``assess_candidate_evidence`` is the in-slice consumer. Not wired into the
runtime: S2 constructs and starts this store when admission exists.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import math
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

from probos.cognitive.repair_candidate import (
    AuthorityClass,
    EvidenceCompleteness,
    EvidenceLink,
    RepairCandidate,
    ReviewAttestation,
    bind_reviews,
    evaluate_completion,
    is_evidence_ref,
    is_sha256_hex,
    verify_gate_receipt,
)
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

REPAIR_EVIDENCE_STORE_SCHEMA_VERSION: Final = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repair_evidence_first_digests (
    candidate_digest TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    evidence_ref NOT NULL, -- first table: no declared type, so no affinity turns a bound number into TEXT before the CHECK
    first_sha256 TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    recorded_at REAL NOT NULL,
    CONSTRAINT repair_evidence_first_candidate_shape CHECK (typeof(candidate_digest) = 'text' AND length(CAST(candidate_digest AS BLOB)) = 64 AND length(candidate_digest) = 64 AND candidate_digest NOT GLOB '*[^0-9a-f]*'),
    CONSTRAINT repair_evidence_first_kind_shape CHECK (typeof(evidence_kind) = 'text' AND length(CAST(evidence_kind AS BLOB)) = length(evidence_kind) AND evidence_kind IN ('gate_receipt', 'review_set')),
    CONSTRAINT repair_evidence_first_ref_shape CHECK (typeof(evidence_ref) = 'text' AND length(CAST(evidence_ref AS BLOB)) = length(evidence_ref) AND length(evidence_ref) BETWEEN 1 AND 128 AND evidence_ref GLOB '[A-Za-z0-9]*' AND evidence_ref NOT GLOB '*[^A-Za-z0-9_.:-]*'),
    CONSTRAINT repair_evidence_first_sha256_shape CHECK (typeof(first_sha256) = 'text' AND length(CAST(first_sha256 AS BLOB)) = 64 AND length(first_sha256) = 64 AND first_sha256 NOT GLOB '*[^0-9a-f]*'),
    PRIMARY KEY (candidate_digest, evidence_kind, evidence_ref)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS repair_evidence_digest_changes (
    candidate_digest TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    evidence_ref NOT NULL, -- change table: no declared type, so no affinity turns a bound number into TEXT before the CHECK
    first_changed_sha256 TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    observed_at REAL NOT NULL,
    CONSTRAINT repair_evidence_change_candidate_shape CHECK (typeof(candidate_digest) = 'text' AND length(CAST(candidate_digest AS BLOB)) = 64 AND length(candidate_digest) = 64 AND candidate_digest NOT GLOB '*[^0-9a-f]*'),
    CONSTRAINT repair_evidence_change_kind_shape CHECK (typeof(evidence_kind) = 'text' AND length(CAST(evidence_kind AS BLOB)) = length(evidence_kind) AND evidence_kind IN ('gate_receipt', 'review_set')),
    CONSTRAINT repair_evidence_change_ref_shape CHECK (typeof(evidence_ref) = 'text' AND length(CAST(evidence_ref AS BLOB)) = length(evidence_ref) AND length(evidence_ref) BETWEEN 1 AND 128 AND evidence_ref GLOB '[A-Za-z0-9]*' AND evidence_ref NOT GLOB '*[^A-Za-z0-9_.:-]*'),
    CONSTRAINT repair_evidence_change_sha256_shape CHECK (typeof(first_changed_sha256) = 'text' AND length(CAST(first_changed_sha256 AS BLOB)) = 64 AND length(first_changed_sha256) = 64 AND first_changed_sha256 NOT GLOB '*[^0-9a-f]*'),
    PRIMARY KEY (candidate_digest, evidence_kind, evidence_ref),
    FOREIGN KEY (candidate_digest, evidence_kind, evidence_ref)
        REFERENCES repair_evidence_first_digests (candidate_digest, evidence_kind, evidence_ref)
) WITHOUT ROWID;
CREATE TRIGGER IF NOT EXISTS repair_evidence_first_digests_no_update BEFORE UPDATE ON repair_evidence_first_digests
BEGIN SELECT RAISE(ABORT, 'repair_evidence_immutable'); END;
CREATE TRIGGER IF NOT EXISTS repair_evidence_first_digests_no_delete BEFORE DELETE ON repair_evidence_first_digests
BEGIN SELECT RAISE(ABORT, 'repair_evidence_immutable'); END;
CREATE TRIGGER IF NOT EXISTS repair_evidence_first_digests_no_replace BEFORE INSERT ON repair_evidence_first_digests
WHEN EXISTS (SELECT 1 FROM repair_evidence_first_digests WHERE candidate_digest = NEW.candidate_digest
             AND evidence_kind = NEW.evidence_kind AND evidence_ref = NEW.evidence_ref)
BEGIN SELECT RAISE(ABORT, 'repair_evidence_immutable'); END;
CREATE TRIGGER IF NOT EXISTS repair_evidence_digest_changes_no_update BEFORE UPDATE ON repair_evidence_digest_changes
BEGIN SELECT RAISE(ABORT, 'repair_evidence_immutable'); END;
CREATE TRIGGER IF NOT EXISTS repair_evidence_digest_changes_no_delete BEFORE DELETE ON repair_evidence_digest_changes
BEGIN SELECT RAISE(ABORT, 'repair_evidence_immutable'); END;
CREATE TRIGGER IF NOT EXISTS repair_evidence_digest_changes_no_replace BEFORE INSERT ON repair_evidence_digest_changes
WHEN EXISTS (SELECT 1 FROM repair_evidence_digest_changes WHERE candidate_digest = NEW.candidate_digest
             AND evidence_kind = NEW.evidence_kind AND evidence_ref = NEW.evidence_ref)
BEGIN SELECT RAISE(ABORT, 'repair_evidence_immutable'); END;
"""

TrustedDigestStatus = Literal["first_recorded", "unchanged", "changed"]
_STATUSES: Final = frozenset({"first_recorded", "unchanged", "changed"})


class RepairEvidenceStoreUnavailable(RuntimeError):
    """The store has not been started, has stopped, or its clock is not a finite real."""


class RepairEvidenceIntegrityError(ValueError):
    """A stored row no longer validates (data integrity: logged at ERROR, then propagated)."""


@dataclass(frozen=True, slots=True)
class TrustedDigestCheck:
    """What the ledger holds for one evidence reference after one observation."""

    status: TrustedDigestStatus
    candidate_digest: str
    kind: str
    evidence_ref: str
    first_sha256: str
    observed_sha256: str

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in _STATUSES:
            raise ValueError("trusted_digest_check_invalid")

    @property
    def changed(self) -> bool:
        """True once this reference has been observed with a digest other than its first."""
        return self.status == "changed"


class TrustedDigestRecorder(Protocol):
    """The one ledger operation ``assess_candidate_evidence`` needs."""

    async def check_and_record(self, evidence_ref: str, link: EvidenceLink) -> TrustedDigestCheck: ...


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    """One assessment: the derived links, the ledger's answer for each recorded one, and C9 completion."""

    completeness: EvidenceCompleteness
    links: tuple[EvidenceLink, ...]
    checks: tuple[TrustedDigestCheck, ...]


def _checked_now(clock: Callable[[], float]) -> float:
    """A finite ``now``; a bad clock refuses the write, because the row could never be corrected."""
    now = clock()
    if type(now) not in (int, float) or not math.isfinite(now):
        raise RepairEvidenceStoreUnavailable("repair_evidence_clock_invalid")
    return float(now)


def _integrity_error(table: str, key: tuple[str, str, str]) -> RepairEvidenceIntegrityError:
    logger.error(
        "AD-1299 S1b: a stored %s row for %s evidence %s of candidate %s no longer validates; "
        "the observation is refused and nothing is recorded",
        table, key[1], key[2], key[0][:12],
    )
    return RepairEvidenceIntegrityError("repair_evidence_integrity")


async def _query(db: Any, sql: str, params: tuple[Any, ...]) -> list[Any]:
    cursor = await db.execute(sql, params)
    return list(await cursor.fetchall())


async def _first_digest(db: Any, key: tuple[str, str, str]) -> str | None:
    rows = await _query(
        db,
        "SELECT first_sha256, schema_version FROM repair_evidence_first_digests "
        "WHERE candidate_digest = ? AND evidence_kind = ? AND evidence_ref = ?",
        key,
    )
    if not rows:
        return None
    first, version = rows[0][0], rows[0][1]
    if type(version) is not int or version != REPAIR_EVIDENCE_STORE_SCHEMA_VERSION or not is_sha256_hex(first):
        raise _integrity_error("first-digest", key)
    return first


async def _first_change(db: Any, key: tuple[str, str, str], first: str) -> str | None:
    rows = await _query(
        db,
        "SELECT first_changed_sha256, schema_version FROM repair_evidence_digest_changes "
        "WHERE candidate_digest = ? AND evidence_kind = ? AND evidence_ref = ?",
        key,
    )
    if not rows:
        return None
    changed, version = rows[0][0], rows[0][1]
    if (
        type(version) is not int
        or version != REPAIR_EVIDENCE_STORE_SCHEMA_VERSION
        or not is_sha256_hex(changed)
        or changed == first
    ):
        raise _integrity_error("digest-change", key)
    return changed


class RepairEvidenceLinkStore:
    """Insert-only first-trusted-digest ledger for repair evidence references.

    Public API:
        start() / stop() -- lifecycle; idempotent
        check_and_record(evidence_ref, link) -> TrustedDigestCheck

    Raises:
        RepairEvidenceStoreUnavailable: not started, stopped, or a clock that is not a finite real.
        RepairEvidenceIntegrityError: a stored row that decides the observation no longer validates.
    """

    def __init__(
        self,
        db_path: str,
        connection_factory: ConnectionFactory | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Nothing is opened until :meth:`start`. ``""`` and ``":memory:"`` are refused: a ledger
        that forgets on restart defeats its purpose."""
        if type(db_path) is not str or not db_path or db_path == ":memory:":
            raise ValueError("repair_evidence_store_path_invalid")
        self._db_path = db_path
        self._clock = clock
        self._started = False
        self._lock = asyncio.Lock()
        if connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            connection_factory = default_factory
        self._connection_factory: ConnectionFactory = connection_factory

    async def start(self) -> None:
        """Apply the schema, then admit operations. Idempotent; a failure leaves the store stopped."""
        async with self._lock:
            if self._started:
                return
            async with self._open() as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.executescript(_SCHEMA)
                await db.commit()
            self._started = True
        logger.info(
            "AD-1299 S1b: RepairEvidenceLinkStore started (db=%s); first trusted digests are insert-only",
            self._db_path,
        )

    async def stop(self) -> None:
        """Stop admitting new operations. Waits for the lock, so a call holding it returns or raises
        first; a COMMIT queued by a cancelled call may still run afterwards. Idempotent."""
        async with self._lock:
            was_started, self._started = self._started, False
        if was_started:
            logger.info(
                "AD-1299 S1b: RepairEvidenceLinkStore stopped (db=%s); calls raise unavailable until start()",
                self._db_path,
            )

    @contextlib.asynccontextmanager
    async def _open(self) -> AsyncIterator[Any]:
        """One connection for one operation, with its own pragmas. Once ``connect`` has returned,
        ``close()`` is awaited in ``finally`` on every exit path (a repeated cancellation can
        interrupt that wait); a ``close()`` that raises is logged, not raised, and that connection
        may then stay open until it is released."""
        db = await self._connection_factory.connect(self._db_path)
        try:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            try:
                await db.close()
            except Exception:  # noqa: BLE001 -- log-and-degrade: the operation's own result or error stands
                logger.warning(
                    "AD-1299 S1b: closing a repair evidence connection failed; its uncommitted work was never "
                    "visible to other connections, and later writes may wait on its lock until it is released",
                    exc_info=True,
                )

    async def check_and_record(self, evidence_ref: str, link: EvidenceLink) -> TrustedDigestCheck:
        """Record ``link``'s digest as the first trusted digest for its reference, or compare with it.

        ``first_recorded`` the first time; ``unchanged`` while no observation has differed; ``changed``
        once any observation differed (that first different digest is recorded once, and the status
        stays ``changed`` for this reference). The first digest is never replaced. Records what it is
        given: pass only a link derived from the evidence itself (``assess_candidate_evidence`` does).

        Cancellation contract (what a caller may rely on): ``CancelledError`` propagates and is not
        swallowed, and it means the outcome is unknown: the observation may or may not have been
        recorded. A retry with the identical link is safe: it answers the same for completion either
        way (``first_recorded`` if the cancelled call did not record, ``unchanged`` if it did;
        ``changed`` for a digest that differs from a recorded first). An abandoned observation of
        different evidence may leave this reference ``changed``: its digest may have become the
        first digest or the recorded change. Such a record can move a later answer only to
        ``changed``, which blocks completion. No promise is made about when ``CancelledError``
        arrives relative to the connection's cleanup, the lock's release or the queued COMMIT.

        Implementation note (not part of the contract; observed with aiosqlite 0.22.1): nothing is
        shielded. A call cancelled before its COMMIT is queued records nothing. Under a single
        cancellation, ``CancelledError`` arrives after the queued COMMIT and the connection's close
        (queued behind it on the same worker) have run, with the lock held until then. A repeated
        cancellation can interrupt the close and aiosqlite's ``stop()`` wait, so the call can end,
        and the lock be released, while the queued COMMIT is still pending; that COMMIT can still
        run afterwards.

        Raises ``ValueError`` for an invalid reference or a link that is not ``present`` with a digest,
        and ``TypeError`` for a non-``EvidenceLink``.
        """
        if not is_evidence_ref(evidence_ref):
            raise ValueError("repair_evidence_ref_invalid")
        if type(link) is not EvidenceLink:
            raise TypeError("repair_evidence_link_required")
        if not link.current or not link.evidence_sha256:
            raise ValueError("repair_evidence_link_untrusted")
        key = (link.candidate_digest, link.kind, evidence_ref)
        observed = link.evidence_sha256
        async with self._lock:
            if not self._started:
                raise RepairEvidenceStoreUnavailable("repair_evidence_store_unavailable")
            now = _checked_now(self._clock)
            async with self._open() as db:
                await db.execute("BEGIN IMMEDIATE")
                first = await _first_digest(db, key)
                if first is None:
                    await db.execute(
                        "INSERT INTO repair_evidence_first_digests (candidate_digest, evidence_kind, "
                        "evidence_ref, first_sha256, schema_version, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (*key, observed, REPAIR_EVIDENCE_STORE_SCHEMA_VERSION, now),
                    )
                    first, status = observed, "first_recorded"
                else:
                    changed = await _first_change(db, key, first)
                    if changed is None and observed != first:
                        await db.execute(
                            "INSERT INTO repair_evidence_digest_changes (candidate_digest, evidence_kind, "
                            "evidence_ref, first_changed_sha256, schema_version, observed_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (*key, observed, REPAIR_EVIDENCE_STORE_SCHEMA_VERSION, now),
                        )
                        changed = observed
                    status = "unchanged" if changed is None else "changed"
                await db.commit()  # not shielded: a COMMIT queued before a cancel may still run (D4a N2)
        return TrustedDigestCheck(status, key[0], key[1], key[2], first, observed)


async def assess_candidate_evidence(
    recorder: TrustedDigestRecorder,
    candidate: RepairCandidate,
    authority_class: AuthorityClass,
    *,
    receipt_ref: str,
    receipt_bytes: bytes | None,
    review_ref: str,
    reviews: Sequence[ReviewAttestation] | None,
    expected_assignee: str,
    expected_label: str | None = None,
    required_reviewers: int = 1,
) -> EvidenceAssessment:
    """Derive both links from the evidence, record each ``present`` one, then evaluate C9.

    The links are derived here, never accepted pre-built. A link that is not ``present`` is not
    recorded. A reference the ledger reports ``changed`` blocks completion as ``evidence_changed``,
    which takes precedence over every other reason. Argument errors raise before anything is
    recorded; every ledger exception propagates; nothing returns complete on an error. Complete
    evidence is not authority: the Captain's approval is separate (S2).
    """
    if not is_evidence_ref(receipt_ref) or not is_evidence_ref(review_ref):
        raise ValueError("repair_evidence_ref_invalid")
    links = (
        verify_gate_receipt(candidate, receipt_bytes, expected_label=expected_label),
        bind_reviews(
            candidate, reviews, expected_assignee=expected_assignee, required_reviewers=required_reviewers,
        ),
    )
    completeness = evaluate_completion(candidate, authority_class, links)
    checks: list[TrustedDigestCheck] = []
    for ref, link in zip((receipt_ref, review_ref), links, strict=True):
        if link.current:
            checks.append(await recorder.check_and_record(ref, link))
    if any(check.changed for check in checks):
        for check in checks:
            if check.changed:
                logger.warning(
                    "AD-1299 S1b: %s evidence %s for candidate %s has a recorded digest change (first trusted "
                    "digest %s, observed now %s); completion stays blocked for this reference even when the "
                    "observed digest equals the first again, so new evidence must be recorded under a new reference",
                    check.kind, check.evidence_ref, check.candidate_digest[:12],
                    check.first_sha256[:12], check.observed_sha256[:12],
                )
        completeness = dataclasses.replace(completeness, reason="evidence_changed")
    return EvidenceAssessment(completeness, links, tuple(checks))
```

## Section 5 (M2): store declaration (`src/probos/cognitive/storage_declarations.py`)

Append inside `STORE_DECLARATIONS` after the `cognitive.elastic-teams` entry (closing `    ),` at `:167`, before `)` at `:168`):

```python
    StoreDeclaration(
        id="cognitive.repair-evidence",
        title="First trusted digest per repair evidence reference (AD-1299 S1b)",
        owner_module="probos.cognitive.repair_evidence_store",
        owner_symbol="RepairEvidenceLinkStore",
        canonical_path="repair_evidence.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="unowned",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Insert-only by design: six triggers abort every UPDATE, every DELETE and every replacing "
            "INSERT on both WITHOUT ROWID tables, and the module has no delete path. Growth is at most "
            "two rows per evidence reference (the first trusted digest and the first different digest), "
            "and references are created per candidate per gate run or review round. Archival belongs to "
            "the S4 release lifecycle; this slice adds none."
        ),
        notes=(
            "Not wired: nothing constructs or starts the store in production until AD-1299 S2 admission, "
            "so a default runtime never creates the file (lifecycle_owner is the 'unowned' sentinel). "
            "Detection only: a writer with ProbOS's OS identity can delete the file, which resets the "
            "first trusted digests (D-B2)."
        ),
    ),
```

## Section 6 (M2): `tests/test_ad1299_s1b_repair_evidence_store.py` (new)

Import `gate`, `repo`, `_candidate`, `_real_receipt`, `_mutate`, `_Review` from `tests.test_ad1299_s1a_repair_candidate` (fixtures register by import). Use `tmp_path / "repair_evidence.db"`. Direct `sqlite3` is allowed in tests only (the `db-connect` gate covers `src/`). For the fault tests write a `_FaultyFactory` wrapping `SQLiteConnectionFactory` that returns a proxy delegating `execute`/`executescript`/`commit`/`close` and raising when armed. **Commit-point parking (review round 2, R2-3):** in park-at-commit mode the proxy's `commit()` (1) queues a blocker on the real connection's worker, `factory.blocker = asyncio.ensure_future(self._inner._execute(factory.block_worker))` (test-only use of aiosqlite's queue, `core.py:150-160`; `block_worker` sets the `threading.Event` `worker_parked`, then returns `release.wait(10)`), (2) `await asyncio.sleep(0)`, (3) queues the real COMMIT behind it, `factory.commit_future = asyncio.ensure_future(self._inner.commit())`, (4) `await asyncio.sleep(0)`, (5) sets `parked`, (6) `await factory.commit_future`: production awaits exactly that COMMIT. The factory keeps `release` (`threading.Event`), `worker_parked` (`threading.Event`), `blocker` and `commit_future` (replacing round 1's `inner_commit`). **Worker-queue spy (review round 3, R3-1).** `_FaultyFactory.connect` asserts `isinstance(inner._tx, queue.SimpleQueue)` (premise: the aiosqlite 0.22.1 internal the spy relies on, `core.py:88`), then replaces `inner._tx` with a `_QueueSpy` whose `put_nowait(item)` appends `(label, weakref.ref(future))` to `factory.queued` and forwards `item` unchanged to the original queue (a strong reference is wrong: the queued future of an `execute` call carries its `sqlite3.Cursor` as its result, and keeping that cursor alive leaves a statement unfinalised, so a second connection fails with `database is locked`; found when this paragraph was first built). **Compatibility (review round 4, R4-1):** `pyproject.toml` allows `aiosqlite>=0.19`, and the worker of 0.19 to 0.21 calls `self._tx.get()` on the attribute, whereas 0.22.1 captures the original queue at construction (`core.py:90`); a spy without `get` therefore killed the worker on 0.21.0 while the `SimpleQueue` premise still passed. The spy reads through to the original queue for every other attribute (`__getattr__`), records only `(future, function)` tuples and forwards the stop sentinel (not a tuple) unchanged, and after installing it `connect` proves the worker still answers with TWO timed round trips, `await asyncio.wait_for(inner.commit(), 5)` twice (no-op COMMITs on the raw connection, recorded as two more `commit` labels before any blocker, which the tail assertions ignore; the worker of 0.19 to 0.21 re-reads its queue between items, so a spy it cannot read through shows on the second one, review round 5, R5-1), and on a failed premise or round trip it closes the connection through a BOUNDED wait (`asyncio.wait({asyncio.ensure_future(inner.close())}, timeout=2)`, never awaiting cleanup that cannot finish: `Connection.close()` awaits the worker's shutdown in a `finally`, so a stuck worker keeps it pending, R5-2) and then calls `pytest.fail("the queue spy broke the aiosqlite worker: its internals differ from the versions this test was written for")`. The worker thread of aiosqlite 0.22.1 keeps the original queue (`core.py:90`) and `put_nowait` is the only method `Connection` calls on `_tx` there (`core.py:131`, `:158`, `:167`), so on 0.22.1 the spy changes no behaviour; on 0.19 to 0.21 the worker also calls `get()` on the attribute, which the read-through below serves. Label of a queued callable `function`: `target = getattr(function, "func", function)` (every `_execute` call is a `functools.partial`, `core.py:155`); `"blocker"` if `getattr(target, "__func__", None) is _FaultyFactory.block_worker`; else `target.__name__` if `isinstance(getattr(target, "__self__", None), sqlite3.Connection)` (`"execute"`, `"commit"`, `"close"`, ...; `core.py:193`, `:206`, `:223`); else `getattr(target, "__name__", type(target).__name__)`. Helpers: `factory.queued_labels()` (all labels in order) and `factory.queued_tail()` (labels from the last `"blocker"` on; `[]` if none). Links for store tests: `EvidenceLink("gate_receipt", "present", "gate_receipt_bound", "0"*64, "1"*64)` and variants.

| # | Test | Asserts |
|---|---|---|
| 1 | `test_constructor_refuses_bad_paths` (`""`, `":memory:"`, `None`, `5`) | `ValueError("repair_evidence_store_path_invalid")` |
| 2 | `test_unstarted_and_stopped_store_raise_unavailable` | before `start()` and after `stop()`; `start`/`stop` idempotent; `start` after `stop` works |
| 3 | `test_first_observation_recorded_then_unchanged` | `first_recorded`, then `unchanged`, `first_sha256` equal both times |
| 4 | `test_different_digest_is_changed_first_kept_and_sticky` | A -> `first_recorded`; B -> `changed`, first A; A again -> still `changed` (ABA); C -> `changed`, first A; direct `sqlite3` read: one first row (A) and one change row (B) |
| 5 | `test_first_digest_survives_restart` | record A; `stop()`; NEW store instance on the same file, `start()`; B -> `changed` with first A |
| 6 | `test_references_are_independent` | same candidate+kind different ref; same ref different kind; same ref different candidate -> each `first_recorded` |
| 7 | `test_untrusted_or_malformed_input_is_refused_before_any_write` | refused link **that carries a digest** -> `ValueError("repair_evidence_link_untrusted")`; present link with `""` digest -> same; non-link -> `TypeError`; bad ref -> `ValueError("repair_evidence_ref_invalid")`; row count 0 afterwards |
| 8 | `test_database_refuses_update_delete_and_replace` (parametrize both tables x UPDATE / DELETE / `INSERT OR REPLACE`) | premise: the row exists; `sqlite3.IntegrityError` matching `repair_evidence_immutable`; row unchanged |
| 9 | `test_unvalidated_stored_row_is_an_integrity_error` (parametrize: first row `schema_version=2`; first row digest `"Z"*64`; change row equal to first) | pre-create permissive tables with `sqlite3` (same names, columns and primary keys; `WITHOUT ROWID`; no CHECKs, so the foreign key still has a parent key), insert the bad row, `start()`, observe -> `RepairEvidenceIntegrityError("repair_evidence_integrity")`, an ERROR record in `caplog` |
| 10 | `test_failed_write_commits_nothing` | arm the fake to raise on the `INSERT INTO repair_evidence_first_digests`: error propagates; disarm; same observation -> `first_recorded` |
| 11 | `test_cancelled_write_commits_nothing` | REAL `task.cancel()` before the COMMIT: the factory parks after the real `INSERT INTO repair_evidence_first_digests` has run (sets `parked`, then waits on a never-set event). Premises: `parked` set, `not task.done()`, `factory.commit_future is None` (no COMMIT was started). Cancel; `pytest.raises(CancelledError)` on `await task`, `task.cancelled()`; row counts `(0, 0)`; next observation (wrapped in `asyncio.wait_for(..., 5)`, so a leaked lock fails rather than hangs) -> `first_recorded` |
| 20 | `test_cancel_after_commit_queued_waits_for_cleanup_and_may_record` (parametrize `first`, `change`) | REAL `task.cancel()` with the COMMIT queued behind a held worker (B1, R2-3, R3-1; proxy and queue spy above). Covers D4a N1-N4, and the implementation note under a SINGLE cancel only (it does not test repeated cancels; N5 promises nothing there). `first`: observe A through the parked store. `change`: record A normally (premise `first_recorded`), then observe B through it. `before = _counts(db_path)`, asserted `(0, 0)` / `(1, 0)`. Start the task; `await asyncio.wait_for(factory.parked.wait(), 5)`. **Premises:** `await asyncio.to_thread(factory.worker_parked.wait, 5)` is True (the worker is held); `factory.commit_future` is not None and `not done()`; `not task.done()`; `_counts(db_path) == before` (the COMMIT has not run). **Queue observation before the cancel (R3-1), on the real worker queue, not the proxy:** `"execute"` occurs in `factory.queued_labels()` before the last `"blocker"` (premise: the spy sees this connection's statements); `factory.queued_tail() == ["blocker", "commit"]` (the real `sqlite3.Connection.commit` was queued after the blocker and BEFORE `task.cancel()`; no close yet). **Cancel:** `task.cancel()`; `_, pending = await asyncio.wait({task}, timeout=0.2)`; `task in pending` (single cancel: the close is queued behind the COMMIT); `factory.commit_future.cancelled()` (no shield); the weakref the spy recorded with the last `"commit"` label still resolves and its referent is `cancelled()` (that referent is the future aiosqlite's `_execute` queued on the worker for that COMMIT, not `factory.commit_future`, which is the `asyncio.Task` wrapping the `Connection.commit()` coroutine; cancelling the awaited Task cancels the future it waits on, so the cancellation reached the queued COMMIT's future); `factory.queued_tail() == ["blocker", "commit", "close"]`; `_counts(db_path) == before` (still not run). **Release** in a `finally` (`factory.release.set()`), then `done, _ = await asyncio.wait({task}, timeout=5)`; `task in done`, `task.cancelled()` (propagated, not swallowed), and `pytest.raises(CancelledError)` on `await task`. Before any retry: `factory.queued_tail()[:3] == ["blocker", "commit", "close"]` and `factory.queued_tail().count("commit") == 1` (no COMMIT was queued after the cancel). `factory.unpark()`. **Outcome** (with the queue observation, proves the COMMIT queued before the cancel is the one that recorded): `first` -> exactly one first row with A, no change row; retry A (identical evidence) -> `unchanged`, `first_sha256 == A`; then B -> `changed` (the abandoned first observation pinned A). `change` -> first row A and one change row B; retry B (identical evidence) -> `changed`, first A; then the ORIGINAL A -> `changed`, first A (R2-1: an abandoned observation of different evidence leaves `changed`). Every retry under `asyncio.wait_for(..., 5)` |
| 21 | `test_database_refuses_values_the_validators_refuse` (parametrize table x column x value) | Raw `sqlite3` on a started store's file. Values: digest columns (`candidate_digest`, `first_sha256` / `first_changed_sha256`) `"0"*64+"\x00x"`, `"0"*32+"\x00"+"0"*31`, `b"0"*64`, `"A"*64`; `evidence_ref` `"-x"`, `".x"`, `":x"`, `"a\x00b"`, `""`, `"a"*129`, `"é"`, `b"abc"`; `evidence_kind` `"gate_receipt\x00x"`, `b"gate_receipt"`. Premises per case: the Python rule refuses the value (`is_sha256_hex` / `is_evidence_ref` False, or kind not one of the two literals as a `str`), and the same INSERT with the valid value succeeds (also the boundaries `"9"` and `"a"*128` for the reference). Change-table cases run with `PRAGMA foreign_keys=OFF` asserted to read `0`, so only the mirrored `CHECK` can refuse. Asserts `sqlite3.IntegrityError` whose message contains the expected constraint name (for example `repair_evidence_change_ref_shape`), and the row count is unchanged. **Numeric cases (review round 2, R2-2)**, a fifth parameter `foreign_keys` (`"off"` for every case above): `_NUMERIC_VALUES = [(9, "9"), (9.0, "9.0"), (True, "1"), (2**63 - 1, "9223372036854775807"), (-1.7976931348623157e308, None), (float("inf"), None)]` (value, string twin or `None`), applied to EVERY column of both tables (both digest columns, `evidence_kind`, `evidence_ref`), each with `foreign_keys` `"off"` and `"on"`. Same premises (the Python rule refuses the number; the valid value is accepted). `"on"`: `PRAGMA foreign_keys=ON` is the FIRST statement on the connection (it is a no-op inside a transaction), then asserted to read `(1,)`; for a change-table case, parent rows are inserted into the first table first for every key the case later inserts (the valid `REF`, plus, when the column is `evidence_ref`, the twin when not `None` and the boundaries `"9"` and `"a"*128`), so the valid and boundary inserts satisfy the foreign key and the twin's parent exists (under mutant L15 the coerced number would match it). The same constraint-name assertion applies in both modes: the per-row `CHECK` fails before the statement-end foreign-key check. **NaN cases (review round 3, R3-3):** `float("nan")` for each of the four string-valued columns of both tables (8 cases, foreign keys `"off"`), same premises, expecting `sqlite3.IntegrityError` whose message contains `NOT NULL constraint failed: <table>.<column>` (SQLite binds NaN as NULL; no `CHECK` is named). Add a function docstring stating, in one sentence, that only the 20 numeric `evidence_ref` cases that TEXT affinity would coerce to a valid reference (`9`, `9.0`, `True`, `2**63 - 1`, `inf` as `"Inf"`; both tables; foreign keys off and on) discriminate the round-2 change, and the other 76 numeric cases also passed before it and stay as regression pins. Scope: numbers bound to `schema_version`, `recorded_at` or `observed_at` are admitted by design and are not cases here (D7) |
| 22 | `test_a_str_subclass_is_stored_as_plain_text_and_passes_the_stored_text_rules` (parametrize table x string-valued column) | Review rounds 4-5, R4-2, R5-3. Raw `sqlite3` on a started store's file: bind a `str` subclass carrying a valid value (`class _Text(str)`; a valid digest, kind literal or reference) to each of the four string-valued columns of both tables (change-table cases with `PRAGMA foreign_keys=OFF` asserted to read `0`, so only the mirrored CHECKs act); the INSERT succeeds; read the row back: `typeof(column) = 'text'`, the value read is `type(...) is str`, equals the plain text, and passes the Python rule for that column (`is_sha256_hex` / `is_evidence_ref` / kind membership). Premises, per column: for the digest and reference columns the exact-`str` rule refuses the subclass (`is_sha256_hex` / `is_evidence_ref` False) and accepts the plain text; for `evidence_kind` the premise is the opposite, because production's kind rule is membership of the two literals: the real `EvidenceLink` accepts a `_Text` kind (it constructs), so the engine admitting it is consistent with production. `_refused_by_python` / `_accepted_by_python` for the kind column therefore test membership only (`value in {"gate_receipt", "review_set"}`), not the exact type. This pins the boundary D6 states: SQLite cannot see the Python object type, so the engine admits the subclass as the plain text it contains. No mutant is attached: nothing in the module would make this fail |
| 12 | `test_invalid_clock_refuses_the_write` (`nan`, `inf`, `"1"`) | `RepairEvidenceStoreUnavailable("repair_evidence_clock_invalid")`; row count 0 |
| 13 | `test_injected_factory_is_used_and_close_failure_is_logged` | every connection comes from the injected factory; a proxy whose `close` closes the real connection then raises -> the result still returns, WARNING logged |
| 14 | `test_assess_crosses_verifier_ledger_and_completion_across_restart` (milestone, real producer) | real receipt + two independent reviews naming `builder`: `complete`, two `first_recorded` checks; restart the store; same evidence -> `complete`, both `unchanged`; `_mutate(receipt, "finished_at", "2026-10-11T23:59:59Z")` (a field the binder does not read; S1a test `:581` precedent; premise: the mutated receipt still binds) under the SAME `receipt_ref` -> `evidence_changed`, `complete is False`, WARNING logged; the same mutated receipt under a NEW `receipt_ref` -> `complete` |
| 15 | `test_assess_does_not_record_non_present_links` | `receipt_bytes=None`: no exception, gate link `unavailable`, `checks` has one entry (review), reason `evidence_not_present` |
| 16 | `test_assess_refuses_relabelled_self_review` | builder self-review labelled `assignee_id="decoy"` with `expected_assignee="builder"` -> review link `review_assignee_mismatch`, reason `evidence_not_present`, nothing recorded for the review ref |
| 17 | `test_assess_argument_errors_raise_before_recording` | bad `receipt_ref` / `review_ref`, bad class, bad `expected_assignee` -> raise; ledger row count 0 |
| 18 | `test_store_is_declared` | `load_default_store_registry().get("cognitive.repair-evidence")` has `owner_symbol == "RepairEvidenceLinkStore"`, `canonical_path == "repair_evidence.db"`, `lifecycle_owner == "unowned"` |
| 19 | `test_nothing_in_src_constructs_the_store` | AST scan of `src/probos/**/*.py` (excluding the module itself): no `RepairEvidenceLinkStore(` call and no import of `repair_evidence_store` (pins D5; S2 changes this test deliberately) |

Test 19 is a source scan; keep it AST-based (no `read_text` of `__file__`) and name in its docstring the slice that will change it.

---

## Mutation table (the campaign of record runs once, after repair 3; see "Review round 3 campaign of record")

Run the unmodified baseline first. Mutate in place with a `.mutbak` sibling, restore in `finally`, single-line anchors only (CRLF tree; T4 is the one two-anchor mutant, both replaced in the same run). An anchor not found is INERT, not killed; a timeout is INVALID. Record the base tree and the sha256 of the four S1b files (`src/probos/cognitive/repair_candidate.py`, `src/probos/cognitive/repair_evidence_store.py`, `tests/test_ad1299_s1b_evidence_completion.py`, `tests/test_ad1299_s1b_repair_evidence_store.py`); a later Builder whose files match does not repeat it.

| Id | File | Anchor (exact line) -> mutant | Killed by |
|---|---|---|---|
| C8a | `repair_candidate.py` | `    if any(assignee != expected_assignee for _, _, assignee, _, _ in projected):` -> `    if all(assignee != expected_assignee for _, _, assignee, _, _ in projected):` | M1 #5 |
| C8b | `repair_candidate.py` | same anchor -> `    if False:` | M1 #3, #4 |
| C8c | `repair_candidate.py` | `    if type(expected_assignee) is not str or _ID_RE.fullmatch(expected_assignee) is None:` -> `    if type(expected_assignee) is not str:` | M1 #2 |
| C9a | `repair_candidate.py` | `    "enhancement": frozenset({"gate_receipt", "review_set"}),` -> `    "enhancement": frozenset({"gate_receipt"}),` | M1 #10 (the pinned table; #11 survives it, because both kinds present still complete; A3) |
| C9b | `repair_candidate.py` | `    present = {link.kind for link in links if link.current and link.candidate_digest == digest}` -> `    present = {link.kind for link in links if link.current}` | M1 #14 |
| C9c | `repair_candidate.py` | `    elif any(not link.current for link in links):` -> `    elif False:` | M1 #15 |
| C9d | `repair_candidate.py` | `    elif missing:` -> `    elif not present:` | M1 #13 |
| L1 | `repair_evidence_store.py` | `                    if changed is None and observed != first:` -> `                    if False:` | M2 #4 |
| L2 | `repair_evidence_store.py` | `                    status = "unchanged" if changed is None else "changed"` -> `                    status = "unchanged" if observed == first else "changed"` | M2 #4 (ABA step) |
| L3 | `repair_evidence_store.py` | `CREATE TRIGGER IF NOT EXISTS repair_evidence_first_digests_no_update BEFORE UPDATE ON repair_evidence_first_digests` -> same with `ON repair_evidence_digest_changes` at the end | M2 #8 |
| L4 | `repair_evidence_store.py` | `    if type(version) is not int or version != REPAIR_EVIDENCE_STORE_SCHEMA_VERSION or not is_sha256_hex(first):` -> `    if not is_sha256_hex(first):` | M2 #9 (schema 2 case) |
| L5 | `repair_evidence_store.py` | `        if not link.current or not link.evidence_sha256:` -> `        if not link.evidence_sha256:` | M2 #7 (refused link with a digest) |
| L6 | `repair_evidence_store.py` | `    if any(check.changed for check in checks):` -> `    if False:` | M2 #14 |
| L7 | `repair_evidence_store.py` | `        if link.current:` -> `        if True:` | M2 #15 |
| L8 | `repair_evidence_store.py` | `    CONSTRAINT repair_evidence_first_sha256_shape CHECK (typeof(first_sha256) = 'text' AND length(CAST(first_sha256 AS BLOB)) = 64 AND length(first_sha256) = 64 AND first_sha256 NOT GLOB '*[^0-9a-f]*'),` -> `    CONSTRAINT repair_evidence_first_sha256_shape CHECK (typeof(first_sha256) = 'text' AND length(first_sha256) = 64 AND first_sha256 NOT GLOB '*[^0-9a-f]*'),` | M2 #21 (`first_sha256` = `"0"*64+"\x00x"`) |
| L9 | `repair_evidence_store.py` | same anchor as L8 -> `    CONSTRAINT repair_evidence_first_sha256_shape CHECK (length(CAST(first_sha256 AS BLOB)) = 64 AND length(first_sha256) = 64 AND first_sha256 NOT GLOB '*[^0-9a-f]*'),` | M2 #21 (`first_sha256` = `b"0"*64`) |
| L10 | `repair_evidence_store.py` | `    CONSTRAINT repair_evidence_first_ref_shape CHECK (typeof(evidence_ref) = 'text' AND length(CAST(evidence_ref AS BLOB)) = length(evidence_ref) AND length(evidence_ref) BETWEEN 1 AND 128 AND evidence_ref GLOB '[A-Za-z0-9]*' AND evidence_ref NOT GLOB '*[^A-Za-z0-9_.:-]*'),` -> `    CONSTRAINT repair_evidence_first_ref_shape CHECK (typeof(evidence_ref) = 'text' AND length(CAST(evidence_ref AS BLOB)) = length(evidence_ref) AND length(evidence_ref) BETWEEN 1 AND 128 AND evidence_ref NOT GLOB '*[^A-Za-z0-9_.:-]*'),` | M2 #21 (`"-x"`, `".x"`, `":x"`) |
| L11 | `repair_evidence_store.py` | same anchor as L10 -> `    CONSTRAINT repair_evidence_first_ref_shape CHECK (typeof(evidence_ref) = 'text' AND length(evidence_ref) BETWEEN 1 AND 128 AND evidence_ref GLOB '[A-Za-z0-9]*' AND evidence_ref NOT GLOB '*[^A-Za-z0-9_.:-]*'),` | M2 #21 (`"a\x00b"`) |
| L12 | `repair_evidence_store.py` | `    CONSTRAINT repair_evidence_change_ref_shape CHECK (typeof(evidence_ref) = 'text' AND length(CAST(evidence_ref AS BLOB)) = length(evidence_ref) AND length(evidence_ref) BETWEEN 1 AND 128 AND evidence_ref GLOB '[A-Za-z0-9]*' AND evidence_ref NOT GLOB '*[^A-Za-z0-9_.:-]*'),` -> `    CONSTRAINT repair_evidence_change_ref_shape CHECK (1),` | M2 #21 (change table, foreign keys off) |
| L13 | `repair_evidence_store.py` | `    CONSTRAINT repair_evidence_change_candidate_shape CHECK (typeof(candidate_digest) = 'text' AND length(CAST(candidate_digest AS BLOB)) = 64 AND length(candidate_digest) = 64 AND candidate_digest NOT GLOB '*[^0-9a-f]*'),` -> `    CONSTRAINT repair_evidence_change_candidate_shape CHECK (1),` | M2 #21 (change table, foreign keys off) |
| L14 | `repair_evidence_store.py` | `    evidence_ref NOT NULL, -- first table: no declared type, so no affinity turns a bound number into TEXT before the CHECK` -> `    evidence_ref TEXT NOT NULL, -- first table: no declared type, so no affinity turns a bound number into TEXT before the CHECK` | M2 #21 numeric first-table `evidence_ref` cases (`9`, `9.0`, `True`, `2**63 - 1`, `inf` coerce to valid references and insert) |
| L15 | `repair_evidence_store.py` | `    evidence_ref NOT NULL, -- change table: no declared type, so no affinity turns a bound number into TEXT before the CHECK` -> `    evidence_ref TEXT NOT NULL, -- change table: no declared type, so no affinity turns a bound number into TEXT before the CHECK` | M2 #21 numeric change-table `evidence_ref` cases, foreign keys off, and on (the twin's parent exists) |
| X1 | `repair_evidence_store.py` | `                await db.close()` -> `                asyncio.ensure_future(db.close())` | M2 #20 (`task in pending` 0.2 s after the cancel fails: the caller returns before its close), also #13 |
| X2 | `repair_evidence_store.py` | `                await db.commit()  # not shielded: a COMMIT queued before a cancel may still run (D4a N2)` -> `                await asyncio.shield(db.commit())  # not shielded: a COMMIT queued before a cancel may still run (D4a N2)` | M2 #20 (`factory.commit_future.cancelled()` fails: the shield keeps the cancellation away from the awaited COMMIT) |

**Test-side mutants for #20 (R2-3).** These prove the test establishes its own premises; they mutate `tests/test_ad1299_s1b_repair_evidence_store.py` in place (anchors in `_FaultyConnection.commit` and, for T4, `_FaultyConnection.close`; `.mutbak` sibling, restore in `finally`, sha256 of the test file equal before and after), run only `-k cancel_after_commit`, and expect BOTH parametrized variants of each mutant to FAIL at the named assertion. A swallowed cancellation has no single-line production form (the commit await is not inside any `try`), so T3 injects it at the commit point from the test side.

| Id | Anchor (exact line) -> mutant | Must fail at |
|---|---|---|
| T1 | `        factory.commit_future = asyncio.ensure_future(self._inner.commit())` -> `        factory.commit_future = asyncio.get_running_loop().create_future()` (the round-2 reviewer's shape: the caller awaits a future, no COMMIT is ever queued) | the pre-cancel queue observation (`queued_tail()` is `["blocker"]`); before R3-1 it failed at the outcome rows |
| T2 | `        factory.blocker = asyncio.ensure_future(self._inner._execute(factory.block_worker))` -> `        factory.blocker = None` (the worker is never held) | the `worker_parked` premise (False after 5 s) |
| T3 | `        await factory.commit_future  # production awaits exactly this COMMIT` -> `        with contextlib.suppress(asyncio.CancelledError): await factory.commit_future` | `task.cancelled()` (the call returns a result) |
| T4 | TWO anchors, both replaced in one run: `        factory.commit_future = asyncio.ensure_future(self._inner.commit())` -> `        factory.commit_future = asyncio.get_running_loop().create_future()` AND `        await self._inner.close()` -> `        await self._inner.commit(); await self._inner.close()` (the round-3 reviewer's shape: the caller awaits a dummy pending future and the real COMMIT is queued only from the proxy's `close()`, after the cancel; every round-2 assertion of #20 passed under it) | the pre-cancel queue observation (`queued_tail()` is `["blocker"]`, not `["blocker", "commit"]`) |

**Review round 3 campaign of record (supersedes both rerun-scope paragraphs below).** After repair 3 is staged, run the whole table once, baseline first: C8a-C9d, L1-L15, X1, X2, T1-T4. No result from an earlier round stands. Record the base tree, the sha256 of the four S1b files named above, and per mutant KILLED / INERT / INVALID with the first failing test id. That report is the campaign of record; M3 copies it into the `DECISIONS.md` S1b entry. A later edit to one of the four files invalidates the mutants pinned to it: `repair_candidate.py` or the M1 test file -> C8a-C9d; the store module or the store test file -> L1-L15, X1, X2, T1-T4.

**Review round 2 rerun scope (superseded by round 3).** No anchor of C8a-C9d or L1-L13 changes text (the reference `CHECK` lines are unchanged; only the two declaration lines, the commit line, docstrings and tests change), and `repair_candidate.py` is not touched. Rerun L8-L13 (their killer, #21, changed), the new L14, L15, X1, X2 and T1-T3. C8a-C9d and L1-L7 stand from the round-1 campaign if `repair_candidate.py`'s sha256 matches that campaign's record; record the new sha256s of the store module and the store test file. If the round-1 campaign was not recorded, run the whole table once.

**Review round 1 rerun scope (superseded by round 3).** Re-execute the whole table (C8a-C9d and L1-L13) as the new campaign of record: every pinned file's hash changes (A1 docstring, B1-B3 store edits, new tests), and the pure mutants cost seconds. Record the new base tree and sha256s.

Every anchor appears exactly once in the file named (verify with a count before mutating; the L3 mutant still creates a distinctly named trigger, so the schema stays valid).

---

## What this does NOT change

- The S1a review-set digest, its domain, and the gate-receipt binder.
- `EvidenceKind` (still two kinds) and `EvidenceLink` validation.
- Runtime, startup, config, routers, events, `CrewSession`, `WorkItem`, `CapabilityRequestStore`, `FaultReportStore`, the `repair_*` modules, `run_test_gate.py`, `WorktreeManager`, `BuildDispatcher`, `routers/build.py`.
- The store registry tooling, baselines (`store-baseline.yaml`, `architecture-baseline.yaml`): a declared store needs no baseline row.

## Do not build

- No runtime wiring: no construction in `startup/`, no data-dir path, no config field, no API route, no event.
- No `captain_approval` kind, approval binder, campaign admission or authority logic (S2).
- No delete, list, scan, reset, archival or "accept new digest" API on the ledger. A reset path is exactly how a pinned-hash store loses its value.
- No in-toto/DSSE envelope, signing or key material (AD-1047; keys are a Captain decision).
- No shared connection helper extracted from `ElasticTeamStore`, and no edit to it.
- No wording that claims prevention, containment, authentication or authority. Say "detects", "refuses", "records".
- No broad `except` other than the documented one in `_open`; never `BaseException`.
- No broad gate run by the Builder; no `git add -A`.

## Tracking (M3)

- `PROGRESS.md` line 5: prepend a one-sentence S1b status (built, unwired, files, test counts) before the S1a sentence; keep S1a's text.
- `DECISIONS.md` AD-1299 section (`:9248` onward): append an "S1b (2026-10-12)" entry recording D1-D7 in one line each (D4a as its normative contract N1-N5), plus the campaign of record: base tree, sha256 of the four S1b files, and per-mutant result (C8a-C9d, L1-L15, X1, X2, T1-T4) with its killing test.
- `docs/development/self-maintenance-architecture.md`: C8 and C9 rows (`:430-431`) gain "Built in S1b"; the S1 slice bullet (`:449-456`) links this prompt; add "ledger reset by deleting the file" to the D-B2 detection-only list as a named S2 constraint (C12, below).
- No roadmap edit unless `docs/development/roadmap.md` already lists S1a as a line item (grep `S1a`); if it does, add S1b beside it.

## Acceptance criteria

1. M1 and M2 focused runs green with `-n 0 -p no:randomly`, `probos.__file__` resolving inside this worktree's `src`.
2. `scripts/check_store_registry.py --check` and `scripts/check_architecture_principles.py --check` exit 0 with the new files **staged** (both read tracked files).
3. Every mutant in the table is KILLED by the named test (or the named test plus others); none INERT or INVALID, in the single round-3 campaign of record. Its base tree, the four file hashes and the per-mutant results are in the campaign report and, after M3, in the `DECISIONS.md` S1b entry.
4. M2 #14 crosses the real producer (`run_test_gate.py` `_write_success_receipt`) -> `verify_gate_receipt`/`bind_reviews` -> ledger on a real SQLite file -> restart -> completion, in ONE test.
5. Nothing under `src/probos/` constructs the store (M2 #19).
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Prior Art and Blind Spots (2026-10-12)

| Source | Idea | Decision |
|---|---|---|
| S1a prompt `:958` (in-toto layouts, https://github.com/in-toto/specification/blob/master/in-toto-spec.md) | The owner fixes which steps must be evidenced; verification fails if one is missing. | **Absorb** as D2: a fixed per-class kind table, counted by kind. |
| OpenSSH `known_hosts` (Oracle, https://docs.oracle.com/en/operating-systems/oracle-linux/openssh/openssh-WorkingWithknownhosts.html) | Trust on first use: record the first key, refuse a changed key, and re-trust only by explicit removal. | **Adapt** as D3. ProbOS has no removal path at all: new evidence takes a new reference, so the old pin and its change record stay as audit. |
| Go module checksums (`go.sum`; reports such as https://answers.netlify.com/t/hugo-go-module-security-error-checksums-not-matching/96535) | A content hash pinned on first download; a mismatch is a security error. The common "fix", deleting `go.sum`, discards the tampering signal. | **Absorb** the lesson: no reset or delete API (Do not build). Deleting the file remains possible for a same-identity writer; recorded as C12. |
| AD-1286 `ElasticTeamStore` (`elastic_team_store.py:1-34`, `:98-129`) | Insert-only enforced by triggers, `WITHOUT ROWID`, per-row `schema_version`, per-operation connections. | **Adapt** (D4, D7): same triggers and versioning; per-operation connections without its tracked-close machinery. |
| AD-1154 `ActionApprovalStore` (`action_approvals.py:126-149`) | Reference constructor: `ConnectionFactory` injection, lazy default factory, WAL and pragmas. | **Absorb** the constructor shape. **Reject** its cache-only `db_path=""` mode for this ledger. |
| AD-1047 | A hash is integrity, not authenticity. | **Absorb**: no field or docstring implies an authenticated producer. |
| `docs/research/` | Searched in the S1a pass for provenance and attestation; nothing applies. | Nothing to cite. |

**Blind spots named (constraints, not scope):**

- **C12 (S2): ledger reset by file deletion.** On a missing file `start()` creates an empty ledger, so first digests vanish without a signal. S2 wiring must decide how a recreated ledger is detected (for example a ledger identity recorded at campaign admission). Not built here: it needs the campaign record S2 introduces.
- **Reference discipline.** Detection is per reference the consumer re-presents. A gate rerun overwrites `logs/gates/<label>.receipt.json`; S2 must derive a fresh reference per run (for example label plus run start time) and must never re-present a reference it already saw change.
- **Permissive pre-existing tables.** `CREATE TABLE IF NOT EXISTS` keeps an older table's weaker shape; the read-side validation (M2 #9) is what catches its rows. Schema verification at start is deferred to the first schema change.
- **Naming.** `work_item_steps.OwnedStepsRepairEvidence` (`:56`) is unrelated (owned-step chain repair); the new names (`RepairEvidenceLinkStore`, `repair_evidence_*` tables) do not collide with it.

---

## Review round 1 amendments (2026-10-12)

Two Diff Reviewers returned NOT READY; the orchestrator reproduced every finding.

| Id | Finding | Ruling | Where amended |
|---|---|---|---|
| B1 (High) | A call cancelled after its COMMIT is queued can still record; D4/D6 said otherwise; test #11 cancelled before COMMIT with a raised error, not a real cancel | Option 1: keep immediate propagation, state the contract (D4a). No logic change; docstrings and one comment | D4, D4a, D6, Section 4 module and `check_and_record` docstrings, Section 6 #11 (real cancel) and new #20 |
| B2 (Medium) | CHECKs admitted NUL-suffixed digests, BLOB digests, leading `-`/`.`/`:` and NUL in references; change table relied on its foreign key | Named table CHECKs on both tables: TEXT only, byte length = character length, owned-id first character; key checks mirrored on the change table. Schema version stays 1 (D7 evidence) | D6, D7, Section 4 `_SCHEMA`, Section 6 #21, mutants L8-L13 |
| B3 (Low) | ABA warning said "differs" after A -> B -> A; `_open` "always closed" overclaimed | Reworded | Section 4 warning and `_open` docstring; staged test `:595` phrase |
| A1 | `bind_reviews` docstring: a changed assignee "still binds" | Reworded for C8 | Section 1 docstring instruction |
| A2 | S1a adapter docstring: "every S1a case names the campaign builder" | Reworded | Section 3 |
| A3 | D1 Compatibility and Absence Verified true only at base; C9a killer list named #11 | Scoped to base, new caller named; C9a killer is #10 only | D1, Absence Verified, mutation table |

Two pre-review amendments (orchestrator, in-envelope: each strengthens the stable-code tier of D6) were built before the first review and are folded into Sections 1 and 4 above: **P1**, `EvidenceCompleteness.__post_init__` refuses a non-`str` `missing_kinds` member with `ValueError("evidence_completeness_invalid")` (a raw `TypeError` before); **P2**, `TrustedDigestCheck.__post_init__` refuses a non-`str` status with `ValueError("trusted_digest_check_invalid")` for the same reason.

## Review round 2 amendments (2026-10-12)

A fresh Diff Reviewer (GPT-6.1 Sol) returned NOT READY with three Medium findings; the orchestrator reproduced each (probe: worker held by a queued blocker ahead of the COMMIT, premises asserted). The executable logic of `check_and_record` stays; B1's "keep immediate propagation" wording in the round-1 table above is superseded by R2-1.

| Id | Finding | Ruling | Where amended |
|---|---|---|---|
| R2-1 (Medium) | "Never delayed / at once / immediately" false: `CancelledError` waits for the queued COMMIT and the `finally` close (0.204 s with the worker held 0.2 s). "A retry answers consistently" and "no effect on any assessment" false for different evidence: record A, abandon B after its COMMIT is queued, a later A reads `changed` | Keep the unshielded code (in envelope: no control weakened). Restate: propagation after awaited cleanup, bounded by the connection's own queue and `busy_timeout`; outcome unknown after the COMMIT is queued; identical-evidence retries answer the same for completion; different evidence can read `changed` (blocking only); S2 treats `CancelledError` as outcome unknown. Absolute-word sweep below | D4, D4a, D6, Section 4 module and `check_and_record` docstrings, commit-line comment (now a trailing comment: unique anchor for X2), Section 6 #20, store test module docstring |
| R2-2 (Medium) | TEXT affinity converts a bound number before the `CHECK`s: raw `9` stored as `'9'` | `evidence_ref` declared with no type in both tables (table-specific SQL comments make each line a unique anchor); other columns kept, argued in D7; schema version stays 1 (`d8af3ac8` is also unbranched) | D6, D7, `_SCHEMA`, #21 numeric cases (both tables, every column, foreign keys off and on), mutants L14, L15 |
| R2-3 (Medium) | #20 could not show the COMMIT was queued before the cancel; the caller waited on a never-set event | Worker-holding proxy: blocker, then the real COMMIT, caller awaits that COMMIT future; assertions for pending-before-release, cancelled COMMIT future and the durable outcome | Section 6 helper paragraph, #11 premise (`commit_future`), #20, mutants X1, X2, test-side T1-T3 |

**Absolute-word sweep (R2-1)** over this contract and Section 4: `never`, `at once`, `immediately`, `always`, `nothing`, `no effect` on the cancellation topic. Fixed: D4 ("at once"), D4a rows 1-3 and the S2 note ("never swallows or delays", "settled before the lock is released", "the only effect"), D6 ("never swallowed or delayed"), module docstring ("still propagates, and a retry answers consistently"), `check_and_record` docstring ("always propagates", "never swallowed or delayed", "no effect on any assessment"), the commit comment, #20's name. Kept, because true: "before its COMMIT is queued leaves nothing / records nothing" (uncommitted rows die with the connection), "never replaces the first digest" and "never the reverse" (insert-only), "nothing returns complete on an error" (a cancelled call returns nothing), `_open`'s "uncommitted work was never visible". History rows (round-1 table, B1) are left as written and marked superseded above.

## Review round 3 amendments (2026-10-12)

A fresh Diff Reviewer (GPT-6.1 Sol) returned NOT READY with two Medium and one Low finding; the orchestrator reproduced each (`probe_s1b_r2.py`, `probe_s1b_r3.py`, real aiosqlite/SQLite, premises asserted). Executable production logic is unchanged; one comment, docstrings and tests change. Rule adopted for this and later rounds: write the weakest true statement, and give every quantifier or absolute a named test or probe, or drop it.

| Id | Finding | Ruling | Where amended |
|---|---|---|---|
| R3-1 (Medium) | #20 accepted a COMMIT queued only after the cancel (proxy `commit()` awaits a dummy pending future; the real COMMIT is queued from `close()`): the test learned of the COMMIT only from its own proxy | Observe the real worker queue: `_QueueSpy` replaces `inner._tx`; before the cancel the tail is `blocker, commit`; after it, `blocker, commit, close` and the queued commit future is cancelled; one COMMIT in total. New two-anchor test-side mutant T4; T1 now fails at the queue observation | Section 6 helper paragraph and #20; T1, T4 |
| R3-2 (Medium) | "Propagation after the awaited cleanup" holds only under a single cancel: with the COMMIT parked, cancel 3 ends the call, lock released, COMMIT pending, row durable after release | Normative contract N1-N5 (propagates; outcome unknown; identical retry safe; different evidence may leave `changed`; no timing promise). Mechanics moved to a labelled non-normative note (aiosqlite 0.22.1; single cancel; repeated cancel stated as observed). #20 keeps asserting single-cancel behaviour (X1 is a real resource bug) without the contract promising it | D4, D4a, D6; Section 4 module, `stop`, `_open`, `check_and_record` docstrings; commit comment (X2 anchor) |
| R3-3 (Low) | "Every number is refused by a named CHECK" over-scoped: NaN binds as NULL and `NOT NULL` refuses it; numbers are admitted by design into `schema_version` and both timestamps | Scoped to the four string-valued columns; NaN via `NOT NULL`; 8 NaN cases in #21; #21 docstring states which numeric cases discriminate | D6, D7, module docstring, #21, L14 row |
| P6 (Not verified) | "C8a-C9d and L1-L7 stand from the round-1 campaign" relied on a record no tracked file holds | One whole-table campaign after repair 3 is the campaign of record; M3 writes base tree, four sha256s and per-mutant results into `DECISIONS.md` | Mutation section, Acceptance 3, Tracking, briefs M2 and M3 |

**Quantifier sweep (R3)** over D4-D7, Section 4 docstrings and Section 6 #20/#21. Each kept absolute and its backing: triggers abort "every" UPDATE/DELETE/replacing INSERT (#8, both tables x three operations); CHECKs admit "only" stored values that meet the validators' rules for the stored text, four columns (#21; the Python-type boundary is #22); "every operation" uses the injected factory (#13); `close()` awaited "on every exit path", now qualified for repeated cancels (#3, #10, #11, #20, X1); the first digest is "never replaced" and a hidden record moves an answer "only" to `changed` (#4, #8); "before its COMMIT is queued leaves nothing" (#10, #11). Dropped or moved to the note: "reaches the caller once the queued COMMIT and close have run", "once queued, this COMMIT runs", "after any in-flight one finishes", "refuses every number".

**Build finding (repair 3, edit phase).** The queue spy as first written stored `(label, future)`. Building it showed a strong reference to the queued future of an `execute` call keeps that call's `sqlite3.Cursor` alive (the future's result), the unfinalised statement holds a lock, and five store tests failed with `database is locked` on a second connection. The spy stores `weakref.ref(future)` instead (the helper paragraph and #20 are amended). A second build finding followed: the future the spy sees is the plain `Future` that `Connection._execute` creates and queues, not `factory.commit_future` (the `asyncio.Task` wrapping `Connection.commit()`), so an identity assertion between them cannot hold; #20 asserts instead that the recorded referent resolves and is `cancelled()`, which with the queue tails and `factory.commit_future.cancelled()` establishes that the COMMIT was queued before the cancel and that the cancellation reached its future.

## Review round 4 amendments (2026-10-12)

A fresh Diff Reviewer (GPT-6.1 Sol) returned NOT READY with one Medium and one Low finding. The orchestrator reproduced the second (a `str` subclass bound to each string-valued column is stored as plain TEXT while the exact-`str` rule refuses it) and read the first against the repository's own constraint (`pyproject.toml` allows `aiosqlite>=0.19`) and the reviewer's execution on aiosqlite 0.21.0. No executable production line changes; one docstring paragraph, test helpers and one new test do.

| Id | Finding | Ruling | Where amended |
|---|---|---|---|
| R4-1 (Medium) | The spy's `SimpleQueue` premise passed on aiosqlite 0.21.0 while that version's worker, which calls `self._tx.get()`, then died on the spy (`'_QueueSpy' object has no attribute 'get'`), stranding every test that uses the faulty factory | The spy reads through to the original queue, tolerates the non-tuple stop sentinel, and `connect` proves the worker answers (`commit()` under a 5 s timeout) or fails loudly | Section 6 helper paragraph |
| R4-2 (Low) | D6 and the module docstring said the engine refuses "a value the Python validators reject"; SQLite cannot see the Python object type, so a `str` subclass with valid text is stored as that text | The claim is scoped to stored values that meet the validators' rules for the stored text; the exact-`str` rule is `check_and_record`'s (#9); new test #22 pins the boundary | D6, D7, Section 4 module docstring, Section 6 #22 |

**Campaign timing.** The campaign of record (all 28 mutants) runs ONCE, after the final review of this slice, on the tree that is committed; M3 writes its base tree, the four sha256s and the per-mutant results into `DECISIONS.md`. The 28 of 28 run at base tree `f676bef263516c21977bf3f2460e10b8c10794c2` preceded this round and is superseded by it.

## Review round 5 amendments (2026-10-12)

The same reviewer family returned NOT READY with two Medium and two Low findings, all in the test helper's failure path or in claims; the orchestrator confirmed them against the tree and the reviewer's execution (aiosqlite 0.22.1 and a verified 0.21.0 wheel). No executable production line changes; the store docstring changes by one sentence.

| Id | Finding | Ruling | Where amended |
|---|---|---|---|
| R5-1 (Medium) | The liveness guard returned a dead worker on 0.21.0 when the spy had no read-through (the first COMMIT used the read already pending on the original queue; the next never answered) | Two timed round trips; the worker re-reads its queue between items, so the second one detects it | Section 6 helper paragraph |
| R5-2 (Medium) | The guard's cleanup was not bounded: `wait_for(inner.close(), 5)` stayed pending for 11 s with the worker held, because `Connection.close()` awaits the worker's shutdown in a `finally` | Close through a bounded `asyncio.wait` (2 s) and fail without awaiting the cleanup | Section 6 helper paragraph |
| R5-3 (Low) | #22 invented an exact-type rule for the kind column: production's kind rule is membership of the two literals, which a `str` subclass equal to a literal satisfies (the real `EvidenceLink` and `check_and_record` accept it) | The exact-`str` claim is scoped to references and digests; the kind premise of #22 is the opposite; `_refused_by_python` / `_accepted_by_python` test kind membership only | D6, store module docstring, Section 4 copy, #22 |
| R5-4 (Low) | The quantifier sweep still said CHECKs admit "what the validators admit"; the helper's last sentence stated 0.22.1 behaviour without the version | Scoped and qualified | Quantifier sweep, Section 6 helper paragraph |

The reviewer also noted that #22 passes against round 4: it pins existing behaviour (the boundary D6 states), not a repair; it has no mutant by design.

## Verified Against Codebase (2026-10-12, base `712daa05`)

Round 3 additions (Grep / ranged Read of the venv's aiosqlite and the staged worktree files):

```
d:/ProbOS/.venv/Lib/site-packages/aiosqlite-0.22.1.dist-info   installed version 0.22.1
aiosqlite/core.py:32-35   set_result skips a future that is already done (a cancelled COMMIT future stays cancelled)
aiosqlite/core.py:48-75   worker: tx.get(), function(), result posted with call_soon_threadsafe
aiosqlite/core.py:88,90   self._tx = SimpleQueue(); Thread(target=_connection_worker_thread, args=(self._tx,))
aiosqlite/core.py:131,158,167   the only uses of _tx in the package: put_nowait (Grep '_tx' over aiosqlite/*.py)
aiosqlite/core.py:155     function = partial(fn, *args, **kwargs)
aiosqlite/core.py:193     await self._execute(self._conn.commit)
aiosqlite/core.py:199-214 close(): await self._execute(self._conn.close) ... finally: future = self.stop(); await future
aiosqlite/core.py:223,255 _execute(self._conn.execute, ...), _execute(self._conn.executescript, ...)
src/probos/storage/sqlite_factory.py:23-24   conn = await aiosqlite.connect(db_path); return conn (unwrapped)
src/probos/cognitive/repair_evidence_store.py:21-24, :301-311, :349   the sentences and comment R3-2 replaces
src/probos/cognitive/repair_evidence_store.py:65-68, :78-81   every string-valued column is NOT NULL
tests/test_ad1299_s1b_repair_evidence_store.py:175, :178, :181   T1/T4, T3, T4 anchors, each once (Grep)
tests/test_ad1299_s1b_repair_evidence_store.py:634-641   _NUMERIC_VALUES: 6 values; x 4 columns x 2 tables x 2 modes = 96 cases
```

Round 2 additions:

```
d:/ProbOS/.venv/Lib/site-packages/aiosqlite/core.py
  :32-35   set_result guards `if not fut.done()` (a cancelled COMMIT future does not break the worker)
  :150-160 `_execute` puts (future, partial) on `self._tx`, then awaits; the test proxy queues its blocker through it
  :199-214 close: `_execute(self._conn.close)`, then in `finally` `stop()` and `await future` (queued after the COMMIT)
src/probos/storage/sqlite_factory.py:23-24 connect returns the aiosqlite.Connection itself (so `_inner._execute` exists)
src/probos/cognitive/repair_evidence_store.py (round-2 candidate, tree e5eafc0a staged)
  :65, :78  `evidence_ref TEXT NOT NULL,` (twice; R2-2 replaces both)
  :253, :345 `await db.commit()` at the same indentation (start and check_and_record): hence the trailing comment for X2
  :283 `await db.close()` (once: X1 anchor)   :299-306 the R2-1 docstring paragraph   :344 the comment R2-1 removes
src/probos/cognitive/repair_candidate.py:133-140 is_sha256_hex / is_evidence_ref return False for any non-str
tests/test_ad1299_s1b_repair_evidence_store.py (candidate)
  :10 "a failed or cancelled write that commits nothing"   :139 _FaultyConnection   :164-173 park-at-commit commit()
  :181 _FaultyFactory (:195 inner_commit)   :541 #11 inner_commit premise   :555-593 #20   :603-605 value lists
  :625 _validator_cases   :658-688 #21 (:673 foreign_keys == (0,))
git log --all -- src/probos/cognitive/repair_evidence_store.py -> d8af3ac8, a9b2431a (snapshots)
git branch --list --all --contains d8af3ac8 -> (empty)
git ls-files --eol: store module and store test -> i/lf w/crlf; this prompt -> i/lf w/lf
scripts/ad_ceiling.py -> CEILING AD-1327 (no new number needed)
```

Round 1 additions:

```
d:/ProbOS/.venv/Lib/site-packages/aiosqlite/core.py
  :54-75   worker thread: `future, function = tx.get()`; `result = function()` runs every queued call in FIFO order
  :150-160 `_execute`: `self._tx.put_nowait((future, function))` then `return await future` (cancelling the await does not dequeue)
  :191-193 commit -> `_execute(self._conn.commit)`;  :199-214 close -> `_execute(self._conn.close)` queued behind it
tests/test_ad1299_s1b_repair_evidence_store.py (round-1 candidate)
  :133 class _FaultyConnection   :162 class _FaultyFactory   :497 test_cancelled_write_commits_nothing
  :595 assert "differs from its first trusted digest" in warnings[0]   (B3 changes this phrase)
src/probos/cognitive/repair_candidate.py (round-1 candidate)
  :67 _ID_RE   :133-140 is_sha256_hex / is_evidence_ref   :482-484 the A1 sentence
```

```
repair_candidate.py
  :45  from collections.abc import Sequence
  :46  from dataclasses import dataclass
  :59  _SHA256_RE: Final = re.compile(r"[0-9a-f]{64}")
  :61  _ID_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
  :63  EvidenceKind = Literal["gate_receipt", "review_set"]
  :64  EvidenceStatus = Literal["present", "refused", "unavailable"]
  :84  "review_attempt_duplicate",
  :89  REASON_CODES: Final[frozenset[str]] = _BOUND | _UNAVAILABLE | _REFUSED
  :103 def _is_git_object(value: object) -> bool:
  :153 class EvidenceLink:   (:183 current property)
  :192 class ReviewAttestation(Protocol):
  :347 def verify_gate_receipt(candidate, receipt_bytes, *, expected_label=None)
  :409 def _review_reason(candidate, projected, required_reviewers) -> str:
  :417 if any(reviewer == assignee for _, reviewer, assignee, _, _ in projected):
  :428 def bind_reviews(candidate, reviews, *, required_reviewers: int = 1)
  :448 raise ValueError("review_required_invalid")
  :479 return _link("review_set", _review_reason(candidate, projected, required_reviewers), digest, evidence)
tests/test_ad1299_s1a_repair_candidate.py
  :53 bind_reviews,   :211 class _Review (:216 assignee_id: str = "builder")
  :237 def _two_independent_reviews   :433 module import scan (no probos at module scope)
  :881 _EXPECTED_REASON_CODES   :943 last _links_for_every_reason element   :948/:959 == 20
  :1278-1283 assignee_id probe test (still holds; see Section 3)
src/probos/protocols.py:325 class DatabaseConnection(Protocol)   :362 class ConnectionFactory(Protocol)
src/probos/storage/sqlite_factory.py:28 default_factory = SQLiteConnectionFactory()
src/probos/storage/registry.py:57-65 DECLARATION_MODULES includes probos.cognitive.storage_declarations
src/probos/storage/declarations.py:66 StoreCriticality (FEATURE_GATED)  :78 StoreRetention (UNBOUNDED)
  :96 BACKUP_DISPOSITIONS {included, excluded, unknown}  :101 RESTORE_DISPOSITIONS {point-in-time, ...}
  :109 UNOWNED_LIFECYCLE: Final[str] = "unowned"
src/probos/cognitive/storage_declarations.py:141-167 cognitive.elastic-teams entry; :168 closing ")"
src/probos/cognitive/elastic_team_store.py:98-129 triggers  :188 _apply_connection_pragmas  :561 BEGIN IMMEDIATE
src/probos/tools/action_approvals.py:126-149 reference constructor and start()
scripts/check_store_registry.py:12-20 both-direction contract; :303 _tracked_files (git ls-files)
scripts/check_architecture_principles.py:160-165 GATING_CATEGORIES srp-size, layer-import, db-connect, unowned-task
  :187-188 SRP_MAX_BODY_LINES = 500, SRP_MAX_DIRECT_METHODS = 15   :1195 --check
tests/test_layer_boundaries.py:51 cognitive may import knowledge, substrate, mesh (probos.protocols / storage unmapped)
tests/test_ad1256_store_registry.py:488,504 len(registry.declarations()) >= 8 (adding one is safe)
pyproject.toml:181 asyncio_mode = "auto"   :196 addopts = "-n 16 --dist=loadfile"
tests/__init__.py exists; cross-test import precedent tests/test_ad1077_group_chat_coaching.py:22
git ls-files --eol: repair_candidate.py, storage_declarations.py, S1a test -> i/lf w/crlf
```

## Absence Verified (2026-10-12)

```
CLAIM: AT BASE 712daa05, bind_reviews / verify_gate_receipt have no caller outside S1a's module and tests
RUN:   Grep "repair_candidate|bind_reviews|verify_gate_receipt" (whole worktree at base, files)
FOUND: tests/test_layer_boundaries.py, tests/test_ad1299_s1a_repair_candidate.py,
       src/probos/cognitive/repair_candidate.py, prompts/ad-1299-s1a-repair-candidate.md, PROGRESS.md
HOLDS: yes at base (layer test names the module path only; no production caller).
       NOT true of the S1b candidate: assess_candidate_evidence calls both
       (repair_evidence_store.py:349-352 in the round-1 candidate). That is the only new caller,
       and it passes expected_assignee as a required keyword (review round 1, A3).

CLAIM: no repair evidence ledger or first-trusted-digest store exists
RUN:   Grep "repair_evidence|first_trusted|RepairEvidence" over src/probos
FOUND: work_item_steps.py:44,52,56 and workforce.py (OwnedStepsRepairEvidence, owned-step chain repair)
HOLDS: yes (unrelated concept; no digest ledger)

CLAIM: no authority-class vocabulary exists to reuse
RUN:   Grep 'AuthorityClass|authority_class|"maintenance"|"enhancement"' over src/probos
FOUND: maintenance agent type, workforce/watch/operational-status "maintenance" enums only
HOLDS: yes

CLAIM: no existing declaration uses the "unowned" lifecycle literal (so no precedent conflicts)
RUN:   Grep 'lifecycle_owner=' over src/probos  -> 18 hits, all dotted owners
HOLDS: yes; "unowned" is the declared sentinel value (declarations.py:109)
```

## Not verified

- SQLite `GLOB '[^...]'` negated classes and composite-key `FOREIGN KEY` on `WITHOUT ROWID` tables are standard SQLite behaviour but were not executed here; M2 #7/#8/#9 exercise them.
- The mutation table is stated byte-exactly against this prompt's code but not executed (the code does not exist yet).
- Round 1: the new named `CHECK`s were not executed by the Architect (no interpreter under the bridge). Relied on: SQLite documents that `length()` of text counts characters before the first NUL, `CAST(x AS BLOB)` keeps every byte, and a failed named `CHECK` reports `CHECK constraint failed: <name>`. M2 #21 and mutants L8-L13 test exactly these; if any premise fails, stop and report.
- Round 1: the live data directory was checked with Glob for `repair_evidence*` (none); the live database itself was not opened.
- Round 2: no interpreter under the bridge, so none of these was executed by the Architect: that an untyped column refuses `9`, `9.0`, `True` through the `typeof` `CHECK` (the orchestrator's in-memory trial did); SQLite's text rendering of REAL and infinity; that a `CHECK` failure is reported before an immediate foreign-key failure in the same INSERT; and the timing of #20 and the outcomes of X1, X2, T1-T3. Each is asserted by #20/#21 or the mutation run; if any premise fails, stop and report rather than weaken the assertion.
- Round 3: no interpreter under the bridge. Not executed by the Architect: the queue spy (labels, `__self__` of the sqlite3 builtin methods, the tails `blocker, commit` / `blocker, commit, close`, the cancelled queued commit future); the T4 outcome; NaN -> `NOT NULL` for the five string-valued columns `probe_s1b_r3.py` does not loop over (it covers the first table's `evidence_ref`, `first_sha256`, `candidate_digest`; the orchestrator reports all eight reproduced); `True` stored as 1 in `schema_version`; the repeated-cancel observations (taken from the orchestrator's report; the probe source was read, its output was not seen). #20, #21 and the campaign assert each; if a premise fails, stop and report rather than weaken the assertion.

=== BUILDER BRIEFS ===

### Brief M1 — C8 + C9 pure contract (effort: max)

**Prompt:** `prompts/ad-1299-s1b-evidence-completion-ledger.md`, Sections 1-3. Do not read the whole prompt; read those sections by range.
**May touch:** `src/probos/cognitive/repair_candidate.py`; `tests/test_ad1299_s1a_repair_candidate.py` (four edits only); new `tests/test_ad1299_s1b_evidence_completion.py`.
**Import root:** set `PYTHONPATH=<worktree>\src` (PowerShell `$env:PYTHONPATH="$PWD\src"`; Bash `PYTHONPATH="$PWD/src"`) and confirm `python -c "import probos; print(probos.__file__)"` prints a path inside this worktree. Stop if it does not.
**CRLF:** all three existing files are CRLF on disk; edit with single-line anchors; never rewrite whole files.
**Steps:**
1. Apply 1a-1i in order (anchors: `:11-12`, `:45`, `:46`, `:64`, `:84`, `:89`, `:103-104`, `:409-420`, `:428-448`, `:479`, end of file). Do not touch the digest block `:462-478`.
2. Apply Section 3's four edits to the S1a test.
3. Write the 20 tests of Section 2 (import `_Review`, `_pure_candidate` from `tests.test_ad1299_s1a_repair_candidate`; import `bind_reviews` from `probos.cognitive.repair_candidate`).
**Focused run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1299_s1b_evidence_completion.py tests/test_ad1299_s1a_repair_candidate.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`
**Stop and report if:** an S1a test other than the reason-code pin fails; the module-scope import scan fails; any anchor is not found exactly once.
**Report:** files changed, test counts, sha256 of `repair_candidate.py` and both test files.

### Brief M2 — ledger, consumer, declaration, mutation campaign (effort: max)

**Prompt:** Sections 4-6 and the Mutation table. M1 must be committed or present in the tree.
**May touch:** new `src/probos/cognitive/repair_evidence_store.py` (copy Section 4 verbatim); `src/probos/cognitive/storage_declarations.py` (append Section 5 after `:167`); new `tests/test_ad1299_s1b_repair_evidence_store.py`.
**Import root / CRLF:** as M1.
**Steps:**
1. Create the module exactly as Section 4. Append the declaration.
2. Write Section 6's 19 tests. Fixtures `gate`, `repo` and helpers `_candidate`, `_real_receipt`, `_mutate`, `_Review` come from `tests.test_ad1299_s1a_repair_candidate`. Test #14 must cross the real producer in one test.
3. Stage the three files by explicit path (`git add <path>`), then run `d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check` and `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check` (both read tracked files).
4. (Superseded by round 3.) The mutation campaign is a separate milestone run once after the final repair: "Review round 3 campaign of record" (baseline first; `.mutbak` in place; restore in `finally`; count each anchor first; record base tree, the four sha256s, KILLED/INERT/INVALID per mutant).
**Focused run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1299_s1b_repair_evidence_store.py tests/test_ad1299_s1b_evidence_completion.py tests/test_ad1299_s1a_repair_candidate.py tests/test_ad1256_store_registry.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`
**Stop and report if:** a checker fails; a mutant survives (first check that the mutant reaches the behaviour); a SQLite construct in the schema is rejected; you need any `src/` change outside the three files.

### Brief M3 — trackers (effort: high)

**Prompt:** section "Tracking (M3)". **May touch:** `PROGRESS.md` (line 5 only), `DECISIONS.md` (AD-1299 section, append), `docs/development/self-maintenance-architecture.md` (`:430-431`, `:449-456`, the D-B2 section), and `docs/development/roadmap.md` only if it already lists S1a. Grep anchors first; ranged reads only; no code or test edits. Wording: "detects/refuses/records", never "prevents/contains". **Campaign of record:** copy the round-3 campaign report into the `DECISIONS.md` S1b entry: base tree, sha256 of `src/probos/cognitive/repair_candidate.py`, `src/probos/cognitive/repair_evidence_store.py`, `tests/test_ad1299_s1b_evidence_completion.py`, `tests/test_ad1299_s1b_repair_evidence_store.py`, and each mutant's result (C8a-C9d, L1-L15, X1, X2, T1-T4) with its killing test. First recompute the four sha256s on disk; if any differs from the report, stop and report (the campaign is stale). **Run:** `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad1299-s1b` on the staged candidate and repair any cheap failure it reports. No broad gate.
