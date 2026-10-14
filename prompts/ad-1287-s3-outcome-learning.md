# AD-1287 S3 (#1334): outcome learning -- raw Beta parameters per execution profile, learned from AD-1286 attempt outcomes

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-14

**Status:** Ready for mechanical install, then a full-suite diagnostic, then Builders (tests only).
**Base:** `origin/main` `5c77cd50` (S1 + S2a). S2b (`feat/ad1287-s2b-20261014-f431dd0f`) touches none of the files Sections 1-3 edit (`git diff --stat 5c77cd50 feat/ad1287-s2b-20261014-f431dd0f`: its prompt, `profile_drift_recorder.py`, its test, `tests/test_ad1287_slot_qualification.py`), so Sections 1-3 install on `5c77cd50` and on `5c77cd50` + S2b alike. Only the trackers (M4) depend on S2b having merged.
**Dependencies:** AD-1286 (`ElasticTeamStore`, shipped), AD-1287 S1/S2a (shipped). No new AD or BF number: S3 is a slice of AD-1287.
**Estimated tests:** about 30 new (two files), 6 edited S1 pins.
**Closes:** #1334 together with S2b (the issue's last open acceptance line, "Outcome updates are idempotent and store raw Beta parameters with task-class/profile provenance").

## Problem

#1334's acceptance asks for outcome learning against the stable profile identity: "Store outcome learning against the stable profile identity using raw Beta parameters, never a derived mean" and "Outcome updates are idempotent and store raw Beta parameters with task-class/profile provenance" (`logs/architect/issue-1334.md:20,42`). S1 handed this on as O-3 (`prompts/ad-1287-s1-execution-profile-qualification.md:1652`, `DECISIONS.md:82`): key on `execution_profile_ref` and the profile's `task_class`, idempotent by `worker_attempt_id`, integer raw counts, `(2, 2)` prior (`consensus/trust.py:66-67`), `cancelled` not counted, nothing written to `TrustNetwork`, gates nothing.

AD-1286 already records each attempt's terminal outcome write-once (`elastic_team_store.py:806` `record_attempt_outcome`, `:874` `get_attempt_outcome`; `elastic_team.py:151` `TerminalStatus = Literal["succeeded", "failed", "cancelled"]`; `:384-396` `WorkerAttemptOutcome`, `error_code` set exactly when not `succeeded`). The attempt names its exact profile (`elastic_team.py:362` `execution_profile_ref`). Nothing turns those outcomes into per-profile evidence.

The S1 store accepts only an empty file or exactly its fifteen statements (`profile_qualification_store.py:509-522`, `_layout_differences` `:299-304`), so a new table needs an explicit accepted-layout extension (S1 contract "Versioning", `:73`).

## Solution overview

One slice, in the S1 store module, with the chain in-slice:

1. **Table.** `profile_outcomes` (`WITHOUT ROWID`, `schema_version = 1` CHECK, FK to `execution_profiles`), one row per learned attempt: provenance (`worker_attempt_id`, `profile_ref`, `task_class`, AD-1286 `terminal_status` and `error_code`), the profile's observation number, the raw integer `alpha`/`beta` **after** this outcome, and `learned_at_ms`. Three triggers refuse UPDATE, DELETE and replacing INSERT, as S1's do.
2. **Layouts.** `start()` accepts: empty (creates S1 + S3); exactly S1 (adds the four S3 objects in the same `BEGIN IMMEDIATE`, logs INFO); exactly S1 + S3. Anything else, including S1 plus part of S3, is refused with `profile_qualification_layout_mismatch` and no write. `_SCHEMA_STATEMENTS` stays byte-identical to S1.
3. **Write.** `record_profile_outcome(attempt, outcome)`: `succeeded` adds `(1, 0)`, `failed` adds `(0, 1)` to the profile's latest row (or the `(2, 2)` prior); `cancelled` is refused as not evidence. Idempotent by `worker_attempt_id`; a different status, code or profile for a learned attempt is a conflict (first learned wins).
4. **Read.** `get_outcome_state(profile_ref)` returns the raw `(alpha, beta)`, the observation count, the task class and the latest row. `ProfileQualification`, `get_qualification`, `find_slot_candidates` and both slot gates are unchanged and never read outcomes.
5. **Producer.** `learn_attempt_outcome(outcomes, attempts, worker_attempt_id)` reads the attempt and its outcome through a narrow `AttemptOutcomeReader` port (satisfied by `ElasticTeamStore`) and records it: `pending` (no outcome yet), `not_evidence` (`cancelled`) or `recorded`. A sweeper (AD-1288) is the intended caller; nothing calls it.

## Slicing decision

| Rank | Cut | Verdict |
|---|---|---|
| 1 | **One slice in the S1 store module:** table, layout extension, write, read, producer function, chain test. | **Chosen.** Whole chain (AD-1286 outcome -> producer -> table -> read, across restart) in one reviewable unit; no new module, so S1 test #16's owner list (which S2b also edits) is untouched; store imports unchanged (pinned, `tests/test_ad1287_profile_qualification_store.py:964-975`). This slice closes #1334's outcome line. |
| 2 | Same, with the producer in a new `profile_outcome_learning.py`. | Rejected: S1 #16 (`tests/test_ad1287_slot_qualification.py:627`) would need the new module in `_S1_MODULES`, the same lines S2b rewrites (merge conflict for no gain). `admit_qualified_attempt` already sets the precedent of composition functions in the store module. |
| 3 | S3a layout + empty table, then S3b producer. | Rejected: a table with no producer is a half chain. |
| 4 | A separate store and file `profile_outcomes.db`. | Rejected: no edit to S1, but a third copy of `_open`/`_set_wal`/layout check (R-1 grows), a second declaration, no FK or same-transaction profile check, and O-3 says "the same store". |

## Decisions and ranked options

### D1. Where alpha/beta live (Q1)

| Rank | Option | Verdict |
|---|---|---|
| 1 | **A separate read `get_outcome_state(profile_ref) -> ProfileOutcomeState | None`; `ProfileQualification` unchanged.** | **Chosen.** `_assess` decides admission (`:420-440`, used by `get_qualification` `:723-734` and `find_slot_candidates` `:774`); an outcome row failing verification inside it would refuse admission, so learning would gate. Kept apart, a corrupt outcome row raises only from the outcome calls (mutant O18 proves the isolation test bites). No identity changes: `ProfileQualification` is an unhashed dataclass and `ExecutionProfile.content_ref()` is untouched. |
| 2 | An additive field on `ProfileQualification`, filled in `_assess`. | Rejected: makes outcome integrity an admission input. |
| 3 | Field on `CandidateQueryResult`. | Rejected: same coupling for the candidate query. |

"See the Beta parameters in the query evidence" (O-3) is met by `get_outcome_state` beside the S1 query.

### D2. What counts, idempotency, conflicts (Q2)

| Rank | Option | Verdict |
|---|---|---|
| 1 | **`succeeded` -> alpha+1; `failed` (any `error_code`) -> beta+1; `cancelled` -> not evidence (refused by the store, `not_evidence` from the producer); no outcome yet -> `pending`. Key `worker_attempt_id`; same attempt + same profile, status and code -> the stored row, nothing written; anything else -> `profile_outcome_conflict`, first learned wins.** | **Chosen.** O-3 already excludes `cancelled`: AD-1286 uses it for owner-side termination (a cancelled attempt can be superseded, `elastic_team_store.py:757`), not a profile result. First-wins mirrors AD-1286's own write-once outcome (`:807-849`) and S1's `record_evaluation` conflict (`:649-650`). `error_code` is stored, so a later policy can see which failures were infrastructure. |
| 2 | Classify `failed` by `error_code` (infrastructure codes neutral). | Deferred: AD-1286 codes are free-form (`elastic_team.py:38,99-102`) and no production writer exists (Absence A2), so there is no code vocabulary to classify. Changing the rule later is a new schema version (S1 "Versioning"). |
| 3 | Last write wins / count both. | Rejected: needs UPDATE (insert-only store) / breaks idempotency. |

A conflict can only arise from a different or rebuilt AD-1286 store: `worker_attempt_id` derives from spec, session, slot and ordinal (`elastic_team.py:340-347`), not the profile, so two stores can disagree.

### D3. The producer's port (Q3)

| Rank | Option | Verdict |
|---|---|---|
| 1 | **`AttemptOutcomeReader(Protocol)`: `get_attempt`, `get_attempt_outcome` (both on `ElasticTeamStore`, `:767`, `:874`). `learn_attempt_outcome` takes one `worker_attempt_id`; a sweeper calls it, as S2b's recorder is called. Profile ref from the attempt; task class from the store's own verified profile.** | **Chosen.** The attempt row is digest-verified by AD-1286 (`get_attempt` `:767-783`); the profile is content-addressed and verified on read here. The slot's task class equals the profile's whenever admission went through the gate (`slot_refusal`, `task_class` code, S1 mutant P8). |
| 2 | Task class from the team spec's slot. | Rejected: one more cross-store read, and equal by construction on the gated path. |
| 3 | Producer enumerates attempts itself. | Rejected: AD-1286 has no list-all read; enumeration is AD-1288's sweeper. |

Learning does not check that the attempt was admitted through the gate (O-1: no production caller of `record_attempt` yet). It refuses only an unregistered profile (`profile_unknown`). Stated in the docstring.

### D4. Layout extension (Q4)

| Rank | Option | Verdict |
|---|---|---|
| 1 | **Two accepted layouts compared exactly: `_S1_LAYOUT` (S1's fifteen statements) and `_LAYOUT` (S1 + S3, nineteen). Empty -> create all; `found == _S1_LAYOUT` -> run `_OUTCOME_STATEMENTS` in the same `BEGIN IMMEDIATE`; else `_layout_differences` against `_LAYOUT`, refuse on any.** | **Chosen.** No relaxation: each accepted file is still an exact `(type, name) -> sql` match. A partial S3 (table without triggers, an edited trigger) matches neither and is refused, naming the objects. DDL inside `BEGIN IMMEDIATE` is transactional, so a failure mid-extension leaves exactly S1 (test M1-4). An S1 file written by S1 code still opens; once started by S3 code it holds S3 objects and the S1 code refuses it (stated in the docstring and declaration; reversible by moving the file aside; no production file exists, Absence A3). |
| 2 | `CREATE TABLE IF NOT EXISTS` on every start. | Rejected: relaxes D3a; a hand-made table with another definition would be accepted. |
| 3 | `PRAGMA user_version`. | Rejected in S1 D3a (a label, not a check). |

### D5. Registry, backup, pins (Q5)

`StoreDeclaration` has no table field (`storage/declarations.py:127-140`), the path is unchanged, and the module is declared, not baselined (rule 11 `baseline-table-drift` applies only to baselined modules, `scripts/check_store_registry.py:55-57`). Only the declaration's prose changes (Section 2). Backup coverage classifies files by name (`tests/test_ad1265_backup_coverage.py:137-208`): unchanged. Six S1 test lines pin the S1-only layout (Section 3, Hidden pins).

### D6. Failure tiers

Bad input (type, attempt mismatch, `cancelled`, malformed id or reference): propagate `TypeError`/`ValueError` before any read. Unknown profile, conflict, observation bound: `ProfileQualificationConflict`, nothing written. A row that decides or is returned and fails verification: `ProfileQualificationIntegrityError` (propagate). Unknown attempt in AD-1286: `ValueError("profile_outcome_attempt_unknown")`. Layout: as S1.

## Section 0: Event types

None. S3 adds no `EventType`.

### Section 1 -- `src/probos/cognitive/profile_qualification_store.py`

```
<<<<<<< SEARCH
Three ``WITHOUT ROWID`` tables; nine triggers abort every UPDATE, every DELETE and every INSERT that
would replace a row (including through a secondary unique key). The store issues plain INSERTs after
read-then-insert checks inside ``BEGIN IMMEDIATE``. Profiles and evaluation records are stored as
=======
Four ``WITHOUT ROWID`` tables (S1's three and S3's ``profile_outcomes``); twelve triggers abort every UPDATE,
every DELETE and every INSERT that would replace a row (including through a secondary unique key). The store
issues plain INSERTs after read-then-insert checks inside ``BEGIN IMMEDIATE``. Profiles and evaluation records are stored as
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
``start()`` accepts a database holding no schema objects (it creates them) or exactly this module's:
the same tables, indexes and triggers, each stored with the definition this module writes, which
SQLite re-reads every time it opens the file. Anything else is refused, and the store issues no schema
=======
``start()`` accepts a database holding no schema objects (it creates them), exactly the S1 layout (it adds the
S3 outcome table and its three triggers in the same ``BEGIN IMMEDIATE`` and changes no S1 object or row), or
exactly this module's: the same tables, indexes and triggers, each stored with the definition this module
writes, which SQLite re-reads every time it opens the file. Anything else is refused, including an S1 file
holding part of the S3 objects, and the store issues no schema
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
Not wired: nothing constructs or starts this store in production; AD-1288 commission admission is
the intended caller of ``admit_qualified_attempt``. Qualification never grants a tool, data scope,
rank or authority lease.
"""
=======
Outcome learning (S3). ``record_profile_outcome`` learns one AD-1286 attempt outcome against the attempt's
execution profile, keyed by ``worker_attempt_id``: ``succeeded`` adds one to ``alpha``, ``failed`` (any error
code) adds one to ``beta``, and ``cancelled`` is refused as not evidence. Each row stores the profile's task
class, AD-1286's status and error code, the profile's observation number and the raw integer ``(alpha, beta)``
after it, from a ``(2, 2)`` prior; the profile's latest row is its state (``get_outcome_state``). A repeat of
the same attempt with the same profile, status and code returns the stored row and writes nothing; anything
else for a learned attempt is refused, so the first learned stands. Outcomes draw no store sequence number.
No S1 read, status, candidate query or slot check reads them, and this module writes nothing to
``TrustNetwork``: learning gates nothing. Reads verify the outcome rows they use (the profile's latest row;
the attempt's own row on a repeat naming the same profile; a row naming another profile is refused as a
conflict without verification). Any other outcome row is not read, so an edit to it is not detected, and
neither is a deleted latest row nor counts rewritten consistently (R-2, R-3). ``learn_attempt_outcome`` is the
producer: it reads an attempt and its outcome through ``AttemptOutcomeReader`` and records it. It does not
check that the attempt was admitted through the slot boundary. A file this code has started holds the S3
objects, so the S1 code refuses it as a layout mismatch.

Not wired: nothing constructs or starts this store in production; AD-1288 commission admission is
the intended caller of ``admit_qualified_attempt``, and nothing calls ``learn_attempt_outcome``.
Qualification and outcome learning never grant a tool, data scope, rank or authority lease.
"""
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
from pydantic import TypeAdapter

from probos.cognitive.elastic_team import ElasticId, ElasticTeamSpec, WorkerAttempt, WorkerSlot, is_sha256_ref
from probos.cognitive.execution_profile import (
=======
from pydantic import TypeAdapter

from probos.cognitive.elastic_team import (
    ElasticId,
    ElasticTeamSpec,
    OutcomeCode,
    WorkerAttempt,
    WorkerAttemptOutcome,
    WorkerSlot,
    is_sha256_ref,
)
from probos.cognitive.execution_profile import (
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    """CREATE TRIGGER profile_invalidations_no_replace BEFORE INSERT ON profile_invalidations
WHEN EXISTS (SELECT 1 FROM profile_invalidations WHERE seq = NEW.seq
             OR (profile_ref = NEW.profile_ref AND invalidation_id = NEW.invalidation_id))
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
)


def _object_key(statement: str) -> tuple[str, str]:
    """``(type, name)`` of one schema statement, as ``sqlite_master`` names the object it creates."""
    _create, kind, name = statement.split(" ", 3)[:3]
    return kind.lower(), name


_LAYOUT: Final = {_object_key(statement): statement for statement in _SCHEMA_STATEMENTS}
_CATALOG_SQL: Final = "SELECT type, name, sql FROM sqlite_master"
=======
    """CREATE TRIGGER profile_invalidations_no_replace BEFORE INSERT ON profile_invalidations
WHEN EXISTS (SELECT 1 FROM profile_invalidations WHERE seq = NEW.seq
             OR (profile_ref = NEW.profile_ref AND invalidation_id = NEW.invalidation_id))
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
)
# AD-1287 S3: the outcome table and its three triggers, in the same normalised form. ``_SCHEMA_STATEMENTS`` stays
# exactly the S1 layout, so ``start()`` can recognise an S1 file and add these to it.
_OUTCOMES_TABLE: Final = """CREATE TABLE profile_outcomes (
    worker_attempt_id TEXT PRIMARY KEY,
    profile_ref TEXT NOT NULL REFERENCES execution_profiles (profile_ref),
    task_class TEXT NOT NULL,
    observation INTEGER NOT NULL,
    terminal_status TEXT NOT NULL,
    error_code TEXT,
    alpha INTEGER NOT NULL,
    beta INTEGER NOT NULL,
    learned_at_ms INTEGER NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1), -- profile_outcomes
    UNIQUE (profile_ref, observation)
) WITHOUT ROWID"""  # end profile_outcomes
_OUTCOME_STATEMENTS: Final = (
    _OUTCOMES_TABLE,
    """CREATE TRIGGER profile_outcomes_no_update BEFORE UPDATE ON profile_outcomes
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_outcomes_no_delete BEFORE DELETE ON profile_outcomes
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_outcomes_no_replace BEFORE INSERT ON profile_outcomes
WHEN EXISTS (SELECT 1 FROM profile_outcomes WHERE worker_attempt_id = NEW.worker_attempt_id
             OR (profile_ref = NEW.profile_ref AND observation = NEW.observation))
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
)


def _object_key(statement: str) -> tuple[str, str]:
    """``(type, name)`` of one schema statement, as ``sqlite_master`` names the object it creates."""
    _create, kind, name = statement.split(" ", 3)[:3]
    return kind.lower(), name


# The S1 file that start() extends, and the S1+S3 layout it otherwise requires; both are exact matches.
_S1_LAYOUT: Final = {_object_key(statement): statement for statement in _SCHEMA_STATEMENTS}
_LAYOUT: Final = {_object_key(statement): statement for statement in _SCHEMA_STATEMENTS + _OUTCOME_STATEMENTS}
_CATALOG_SQL: Final = "SELECT type, name, sql FROM sqlite_master"
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
_EVALUATION_COLUMNS: Final = "evidence_ref, seq, issued_at_ms, expires_at_ms, schema_version, canonical_json"
_INVALIDATION_COLUMNS: Final = "profile_ref, invalidation_id, seq, reason_code, invalidated_at_ms, schema_version"
# Each table's MAX(seq) is read from its ``seq`` unique index, so the work does not grow with the rows.
=======
_EVALUATION_COLUMNS: Final = "evidence_ref, seq, issued_at_ms, expires_at_ms, schema_version, canonical_json"
_INVALIDATION_COLUMNS: Final = "profile_ref, invalidation_id, seq, reason_code, invalidated_at_ms, schema_version"
# AD-1287 S3: one row per learned attempt outcome, holding the raw Beta parameters after it.
_OUTCOME_COLUMNS: Final = (
    "worker_attempt_id, profile_ref, task_class, observation, terminal_status, error_code, alpha, beta, "
    "learned_at_ms, schema_version"
)
PROFILE_OUTCOME_PRIOR: Final[tuple[int, int]] = (2, 2)  # TrustNetwork's default prior (consensus/trust.py:66-67)
# What each AD-1286 terminal status adds to (alpha, beta). ``cancelled`` is absent: it is not evidence.
_OUTCOME_DELTAS: Final = {"succeeded": (1, 0), "failed": (0, 1)}
PROFILE_OUTCOME_EVIDENCE: Final = frozenset(_OUTCOME_DELTAS)
_OUTCOME_CODE: Final = TypeAdapter(OutcomeCode)
# Each table's MAX(seq) is read from its ``seq`` unique index, so the work does not grow with the rows.
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    candidates: tuple[ProfileQualification, ...]
    examined: int
    complete: bool
    next_after: str | None
=======
    candidates: tuple[ProfileQualification, ...]
    examined: int
    complete: bool
    next_after: str | None


@dataclass(frozen=True)
class RecordedProfileOutcome:
    """One AD-1286 attempt outcome learned against its execution profile (AD-1287 S3): provenance and the raw
    Beta parameters after it. Evidence, never a grant."""

    worker_attempt_id: str
    profile_ref: str
    task_class: str  # the profile's own task class
    terminal_status: str  # "succeeded" or "failed"; a cancelled attempt is not learned
    error_code: str | None  # AD-1286's code; None exactly when "succeeded"
    observation: int  # 1 for the profile's first learned outcome, then one more each time
    alpha: int  # 2 + successes learned up to and including this one
    beta: int  # 2 + failures learned up to and including this one
    learned_at_ms: int


@dataclass(frozen=True)
class ProfileOutcomeState:
    """A profile's raw Beta parameters from the outcomes learned so far: ``(2, 2)``, no observations and
    ``latest=None`` before any. Reported for the process owner; nothing in this module admits or refuses by it."""

    profile_ref: str
    task_class: str
    alpha: int
    beta: int
    observations: int
    latest: RecordedProfileOutcome | None


@dataclass(frozen=True)
class ProfileOutcomeLearning:
    """What ``learn_attempt_outcome`` did for one attempt."""

    worker_attempt_id: str
    disposition: str  # "pending" (no outcome yet), "not_evidence" (cancelled) or "recorded"
    recorded: RecordedProfileOutcome | None  # the stored row when "recorded", the same row on every repeat
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    async def record_attempt(self, attempt: WorkerAttempt) -> WorkerAttempt: ...


def _checked_now_ms(clock: Callable[[], float]) -> int:
=======
    async def record_attempt(self, attempt: WorkerAttempt) -> WorkerAttempt: ...


class AttemptOutcomeReader(Protocol):
    """The two ``ElasticTeamStore`` reads outcome learning uses; ``ElasticTeamStore`` satisfies it."""

    async def get_attempt(self, worker_attempt_id: str) -> WorkerAttempt | None: ...

    async def get_attempt_outcome(self, worker_attempt_id: str) -> WorkerAttemptOutcome | None: ...


class ProfileOutcomeRecorder(Protocol):
    """The ``ProfileQualificationStore`` write outcome learning uses; ``ProfileQualificationStore`` satisfies it."""

    async def record_profile_outcome(
        self, attempt: WorkerAttempt, outcome: WorkerAttemptOutcome,
    ) -> RecordedProfileOutcome: ...


def _checked_now_ms(clock: Callable[[], float]) -> int:
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    except ValueError:
        return False
    return True


def _is_stamp(value: object) -> bool:
=======
    except ValueError:
        return False
    return True


def _is_outcome_code(value: object) -> bool:
    """An AD-1286 outcome code (``OutcomeCode``)."""
    try:
        _OUTCOME_CODE.validate_python(value)
    except ValueError:
        return False
    return True


def _is_stamp(value: object) -> bool:
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    return RecordedInvalidation(profile_ref, invalidation_id, reason_code, seq, invalidated_at)


async def _next_seq(db: Any) -> int:
=======
    return RecordedInvalidation(profile_ref, invalidation_id, reason_code, seq, invalidated_at)


def _verified_outcome_row(row: Any, profile_ref: str, profile: ExecutionProfile) -> RecordedProfileOutcome:
    """Verify one ``_OUTCOME_COLUMNS`` row of ``profile``: provenance, AD-1286 status and code, observation number,
    raw counts consistent with it, stamp and schema version. Counts or stamps rewritten consistently are not
    detected (R-3)."""
    attempt_id, row_profile_ref, task_class, observation, status, error_code, alpha, beta, learned_at, version = row
    delta = _OUTCOME_DELTAS.get(status) if type(status) is str else None
    verified = (
        _is_elastic_id(attempt_id)
        and row_profile_ref == profile_ref
        and task_class == profile.task_class
        and delta is not None
        and (error_code is None) == (status == "succeeded")
        and (error_code is None or _is_outcome_code(error_code))
        and _is_seq(observation)
        and type(alpha) is int
        and type(beta) is int
        and alpha >= PROFILE_OUTCOME_PRIOR[0] + delta[0]
        and beta >= PROFILE_OUTCOME_PRIOR[1] + delta[1]
        and alpha + beta == sum(PROFILE_OUTCOME_PRIOR) + observation
        and _is_stamp(learned_at)
        and type(version) is int
        and version == PROFILE_QUALIFICATION_SCHEMA_VERSION
    )
    if not verified:
        raise _integrity("profile outcome", attempt_id)
    return RecordedProfileOutcome(
        attempt_id, profile_ref, task_class, status, error_code, observation, alpha, beta, learned_at,
    )


async def _latest_outcome(db: Any, profile_ref: str, profile: ExecutionProfile) -> RecordedProfileOutcome | None:
    """The profile's latest learned outcome (highest observation), verified, or None before any."""
    rows = await _query(
        db,
        f"SELECT {_OUTCOME_COLUMNS} FROM profile_outcomes WHERE profile_ref = ? ORDER BY observation DESC LIMIT 1",
        (profile_ref,),
    )
    return _verified_outcome_row(rows[0], profile_ref, profile) if rows else None


async def _next_seq(db: Any) -> int:
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
        get_qualification(profile_ref) -> ProfileQualification | None -- satisfies ProfileQualificationReader
        find_slot_candidates(slot, *, limit, after) -> CandidateQueryResult -- bounded, deterministic

=======
        get_qualification(profile_ref) -> ProfileQualification | None -- satisfies ProfileQualificationReader
        find_slot_candidates(slot, *, limit, after) -> CandidateQueryResult -- bounded, deterministic
        record_profile_outcome(attempt, outcome) -> RecordedProfileOutcome -- S3; idempotent by worker_attempt_id
        get_outcome_state(profile_ref) -> ProfileOutcomeState | None -- S3; raw (alpha, beta), gates nothing

>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
        Accepts a database holding no schema objects, which it gives this module's layout, or exactly this
        module's layout. Any other file is refused inside one ``BEGIN IMMEDIATE``; the store issues no schema
=======
        Accepts a database holding no schema objects, which it gives this module's layout; exactly the S1
        layout, to which it adds the S3 outcome objects in the same transaction; or exactly this module's
        layout. Any other file is refused inside one ``BEGIN IMMEDIATE``; the store issues no schema
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
            async with self._open() as db:
                await db.execute("BEGIN IMMEDIATE")
                found = _schema_objects(await _query(db, _CATALOG_SQL, ()))
                if not found:
                    for statement in _SCHEMA_STATEMENTS:
                        await db.execute(statement)
                else:
=======
            added_outcomes = False
            async with self._open() as db:
                await db.execute("BEGIN IMMEDIATE")
                found = _schema_objects(await _query(db, _CATALOG_SQL, ()))
                if not found:
                    for statement in _SCHEMA_STATEMENTS + _OUTCOME_STATEMENTS:
                        await db.execute(statement)
                elif found == _S1_LAYOUT:  # exactly an S1 file: add the S3 objects in this same transaction
                    for statement in _OUTCOME_STATEMENTS:
                        await db.execute(statement)
                    added_outcomes = True
                else:
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
        logger.info(
            "AD-1287: ProfileQualificationStore started (db=%s); profiles, evaluations and invalidations "
            "are insert-only",
            self._db_path,
        )
=======
        if added_outcomes:
            logger.info(
                "AD-1287: added the S3 outcome table to the S1 file %s and changed no S1 object or row; the S1 "
                "code now refuses this file as a layout mismatch",
                self._db_path,
            )
        logger.info(
            "AD-1287: ProfileQualificationStore started (db=%s); profiles, evaluations, invalidations and "
            "learned outcomes are insert-only",
            self._db_path,
        )
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    @contextlib.asynccontextmanager
    async def _operation(self) -> AsyncIterator[tuple[Any, int]]:
        """The frame of each of the six data methods: hold the lock, refuse when stopped, take "now", open one
=======
    @contextlib.asynccontextmanager
    async def _operation(self) -> AsyncIterator[tuple[Any, int]]:
        """The frame of each of the eight data methods: hold the lock, refuse when stopped, take "now", open one
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
            complete = examined == len(rows)
            next_after = None if complete else rows[examined - 1][0]
        return CandidateQueryResult(tuple(candidates), examined, complete, next_after)
=======
            complete = examined == len(rows)
            next_after = None if complete else rows[examined - 1][0]
        return CandidateQueryResult(tuple(candidates), examined, complete, next_after)

    async def record_profile_outcome(
        self, attempt: WorkerAttempt, outcome: WorkerAttemptOutcome,
    ) -> RecordedProfileOutcome:
        """Learn ``outcome`` of ``attempt`` against the attempt's execution profile, once (AD-1287 S3).

        ``succeeded`` adds one to ``alpha`` and ``failed`` one to ``beta``, from the profile's latest learned row
        or the ``(2, 2)`` prior. The new row stores the profile's task class, AD-1286's status and error code, the
        next observation number and the raw ``(alpha, beta)`` after it. Idempotent: the same attempt with the same
        profile, status and error code returns the stored row (its first ``learned_at_ms``) and writes nothing.
        Evidence only: no S1 read, status, candidate query or slot check reads these rows.

        Raises:
            TypeError: ``profile_outcome_type_invalid``.
            ValueError: (``pydantic.ValidationError``) either argument no longer validates;
                ``profile_outcome_attempt_mismatch`` when they name different attempts;
                ``profile_outcome_not_evidence`` for ``cancelled``. Nothing is read or written.
            ProfileQualificationConflict: ``profile_unknown``; ``profile_outcome_conflict`` (this attempt was
                learned with another profile, status or error code; the first learned stands); or
                ``profile_sequence_exhausted``. Nothing is written.
            ProfileQualificationIntegrityError: a row that decides the write does not verify.
        """
        if type(attempt) is not WorkerAttempt or type(outcome) is not WorkerAttemptOutcome:
            raise TypeError("profile_outcome_type_invalid")
        attempt = WorkerAttempt.model_validate(attempt)  # a model_copy(update=...) skips validation
        outcome = WorkerAttemptOutcome.model_validate(outcome)
        if attempt.worker_attempt_id != outcome.worker_attempt_id:
            raise ValueError("profile_outcome_attempt_mismatch")
        delta = _OUTCOME_DELTAS.get(outcome.terminal_status)
        if delta is None:
            raise ValueError("profile_outcome_not_evidence")
        profile_ref = attempt.execution_profile_ref
        async with self._operation() as (db, now_ms):
            await db.execute("BEGIN IMMEDIATE")
            profile = await _load_profile(db, profile_ref)
            if profile is None:
                raise ProfileQualificationConflict("profile_unknown")
            rows = await _query(
                db,
                f"SELECT {_OUTCOME_COLUMNS} FROM profile_outcomes WHERE worker_attempt_id = ?",
                (attempt.worker_attempt_id,),
            )
            if rows:
                if rows[0][1] != profile_ref:
                    raise ProfileQualificationConflict("profile_outcome_conflict")
                learned = _verified_outcome_row(rows[0], profile_ref, profile)
                if (learned.terminal_status, learned.error_code) != (outcome.terminal_status, outcome.error_code):
                    raise ProfileQualificationConflict("profile_outcome_conflict")
                await db.commit()
                return learned
            latest = await _latest_outcome(db, profile_ref, profile)
            if latest is None:
                alpha, beta, observation = PROFILE_OUTCOME_PRIOR[0], PROFILE_OUTCOME_PRIOR[1], 0
            else:
                alpha, beta, observation = latest.alpha, latest.beta, latest.observation
            if observation == _MAX_SEQ:
                raise ProfileQualificationConflict("profile_sequence_exhausted")
            recorded = RecordedProfileOutcome(
                attempt.worker_attempt_id,
                profile_ref,
                profile.task_class,
                outcome.terminal_status,
                outcome.error_code,
                observation + 1,
                alpha + delta[0],
                beta + delta[1],
                now_ms,
            )
            await db.execute(
                f"INSERT INTO profile_outcomes ({_OUTCOME_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    recorded.worker_attempt_id,
                    recorded.profile_ref,
                    recorded.task_class,
                    recorded.observation,
                    recorded.terminal_status,
                    recorded.error_code,
                    recorded.alpha,
                    recorded.beta,
                    recorded.learned_at_ms,
                    PROFILE_QUALIFICATION_SCHEMA_VERSION,
                ),
            )
            await db.commit()  # not shielded: a COMMIT queued before a cancel may still run (N2)
        logger.info(
            "AD-1287: learned %s of worker attempt %s for execution profile %s (observation %d, alpha %d, beta %d); "
            "evidence only, it gates nothing",
            recorded.terminal_status,
            recorded.worker_attempt_id,
            recorded.profile_ref,
            recorded.observation,
            recorded.alpha,
            recorded.beta,
        )
        return recorded

    async def get_outcome_state(self, profile_ref: str) -> ProfileOutcomeState | None:
        """``profile_ref``'s raw Beta parameters from the outcomes learned so far, or None when it is not registered.

        ``(2, 2)`` with no observations before any outcome is learned. Reported for the process owner; nothing in
        this module admits or refuses a profile by it.

        Raises:
            ValueError: ``execution_profile_ref_invalid`` for a malformed reference.
            ProfileQualificationIntegrityError: the profile row or its latest outcome row does not verify.
        """
        if not is_sha256_ref(profile_ref):
            raise ValueError("execution_profile_ref_invalid")
        async with self._operation() as (db, _now_ms):
            profile = await _load_profile(db, profile_ref)
            if profile is None:
                return None
            latest = await _latest_outcome(db, profile_ref, profile)
        if latest is None:
            return ProfileOutcomeState(profile_ref, profile.task_class, *PROFILE_OUTCOME_PRIOR, 0, None)
        return ProfileOutcomeState(
            profile_ref, profile.task_class, latest.alpha, latest.beta, latest.observation, latest,
        )
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
            refused,
        )
        raise
    return await teams.record_attempt(attempt)
=======
            refused,
        )
        raise
    return await teams.record_attempt(attempt)


async def learn_attempt_outcome(
    outcomes: ProfileOutcomeRecorder, attempts: AttemptOutcomeReader, worker_attempt_id: str,
) -> ProfileOutcomeLearning:
    """Learn one AD-1286 attempt's terminal outcome against its execution profile (the AD-1287 S3 producer).

    Reads the attempt, then its outcome, through ``attempts``. No outcome yet: ``pending``, nothing written.
    ``cancelled``: ``not_evidence``, nothing written. Otherwise ``outcomes.record_profile_outcome`` records it:
    ``recorded``, with the stored row, which is the same row on every repeat. Safe to call again for the same
    attempt. It does not check that the attempt was admitted through the slot boundary; learning gates nothing.

    Raises:
        ValueError: ``profile_outcome_attempt_invalid`` for a malformed id (nothing is read);
            ``profile_outcome_attempt_unknown`` when ``attempts`` holds no such attempt;
            ``profile_outcome_evidence_mismatch`` when ``attempts`` answers for another attempt.
        What ``attempts`` or ``outcomes.record_profile_outcome`` raises, unchanged.
    """
    if not _is_elastic_id(worker_attempt_id):
        raise ValueError("profile_outcome_attempt_invalid")
    attempt = await attempts.get_attempt(worker_attempt_id)
    if attempt is None:
        raise ValueError("profile_outcome_attempt_unknown")
    if attempt.worker_attempt_id != worker_attempt_id:
        raise ValueError("profile_outcome_evidence_mismatch")
    outcome = await attempts.get_attempt_outcome(worker_attempt_id)
    if outcome is None:
        return ProfileOutcomeLearning(worker_attempt_id, "pending", None)
    if outcome.worker_attempt_id != worker_attempt_id:
        raise ValueError("profile_outcome_evidence_mismatch")
    if outcome.terminal_status not in PROFILE_OUTCOME_EVIDENCE:
        logger.info(
            "AD-1287: worker attempt %s ended %s; not learned as evidence for execution profile %s",
            worker_attempt_id,
            outcome.terminal_status,
            attempt.execution_profile_ref,
        )
        return ProfileOutcomeLearning(worker_attempt_id, "not_evidence", None)
    recorded = await outcomes.record_profile_outcome(attempt, outcome)
    return ProfileOutcomeLearning(worker_attempt_id, "recorded", recorded)
>>>>>>> REPLACE
```

### Section 2 -- `src/probos/cognitive/storage_declarations.py`

```
<<<<<<< SEARCH
            "Insert-only by design: nine triggers abort every UPDATE, every DELETE and every replacing "
            "INSERT on the three WITHOUT ROWID tables, and the module has no delete path. Growth is one row "
            "per registered profile, one per evaluation run and one per invalidation; this slice does not "
            "bound evaluation runs per profile. Archival belongs to a later lifecycle slice; this one adds none."
=======
            "Insert-only by design: twelve triggers abort every UPDATE, every DELETE and every replacing "
            "INSERT on the four WITHOUT ROWID tables, and the module has no delete path. Growth is one row "
            "per registered profile, one per evaluation run, one per invalidation and one per learned attempt "
            "outcome (S3); no retention or lifecycle cap bounds evaluation runs or learned outcomes per profile "
            "(only the 2**53 - 1 sequence limit does). Archival belongs to a "
            "later lifecycle slice; S1 and S3 add none."
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
            "admission calls admit_qualified_attempt, so a default runtime never creates the file "
            "(lifecycle_owner is the 'unowned' sentinel). start() refuses a file whose schema is not exactly "
            "this store's and issues no schema or data write to it. Each row the store uses to decide or return a result is re-verified and one that "
            "does not verify is refused; a missing row, or a store stamp rewritten within range, is not "
            "detected, and evaluators are not authenticated."
=======
            "admission calls admit_current_qualified_attempt, so a default runtime never creates the file "
            "(lifecycle_owner is the 'unowned' sentinel). start() accepts an empty file, exactly the S1 layout "
            "(to which it adds the S3 outcome table and triggers in the same transaction) or exactly the S1+S3 "
            "layout, refuses any other file and issues no schema or data write to it; the S1 code refuses a file "
            "the S3 code has started. Each row the store uses to decide or return a result is re-verified and one that "
            "does not verify is refused, except that a learned attempt whose stored profile differs from the one "
            "named is refused as a conflict without verifying that row; a missing row, or a store stamp rewritten "
            "within range, is not detected, and evaluators are not authenticated."
>>>>>>> REPLACE
```

### Section 3 -- `tests/test_ad1287_profile_qualification_store.py`

The S1 tests pin the S1-only layout in six lines (hidden pins H1-H4). Each edit widens the pinned layout to S1+S3 and says why inline; none is deleted. `_TABLES` stays S1's three, since the immutability, schema-version and raw-insert tests that use it are about S1 tables.

```
<<<<<<< SEARCH
    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        definitions = dict(raw.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'"))

    assert set(definitions) == set(_TABLES)
=======
    with contextlib.closing(sqlite3.connect(db_path)) as raw:
        definitions = dict(raw.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'"))

    assert set(definitions) == {*_TABLES, "profile_outcomes"}  # AD-1287 S3 adds the outcome table
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
        objects = _catalog(db_path)
        ours = sorted(kind for kind, name, _table, _sql in objects if not name.startswith("sqlite_"))
        assert ours == ["index"] * 3 + ["table"] * 3 + ["trigger"] * 9  # premise: the fifteen objects of this layout
=======
        objects = _catalog(db_path)
        ours = sorted(kind for kind, name, _table, _sql in objects if not name.startswith("sqlite_"))
        assert ours == ["index"] * 3 + ["table"] * 4 + ["trigger"] * 12  # premise: the S1+S3 layout's nineteen objects
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    assert checker.detect_tables(each_named) == tables

    assert checker.detect_tables(Path(store_module.__file__).read_text(encoding="utf-8")) == tables
=======
    assert checker.detect_tables(each_named) == tables

    # AD-1287 S3 binds its table to its own name too, so the detector sees four
    assert checker.detect_tables(Path(store_module.__file__).read_text(encoding="utf-8")) == (*tables, "profile_outcomes")
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
_FIFTEEN = ["index"] * 3 + ["table"] * 3 + ["trigger"] * 9  # the kinds of the fifteen objects of this layout (#35)


def _own_kinds(path: Path) -> list[str]:
=======
# the kinds of the S1+S3 layout's nineteen objects (#35; AD-1287 S3 adds a table and three triggers)
_NINETEEN = ["index"] * 3 + ["table"] * 4 + ["trigger"] * 12


def _own_kinds(path: Path) -> list[str]:
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    await store.start()  # a later start, on the same instance
    assert await store.get_profile(ref) is None  # started: a data call is served
    assert _own_kinds(db_path) == _FIFTEEN  # and the whole layout is there
=======
    await store.start()  # a later start, on the same instance
    assert await store.get_profile(ref) is None  # started: a data call is served
    assert _own_kinds(db_path) == _NINETEEN  # and the whole layout is there
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    assert await second.get_profile(ref) is None
    assert _own_kinds(db_path) == _FIFTEEN  # the layout was created once, and whole
    assert _journal_mode(db_path) == "wal"
=======
    assert await second.get_profile(ref) is None
    assert _own_kinds(db_path) == _NINETEEN  # the layout was created once, and whole
    assert _journal_mode(db_path) == "wal"
>>>>>>> REPLACE
```

## Section 4 (orchestrator addendum, 2026-10-14): the S1 pins the Architect's H10 row missed

H10 below said the S1 store test's data-method lists "enumerate S1's six" and stay unchanged. They do not all: `test_unstarted_and_stopped_store_raise_unavailable` asserts that the store's whole public async surface equals the keys of `_data_calls`, so the two new public methods (`record_profile_outcome`, `get_outcome_state`) fail it (found by the full-suite diagnostic). Widening `_data_calls` to the eight methods fixes it and gives the two new methods the stopped/unstarted, clock-once and foreign-keys coverage the other six have; two tests derived from `_data_calls` then need their local lists extended. Applied by the orchestrator before the Builders, with the diagnostic and the focused run as evidence.

### Section 4 -- `tests/test_ad1287_profile_qualification_store.py`

```
<<<<<<< SEARCH
from probos.cognitive.elastic_team import AuthorityCeiling, WorkerSlot, canonicalize_projection
=======
from probos.cognitive.elastic_team import (
    AuthorityCeiling,
    WorkerAttemptOutcome,
    WorkerSlot,
    canonicalize_projection,
)
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
from tests.test_ad1286_elastic_team_contract import _review_slot
=======
from tests.test_ad1286_elastic_team_contract import _attempt, _review_slot
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    """The six data methods, with arguments well formed in every respect but the store's state."""
    slot = WorkerSlot.model_validate(_review_slot())
    return {
=======
    """The eight data methods (S1's six, then S3's two), with arguments well formed in every respect but the store's state."""
    slot = WorkerSlot.model_validate(_review_slot())
    attempt = _attempt(execution_profile_ref=profile_ref)
    outcome = WorkerAttemptOutcome(
        worker_attempt_id=attempt.worker_attempt_id, terminal_status="succeeded", error_code=None, recorded_at=2000.0,
    )
    return {
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
        "find_slot_candidates": lambda store: store.find_slot_candidates(slot),
    }
=======
        "find_slot_candidates": lambda store: store.find_slot_candidates(slot),
        "record_profile_outcome": lambda store: store.record_profile_outcome(attempt, outcome),
        "get_outcome_state": lambda store: store.get_outcome_state(profile_ref),
    }
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    # the list under test is the store's whole public async surface, so a seventh data method cannot slip past it
=======
    # the list under test is the store's whole public async surface, so a ninth data method cannot slip past it
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
        "find_slot_candidates": (lambda s: s.find_slot_candidates({}), TypeError, "profile_slot_type_invalid"),
    }
=======
        "find_slot_candidates": (lambda s: s.find_slot_candidates({}), TypeError, "profile_slot_type_invalid"),
        "record_profile_outcome": (
            lambda s: s.record_profile_outcome({}, {}), TypeError, "profile_outcome_type_invalid",
        ),
        "get_outcome_state": (lambda s: s.get_outcome_state("x"), ValueError, "execution_profile_ref_invalid"),
    }
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
    assert len(seen) == 8  # premise: start on a new file, start on a populated one and the six data methods
=======
    assert len(seen) == 10  # premise: start on a new file, start on a populated one and the eight data methods
>>>>>>> REPLACE
```

## Tests (written by Builders against the installed source; tests only)

Every test asserts its own premise; fakes are `_Fake*` classes; each refusal has a negative control (the accepted neighbour). Copy the helpers you need (`_Clock`, `_profile_model`, `_evaluation`, `_ProxyFactory`, `_catalog`, `_run_script`, `_journal_mode`, `_file_sha256`) from `tests/test_ad1287_profile_qualification_store.py`, and the two-store world from `tests/test_ad1287_slot_qualification.py` (`_World`, ~line 90). Do not import from another test module. Real stores in `tmp_path` only. Never edit `src/`.

### M1 `tests/test_ad1287_s3_profile_outcomes.py` (store)

1. `test_fresh_file_holds_the_s1_and_s3_layout`: 19 own objects; each S3 object's stored `sql` equals its `_OUTCOME_STATEMENTS` text and each S1 object's equals its `_SCHEMA_STATEMENTS` text; restart on a new instance accepted.
2. `test_an_s1_file_is_extended_once_and_keeps_every_s1_object_and_row`: an S1 file built raw from `_SCHEMA_STATEMENTS` plus one profile and one passing evaluation inserted raw with canonical text (premise: 15 objects). Start: the 15 S1 catalog rows `(type, name, tbl_name, sql)` and every S1 table row are unchanged; 19 objects; one INFO "added the S3 outcome table". `get_qualification` reports the raw evaluation; learning works. Second start on a new instance: no "added" INFO.
3. `test_partial_s3_objects_are_refused_and_the_file_is_left_unchanged[table_only, table_and_two_triggers, edited_outcome_trigger, outcome_table_without_check]`: raw S1 layout plus those objects, in rollback mode. `profile_qualification_layout_mismatch`; one ERROR naming a missing or changed S3 object; file sha256 and catalog unchanged. Negative control: S1 plus all four S3 objects, raw, is accepted.
4. `test_an_extension_failing_midway_leaves_the_s1_layout_and_a_later_start_extends_it`: `_ProxyFactory` fails after `CREATE TRIGGER profile_outcomes_no_delete `; the start raises; the store stays stopped; the catalog equals the S1 15; a later start reaches 19.
5. `test_two_concurrent_starts_on_an_s1_file_both_succeed`: 19 objects once, WAL, both serve.
6. `test_succeeded_adds_alpha_and_failed_adds_beta_from_the_2_2_prior`: succeeded, failed, succeeded give `(3,2)`, `(3,3)`, `(4,3)` and observations 1, 2, 3; `task_class`, `error_code` and `profile_ref` are stored; `get_outcome_state` equals the latest.
7. `test_unobserved_profile_reports_the_prior_and_unknown_reports_none`: a registered profile gives `(2, 2, 0, None)`; an unknown one gives None; a malformed reference gives `execution_profile_ref_invalid`.
8. `test_learning_is_idempotent_and_survives_restart`: a repeat (clock advanced) returns the identical row (first `learned_at_ms`) with one row stored. After a restart, the repeat returns the same row and the state is unchanged.
9. `test_a_different_outcome_or_profile_for_a_learned_attempt_is_refused[other_status, other_error_code, other_profile]`: `profile_outcome_conflict`, row count unchanged, first row stands. `other_profile` uses a second registered profile and the same `worker_attempt_id`.
10. `test_bad_input_is_refused_before_any_read[wrong_type, attempt_mismatch, cancelled]`: the codes; the clock is never read. Also `test_an_unregistered_profile_is_refused_and_nothing_written` (`profile_unknown`).
11. `test_tampered_outcome_rows_are_integrity_errors[sum, task_class, succeeded_with_code, failed_without_code, bad_code, learned_at_negative, observation_zero, status_cancelled, alpha_below_own_count]`: a raw new latest row (the triggers allow new rows) makes `get_outcome_state` and the next `record_profile_outcome` raise `profile_qualification_integrity`. Negative control: a consistent raw row is accepted.
12. `test_the_database_refuses_update_delete_and_replace_of_outcomes[update, delete, replace_by_attempt, replace_by_observation]`.
13. `test_the_outcome_schema_version_check_refuses_other_versions`.
14. `test_the_observation_bound_is_refused_before_any_write`: a raw row with `observation = 2**53 - 1` (the test's own literal) leads to `profile_sequence_exhausted` and an unchanged row count.
15. `test_learning_gates_nothing`: (a) a profile `qualified` with only failures learned is still `qualified`, is in `find_slot_candidates` and is admitted by `admit_qualified_attempt`; (b) an unevaluated profile with successes learned is still refused; (c) after a tampered latest outcome row, `get_qualification`, `find_slot_candidates` and `check_slot_qualification` return what they returned before, at a fixed clock, while `get_outcome_state` raises.
16. `test_outcome_calls_read_the_clock_once`: one read per served call, none for refused input.
17. `test_outcome_result_types_carry_no_authority_fields`: the S1 authority-word check over `RecordedProfileOutcome`, `ProfileOutcomeState` and `ProfileOutcomeLearning`, with a negative control.

### M2 `tests/test_ad1287_s3_outcome_learning.py` (producer and chain)

1. `test_pending_when_no_outcome_and_nothing_written` (`_FakeAttempts`, `_FakeOutcomes` recording calls).
2. `test_cancelled_is_not_evidence_and_nothing_written`.
3. `test_malformed_and_unknown_attempts_are_refused[malformed, unknown]`: `profile_outcome_attempt_invalid` with no reader call; `profile_outcome_attempt_unknown`.
4. `test_a_reader_answering_for_another_attempt_is_refused[attempt, outcome]`: `profile_outcome_evidence_mismatch`, nothing recorded.
5. `test_recorded_returns_the_stored_row_on_every_repeat`.
6. `test_chain_admit_record_learn_restart_replay` (**the seam test**): real `ElasticTeamStore` and real `ProfileQualificationStore` in `tmp_path`. Register a profile and record a passing evaluation; put the spec. Admit three attempts through `admit_qualified_attempt` (premise: an unqualified profile is refused). Record AD-1286 outcomes succeeded, failed, cancelled with `record_attempt_outcome`, then learn each: `recorded (3,2)`, `recorded (3,3)`, `not_evidence`. Stop both stores, start new instances on the same files. `get_outcome_state` gives `(3, 3)`, 2 observations, the profile's `task_class` and `profile_ref`. Replaying all three learns gives the same dispositions and rows, and the row count is unchanged. Only the two store files (and their `-wal`/`-shm`) exist in `tmp_path`.
7. `test_the_real_stores_satisfy_the_ports`: `inspect.signature` parity of `ElasticTeamStore.get_attempt`/`get_attempt_outcome` with `AttemptOutcomeReader`, and of `ProfileQualificationStore.record_profile_outcome` with `ProfileOutcomeRecorder`.

Focused gate (each milestone): `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1287_s3_profile_outcomes.py tests/test_ad1287_s3_outcome_learning.py tests/test_ad1287_profile_qualification_store.py tests/test_ad1287_slot_qualification.py tests/test_ad1287_s2a_profile_currency.py tests/test_ad1256_store_registry.py -q -n 0`. Broad gate once, by the orchestrator, after review: `scripts/run_test_gate.py --label ad1287-s3 --receipt logs/gates/ad1287-s3.receipt.json`.

## Mutation campaign of record

Run once (M3), on the frozen tree after M1 and M2. Record the base commit, tree and sha256 (CRLF working tree) of `profile_qualification_store.py`, `storage_declarations.py` and the three test files. Every anchor occurs exactly once in `src/probos/cognitive/profile_qualification_store.py`. Rows `R-*` re-run S1 rows whose code or killing test S3 changes. The other S1 rows (P1-P13; S1-S17, S21-S25, S27-S28, S35, S40-S47) stay valid on S1's record: their anchor lines, the functions holding them and their killing tests are byte-unchanged, and S3's new paths are reached only through the two new methods and the S1-file branch of `start()`. If any of those lines differs on the build tree, re-run that row too.

| Id | File | Anchor | Replacement | Killer |
|---|---|---|---|---|
| O1 | `src/probos/cognitive/profile_qualification_store.py` | `                elif found == _S1_LAYOUT:  # exactly an S1 file: add the S3 objects in this same transaction` | `                elif False:  # exactly an S1 file: add the S3 objects in this same transaction` | `tests/test_ad1287_s3_profile_outcomes.py::test_an_s1_file_is_extended_once_and_keeps_every_s1_object_and_row` |
| O2 | `src/probos/cognitive/profile_qualification_store.py` | `                    for statement in _SCHEMA_STATEMENTS + _OUTCOME_STATEMENTS:` | `                    for statement in _SCHEMA_STATEMENTS:` | `tests/test_ad1287_s3_profile_outcomes.py::test_fresh_file_holds_the_s1_and_s3_layout` |
| O3 | `src/probos/cognitive/profile_qualification_store.py` | `                    for statement in _OUTCOME_STATEMENTS:` | `                    for statement in ():` | `tests/test_ad1287_s3_profile_outcomes.py::test_an_s1_file_is_extended_once_and_keeps_every_s1_object_and_row` |
| O4 | `src/probos/cognitive/profile_qualification_store.py` | `_LAYOUT: Final = {_object_key(statement): statement for statement in _SCHEMA_STATEMENTS + _OUTCOME_STATEMENTS}` | `_LAYOUT: Final = {_object_key(statement): statement for statement in _SCHEMA_STATEMENTS}` | `tests/test_ad1287_s3_profile_outcomes.py::test_fresh_file_holds_the_s1_and_s3_layout` |
| O5 | `src/probos/cognitive/profile_qualification_store.py` | `_OUTCOME_DELTAS: Final = {"succeeded": (1, 0), "failed": (0, 1)}` | `_OUTCOME_DELTAS: Final = {"succeeded": (1, 0), "failed": (1, 0)}` | `tests/test_ad1287_s3_profile_outcomes.py::test_succeeded_adds_alpha_and_failed_adds_beta_from_the_2_2_prior` |
| O6 | `src/probos/cognitive/profile_qualification_store.py` | `_OUTCOME_DELTAS: Final = {"succeeded": (1, 0), "failed": (0, 1)}` | `_OUTCOME_DELTAS: Final = {"succeeded": (1, 0), "failed": (0, 1), "cancelled": (0, 1)}` | `tests/test_ad1287_s3_profile_outcomes.py::test_bad_input_is_refused_before_any_read[cancelled]` |
| O7 | `src/probos/cognitive/profile_qualification_store.py` | `                alpha, beta, observation = PROFILE_OUTCOME_PRIOR[0], PROFILE_OUTCOME_PRIOR[1], 0` | `                alpha, beta, observation = 1, 1, 0` | `tests/test_ad1287_s3_profile_outcomes.py::test_succeeded_adds_alpha_and_failed_adds_beta_from_the_2_2_prior` |
| O8 | `src/probos/cognitive/profile_qualification_store.py` | `        f"SELECT {_OUTCOME_COLUMNS} FROM profile_outcomes WHERE profile_ref = ? ORDER BY observation DESC LIMIT 1",` | `        f"SELECT {_OUTCOME_COLUMNS} FROM profile_outcomes WHERE profile_ref = ? ORDER BY observation ASC LIMIT 1",` | `tests/test_ad1287_s3_profile_outcomes.py::test_succeeded_adds_alpha_and_failed_adds_beta_from_the_2_2_prior` |
| O9 | `src/probos/cognitive/profile_qualification_store.py` | `                if (learned.terminal_status, learned.error_code) != (outcome.terminal_status, outcome.error_code):` | `                if False:` | `tests/test_ad1287_s3_profile_outcomes.py::test_a_different_outcome_or_profile_for_a_learned_attempt_is_refused[other_status]` |
| O10 | `src/probos/cognitive/profile_qualification_store.py` | `                if rows[0][1] != profile_ref:` | `                if False:` | `tests/test_ad1287_s3_profile_outcomes.py::test_a_different_outcome_or_profile_for_a_learned_attempt_is_refused[other_profile]` |
| O11 | `src/probos/cognitive/profile_qualification_store.py` | `        and alpha + beta == sum(PROFILE_OUTCOME_PRIOR) + observation` | `        and True` | `tests/test_ad1287_s3_profile_outcomes.py::test_tampered_outcome_rows_are_integrity_errors[sum]` |
| O12 | `src/probos/cognitive/profile_qualification_store.py` | `        and task_class == profile.task_class` | `        and True` | `tests/test_ad1287_s3_profile_outcomes.py::test_tampered_outcome_rows_are_integrity_errors[task_class]` |
| O13 | `src/probos/cognitive/profile_qualification_store.py` | `        and (error_code is None) == (status == "succeeded")` | `        and True` | `tests/test_ad1287_s3_profile_outcomes.py::test_tampered_outcome_rows_are_integrity_errors[succeeded_with_code]` |
| O14 | `src/probos/cognitive/profile_qualification_store.py` | `        and _is_stamp(learned_at)` | `        and True` | `tests/test_ad1287_s3_profile_outcomes.py::test_tampered_outcome_rows_are_integrity_errors[learned_at_negative]` |
| O15 | `src/probos/cognitive/profile_qualification_store.py` | `            if observation == _MAX_SEQ:` | `            if False:` | `tests/test_ad1287_s3_profile_outcomes.py::test_the_observation_bound_is_refused_before_any_write` |
| O16 | `src/probos/cognitive/profile_qualification_store.py` | `    if outcome.terminal_status not in PROFILE_OUTCOME_EVIDENCE:` | `    if False:` | `tests/test_ad1287_s3_outcome_learning.py::test_cancelled_is_not_evidence_and_nothing_written` |
| O17 | `src/probos/cognitive/profile_qualification_store.py` | `    if outcome is None:` | `    if False:` | `tests/test_ad1287_s3_outcome_learning.py::test_pending_when_no_outcome_and_nothing_written` |
| O18 | `src/probos/cognitive/profile_qualification_store.py` | `    deciding = _verified_evaluation(latest[0], profile_ref, profile)` | `    deciding = _verified_evaluation(latest[0], profile_ref, profile); await _latest_outcome(db, profile_ref, profile)` | `tests/test_ad1287_s3_profile_outcomes.py::test_learning_gates_nothing` |
| O19 | `src/probos/cognitive/profile_qualification_store.py` | `WHEN EXISTS (SELECT 1 FROM profile_outcomes WHERE worker_attempt_id = NEW.worker_attempt_id` | `WHEN EXISTS (SELECT 1 FROM profile_outcomes WHERE 0` | `tests/test_ad1287_s3_profile_outcomes.py::test_the_database_refuses_update_delete_and_replace_of_outcomes[replace_by_attempt]` |
| O20 | `src/probos/cognitive/profile_qualification_store.py` | `    """CREATE TRIGGER profile_outcomes_no_update BEFORE UPDATE ON profile_outcomes` | `    """CREATE TRIGGER profile_outcomes_no_update BEFORE UPDATE ON profile_evaluations` | `tests/test_ad1287_s3_profile_outcomes.py::test_the_database_refuses_update_delete_and_replace_of_outcomes[update]` |
| O21 | `src/probos/cognitive/profile_qualification_store.py` | `    """CREATE TRIGGER profile_outcomes_no_delete BEFORE DELETE ON profile_outcomes` | `    """CREATE TRIGGER profile_outcomes_no_delete BEFORE DELETE ON profile_evaluations` | `tests/test_ad1287_s3_profile_outcomes.py::test_the_database_refuses_update_delete_and_replace_of_outcomes[delete]` |
| O22 | `src/probos/cognitive/profile_qualification_store.py` | `) WITHOUT ROWID"""  # end profile_outcomes` | `)"""  # end profile_outcomes` | `tests/test_ad1287_profile_qualification_store.py::test_every_table_is_without_rowid` |
| O23 | `src/probos/cognitive/profile_qualification_store.py` | `    schema_version INTEGER NOT NULL CHECK (schema_version = 1), -- profile_outcomes` | `    schema_version INTEGER NOT NULL, -- profile_outcomes` | `tests/test_ad1287_s3_profile_outcomes.py::test_the_outcome_schema_version_check_refuses_other_versions` |
| O24 | `src/probos/cognitive/profile_qualification_store.py` | `        if attempt.worker_attempt_id != outcome.worker_attempt_id:` | `        if False:` | `tests/test_ad1287_s3_profile_outcomes.py::test_bad_input_is_refused_before_any_read[attempt_mismatch]` |
| O25 | `src/probos/cognitive/profile_qualification_store.py` | `    if attempt.worker_attempt_id != worker_attempt_id:` | `    if False:` | `tests/test_ad1287_s3_outcome_learning.py::test_a_reader_answering_for_another_attempt_is_refused[attempt]` |
| O26 | `src/probos/cognitive/profile_qualification_store.py` | `            return ProfileOutcomeState(profile_ref, profile.task_class, *PROFILE_OUTCOME_PRIOR, 0, None)` | `            return ProfileOutcomeState(profile_ref, profile.task_class, 1, 1, 0, None)` | `tests/test_ad1287_s3_profile_outcomes.py::test_unobserved_profile_reports_the_prior_and_unknown_reports_none` |
| O27 | `src/probos/cognitive/profile_qualification_store.py` | `    if not _is_elastic_id(worker_attempt_id):` | `    if False:` | `tests/test_ad1287_s3_outcome_learning.py::test_malformed_and_unknown_attempts_are_refused[malformed]` |
| O28 | `src/probos/cognitive/profile_qualification_store.py` | `        and alpha >= PROFILE_OUTCOME_PRIOR[0] + delta[0]` | `        and True` | `tests/test_ad1287_s3_profile_outcomes.py::test_tampered_outcome_rows_are_integrity_errors[alpha_below_own_count]` |
| R-S18 | `src/probos/cognitive/profile_qualification_store.py` | `) WITHOUT ROWID"""  # end execution_profiles` | `)"""  # end execution_profiles` | `tests/test_ad1287_profile_qualification_store.py::test_rowid_replacement_is_refused_on_every_table` |
| R-S19 | `src/probos/cognitive/profile_qualification_store.py` | `) WITHOUT ROWID"""  # end profile_evaluations` | `)"""  # end profile_evaluations` | `tests/test_ad1287_profile_qualification_store.py::test_rowid_replacement_is_refused_on_every_table` |
| R-S20 | `src/probos/cognitive/profile_qualification_store.py` | `) WITHOUT ROWID"""  # end profile_invalidations` | `)"""  # end profile_invalidations` | `tests/test_ad1287_profile_qualification_store.py::test_rowid_replacement_is_refused_on_every_table` |
| R-S26 | `src/probos/cognitive/profile_qualification_store.py` | `            now_ms = _checked_now_ms(self._clock)` | `            now_ms = max(_checked_now_ms(self._clock), _checked_now_ms(self._clock))` | `tests/test_ad1287_profile_qualification_store.py::test_clock_is_read_once_per_data_call_and_never_otherwise` |
| R-S29 | `src/probos/cognitive/profile_qualification_store.py` | `    differences = sorted(name for _kind, name in set(found) ^ set(_LAYOUT))` | `    differences: list[str] = []` | `tests/test_ad1287_profile_qualification_store.py::test_start_accepts_only_this_layout` |
| R-S30 | `src/probos/cognitive/profile_qualification_store.py` | `    differences += sorted(key[1] for key, sql in found.items() if key in _LAYOUT and sql != _LAYOUT[key])` | `    differences += []` | `tests/test_ad1287_profile_qualification_store.py::test_start_accepts_only_this_layout` |
| R-S31 | `src/probos/cognitive/profile_qualification_store.py` | `                if not found:` | `                if True:` | `tests/test_ad1287_profile_qualification_store.py::test_unstarted_and_stopped_store_raise_unavailable` |
| R-S32 | `src/probos/cognitive/profile_qualification_store.py` | `                    if differences:` | `                    if False:` | `tests/test_ad1287_profile_qualification_store.py::test_start_refuses_the_pre_round_1_layout_and_leaves_the_file_unmodified` |
| R-S33 | `src/probos/cognitive/profile_qualification_store.py` | `                await db.execute("BEGIN IMMEDIATE")` | `                await (await db.execute("PRAGMA journal_mode=WAL")).fetchall(); await db.execute("BEGIN IMMEDIATE")` | `tests/test_ad1287_profile_qualification_store.py::test_start_refuses_the_pre_round_1_layout_and_leaves_the_file_unmodified` |
| R-S34 | `src/probos/cognitive/profile_qualification_store.py` | `    return {(kind, name): sql for kind, name, sql in catalog if not str(name).lower().startswith("sqlite_")}` | `    return {(kind, name): sql for kind, name, sql in catalog}` | `tests/test_ad1287_profile_qualification_store.py::test_unstarted_and_stopped_store_raise_unavailable` |
| R-S36 | `src/probos/cognitive/profile_qualification_store.py` | `            await db.execute("PRAGMA foreign_keys=ON")` | `            await db.execute("PRAGMA foreign_keys=OFF")` | `tests/test_ad1287_profile_qualification_store.py::test_foreign_keys_are_on_before_the_first_statement_of_every_connection` |
| R-S37 | `src/probos/cognitive/profile_qualification_store.py` | `_PROFILES_TABLE: Final = """CREATE TABLE execution_profiles (` | `_PROFILES_TABLE: Final = "" + """CREATE TABLE execution_profiles (` | `tests/test_ad1287_profile_qualification_store.py::test_store_tables_are_visible_to_the_store_registry_detector` |
| R-S38 | `src/probos/cognitive/profile_qualification_store.py` | `                await db.execute("BEGIN IMMEDIATE")` | `                pass` | `tests/test_ad1287_profile_qualification_store.py::test_a_start_failing_while_creating_leaves_no_layout_and_a_later_start_creates_it` |
| R-S39 | `src/probos/cognitive/profile_qualification_store.py` | `    differences = sorted(name for _kind, name in set(found) ^ set(_LAYOUT))` | `    differences = sorted(name for kind, name in set(found) ^ set(_LAYOUT) if kind != "index" or (kind, name) in _LAYOUT)` | `tests/test_ad1287_profile_qualification_store.py::test_start_accepts_only_this_layout` |

R-S30 changes killer from S1's record: the pre-round-1 file now also lacks the S3 objects, so it is refused by name and no longer isolates the definition comparison; `weakened_trigger` and `changed_index` in `test_start_accepts_only_this_layout` (a store-created S1+S3 file, then one definition edited) do. Uniqueness notes for the driver: R-S33/R-S38 anchor is the 16-space `BEGIN IMMEDIATE` in `start()`; every other `BEGIN IMMEDIATE` in the file is indented 12, which is not a superstring of the 16-space text. R-S26's anchor also frames the two new methods (via `_operation`). O22's killer is the S1 test as edited in Section 3. The "Killer" for parametrised S1 tests is the whole test function (all its cases).

## What this does NOT change

- `ProfileQualification`, `CandidateQueryResult`, `_assess`, `get_qualification`, `find_slot_candidates`, `check_slot_qualification`, `admit_qualified_attempt`, S2a `admit_current_qualified_attempt`, S2b `record_component_drift`: unchanged, and none reads outcomes.
- `_SCHEMA_STATEMENTS`, S1 rows, the store-wide sequence (`_NEXT_SEQ_SQL`): unchanged; outcomes draw no `seq`.
- `ElasticTeamStore` and AD-1286 types: unchanged (read only).
- `TrustNetwork`, `consensus/trust.py`: not imported, not written.
- `_open`, `_set_wal`, `_operation` bodies (R-1 not touched).
- S1 test #16 (`tests/test_ad1287_slot_qualification.py`): unchanged. The new names live in an owner module, and any wiring would construct the store or import the module, both of which #16 detects.

## Do not build

Wiring or a sweeper (AD-1288); TrustNetwork writes; ranking, Thompson sampling or any scheduling heuristic over `(alpha, beta)`; a derived mean in storage; outcome classification by `error_code`; signing or chain anchoring (AD-1047); extracting `_open` (R-1); a migration of existing S1 rows; a new event type; HXI.

## Obligations handed on

- **O-4 (AD-1288):** the sweeper calls `learn_attempt_outcome` for each attempt with a recorded outcome. It treats `pending` as retry-later and `profile_unknown`/`profile_outcome_conflict` as permanent (log, do not retry hot). Any scheduling use of `(alpha, beta)` is AD-1288's decision and must not feed admission.
- **R-4 (residual, documented):** only outcome rows a read uses are verified (latest per profile; the attempt's own row on a repeat naming the same profile; a row naming another profile is a conflict, unverified). An edited earlier row, a deleted latest row, or counts rewritten consistently (same sum, each at least its own count) are not detected. Same root as R-2/R-3 (needs AD-1047).
- **R-5 (residual, documented):** learning does not prove the attempt was admitted through the gate (O-1 owns admission); an attempt recorded around the gate still teaches its profile.

## Acceptance criteria (S3)

- [ ] Sections 1-3 install mechanically on `5c77cd50` (and on `5c77cd50` + S2b), and the full-suite diagnostic is green before any Builder.
- [ ] A fresh file holds 19 objects; an S1 file is extended in one transaction with every S1 object and row unchanged; S1 + partial S3 is refused and left unchanged; a mid-extension failure leaves exactly S1.
- [ ] Outcome updates are idempotent by `worker_attempt_id` and store raw integer `alpha`/`beta` with `profile_ref` and `task_class` provenance, from a `(2, 2)` prior; `cancelled` is not counted; a different outcome for a learned attempt is refused.
- [ ] The seam test crosses admit -> AD-1286 outcome -> learn -> restart -> state -> replay on real stores.
- [ ] Learning gates nothing (M1-15, mutant O18) and writes nothing to `TrustNetwork` (store imports pinned by the S1 test).
- [ ] Campaign of record: every O-row and R-row killed by its named test.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Hidden pins (enumerated)

| Id | Pin | Command | Effect here |
|---|---|---|---|
| H1 | `test_every_table_is_without_rowid` table set | `rg -n "set\(_TABLES\)" tests/test_ad1287_profile_qualification_store.py` -> `:1149` | Edited (Section 3) |
| H2 | `test_start_accepts_only_this_layout[fresh]` fifteen objects | `rg -n "fifteen" tests/test_ad1287_profile_qualification_store.py` -> `:1608`, `:1770` | Edited |
| H3 | Registry detector sees exactly three tables | `rg -n "detect_tables\(Path\(store_module" tests/` -> `:1763` | Edited |
| H4 | `_FIFTEEN` used by #39 and #41 | `rg -n "_FIFTEEN" tests/` -> `:1770`, `:1798`, `:1964` | Edited (renamed `_NINETEEN`) |
| H5 | Store module import allowlist | `rg -n "_ALLOWED_PROBOS_IMPORTS" tests/` -> `:964-975` | Unchanged: S3 imports only more names from `probos.cognitive.elastic_team` |
| H6 | S1 #16 not-wired scan | `rg -n "_S1_MODULES\|_GATE_NAMES" tests/test_ad1287_slot_qualification.py` -> `:627-634` | Unchanged (no new module); S2b edits it separately |
| H7 | Declaration fields | `rg -n "cognitive.profile-qualifications" tests/` -> `:952-961` (id, owner, path, lifecycle) | Unchanged; only prose edited, which no test pins (`rg -n "nine triggers" tests/` -> none) |
| H8 | Store registry baseline | `rg -n "profile_qualification" docs/development/` -> none | Declared, not baselined; rule 11 does not apply |
| H9 | Backup coverage | `rg -n "profile_qualifications" tests/` -> store test `:225`, slot test `:101` (paths only); `tests/test_ad1265_backup_coverage.py` classifies by file name | Unchanged (same file) |
| H10 | Six-data-method premises | `rg -n "six data methods" tests/` -> `:305`, `:1726` | **Corrected by the orchestrator (Section 4):** `test_unstarted_and_stopped_store_raise_unavailable` pins the whole public async surface to `_data_calls`, so `_data_calls` is widened to eight methods and the two tests derived from it (`test_clock_is_read_once_per_data_call_and_never_otherwise`, `test_foreign_keys_are_on_before_the_first_statement_of_every_connection`) are extended; the S3 methods also have their own clock coverage (M1-16) and check the profile exists before inserting (M1-10) |
| H11 | Architecture checks | `rg -n "profile_qualification" scripts/ config/` -> none | No `aiosqlite.connect`; the injected factory is used through `_open` |

## Prior Art and Blind Spots (2026-10-14)

- **Internal.** TrustNetwork keeps raw `(alpha, beta)` with a `(2, 2)` prior (`consensus/trust.py:54-67`) and applies one durable outcome once, keyed by `outcome_id`, returning `duplicate` on a replay (`:612-674`). **Adopted:** raw integer counts with the same prior, first-wins idempotency by the attempt key. **Not adopted:** its weighted float updates and reservation/reconciliation (no cross-store side effect here to reconcile). `docs/research/` has no study on per-configuration outcome learning (`rg -il "thompson|beta-bernoulli|bandit" docs/research` -> only `unified-knowledge-graph.md`, unrelated).
- **Idempotent consumer** ([microservices.io](https://microservices.io/patterns/communication-style/idempotent-consumer.html)): record the message id in the same transaction as the effect, so the key rejects a redelivery. **Adopted** in its strongest form: the outcome row is both the effect and the processed-id record (PK `worker_attempt_id`), written in one `BEGIN IMMEDIATE`.
- **Beta-Bernoulli routers** (e.g. [zeph-llm](https://docs.rs/crate/zeph-llm/latest): per-provider `Beta(alpha, beta)`, updated on success/failure and persisted; [Thompson-sampling routing case study](https://www.zenml.io/llmops-database/cost-efficient-llm-routing-with-online-learning-and-thompson-sampling)). **Adopted:** raw parameters, not a mean. **Rejected here:** sampling or decay. Selection is AD-1288's, and decay would make the stored state depend on time, which breaks replay identity. Considered, deferred.
- **Blind spots named:** (1) a failure caused by infrastructure counts against the profile (D2 rank 2, deferred; `error_code` is stored). (2) Learning does not check gated admission (R-5). (3) The prior is baked into stored rows, so changing it is a schema version. (4) Downgrade: the S1 code refuses an S3-started file (stated; no production file). (5) A conflicting outcome can come only from another AD-1286 store, because `worker_attempt_id` excludes the profile (D2). (6) Observation order is learning order, not outcome time; nothing uses order except "latest". (7) *Declaration prose (review round 1, F1 and F2; injected reach, corrected without a logic change):* the store declaration said every deciding row is re-verified and that nothing bounds learned outcomes per profile. Two narrow exceptions exist: an attempt already learned under another profile is refused as `profile_outcome_conflict` without verifying that stored row (the first learned stands), and the `observation` number is bounded by the 2**53 - 1 sequence limit (`profile_sequence_exhausted`, raised before any write). The declaration now says both, and no longer names `admit_qualified_attempt` as AD-1288's caller (S2a amended O-1: `admit_current_qualified_attempt`).

## Verified Against Codebase (2026-10-14, base `5c77cd50`)

```
git log --oneline -1                          -> 5c77cd50 Merge pull request #1527 (S2a)
rg -n "_SCHEMA_STATEMENTS|_LAYOUT|_layout_differences|def start|def _open|_set_wal|def get_qualification|class ProfileQualification\b" src/probos/cognitive/profile_qualification_store.py
  122 _SCHEMA_STATEMENTS; 162 _LAYOUT; 299 _layout_differences; 313 _set_wal; 488 start; 509-522 create/compare/refuse; 551 _open; 723 get_qualification; 216 ProfileQualification (frozen dataclass)
rg -n "def _assess|deciding = _verified_evaluation" src/probos/cognitive/profile_qualification_store.py  -> 420, 429
rg -n "def (record_attempt_outcome|get_attempt_outcome|get_attempt)\b" src/probos/cognitive/elastic_team_store.py -> 767, 806, 874
rg -n "TerminalStatus|class WorkerAttemptOutcome|execution_profile_ref|OutcomeCode =" src/probos/cognitive/elastic_team.py -> 151, 384, 362, 146
rg -n "_CODE_RE|def _code" src/probos/cognitive/elastic_team.py -> 38, 99
rg -n "alpha: float = 2.0|beta: float = 2.0|async def record_outcome_once|disposition=\"duplicate\"" src/probos/consensus/trust.py -> 66, 67, 612, 671
rg -n "terminal_status not in \(\"failed\", \"cancelled\"\)" src/probos/cognitive/elastic_team_store.py -> 757
rg -n "task_class: ElasticId" src/probos/cognitive/execution_profile.py -> 168
rg -n "cognitive.profile-qualifications" src/probos/cognitive/storage_declarations.py -> 194 (fields 194-217)
rg -n "^    \w+: " src/probos/storage/declarations.py -> 127-140 (no table field)
rg -n "baseline-table-drift" scripts/check_store_registry.py -> 55
rg -n "_FIFTEEN|_TABLES\b|fifteen" tests/test_ad1287*.py -> 62, 272, 277, 669, 736, 1149, 1162-1169, 1608, 1770, 1798, 1964
rg -n "_S1_MODULES|_GATE_NAMES" tests/test_ad1287_slot_qualification.py -> 627, 628
git diff --stat 5c77cd50 feat/ad1287-s2b-20261014-f431dd0f -> 4 files (prompt, profile_drift_recorder.py, its test, test_ad1287_slot_qualification.py)
S1 campaign rows and killers: prompts/ad-1287-s1-execution-profile-qualification.md:1566-1613; DECISIONS.md:92-166
```

## Absence Verified (2026-10-14, base `5c77cd50`)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A1 | The S3 names are new | `rg -n "profile_outcomes\|record_profile_outcome\|get_outcome_state\|learn_attempt_outcome" src tests scripts docs config` | none | yes |
| A2 | No production caller of AD-1286 outcome writes or reads | `rg -n "record_attempt_outcome\|get_attempt_outcome" src` | `elastic_team_store.py:407,408` (docstring), `:806`, `:874` (definitions) | yes |
| A3 | Nothing constructs the store in production | `rg -n "ProfileQualificationStore" src` | the module itself; `profile_currency.py:32` (import, an S2a owner module); `storage_declarations.py:197` (string) | yes (direct references only; aliases and string lookups not covered, as S1 #16 states) |
| A4 | The store is not baselined | `rg -n "profile_qualification" docs/development` | none | yes |
| A5 | No test pins the declaration prose | `rg -n "nine triggers" tests` | none | yes |
| A6 | S2b does not touch Sections 1-3 files | `git diff --stat 5c77cd50 feat/ad1287-s2b-20261014-f431dd0f` | 4 files, none of them in Sections 1-3 | yes |
| A7 | No research study on this | `rg -il "thompson\|beta\(\|beta-binomial\|beta-bernoulli\|bandit" docs/research` | `unified-knowledge-graph.md` only | yes |

## Not verified

- No code was executed: the SQL statements, the Section 1-3 installs and the S1 suite after install are first run by the orchestrator's diagnostic. Expect `test_start_accepts_only_this_layout[module_statements_rollback]` to pass, because it now exercises the S1 -> S3 extension.
- The S2b contract's own Section 3 targets `roadmap.md`; the S2b branch diff does not yet show it, so the post-S2b roadmap row text is unknown (M4 edits by meaning, not SEARCH).

## Tracking (M4, after the campaign; not installed)

1. `DECISIONS.md`: insert `### AD-1287 S3 -- Outcome learning: raw Beta parameters per execution profile (2026-10-14, #1334)` directly above the `### AD-1287 S2b` heading (above `### AD-1287 S2a` if S2b's entry is absent). One paragraph: what shipped and that it is unwired. D1-D6 one line each. O-4, R-4, R-5. The review record. The campaign of record: base, tree, sha256s and an `Id | Killed first by` table.
2. `PROGRESS.md`: a new top paragraph `**AD-1287 slice S3 BUILT (<date>), #1334, built and unwired -- outcome learning ...**` naming the module, the two methods and the producer, and stating that #1334 closes with S2b and S3.
3. `docs/development/roadmap.md` AD-1287 row (`:527` on base): set the title's parenthetical to list S1, S2a, S2b and S3 as built and unwired, and mark the row done in whatever form the table uses for closed ADs.
4. Regenerate the ledger: `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py`, then `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py --check` (exit 0). Commit as `chore(ledger): ...` as the S2a wave did (`f431dd0f`).

**#1334 closing comment must say:** S3's PR and merge commit, and S2b's. What is on `main`: the `profile_outcomes` table, `record_profile_outcome`, `get_outcome_state`, `learn_attempt_outcome` and the two-layout `start()`. Each acceptance line mapped to its test: idempotent raw Beta with provenance -> M1-6/8, M2-6; restart -> M1-8, M2-6; S1/S2a/S2b lines -> their contracts. The canonical gate receipt (label `ad1287-s3`, passed/skipped, receipt sha256, HEAD, tree). The campaign result (n of n killed, base). That everything is unwired (nothing calls `learn_attempt_outcome`). That nothing is written to `TrustNetwork` and learning gates nothing. O-1 and O-4 handed to AD-1288 (#1335), and residuals R-1 to R-5. Close with `state_reason: completed`.

=== BUILDER BRIEFS ===

### Brief M1 -- store tests (effort: max, at most 150 calls)

Write ONLY `tests/test_ad1287_s3_profile_outcomes.py`, tests 1-17 as listed under "M1" in `prompts/ad-1287-s3-outcome-learning.md`, with exactly those names and parametrize ids (the campaign's Killer column depends on them). The source is frozen: never edit `src/` or another test file; if a test cannot pass against the installed source, stop and report the exact assertion and output. Read `src/probos/cognitive/profile_qualification_store.py` for the S3 sections by grep (`_OUTCOME`, `record_profile_outcome`, `get_outcome_state`, `_S1_LAYOUT`), and copy (do not import) the helpers you need from `tests/test_ad1287_profile_qualification_store.py` (`_Clock`, `_profile_model`, `_evaluation`, `_ProxyFactory`, `_catalog`, `_run_script`, `_journal_mode`, `_file_sha256`). Build `WorkerAttempt`/`WorkerAttemptOutcome` with `derive_worker_attempt_id` from `probos.cognitive.elastic_team`; outcome `recorded_at` is a float. Every test asserts its premise first (e.g. the S1 file holds 15 objects before the start). Each refusal has a negative control. Tampered rows are raw INSERTs of new latest rows, since the triggers allow new rows; write no trigger dance. Use the test's own literal `2**53 - 1`. Real files in `tmp_path`; for byte-identity cases, keep the file in rollback mode. Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1287_s3_profile_outcomes.py tests/test_ad1287_profile_qualification_store.py -q -n 0`. Report: the test count, the gate output and any premise that surprised you.

### Brief M2 -- producer and chain tests (effort: max, at most 150 calls)

Write ONLY `tests/test_ad1287_s3_outcome_learning.py`, tests 1-7 under "M2" in the contract, with exactly those names and ids. The source is frozen. Tests 1-5 use `_FakeAttempts` (`get_attempt`, `get_attempt_outcome`, recording calls) and `_FakeOutcomes` (`record_profile_outcome`, recording calls); assert the exact calls made, including none. Test 6 is the seam test: real `ElasticTeamStore` and `ProfileQualificationStore` in `tmp_path`. Follow `_World` in `tests/test_ad1287_slot_qualification.py` (~line 90) to build a spec, a profile, a passing evaluation and three admitted attempts (distinct slots or sessions; supersession needs a failed or cancelled predecessor, `elastic_team_store.py:743-765`). Admit through `admit_qualified_attempt`, record outcomes with `record_attempt_outcome`, learn with `learn_attempt_outcome`, then stop both stores and start NEW instances on the same paths before reading `get_outcome_state` and replaying. Assert the row count via a raw `sqlite3` `SELECT COUNT(*) FROM profile_outcomes`. Assert the directory listing holds only the two stores' files. Test 7 compares `inspect.signature` parameters. Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1287_s3_outcome_learning.py tests/test_ad1287_slot_qualification.py -q -n 0`. Report as M1.

### Brief M3 -- mutation campaign of record (effort: high, at most 150 calls)

Run the table under "## Mutation campaign of record" in the contract, once, on the committed tree after M1 and M2. For each row, confirm that the anchor occurs exactly once in the CRLF file, replace it literally, run its Killer with `-q -n 0 -x`, record KILLED, SURVIVED, INERT or INVALID, then restore the file and confirm its sha256 matches the pre-run value. Record the base commit, tree and sha256 of `profile_qualification_store.py`, `storage_declarations.py` and the three test files. A survivor is a stop: report it with its output, and do not edit tests to kill it. Do not re-run the S1 rows the contract marks as still valid unless their anchor line differs from base `5c77cd50`. Report the table `Id | Result | Killed first by`.

### Brief M4 -- trackers (effort: high, at most 60 calls)

Apply "## Tracking" items 1-4 of the contract after S2b has merged. In `DECISIONS.md`, `PROGRESS.md` and `docs/development/roadmap.md`, edit only the named entries, and stage explicit paths only (never `git add -A`). Use the campaign table from M3 verbatim. Run both ledger commands and report their exit codes. Do not close #1334, and do not draft or post its comment; the orchestrator does.
