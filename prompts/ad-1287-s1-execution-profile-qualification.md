# AD-1287 S1 (#1334): execution-profile identity, insert-only evaluation evidence, bounded candidate query and the slot-boundary gate

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-12
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-12 (review round 1, store scope and Reviewer B rulings; Brief R1)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-12 (review round 2, reviewer C rulings C1-C4; Brief R2)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-12 (R2b: registry detection restored in Section 3, #38, S33 corrected, S37; Brief R2b)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-12 (round 3, reviewers D1/D2: WAL retry D3b, refusal wording, #39-#44, S38-S44; Brief R3)
**Status:** build-ready (slice S1 of three). Base `origin/main` `f85cd42c`. Branch `feat/ad1287-1334-20261012-f85cd42c`.
**Issue / epic:** #1334 / #1332. AD-1287 is already allocated (ceiling AD-1327 from GitHub issue titles, `scripts/ad_ceiling.py`, 2026-10-12); this slice allocates no AD or BF number.
**Depends on:** AD-1286 (shipped, `cddcb9f6`). **Dependents:** AD-1288 #1335 (commission admission must call `admit_qualified_attempt`), S2 and S3 below.
**Estimated tests:** about 30 (M1) + 44 (M2, after round 3) + 18 (M3), several parametrized. New files only, plus one storage declaration.
**Builder phases:** M1 pure contract, M2 store, M3 query, gate and seam, M4 mutation campaign of record, M5 trackers. The briefs follow `=== BUILDER BRIEFS ===`.

One-line summary: a content-addressed `ExecutionProfile` (role, task class, skills, model, prompts, tools, policy, evaluation suite), an insert-only SQLite store of raw evaluation evidence with expiry and sequence-scoped invalidation, a bounded deterministic candidate query that returns evidence and chooses nothing, and the slot-boundary gate that refuses an unqualified profile before `ElasticTeamStore.record_attempt`. Built and unwired.

---

## Problem

- AD-1286 ships `WorkerAttempt.execution_profile_ref` as a bare 64-hex reference that "AD-1287 defines" (`src/probos/cognitive/elastic_team.py:350-362`), and `QualificationRequirement` (`qualification_ids`, `pinned_profile_refs`, `:195-199`) is declared but never evaluated. The store's only profile check is pin membership (`elastic_team_store.py:731-733`).
- No owner computes a digest for a skill's resources: `CognitiveSkillCatalog` has no hashing (`skill_catalog.py`, 0 hits for `hashlib|digest`). The issue's "AD-596 skill/resource digests" premise does not hold at `f85cd42c` (Absence Verified A1).
- `QualificationStore` records per-agent psychometric results (`agent_id`, `test_name`, REAL `score`, `qualification.py:122-136`) on one long-lived connection with an `ALTER TABLE` migration (`:170-182`). It has no profile identity, no immutability and no expiry. `QualificationSkillBridge` (`qual_skill_bridge.py:43`, `:67`) maps those agent results to proficiency. Neither can say "this exact combination passed".
- `ModelDescriptor` has `name`, `provider`, `tier` and no version (`model_registry.py:33-43`). `Tool` exposes `input_schema`/`output_schema` and no implementation version (`tools/protocol.py:127-133`).
- `TrustNetwork` keeps raw `(alpha, beta)` per **agent** (`consensus/trust.py:55-67`). A profile is not an agent.

So nothing can produce, store, or check at the slot boundary a credential bound to an exact profile.

## Solution overview (S1)

1. **`src/probos/cognitive/execution_profile.py` (new, pure).** `ExecutionProfile` and its component types, a domain-separated content reference, `EvaluationRecord` (raw per-case integers), `assess_evaluation` (status rule), `slot_refusal` (slot constraint rule), `expires_at_ms`.
2. **`src/probos/cognitive/profile_qualification_store.py` (new).** `ProfileQualificationStore`: three insert-only `WITHOUT ROWID` tables (profiles, evaluations, invalidations), nine triggers, verified reads, one store-wide sequence; `find_slot_candidates` (bounded, deterministic, evidence only); the slot-boundary consumers `check_slot_qualification` and `admit_qualified_attempt`.
3. **One `StoreDeclaration`** in `src/probos/cognitive/storage_declarations.py` (`lifecycle_owner="unowned"`).
4. **Chain proof (M3 #10):** an evaluation on a real store file is the producer. After a restart of both stores, the gate refuses an unevaluated profile (no attempt row) and admits the exact qualified one into a real `ElasticTeamStore` file. One test crosses the seam.

Nothing constructs the store in production. AD-1288 commission admission is the intended caller of `admit_qualified_attempt` (obligation O-1).

## Slicing decision

| Rank | Option | Verdict |
|---|---|---|
| 1 | **Three slices.** S1 (this prompt): identity, evidence store, query and slot gate, a complete producer-to-consumer chain on declared component digests. S2: component-digest producers (skill directory, tool schema, model, policy, structural validity from `validate_skill`), drift detection that records `component_drift_*` invalidations, and a currency check in the gate. S3: outcome learning on raw Beta parameters from AD-1286 attempt outcomes. Each is shippable and unwired. | **Chosen.** S1 is a whole chain. S2 and S3 add producers to it and change no S1 contract. |
| 2 | One AD-1287 prompt with milestones for everything. | Rejected. Too much for one prompt: three stores' worth of contract, filesystem digesting and a Beta ledger, with AD-1299 S1b's five review rounds as the measured cost of one store. The milestones would not fit fresh Builders of about 150 calls. |
| 3 | Slice by layer: pure contract, then store, then query. | Rejected. The first two would be half-chains: built and tested, with nothing crossing the seam. |

S2 goes before S3 because drift is the safety-relevant half: until S2, a qualified reference stays admissible after a live component changes, because S1 has no live component source. No production caller of the slot boundary exists until AD-1288 (A2), so nothing in production depends on this before S2.

## Decisions and ranked options

### D1. Where profile identity lives

| Rank | Option | Verdict |
|---|---|---|
| 1 | New `cognitive/execution_profile.py` with its own domains (`probos.execution_profile/profile/v1\x00`, `.../evaluation/v1\x00`). It reuses AD-1286's public `canonicalize_projection`, `ElasticId`, `Sha256Ref`, `Revision` and `WorkerSlot`. | **Chosen.** No edit to the shipped AD-1286 module. Same identity scheme (RFC 8785, domain prefix, no floats, sorted sets). |
| 2 | Add a kind to `elastic_team._DOMAINS`. | Rejected. It edits a shipped, review-hardened module and puts profile semantics in the team contract. |
| 3 | Put digests in `skill_catalog.py`. | Rejected. Skills are one component of six. |

### D2. Profile digest scope and canonicalisation

| Rank | Option | Verdict |
|---|---|---|
| 1 | **One digest over everything the issue lists**: role, task class, skills (`skill_name`, `resource_digest`), model (`provider`, `name`, `version`), prompts (`prompt_id`, `revision_digest`), tools (`tool_id`, `schema_digest`, `implementation_digest`), policy (`policy_digest`), and the evaluation suite (`qualification_id`, `suite_revision`, `dataset_digest`, `min_samples`, `min_pass_bp`, `validity_seconds`). The pass rule and validity window are part of the suite, so changing them also gives a new profile. Component sequences are sorted by key, and duplicates are refused. Integers only. | **Chosen.** It matches the issue text ("creates a new profile") and makes slot pinning exact. Its cost: outcome learning (S3) restarts when the suite is revised, which is the conservative direction. |
| 2 | Two digests: a runtime profile without the suite, and a qualification subject (profile + suite). | Considered, deferred. It keeps S3's outcome history across suite revisions, but it contradicts the acceptance wording and needs a slot-side registry of "current suite revision". A future migration policy can add it. |
| 3 | Component digests are computed inside S1 from live owners. | Rejected for S1 (it is S2). Live sources need filesystem walking and schema hashing rules of their own, so S1 takes them as declared `Sha256Ref` values, exactly as AD-1286 took `execution_profile_ref`. |

### D3. Where evidence persists, and its schema

| Rank | Option | Verdict |
|---|---|---|
| 1 | New `ProfileQualificationStore`, own file `profile_qualifications.db`, three `WITHOUT ROWID` tables with per-row `schema_version` and `CHECK (schema_version = 1)`, nine triggers refusing UPDATE, DELETE and replacing INSERT, canonical JSON re-verified on every row used to decide or return a result. The columns used to select or to enforce uniqueness (profiles: `role_id`, `task_class`; evaluations: `profile_ref`, `evaluation_id`) are `VIRTUAL` columns generated by `json_extract` from the canonical text, not stored copies (review round 1, A1). | **Chosen.** It follows the AD-1286 and AD-1299 S1b precedent. |
| 2 | Extend `QualificationStore`. | Rejected. Its rows are agent-keyed and mutable. It uses REAL scores, an `ALTER` migration and one shared connection (`qualification.py:122-182`). |
| 3 | Add tables to `elastic_teams.db`. | Rejected. That ties the lifecycle to `orchestrator_enabled` wiring (`startup/finalize.py:2041-2069`) and changes a pinned schema. |

**Versioning.** `schema_version` stays 1. A new column or table is a new schema version with its own migration slice. **(Round 2, overrides "Later slices" S3 wording.)** Because `start()` accepts only an empty file or exactly this layout (D3a), S3's additive outcome table must extend the accepted layouts: accept the S1 layout and add its table in the same `BEGIN IMMEDIATE`, accept the S1+S3 layout, refuse anything else. No existing row needs migration.

**D3a. Start-up layout check (round 2, C1).** `start()` previously ran `executescript` of `IF NOT EXISTS` statements, so a file holding another layout (measured: the pre-round-1 layout with stored selection columns) started, and A1 reopened on it.

| Rank | Option | Verdict |
|---|---|---|
| 1 | **Exact catalog match against the module's own statements.** One statement per object (`_SCHEMA_STATEMENTS`, no `IF NOT EXISTS`). Inside one `BEGIN IMMEDIATE`, read `sqlite_master` (objects named `sqlite_*` excluded): none -> create all fifteen; otherwise the `(type, name)` set must equal the fifteen and each stored `sql` must equal its statement exactly; anything else -> refuse, with no schema or data write by the store. `PRAGMA journal_mode=WAL` only after the commit, tried again on BUSY with the busy handler off (round 3, H1; round 4, E1). | **Chosen.** SQLite stores each statement as written, normalising only leading keywords and spaces, the database-name qualifier and `TEMP` ([schema table](https://www.sqlite.org/schematab.html) §3), none of which these statements contain, and it re-parses that text at every open. Equality therefore covers every property at once: column kinds, generated-column expressions, `WITHOUT ROWID`, `CHECK`s, `UNIQUE`/FK clauses, index columns, trigger `WHEN` bodies. No comparison between two SQLite versions' normalisations is involved. Internal precedent: `execution/authority.py:1039-1057` compares stored table SQL with its own source. |
| 2 | Semantic catalog subset (`table_xinfo` hidden flags, `WITHOUT ROWID`, trigger names and messages, `CHECK`s). | Rejected as the check: it covers what is enumerated, so C1 recurs on any property left out (expressions, `WHEN` clauses, index columns), and each property needs its own PRAGMA, refusing case and mutant. Kept as test evidence (#31) on a fresh file. |
| 3 | `PRAGMA user_version` stamp. | Rejected: a label, not a check. A pre-created or edited file carries any label. Adds nothing to option 1, and S3 can recognise layouts by object set. |
| 4 | Text fingerprint against a freshly built reference. | Rejected for the reason given: two SQLite versions' normalisations. |
| 5 | Claim narrowing only. | Rejected: the store would still start on an honest older file and decide on unverified selection columns. |

**Claimed afterwards (round 3 wording):** `start()` refuses a database whose schema objects are not exactly this module's (the same names, each stored with the definition this module writes), with `ProfileQualificationStoreUnavailable("profile_qualification_layout_mismatch")`, an ERROR log naming up to 16 differing objects, and the store left stopped. **The store issues no schema or data write to a file it refuses.** **(Round 4, E2)** SQLite itself can still change a refused file: on open it replays a hot rollback journal a crashed writer left (measured by reviewer E, round 4; [lockingv3](https://www.sqlite.org/lockingv3.html) §4.1) or recovers a `-wal` file, and when the last connection closes, SQLite can checkpoint a WAL-mode file and remove its `-wal`/`-shm` files (measured by reviewer D1, round 3); no test pins either, and neither is a store write. A refused rollback-journal file that needs no recovery is byte-identical (M2 #34, a clean file). **Not checked:** SQLite's own `sqlite_*` objects, page-level integrity (`PRAGMA integrity_check` is not run), and a layout changed while the store is started (seen only when a stopped store is next started: `start()` on a started store checks nothing). A file-level writer with a valid layout stays R-2/R-3. No self-heal: a file missing one trigger is refused, not repaired, because a missing guard is a changed layout. **Creation is atomic (round 3, D2.1):** it runs inside the same `BEGIN IMMEDIATE` (SQLite DDL is transactional), so a start that fails part-way through creation leaves no schema object, and a later start creates the layout (M2 #39).

**D3b. WAL after the check (round 3, H1).** Ranked: (1) **bounded retry, then log-and-degrade** -- chosen; (2) bounded retry, then refuse (`ProfileQualificationStoreUnavailable`) -- rejected: nothing in the store's correctness needs WAL (every write is `BEGIN IMMEDIATE` on its own connection behind one lock, every read is one autocommit statement or a sequence the D4/D9 claims already treat per row), so a refusal turns a concurrency property into an outage on a filesystem without WAL; (3) best effort with no retry -- rejected: a healthy concurrent first start would stay in rollback mode until the next restart; (4) WAL before the check -- rejected: it writes to a file that is then refused (#34, S33). `_set_wal` first runs `PRAGMA busy_timeout=0` on its connection (**round 4, E1**: under another connection's RESERVED lock -- an open write transaction -- the switch answers `SQLITE_BUSY` at once, but under an EXCLUSIVE lock -- a commit in progress or `BEGIN EXCLUSIVE` -- SQLite runs the busy handler first, measured 7.45 s per try at `busy_timeout=5000`, so 50 tries could hold `start()`, and the store's lock, for minutes). It then retries `PRAGMA journal_mode=WAL` on `SQLITE_BUSY` (primary code, read only from an error that carries `sqlite_errorcode`; an `OperationalError` without one propagates unchanged, **round 4, E3**), up to `_WAL_ATTEMPTS` = 50 tries `_WAL_RETRY_DELAY_S` = 0.1 s apart, about 5 s in all whichever lock is held, reads the mode SQLite answers, and propagates any other error. `start()` closes the connection straight after, so no other statement runs with the handler off (M2 #45). A `wal` answer starts the store silently; any other answer, or busy on every try, starts it in the file's current mode with one WARNING naming the mode. No test or claim needs WAL except as evidence that an accepted start writes (#35 `module_statements_rollback`, uncontended); M2 #41-#44 pin the retry and both degrade branches; #45-#47 pin the handler-off budget and the code-less error.

### D4. How expiry and invalidation compose

| Rank | Option | Verdict |
|---|---|---|
| 1 | The **latest evaluation (highest store sequence) decides**. Expiry is `issued_at_ms + validity_seconds * 1000`, and both are stamped by the store's clock. An invalidation applies to every evaluation **of that profile with a lower sequence**. Requalification is a new evaluation recorded after it. Status precedence: `invalidated` > `expired` > `structurally_invalid` > `insufficient_sample` > `failed` > `qualified`. | **Chosen.** Ordering uses one store-wide sequence drawn under `BEGIN IMMEDIATE`, not the wall clock, so a clock moved backwards cannot let a pre-invalidation evaluation survive. A newer failed run is never masked by an older pass. |
| 2 | Invalidation is permanent per profile. | Rejected. The same configuration could never be requalified, and a reverted component would stay dead forever. |
| 3 | Order invalidation against evaluation by wall clock. | Rejected for the reason in option 1. |

Non-normative limitation: expiry is wall-clock, so a clock moved backwards lengthens an evaluation's effective window by the size of the jump.

**Sequence bound (round 2, C2).** `_next_seq` raises `ProfileQualificationConflict("profile_sequence_exhausted")` when the highest stored sequence is already `_MAX_SEQ` (`2**53-1`). It runs inside `BEGIN IMMEDIATE` before either writer's INSERT, so nothing is written, and every row stays readable. An identical replay allocates nothing and still returns the stored row (M2 #36).

**Stamp bounds (review round 1, A2).** Every store stamp on a row the store uses is checked for type and range: `issued_at_ms`, `recorded_at_ms` and `invalidated_at_ms` are ints in `[0, 253402300799000]` (the clock bound in ms), `seq` is an int in `[1, 2**53-1]`, and `expires_at_ms` must equal `issued_at_ms + validity_seconds * 1000`. A stamp outside that is an integrity error. A stamp is not compared with "now": a clock moved backwards legitimately leaves honest rows in the future. A stamp rewritten inside these bounds is not detected (R-3). The selection order (`seq`) is a stamp, so R-3 includes reordering which evaluation decides.

### D5. The slot boundary: may AD-1286's slot consult qualification now?

| Rank | Option | Verdict |
|---|---|---|
| 1 | **Now, by composition.** `admit_qualified_attempt(qualifications, teams, attempt)` loads the stored spec through `teams.get_team_spec` and runs `check_slot_qualification`. Only then does it call `teams.record_attempt`, which applies AD-1286's own admission rules. AD-1286 is unchanged. It is unwired, and AD-1288 must route commission through it (O-1). | **Chosen.** No production caller of `record_attempt` exists (A2), so no control is weakened. The two stores share no transaction: admission is decided as of the qualification read. |
| 2 | Edit `ElasticTeamStore._admit_attempt` to consult a qualification port. | Rejected. It changes a shipped store with a campaign of record, and a cross-database read inside its transaction would still give no atomicity. |
| 3 | Leave it all to AD-1288. | Rejected. The acceptance list demands the slot-boundary proof in this AD. |

Semantics fixed here: **every slot requires a `qualified` profile**. A non-empty `qualification_ids` must contain `evaluation_suite.qualification_id`, and a non-empty `pinned_profile_refs` must contain the profile reference. Both only narrow the set. Role and task class must be equal to the slot's.

### D6. Migration policy for "no inherited credential"

| Rank | Option | Verdict |
|---|---|---|
| 1 | **No migration in S1.** Any component change gives a new reference with zero evaluations. No API copies or links evidence between references. M2 #16 and M3 #11 prove it per component. | **Chosen.** This is the weakest and safest option, and the acceptance text allows it. |
| 2 | A declared equivalence migration (for example, a dataset superset carries the pass forward). | Considered, deferred. It needs a governed approver, so it belongs to a later AD. |

### D7. Connection model and cancellation

| Rank | Option | Verdict |
|---|---|---|
| 1 | AD-1299 S1b's per-operation `_open` (`repair_evidence_store.py:277-297`) copied with this module's log text: one connection per operation from the injected `ConnectionFactory`, `BEGIN IMMEDIATE`, no explicit `ROLLBACK` (closing discards uncommitted work), `close()` awaited in `finally`, one `asyncio.Lock`. | **Chosen.** |
| 2 | Extract a shared helper now. | Deferred: S1b declared "if a third store needs it, extract a shared helper then". This is the third, but extraction would edit S1b's `_open`, whose mutants X1/X2 are pinned in a fresh campaign of record. **Residual R-1** for the orchestrator to file: extract it once AD-1299 S2 has landed. |

**Normative cancellation contract (every public method):**

- **N1.** `CancelledError` propagates. The store never catches it: its `try`s around an `await` are `_open`'s guard on `db.close()`, which catches `Exception`, and `_set_wal`'s, which catches `sqlite3.OperationalError` (round 3); neither catches `CancelledError` (a `BaseException`).
- **N2.** For a write, `CancelledError` means the outcome is unknown: the call may or may not have recorded.
- **N3.** Every write is idempotent for identical input (`register_profile` by content, `record_evaluation` by `evidence_ref`, `invalidate_profile` by `(profile_ref, invalidation_id, reason_code)`). Retrying the identical call is safe and returns the stored result either way (M2 #6, #13, #22).
- **N4.** No promise is made about when `CancelledError` arrives relative to the connection's cleanup, the lock's release, or a queued COMMIT.

Implementation note (not normative, aiosqlite 0.22.1, pydantic 2.12.5 in this venv): a cancel that lands before the COMMIT is queued records nothing, because the uncommitted rows die with the connection (M2 #22). S1b measured the after-COMMIT timing (`ad-1299-s1b-evidence-completion-ledger.md` D4a), and this slice makes no claim about it.

### D8. Authority

Qualification grants nothing. The weakest true, tested statement: **no field of any S1 model or result type has a name containing `scope`, `rank`, `lease`, `grant`, `authority` or `permission`** (M1 #13, M2 #25, each with a negative control on `AuthorityCeiling`). **The two S1 modules import no ProbOS module outside an explicit allowlist** (M1 #14, M2 #24). Neither test says that downstream code cannot misuse a result. AD-1288 leases authority from `AuthorityCeiling` alone.

### D9. Failure tiers

| Condition | Tier | Behaviour |
|---|---|---|
| Wrong type or malformed argument | Propagate | `TypeError` / `ValueError` with a stable code, before any write |
| Store not started, stopped, or clock not an `int`/`float` in `[0, 253402300799]` (NaN, infinities and ints of any size included) | Propagate | `ProfileQualificationStoreUnavailable` (`..._store_unavailable` / `..._clock_invalid`) |
| **(R2, C1)** `start()` on a file whose schema objects are not exactly this module's (D3a) | Propagate | `logger.error` naming up to 16 differing objects, then `ProfileQualificationStoreUnavailable("profile_qualification_layout_mismatch")`; **(R3, M1)** the store issues no schema or data write to the file (**R4, E2:** SQLite's own hot-journal or WAL recovery on open, and its checkpoint when the last connection closes, can still change the file and its sidecars; a rollback-journal file that needs no recovery stays byte-identical, #34); the store stays stopped |
| **(R3, H1)** `PRAGMA journal_mode=WAL` after the layout commit answers `SQLITE_BUSY` (another connection holds the lock; **R4, E1:** the busy handler is off for the switch, so an EXCLUSIVE holder is answered at once too), or SQLite answers a mode other than `wal` | Log-and-degrade | Retried up to `_WAL_ATTEMPTS` (50) tries `_WAL_RETRY_DELAY_S` (0.1 s) apart. Still busy, or another mode answered: one `logger.warning` naming the mode, and the store starts in the file's current mode (D3b). Not claimed: SQLite documents a very small power-loss corruption risk for `synchronous=NORMAL` in rollback mode on older filesystems; the WARNING is the signal. Any other error from the switch, including an `OperationalError` with no `sqlite_errorcode` (R4, E3), propagates unchanged and the store stays stopped |
| **(R3, L1)** `start()` on a started store; a `start()` cancelled while waiting for the lock | Not a failure | Returns at once, checking nothing; a cancelled one leaves a started store started |
| Unknown profile on a write; conflicting evaluation or invalidation; **(R2, C2)** a write needing a sequence above `2**53-1` | Propagate | `ProfileQualificationConflict` (`profile_unknown`, `profile_evaluation_conflict`, `profile_invalidation_conflict`, `profile_sequence_exhausted`); nothing written |
| A stored row that decides or is returned does not verify: schema version, canonical text against its content reference, or a store stamp out of type or range (times `[0, 253402300799000]` ms, sequence `[1, 2**53-1]`) | Propagate (data integrity) | `logger.error`, then `ProfileQualificationIntegrityError("profile_qualification_integrity")` |
| A row missing from a selection (deleted, or edited so no selection reaches it, e.g. an invalidation moved to another key), or a store stamp rewritten within type and range | Not detected (R-2, R-3) | Per-row verification sees only rows the store uses (a row a query fetches beyond `limit` is not examined). Indistinguishable from a row never written or stamped that way. Moving an evaluation or profile needs an edit to its canonical text, which then fails verification wherever it is read |
| Slot boundary refuses | Propagate | `SlotAdmissionRefused(code)` and an `info` log; `record_attempt` is not called |
| `close()` fails | Log-and-degrade | `logger.warning`; the operation's own result or error stands (in `start()` too: a start whose only failure is its close succeeds) |
| Engine-level shape | Not claimed | The engine's own checks are `schema_version = 1` per table, the triggers, the unique keys, the generated columns (a raw `UPDATE` of one is refused by SQLite) and, on the store's own connections, foreign keys. Every other rule is enforced in Python before a write and re-verified on read. A raw writer can insert a row the store then refuses to read, and a raw writer that forges valid content is indistinguishable from a real evaluator: the store **detects a row it uses that does not verify; it does not detect a missing or re-stamped row, and it does not authenticate evaluators** (no signing; AD-1047 keys are a Captain decision) |

---

## Section 0: Event types

None. S1 adds no `EventType`.

## Section 1 (M1): `src/probos/cognitive/execution_profile.py` (new, full file)

```python
"""AD-1287 S1: execution profiles -- the exact combination a worker slot qualifies -- and their evaluation evidence.

An ``ExecutionProfile`` names one exact combination: role, task class, the resource digest of each
cognitive skill, the model (provider, name, version label), each prompt revision, each tool's schema
and implementation digests, the policy digest, and the evaluation suite (its id, revision, dataset
digest, pass rule and validity). Its identity is ``sha256(PROFILE_DOMAIN + RFC 8785 bytes)`` over
``model_dump(mode="json")``, computed with AD-1286's ``canonicalize_projection``. Identity material
holds no floats. Component sequences are sorted by their key at validation and a duplicate key is
refused, so declaration order never changes a reference. Every field is always emitted: a new field
is a new schema version, never a silent re-hash of v1.

Evidence is keyed by profile reference and this slice has no migration path, so a profile that
differs in any component starts with no evaluation. ``EvaluationRecord`` is one evaluator run, raw:
per case, whether it passed, its quality score in basis points, its cost in micro-USD and its latency
in milliseconds, all integers. ``assess_evaluation`` turns one record plus the store's facts (issue
time, invalidation, now) into a status; ``slot_refusal`` compares a profile with a slot's declared
constraints. These types carry no tool scope, data scope, rank or lease, and nothing here grants
authority: qualification permits selection consideration only (AD-1288 leases authority).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict

from probos.cognitive.elastic_team import ElasticId, Revision, Sha256Ref, WorkerSlot, canonicalize_projection

EXECUTION_PROFILE_SCHEMA_VERSION: Final = 1
PROFILE_DOMAIN: Final = b"probos.execution_profile/profile/v1\x00"
EVALUATION_DOMAIN: Final = b"probos.execution_profile/evaluation/v1\x00"
BASIS_POINTS: Final = 10_000

_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,127}$")
_MAX_COMPONENTS: Final = 32
_MAX_OBSERVATIONS: Final = 1_024
_MAX_SAFE_INT: Final = 2**53 - 1
_MAX_VALIDITY_SECONDS: Final = 31_622_400  # 366 days

QualificationStatus = Literal[
    "qualified",
    "unevaluated",
    "invalidated",
    "expired",
    "structurally_invalid",
    "insufficient_sample",
    "failed",
]


def _int_range(low: int, high: int, code: str) -> Callable[[Any], int]:
    def check(value: Any) -> int:
        if type(value) is not int or not low <= value <= high:
            raise ValueError(code)
        return value

    return check


def _label(value: Any) -> str:
    if type(value) is not str or _LABEL_RE.fullmatch(value) is None:
        raise ValueError("execution_profile_model_invalid")
    return value


def _keyed(
    model: type[BaseModel], key: str, minimum: int, maximum: int, code: str,
) -> Callable[[Any], tuple[Any, ...]]:
    """Sort a component sequence by ``key`` and refuse a duplicate key, so declaration order never matters."""

    def check(value: Any) -> tuple[Any, ...]:
        if type(value) not in (list, tuple) or not minimum <= len(value) <= maximum:
            raise ValueError(code)
        keyed: list[tuple[str, Any]] = []
        for entry in value:
            if type(entry) is model:
                name: Any = getattr(entry, key)
            elif type(entry) is dict:
                name = entry.get(key)
            else:
                name = None
            if type(name) is not str:
                raise ValueError(code)
            keyed.append((name, entry))
        names = [name for name, _ in keyed]
        if len(set(names)) != len(names):
            raise ValueError(code)
        return tuple(entry for _, entry in sorted(keyed, key=lambda pair: pair[0]))

    return check


ModelLabel = Annotated[str, BeforeValidator(_label)]
ProfileSchemaVersion = Annotated[
    Literal[1], BeforeValidator(_int_range(1, 1, "execution_profile_schema_version_invalid"))
]
MinSamples = Annotated[int, BeforeValidator(_int_range(1, _MAX_OBSERVATIONS, "execution_profile_suite_invalid"))]
PassBasisPoints = Annotated[int, BeforeValidator(_int_range(1, BASIS_POINTS, "execution_profile_suite_invalid"))]
ValiditySeconds = Annotated[
    int, BeforeValidator(_int_range(1, _MAX_VALIDITY_SECONDS, "execution_profile_suite_invalid"))
]
ScoreBasisPoints = Annotated[int, BeforeValidator(_int_range(0, BASIS_POINTS, "profile_evaluation_invalid"))]
Measure = Annotated[int, BeforeValidator(_int_range(0, _MAX_SAFE_INT, "profile_evaluation_invalid"))]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class SkillComponent(_Frozen):
    """One AD-596 cognitive skill by ``CognitiveSkillEntry.name`` and the digest of its resources."""

    skill_name: ElasticId
    resource_digest: Sha256Ref


class ModelComponent(_Frozen):
    """The model a profile runs on: ``ModelDescriptor.provider`` and ``.name``, plus the provider's version label."""

    provider: ElasticId
    name: ModelLabel
    version: ModelLabel


class PromptComponent(_Frozen):
    """One prompt by id and the digest of the exact revision used."""

    prompt_id: ElasticId
    revision_digest: Sha256Ref


class ToolComponent(_Frozen):
    """One tool by ``Tool.tool_id`` and digests of its declared schemas and implementation. Names it; grants nothing."""

    tool_id: ElasticId
    schema_digest: Sha256Ref
    implementation_digest: Sha256Ref


class PolicyComponent(_Frozen):
    """The digest of the policy and permission profile a worker would run under. A reference, never a grant."""

    policy_digest: Sha256Ref


class EvaluationSuite(_Frozen):
    """The evaluation that decides qualification: id, revision, dataset, pass rule and how long a pass counts.

    ``qualification_id`` is the value ``WorkerSlot.qualification.qualification_ids`` names.
    """

    qualification_id: ElasticId
    suite_revision: Revision
    dataset_digest: Sha256Ref
    min_samples: MinSamples
    min_pass_bp: PassBasisPoints
    validity_seconds: ValiditySeconds


class ExecutionProfile(_Frozen):
    """One exact execution profile. Any component change gives a different ``content_ref()``."""

    schema_version: ProfileSchemaVersion
    role_id: ElasticId
    task_class: ElasticId
    skills: Annotated[
        tuple[SkillComponent, ...],
        BeforeValidator(_keyed(SkillComponent, "skill_name", 0, _MAX_COMPONENTS, "execution_profile_skills_invalid")),
    ]
    model: ModelComponent
    prompts: Annotated[
        tuple[PromptComponent, ...],
        BeforeValidator(_keyed(PromptComponent, "prompt_id", 0, _MAX_COMPONENTS, "execution_profile_prompts_invalid")),
    ]
    tools: Annotated[
        tuple[ToolComponent, ...],
        BeforeValidator(_keyed(ToolComponent, "tool_id", 0, _MAX_COMPONENTS, "execution_profile_tools_invalid")),
    ]
    policy: PolicyComponent
    evaluation_suite: EvaluationSuite

    def canonical_bytes(self) -> bytes:
        """RFC 8785 bytes of the full projection (no domain prefix); what the store persists."""
        return canonicalize_projection(self.model_dump(mode="json"))

    def content_ref(self) -> str:
        """The profile's identity: ``sha256(PROFILE_DOMAIN + canonical_bytes())``."""
        return hashlib.sha256(PROFILE_DOMAIN + self.canonical_bytes()).hexdigest()


class EvaluationObservation(_Frozen):
    """One evaluation case, raw. Integers only: score in basis points, cost in micro-USD, latency in ms."""

    case_id: ElasticId
    passed: bool
    score_bp: ScoreBasisPoints
    cost_micro_usd: Measure
    latency_ms: Measure


class EvaluationRecord(_Frozen):
    """One evaluation run of one profile as the evaluator reports it. The store stamps issue time and sequence.

    ``evaluator_id`` is provenance only; this slice does not authenticate it.
    """

    schema_version: ProfileSchemaVersion
    profile_ref: Sha256Ref
    evaluation_id: ElasticId
    evaluator_id: ElasticId
    structurally_valid: bool
    observations: Annotated[
        tuple[EvaluationObservation, ...],
        BeforeValidator(_keyed(EvaluationObservation, "case_id", 1, _MAX_OBSERVATIONS, "profile_evaluation_invalid")),
    ]

    @property
    def sample_size(self) -> int:
        """How many cases were observed."""
        return len(self.observations)

    @property
    def pass_count(self) -> int:
        """How many observed cases passed."""
        return sum(1 for observation in self.observations if observation.passed)

    def canonical_bytes(self) -> bytes:
        """RFC 8785 bytes of the full record (no domain prefix); what the store persists."""
        return canonicalize_projection(self.model_dump(mode="json"))

    def content_ref(self) -> str:
        """The record's identity (its ``evidence_ref``): ``sha256(EVALUATION_DOMAIN + canonical_bytes())``."""
        return hashlib.sha256(EVALUATION_DOMAIN + self.canonical_bytes()).hexdigest()


def expires_at_ms(profile: ExecutionProfile, issued_at_ms: int) -> int:
    """When an evaluation issued at ``issued_at_ms`` stops counting: issue time plus the suite's validity."""
    return issued_at_ms + profile.evaluation_suite.validity_seconds * 1_000


def assess_evaluation(
    profile: ExecutionProfile,
    record: EvaluationRecord,
    *,
    issued_at_ms: int,
    invalidated: bool,
    now_ms: int,
) -> QualificationStatus:
    """The status ``record`` gives ``profile`` at ``now_ms``. The first matching rule wins:

    ``invalidated``; ``expired`` (``now_ms`` at or after expiry); ``structurally_invalid``;
    ``insufficient_sample`` (fewer observations than ``min_samples``); ``failed`` (pass rate below
    ``min_pass_bp``, compared in integers, so a rate exactly at the threshold qualifies); otherwise
    ``qualified``.

    Raises:
        TypeError: ``profile_evaluation_type_invalid`` for a wrong argument type.
        ValueError: ``profile_evaluation_profile_mismatch`` when ``record`` is evidence for another profile.
    """
    if (
        type(profile) is not ExecutionProfile
        or type(record) is not EvaluationRecord
        or type(issued_at_ms) is not int
        or type(now_ms) is not int
        or type(invalidated) is not bool
    ):
        raise TypeError("profile_evaluation_type_invalid")
    if record.profile_ref != profile.content_ref():
        raise ValueError("profile_evaluation_profile_mismatch")
    suite = profile.evaluation_suite
    if invalidated:
        return "invalidated"
    if now_ms >= expires_at_ms(profile, issued_at_ms):
        return "expired"
    if not record.structurally_valid:
        return "structurally_invalid"
    if record.sample_size < suite.min_samples:
        return "insufficient_sample"
    if record.pass_count * BASIS_POINTS < suite.min_pass_bp * record.sample_size:
        return "failed"
    return "qualified"


def slot_refusal(slot: WorkerSlot, profile: ExecutionProfile) -> str | None:
    """The first of ``slot``'s declared constraints ``profile`` does not meet, as a stable code, or None.

    Role and task class must be equal; a non-empty ``qualification_ids`` must contain the suite's
    ``qualification_id``; a non-empty ``pinned_profile_refs`` must contain the profile's reference.
    Qualification status is a separate check (``check_slot_qualification``).

    Raises:
        TypeError: ``profile_slot_type_invalid`` for a wrong argument type.
    """
    if type(slot) is not WorkerSlot or type(profile) is not ExecutionProfile:
        raise TypeError("profile_slot_type_invalid")
    if profile.role_id != slot.role_id:
        return "profile_role_mismatch"
    if profile.task_class != slot.task_class:
        return "profile_task_class_mismatch"
    wanted = slot.qualification.qualification_ids
    if wanted and profile.evaluation_suite.qualification_id not in wanted:
        return "profile_qualification_id_mismatch"
    pinned = slot.qualification.pinned_profile_refs
    if pinned and profile.content_ref() not in pinned:
        return "profile_not_pinned"
    return None
```

## Section 2 (M1): `tests/test_ad1287_execution_profile.py` (new)

Fixtures (literal dicts in the test file): `_SUITE = {"qualification_id": "finding_review", "suite_revision": 1, "dataset_digest": "d"*64, "min_samples": 4, "min_pass_bp": 7500, "validity_seconds": 86400}`. `_PROFILE = {"schema_version": 1, "role_id": "reviewer", "task_class": "finding_review", "skills": [{"skill_name": "code-review", "resource_digest": "1"*64}, {"skill_name": "audit-trail", "resource_digest": "2"*64}], "model": {"provider": "anthropic", "name": "claude-sonnet-5.5", "version": "2026-09-01"}, "prompts": [{"prompt_id": "review.system", "revision_digest": "3"*64}], "tools": [{"tool_id": "codebase_query", "schema_digest": "4"*64, "implementation_digest": "5"*64}], "policy": {"policy_digest": "6"*64}, "evaluation_suite": _SUITE}`. The skills are declared deliberately unsorted. `_observations(passes, total)` gives cases `c001`..`cNNN`, the first `passes` passing, with `score_bp` 9000 or 1000, `cost_micro_usd` 120 and `latency_ms` 800. `_record(profile_ref, evaluation_id="eval-1", passes=4, total=4, structurally_valid=True, evaluator_id="qual-harness")`. Export `_PROFILE`, `_profile(**path_overrides)`, `_record` and `_observations` for M2 and M3.

**Known answers.** Compute `_KAT_PROFILE_REF` and `_KAT_EVALUATION_REF` ONCE, with a scratch run that imports only `_independent_digest` from `tests.test_ad1286_elastic_team_contract` (`:134`) and never `probos.cognitive.execution_profile`. Run it over `_canonical_profile()`, a deep copy written by hand in the test with `skills`, `prompts` and `tools` sorted by their key, using domain literals written as bytes in the test. For the record KAT, use `_record(_KAT_PROFILE_REF)` with observations declared in REVERSE case order, also sorted by hand. Paste both literals.

| # | Test | Asserts |
|---|---|---|
| 1 | `test_profile_reference_matches_independent_known_answer` | `ExecutionProfile.model_validate(_PROFILE).content_ref() == _KAT_PROFILE_REF`; `canonical_bytes() == _independent_jcs(_canonical_profile())` |
| 2 | `test_evaluation_reference_matches_independent_known_answer` | as #1 for the record (`_KAT_EVALUATION_REF`) |
| 3 | `test_reference_is_stable_in_a_fresh_interpreter` | `subprocess.run([sys.executable, "-c", <validate argv[1] JSON, print content_ref()>, json.dumps(_PROFILE)], env={**os.environ, "PYTHONPATH": <worktree src>, "PYTHONHASHSEED": "12345"}, timeout=60, check=True)`; stdout equals `_KAT_PROFILE_REF` |
| 4 | `test_component_order_does_not_change_the_reference` | reversing `skills`, `prompts`, `tools` (profile) and `observations` (record) leaves both refs unchanged |
| 5 | `test_each_component_change_gives_a_new_reference` (parametrize 19 paths) | `role_id`, `task_class`, `skills.0.resource_digest`, skill added, skill removed, `model.provider`, `model.name`, `model.version`, `prompts.0.revision_digest`, `tools.0.schema_digest`, `tools.0.implementation_digest`, `policy.policy_digest`, `evaluation_suite.{qualification_id, suite_revision, dataset_digest, min_samples, min_pass_bp, validity_seconds}`, and one new-prompt case: each ref differs from the KAT; a companion assertion checks that the 19 refs are pairwise distinct |
| 6 | `test_profile_refuses_malformed_input` (parametrize) | schema_version `2` and `True`; role `"bad id"`; duplicate skill name; 33 skills; skills `"x"`; resource digest `"A"*64`; model name `"has space"` and `"a"*129`; a prompt missing `revision_digest`; duplicate tool id; extra top-level key; `min_samples` `0`, `1025`, `True`; `min_pass_bp` `0`, `10001`; `validity_seconds` `0`, `31_622_401`; `suite_revision` `0` -> `pydantic.ValidationError` |
| 7 | `test_evaluation_record_refuses_malformed_input` (parametrize) | empty observations; 1025 observations; duplicate `case_id`; `passed` `1`; `score_bp` `10001` and `50.5`; `cost_micro_usd` `-1`; `latency_ms` `2**53`; `structurally_valid` `"yes"`; `profile_ref` `"x"`; extra key -> `ValidationError` |
| 8 | `test_assess_evaluation_status_boundaries` (parametrize) | issued 1_000_000, now 1_000_001, not invalidated: 4/4 and 3/4 -> `qualified` (3*10000 == 7500*4, the equality boundary); 2/4 -> `failed`; 4/5 -> `qualified`; 3/5 -> `failed`; 3/3 -> `insufficient_sample`; 4/4 with `structurally_valid=False` -> `structurally_invalid`; now = expiry - 1 -> `qualified`; now = expiry -> `expired` |
| 9 | `test_assess_evaluation_precedence` | invalidated + expired + structurally invalid + insufficient -> `invalidated`; expired + structurally invalid -> `expired`; structurally invalid + insufficient + failed -> `structurally_invalid`; insufficient + failed -> `insufficient_sample` |
| 10 | `test_assess_evaluation_refuses_wrong_types_and_foreign_records` | a record whose `profile_ref` is another profile's -> `ValueError("profile_evaluation_profile_mismatch")`; `now_ms=True`, `issued_at_ms=1.0`, `invalidated=0`, `profile=<dict>` -> `TypeError("profile_evaluation_type_invalid")` |
| 11 | `test_slot_refusal_codes` (parametrize) | build `WorkerSlot`s from `tests.test_ad1286_elastic_team_contract._review_slot(...)` (role `reviewer`, task `finding_review`, qualification id `finding_review`): matching -> `None`; empty `qualification_ids` and empty pins -> `None`; role `auditor` -> `profile_role_mismatch`; task -> `profile_task_class_mismatch`; ids `["other"]` -> `profile_qualification_id_mismatch`; pins `["e"*64]` -> `profile_not_pinned`; pins `[profile ref]` -> `None` |
| 12 | `test_slot_refusal_refuses_wrong_types` | dict slot or dict profile -> `TypeError("profile_slot_type_invalid")` |
| 13 | `test_profile_types_carry_no_authority_fields` | recursive walk of `model_fields` from `ExecutionProfile` and `EvaluationRecord`: no field name contains `scope`, `rank`, `lease`, `grant`, `authority` or `permission`. **Negative control:** the same walker flags `probos.cognitive.elastic_team.AuthorityCeiling` (`tool_scopes`) |
| 14 | `test_module_imports_only_elastic_team` | AST of the module file (all import nodes, any depth): the `probos.*` imports are exactly `{"probos.cognitive.elastic_team"}`. **Negative control:** the helper flags `ast.parse("import probos.tools.registry")` and `ast.parse("from probos.tools import registry")` |
| 15 | `test_expires_at_ms_adds_validity` | `expires_at_ms(profile, 1_000_000) == 1_000_000 + 86_400_000` |

## Section 3 (M2): `src/probos/cognitive/profile_qualification_store.py` (new, full file)

```python
"""AD-1287 S1: ProfileQualificationStore -- insert-only execution profiles, evaluation evidence and invalidations.

Three ``WITHOUT ROWID`` tables; nine triggers abort every UPDATE, every DELETE and every INSERT that
would replace a row (including through a secondary unique key). The store issues plain INSERTs after
read-then-insert checks inside ``BEGIN IMMEDIATE``. Profiles and evaluation records are stored as
RFC 8785 canonical text under their content reference. The columns the store selects and enforces
uniqueness by (a profile's role and task class; an evaluation's profile and evaluation id) are
``VIRTUAL`` columns generated from that text, so they hold no value of their own to edit.

``start()`` accepts a database holding no schema objects (it creates them) or exactly this module's:
the same tables, indexes and triggers, each stored with the definition this module writes, which
SQLite re-reads every time it opens the file. Anything else is refused, and the store issues no schema
or data write to a file it refuses. SQLite itself can still change a refused file: opening it replays
a hot rollback journal a crashed writer left, or recovers its ``-wal`` file, and closing the last
connection to a WAL-mode file can checkpoint it and remove its ``-wal`` and ``-shm`` files. A refused file that needs no such
recovery, in rollback-journal mode, is left byte-identical. SQLite's own ``sqlite_*`` objects and
page-level integrity are not checked, and a layout changed while the store is started is seen only
when a stopped store is next started. WAL is requested after the check and tried again while another
connection holds the lock; a file that does not end in WAL is logged as a WARNING and served as it is.

Verification is per row, on read. Every stored row the store uses -- to decide a result or to return
it, including each profile ``find_slot_candidates`` examines -- is re-verified first (schema version;
canonical text against its content reference; each store stamp's type and range); one that does not
verify raises ``ProfileQualificationIntegrityError`` and is never relied on. A row a query fetches but
does not examine (``find_slot_candidates`` stops at ``limit``) is not verified. That is all the store
detects. A row that is missing -- deleted, or edited so that no selection
reaches it any more (for example an invalidation moved to another key) -- is indistinguishable from
one never written (R-2). Store stamps (sequence, issue, record and invalidation times) are bound to no
content identity, so a stamp rewritten within its type and range is not detected (R-3). A row forged
with valid content is indistinguishable from a real one: the store does not authenticate evaluators
(no signing; AD-1047). The engine's own checks are ``schema_version = 1`` per table, the triggers, the
unique keys, the generated columns and, on the store's own connections, foreign keys; every other
rule is enforced in Python before a write and on read, so a raw writer can insert a row the store
then refuses to read.

Evaluations and invalidations draw one store-wide sequence number, at most ``2**53 - 1``; a write that
would need a higher one is refused and writes nothing. The latest evaluation of a
profile (highest sequence) decides its status; an invalidation applies to every evaluation of that
profile with a lower sequence, so requalification is a new evaluation recorded after it. Expiry is
wall clock: issue time plus the suite's validity, both stamped by this store's clock.

Not wired: nothing constructs or starts this store in production; AD-1288 commission admission is
the intended caller of ``admit_qualified_attempt``. Qualification never grants a tool, data scope,
rank or authority lease.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

from pydantic import TypeAdapter

from probos.cognitive.elastic_team import ElasticId, ElasticTeamSpec, WorkerAttempt, WorkerSlot, is_sha256_ref
from probos.cognitive.execution_profile import (
    EvaluationRecord,
    ExecutionProfile,
    QualificationStatus,
    assess_evaluation,
    expires_at_ms,
    slot_refusal,
)
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

PROFILE_QUALIFICATION_SCHEMA_VERSION: Final = 1
MAX_CANDIDATES: Final = 64
_MAX_SCAN = 128  # profiles examined per find_slot_candidates call; not Final so a test can lower it
_MAX_REASONS: Final = 16
_MAX_TIMESTAMP: Final = 253_402_300_799.0  # 9999-12-31T23:59:59Z in seconds: the largest clock accepted
_MAX_TIMESTAMP_MS: Final = 253_402_300_799_000  # the same instant in the store's integer milliseconds
_MAX_SEQ: Final = 2**53 - 1
_WAL_ATTEMPTS = 50  # tries of PRAGMA journal_mode=WAL in start(); not Final so a test can lower it
_WAL_RETRY_DELAY_S = 0.1  # seconds between those tries, about 5 s in all with no busy handler; not Final either
_REASON_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_ELASTIC_ID: Final = TypeAdapter(ElasticId)

# One statement per schema object, run in this order on a database holding none. SQLite stores each
# statement's text as written after normalising its leading keywords and spaces and removing any TEMP
# keyword or database-name qualifier (https://www.sqlite.org/schematab.html, section 3); these statements
# are already in that normalised form, so a file holding this layout holds exactly these texts in
# ``sqlite_master``, and ``start()`` compares them. Each CREATE TABLE is bound to its own name so
# ``scripts/check_store_registry.py`` detects the tables (AD-1256 rule (a)).
_PROFILES_TABLE: Final = """CREATE TABLE execution_profiles (
    profile_ref TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1), -- execution_profiles
    canonical_json TEXT NOT NULL,
    recorded_at_ms INTEGER NOT NULL,
    role_id TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.role_id')) VIRTUAL,
    task_class TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.task_class')) VIRTUAL
) WITHOUT ROWID"""  # end execution_profiles
_EVALUATIONS_TABLE: Final = """CREATE TABLE profile_evaluations (
    evidence_ref TEXT PRIMARY KEY,
    seq INTEGER NOT NULL UNIQUE,
    issued_at_ms INTEGER NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1), -- profile_evaluations
    canonical_json TEXT NOT NULL,
    profile_ref TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.profile_ref')) VIRTUAL
        REFERENCES execution_profiles (profile_ref),
    evaluation_id TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.evaluation_id')) VIRTUAL,
    UNIQUE (profile_ref, evaluation_id)
) WITHOUT ROWID"""  # end profile_evaluations
_INVALIDATIONS_TABLE: Final = """CREATE TABLE profile_invalidations (
    profile_ref TEXT NOT NULL REFERENCES execution_profiles (profile_ref),
    invalidation_id TEXT NOT NULL,
    seq INTEGER NOT NULL UNIQUE,
    reason_code TEXT NOT NULL,
    invalidated_at_ms INTEGER NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1), -- profile_invalidations
    PRIMARY KEY (profile_ref, invalidation_id)
) WITHOUT ROWID"""  # end profile_invalidations
_SCHEMA_STATEMENTS: Final = (
    _PROFILES_TABLE,
    "CREATE INDEX execution_profiles_by_slot ON execution_profiles (role_id, task_class, profile_ref)",
    _EVALUATIONS_TABLE,
    "CREATE INDEX profile_evaluations_latest ON profile_evaluations (profile_ref, seq)",
    _INVALIDATIONS_TABLE,
    "CREATE INDEX profile_invalidations_latest ON profile_invalidations (profile_ref, seq)",
    """CREATE TRIGGER execution_profiles_no_update BEFORE UPDATE ON execution_profiles
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER execution_profiles_no_delete BEFORE DELETE ON execution_profiles
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER execution_profiles_no_replace BEFORE INSERT ON execution_profiles
WHEN EXISTS (SELECT 1 FROM execution_profiles WHERE profile_ref = NEW.profile_ref)
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_evaluations_no_update BEFORE UPDATE ON profile_evaluations
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_evaluations_no_delete BEFORE DELETE ON profile_evaluations
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_evaluations_no_replace BEFORE INSERT ON profile_evaluations
WHEN EXISTS (SELECT 1 FROM profile_evaluations WHERE evidence_ref = NEW.evidence_ref OR seq = NEW.seq
             OR (profile_ref = json_extract(NEW.canonical_json, '$.profile_ref')
                 AND evaluation_id = json_extract(NEW.canonical_json, '$.evaluation_id')))
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_invalidations_no_update BEFORE UPDATE ON profile_invalidations
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
    """CREATE TRIGGER profile_invalidations_no_delete BEFORE DELETE ON profile_invalidations
BEGIN SELECT RAISE(ABORT, 'profile_qualification_immutable'); END""",
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

_PROFILE_COLUMNS: Final = "profile_ref, schema_version, canonical_json, recorded_at_ms"
_EVALUATION_COLUMNS: Final = "evidence_ref, seq, issued_at_ms, expires_at_ms, schema_version, canonical_json"
_INVALIDATION_COLUMNS: Final = "profile_ref, invalidation_id, seq, reason_code, invalidated_at_ms, schema_version"
# Each table's MAX(seq) is read from its ``seq`` unique index, so the work does not grow with the rows.
_NEXT_SEQ_SQL: Final = (
    "SELECT MAX(m) FROM (SELECT MAX(seq) AS m FROM profile_evaluations "
    "UNION ALL SELECT MAX(seq) AS m FROM profile_invalidations)"
)


class ProfileQualificationStoreUnavailable(RuntimeError):
    """The store has not been started, has stopped, refused its file's layout, or its clock is not a finite real
    in range. ``str(exc)`` is the code."""


class ProfileQualificationConflict(ValueError):
    """A write that contradicts the record, names a profile the store does not hold, or would need a sequence
    number above ``_MAX_SEQ``. ``str(exc)`` is the code."""


class ProfileQualificationIntegrityError(ValueError):
    """A stored row no longer verifies (data integrity: propagate)."""


class SlotAdmissionRefused(ValueError):
    """The slot boundary refused a profile; ``str(exc)`` is the stable code. Nothing was recorded."""


@dataclass(frozen=True)
class RecordedEvaluation:
    """One stored evaluation: the evaluator's raw record plus what this store stamped on it."""

    evidence_ref: str
    seq: int
    issued_at_ms: int
    expires_at_ms: int
    record: EvaluationRecord


@dataclass(frozen=True)
class RecordedInvalidation:
    """One stored invalidation of a profile's evaluations recorded before it."""

    profile_ref: str
    invalidation_id: str
    reason_code: str
    seq: int
    invalidated_at_ms: int


@dataclass(frozen=True)
class ProfileQualification:
    """A profile's status at ``assessed_at_ms`` with the evidence that decided it. Evidence, never a grant."""

    profile_ref: str
    profile: ExecutionProfile
    status: QualificationStatus
    deciding: RecordedEvaluation | None  # the latest evaluation; None when unevaluated
    invalidation_reasons: tuple[str, ...]  # reasons that apply to ``deciding``, oldest first, at most 16
    assessed_at_ms: int


@dataclass(frozen=True)
class CandidateQueryResult:
    """Qualified profiles meeting one slot's constraints, ascending by reference. Nothing is ranked or chosen.

    ``complete`` is True when every stored profile with the slot's role and task class after the cursor
    was examined; otherwise ``next_after`` resumes after the last one examined.
    """

    candidates: tuple[ProfileQualification, ...]
    examined: int
    complete: bool
    next_after: str | None


class ProfileQualificationReader(Protocol):
    """The narrow read port the slot boundary depends on (ISP); ``ProfileQualificationStore`` satisfies it."""

    async def get_qualification(self, profile_ref: str) -> ProfileQualification | None: ...


class TeamAttemptRecorder(Protocol):
    """The two ``ElasticTeamStore`` operations the slot boundary uses; ``ElasticTeamStore`` satisfies it."""

    async def get_team_spec(self, team_spec_ref: str) -> ElasticTeamSpec | None: ...

    async def record_attempt(self, attempt: WorkerAttempt) -> WorkerAttempt: ...


def _checked_now_ms(clock: Callable[[], float]) -> int:
    """The store's "now" in integer milliseconds, or ``ProfileQualificationStoreUnavailable`` for a bad clock.

    Only exact comparisons: NaN and both infinities fail the range test, and Python compares an int of any
    size with a float without converting it, so no int or float clock value raises anything else."""
    now = clock()
    if type(now) not in (int, float) or not 0 <= now <= _MAX_TIMESTAMP:
        raise ProfileQualificationStoreUnavailable("profile_qualification_clock_invalid")
    return int(now * 1_000)


def _integrity(what: str, key: object) -> ProfileQualificationIntegrityError:
    logger.error(
        "AD-1287: stored %s %s no longer verifies; refusing to rely on it, so no status is reported and no "
        "slot is admitted from it -- inspect or restore profile_qualifications.db",
        what,
        str(key)[:80],
    )
    return ProfileQualificationIntegrityError("profile_qualification_integrity")


def _is_elastic_id(value: object) -> bool:
    try:
        _ELASTIC_ID.validate_python(value)
    except ValueError:
        return False
    return True


def _is_stamp(value: object) -> bool:
    """A time this store stamped: integer milliseconds in ``[0, _MAX_TIMESTAMP_MS]``."""
    return type(value) is int and 0 <= value <= _MAX_TIMESTAMP_MS


def _is_seq(value: object) -> bool:
    """A sequence number this store drew: an integer in ``[1, _MAX_SEQ]``."""
    return type(value) is int and 1 <= value <= _MAX_SEQ


def _schema_objects(catalog: list[Any]) -> dict[tuple[str, str], Any]:
    """``(type, name) -> stored definition`` of the file's schema objects, without SQLite's own ``sqlite_*`` ones."""
    return {(kind, name): sql for kind, name, sql in catalog if not str(name).lower().startswith("sqlite_")}


def _layout_differences(found: dict[tuple[str, str], Any]) -> list[str]:
    """Names of the objects missing from ``found``, extra in it, or stored with another definition than this
    module writes; empty when ``found`` is exactly this module's layout."""
    differences = sorted(name for _kind, name in set(found) ^ set(_LAYOUT))
    differences += sorted(key[1] for key, sql in found.items() if key in _LAYOUT and sql != _LAYOUT[key])
    return differences


async def _query(db: Any, sql: str, params: tuple[Any, ...]) -> list[Any]:
    """Run one read and return every row. Rows are indexed positionally by every caller."""
    cursor = await db.execute(sql, params)
    return list(await cursor.fetchall())


async def _set_wal(db: Any) -> str | None:
    """Ask SQLite for WAL mode; return the journal mode it reports, or None when every try found the file busy.

    Another connection's lock makes the switch answer SQLITE_BUSY. Under a RESERVED lock (an open write
    transaction) SQLite answers at once; under an EXCLUSIVE lock (a commit in progress, or BEGIN EXCLUSIVE)
    it first runs the busy handler, which held one try for 7.45 s under ``busy_timeout=5000`` (measured,
    review round 4, E1). The handler is therefore turned off on this connection before the first try, so
    every try answers at once and this loop alone bounds the wait: ``_WAL_ATTEMPTS`` tries
    ``_WAL_RETRY_DELAY_S`` apart, about 5 s. ``start()`` closes the connection straight after, so no other
    statement runs without the handler. A busy answer is tried again; any other error propagates, including
    an ``OperationalError`` that carries no SQLite error code (one a connection wrapper built itself)."""
    await db.execute("PRAGMA busy_timeout=0")  # the loop owns the budget (review round 4, E1)
    for attempt in range(_WAL_ATTEMPTS):
        if attempt:
            await asyncio.sleep(_WAL_RETRY_DELAY_S)
        try:
            rows = await _query(db, "PRAGMA journal_mode=WAL", ())
        except sqlite3.OperationalError as exc:
            code = getattr(exc, "sqlite_errorcode", None)  # set only on errors the sqlite3 library raised (E3)
            if not isinstance(code, int) or code & 0xFF != sqlite3.SQLITE_BUSY:
                raise
            continue
        return str(rows[0][0]).lower()
    return None  # every try found the file busy


def _verified_profile(row: Any) -> ExecutionProfile:
    """Verify one ``_PROFILE_COLUMNS`` row: schema version, canonical text, content identity, record time."""
    ref, version, stored, recorded_at = row
    try:
        profile = ExecutionProfile.model_validate(json.loads(stored))
        verified = (
            type(version) is int
            and version == PROFILE_QUALIFICATION_SCHEMA_VERSION
            and profile.content_ref() == ref
            and profile.canonical_bytes().decode("utf-8") == stored
            and _is_stamp(recorded_at)
        )
    except (TypeError, ValueError):
        verified = False
    if not verified:
        raise _integrity("execution profile", ref)
    return profile


def _verified_evaluation(row: Any, profile_ref: str, profile: ExecutionProfile) -> RecordedEvaluation:
    """Verify one ``_EVALUATION_COLUMNS`` row of ``profile``: canonical text, identity, stamps and expiry."""
    evidence_ref, seq, issued, expires, version, stored = row
    try:
        record = EvaluationRecord.model_validate(json.loads(stored))
        verified = (
            type(version) is int
            and version == PROFILE_QUALIFICATION_SCHEMA_VERSION
            and record.content_ref() == evidence_ref
            and record.canonical_bytes().decode("utf-8") == stored
            and record.profile_ref == profile_ref
            and _is_seq(seq)
            and _is_stamp(issued)
            and type(expires) is int and expires == expires_at_ms(profile, issued)
        )
    except (TypeError, ValueError):
        verified = False
    if not verified:
        raise _integrity("profile evaluation", evidence_ref)
    return RecordedEvaluation(evidence_ref, seq, issued, expires, record)


def _verified_invalidation(row: Any, profile_ref: str) -> RecordedInvalidation:
    """Verify one ``_INVALIDATION_COLUMNS`` row of ``profile_ref``."""
    row_profile_ref, invalidation_id, seq, reason_code, invalidated_at, version = row
    verified = (
        row_profile_ref == profile_ref
        and _is_elastic_id(invalidation_id)
        and type(reason_code) is str
        and _REASON_RE.fullmatch(reason_code) is not None
        and _is_seq(seq)
        and _is_stamp(invalidated_at)
        and type(version) is int
        and version == PROFILE_QUALIFICATION_SCHEMA_VERSION
    )
    if not verified:
        raise _integrity("profile invalidation", (row_profile_ref, invalidation_id))
    return RecordedInvalidation(profile_ref, invalidation_id, reason_code, seq, invalidated_at)


async def _next_seq(db: Any) -> int:
    """One more than the highest sequence in either table (1 for an empty store). Called inside BEGIN IMMEDIATE,
    before the caller's INSERT, so a refusal here writes nothing.

    Raises ``ProfileQualificationConflict("profile_sequence_exhausted")`` when the highest is ``_MAX_SEQ``: a
    higher number would be a row this store refuses to read."""
    rows = await _query(db, _NEXT_SEQ_SQL, ())
    latest = rows[0][0]
    if latest is None:
        return 1
    if not _is_seq(latest):
        raise _integrity("sequence", latest)
    if latest == _MAX_SEQ:
        raise ProfileQualificationConflict("profile_sequence_exhausted")
    return latest + 1


async def _load_profile(db: Any, profile_ref: str) -> ExecutionProfile | None:
    rows = await _query(db, f"SELECT {_PROFILE_COLUMNS} FROM execution_profiles WHERE profile_ref = ?", (profile_ref,))
    return _verified_profile(rows[0]) if rows else None


async def _assess(db: Any, profile_ref: str, profile: ExecutionProfile, now_ms: int) -> ProfileQualification:
    """The profile's status from its latest evaluation and the invalidations recorded after it."""
    latest = await _query(
        db,
        f"SELECT {_EVALUATION_COLUMNS} FROM profile_evaluations WHERE profile_ref = ? ORDER BY seq DESC LIMIT 1",
        (profile_ref,),
    )
    if not latest:
        return ProfileQualification(profile_ref, profile, "unevaluated", None, (), now_ms)
    deciding = _verified_evaluation(latest[0], profile_ref, profile)
    later = await _query(
        db,
        f"SELECT {_INVALIDATION_COLUMNS} FROM profile_invalidations WHERE profile_ref = ? AND seq > ? "
        "ORDER BY seq LIMIT ?",
        (profile_ref, deciding.seq, _MAX_REASONS),
    )
    reasons = tuple(_verified_invalidation(row, profile_ref).reason_code for row in later)
    status = assess_evaluation(
        profile, deciding.record, issued_at_ms=deciding.issued_at_ms, invalidated=bool(reasons), now_ms=now_ms,
    )
    return ProfileQualification(profile_ref, profile, status, deciding, reasons, now_ms)


class ProfileQualificationStore:
    """Insert-only execution profiles, evaluation evidence and invalidations (AD-1287 S1).

    Public API:
        start() / stop() -- lifecycle; idempotent
        register_profile(profile) -> profile_ref -- idempotent
        get_profile(profile_ref) -> ExecutionProfile | None -- verified
        record_evaluation(record) -> RecordedEvaluation -- idempotent for an identical record
        invalidate_profile(profile_ref, invalidation_id, reason_code) -> RecordedInvalidation -- idempotent
        get_qualification(profile_ref) -> ProfileQualification | None -- satisfies ProfileQualificationReader
        find_slot_candidates(slot, *, limit, after) -> CandidateQueryResult -- bounded, deterministic

    Cancellation contract (every method): ``CancelledError`` propagates and is not swallowed; for a write
    it means the outcome is unknown. Every write is idempotent for identical input, so retrying the
    identical call is safe whether or not the cancelled one recorded. No promise is made about when
    ``CancelledError`` arrives relative to the connection's cleanup, the lock's release or a queued COMMIT.

    Raises:
        ProfileQualificationStoreUnavailable: not started, stopped, a refused file layout (``start``), or a clock
            that is not a finite real in range.
        ProfileQualificationConflict: a write that contradicts the record or exceeds the sequence bound;
            ``str(exc)`` is the code.
        ProfileQualificationIntegrityError: a stored row that decides or is returned does not verify.
    """

    def __init__(
        self,
        db_path: str,
        connection_factory: ConnectionFactory | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Nothing is opened until :meth:`start`. ``""`` and ``":memory:"`` are refused: evidence that forgets
        on restart defeats its purpose, and per-operation connections would each see an empty database."""
        if type(db_path) is not str or not db_path or db_path == ":memory:":
            raise ValueError("profile_qualification_store_path_invalid")
        self._db_path = db_path
        self._clock = clock
        self._started = False
        self._lock = asyncio.Lock()
        if connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            connection_factory = default_factory
        self._connection_factory: ConnectionFactory = connection_factory

    async def start(self) -> None:
        """Check the file's layout (creating it in a file that holds none), then admit operations. Idempotent.

        Accepts a database holding no schema objects, which it gives this module's layout, or exactly this
        module's layout. Any other file is refused inside one ``BEGIN IMMEDIATE``; the store issues no schema
        or data write to it (SQLite's own journal recovery and checkpoint can still change it). WAL is
        requested only after the check, and tried again while another connection holds the lock; a file that
        does not end in WAL is served as it is, with a WARNING. A start that finds the store stopped and fails
        leaves it stopped and propagates, except that a ``close()`` failure is logged and does not fail it
        (D9). A start that finds the store started returns at once without checking, and one cancelled while
        waiting for the lock leaves a started store started.

        Raises:
            ProfileQualificationStoreUnavailable: ``profile_qualification_layout_mismatch``.
        """
        async with self._lock:
            if self._started:
                return
            async with self._open() as db:
                await db.execute("BEGIN IMMEDIATE")
                found = _schema_objects(await _query(db, _CATALOG_SQL, ()))
                if not found:
                    for statement in _SCHEMA_STATEMENTS:
                        await db.execute(statement)
                else:
                    differences = _layout_differences(found)
                    if differences:
                        logger.error(
                            "AD-1287: %s does not hold the profile qualification layout (missing, extra or "
                            "differently defined: %s); refusing to start, and the store wrote no schema or data "
                            "to it -- move the file aside or restore it",
                            self._db_path,
                            ", ".join(differences[:16]),
                        )
                        raise ProfileQualificationStoreUnavailable("profile_qualification_layout_mismatch")
                await db.commit()
                mode = await _set_wal(db)
            self._started = True
        if mode != "wal":
            logger.warning(
                "AD-1287: %s is not in WAL mode (SQLite answered %s within %d tries); the store works without "
                "WAL, but its readers and its writer now wait on each other",
                self._db_path,
                mode or "busy on every try",
                _WAL_ATTEMPTS,
            )
        logger.info(
            "AD-1287: ProfileQualificationStore started (db=%s); profiles, evaluations and invalidations "
            "are insert-only",
            self._db_path,
        )

    async def stop(self) -> None:
        """Stop admitting operations. Waits for the lock, so a call holding it returns or raises first. Idempotent."""
        async with self._lock:
            was_started, self._started = self._started, False
        if was_started:
            logger.info(
                "AD-1287: ProfileQualificationStore stopped (db=%s); calls raise unavailable until start()",
                self._db_path,
            )

    @contextlib.asynccontextmanager
    async def _open(self) -> AsyncIterator[Any]:
        """One connection for one operation, with its own pragmas. Once ``connect`` has returned, ``close()``
        is awaited in ``finally`` on every exit path (a repeated cancellation can interrupt that wait); a
        ``close()`` that raises is logged, not raised, and that connection may then stay open until released."""
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
                    "AD-1287: closing a profile qualification connection failed; its uncommitted work was never "
                    "visible to other connections, and later writes may wait on its lock until it is released",
                    exc_info=True,
                )

    @contextlib.asynccontextmanager
    async def _operation(self) -> AsyncIterator[tuple[Any, int]]:
        """The frame of each of the six data methods: hold the lock, refuse when stopped, take "now", open one
        connection. ``start`` and ``stop`` take the lock but read no clock."""
        async with self._lock:
            if not self._started:
                raise ProfileQualificationStoreUnavailable("profile_qualification_store_unavailable")
            now_ms = _checked_now_ms(self._clock)
            async with self._open() as db:
                yield db, now_ms

    async def register_profile(self, profile: ExecutionProfile) -> str:
        """Store ``profile`` and return its reference. Idempotent: the same profile again writes nothing.

        Raises:
            TypeError: ``execution_profile_type_invalid``.
            ValueError: (``pydantic.ValidationError``) the profile no longer validates (built without validation).
            ProfileQualificationIntegrityError: the row stored under its reference does not verify.
        """
        if type(profile) is not ExecutionProfile:
            raise TypeError("execution_profile_type_invalid")
        profile = ExecutionProfile.model_validate(profile)  # a model_copy(update=...) skips validation
        profile_ref = profile.content_ref()
        canonical = profile.canonical_bytes().decode("utf-8")
        async with self._operation() as (db, now_ms):
            await db.execute("BEGIN IMMEDIATE")
            if await _load_profile(db, profile_ref) is None:
                await db.execute(
                    "INSERT INTO execution_profiles (profile_ref, schema_version, canonical_json, recorded_at_ms) "
                    "VALUES (?, ?, ?, ?)",
                    (profile_ref, PROFILE_QUALIFICATION_SCHEMA_VERSION, canonical, now_ms),
                )
            await db.commit()  # not shielded: a COMMIT queued before a cancel may still run (N2)
        return profile_ref

    async def get_profile(self, profile_ref: str) -> ExecutionProfile | None:
        """The profile stored under ``profile_ref``, verified, or None.

        Raises:
            ValueError: ``execution_profile_ref_invalid`` for a malformed reference.
            ProfileQualificationIntegrityError: the stored row does not verify.
        """
        if not is_sha256_ref(profile_ref):
            raise ValueError("execution_profile_ref_invalid")
        async with self._operation() as (db, _now_ms):
            return await _load_profile(db, profile_ref)

    async def record_evaluation(self, record: EvaluationRecord) -> RecordedEvaluation:
        """Store one evaluation run of a registered profile; this store stamps its issue time and sequence.

        Idempotent: an identical record returns what was stored the first time (same sequence and issue
        time) and writes nothing, so renewing a pass needs a new run (a new ``evaluation_id``).

        Raises:
            TypeError: ``profile_evaluation_type_invalid``.
            ValueError: (``pydantic.ValidationError``) the record no longer validates.
            ProfileQualificationConflict: ``profile_unknown``, ``profile_evaluation_conflict`` (this profile
                already holds a different record under this ``evaluation_id``) or ``profile_sequence_exhausted``.
                Nothing is written.
            ProfileQualificationIntegrityError: a row that decides the write does not verify.
        """
        if type(record) is not EvaluationRecord:
            raise TypeError("profile_evaluation_type_invalid")
        record = EvaluationRecord.model_validate(record)
        evidence_ref = record.content_ref()
        canonical = record.canonical_bytes().decode("utf-8")
        async with self._operation() as (db, now_ms):
            await db.execute("BEGIN IMMEDIATE")
            profile = await _load_profile(db, record.profile_ref)
            if profile is None:
                raise ProfileQualificationConflict("profile_unknown")
            rows = await _query(
                db,
                f"SELECT {_EVALUATION_COLUMNS} FROM profile_evaluations "
                "WHERE evidence_ref = ? OR (profile_ref = ? AND evaluation_id = ?)",
                (evidence_ref, record.profile_ref, record.evaluation_id),
            )
            stored = [_verified_evaluation(row, record.profile_ref, profile) for row in rows]
            if any(item.evidence_ref != evidence_ref for item in stored):
                raise ProfileQualificationConflict("profile_evaluation_conflict")
            if stored:
                await db.commit()
                return stored[0]
            seq = await _next_seq(db)
            recorded = RecordedEvaluation(evidence_ref, seq, now_ms, expires_at_ms(profile, now_ms), record)
            await db.execute(
                "INSERT INTO profile_evaluations (evidence_ref, seq, issued_at_ms, expires_at_ms, schema_version, "
                "canonical_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    evidence_ref,
                    seq,
                    recorded.issued_at_ms,
                    recorded.expires_at_ms,
                    PROFILE_QUALIFICATION_SCHEMA_VERSION,
                    canonical,
                ),
            )
            await db.commit()  # not shielded: a COMMIT queued before a cancel may still run (N2)
        return recorded

    async def invalidate_profile(
        self, profile_ref: str, invalidation_id: str, reason_code: str,
    ) -> RecordedInvalidation:
        """Record that ``profile_ref``'s evaluations recorded so far no longer qualify it.

        Applies to every evaluation of the profile with a lower sequence; an evaluation recorded later can
        qualify it again. Idempotent for the same ``invalidation_id`` and ``reason_code``.

        Raises:
            ValueError: ``profile_invalidation_invalid`` for a malformed reference, id or reason code.
            ProfileQualificationConflict: ``profile_unknown``, ``profile_invalidation_conflict`` (the id is
                already recorded with another reason) or ``profile_sequence_exhausted``. Nothing is written.
            ProfileQualificationIntegrityError: a row that decides the write does not verify.
        """
        if (
            not is_sha256_ref(profile_ref)
            or not _is_elastic_id(invalidation_id)
            or type(reason_code) is not str
            or _REASON_RE.fullmatch(reason_code) is None
        ):
            raise ValueError("profile_invalidation_invalid")
        async with self._operation() as (db, now_ms):
            await db.execute("BEGIN IMMEDIATE")
            if await _load_profile(db, profile_ref) is None:
                raise ProfileQualificationConflict("profile_unknown")
            rows = await _query(
                db,
                f"SELECT {_INVALIDATION_COLUMNS} FROM profile_invalidations "
                "WHERE profile_ref = ? AND invalidation_id = ?",
                (profile_ref, invalidation_id),
            )
            if rows:
                existing = _verified_invalidation(rows[0], profile_ref)
                if existing.reason_code != reason_code:
                    raise ProfileQualificationConflict("profile_invalidation_conflict")
                await db.commit()
                return existing
            seq = await _next_seq(db)
            await db.execute(
                "INSERT INTO profile_invalidations (profile_ref, invalidation_id, seq, reason_code, "
                "invalidated_at_ms, schema_version) VALUES (?, ?, ?, ?, ?, ?)",
                (profile_ref, invalidation_id, seq, reason_code, now_ms, PROFILE_QUALIFICATION_SCHEMA_VERSION),
            )
            await db.commit()  # not shielded: a COMMIT queued before a cancel may still run (N2)
        logger.info(
            "AD-1287: invalidated execution profile %s (%s); evaluations recorded before this no longer "
            "qualify it, and a new evaluation is needed",
            profile_ref,
            reason_code,
        )
        return RecordedInvalidation(profile_ref, invalidation_id, reason_code, seq, now_ms)

    async def get_qualification(self, profile_ref: str) -> ProfileQualification | None:
        """``profile_ref``'s status now, with the evidence that decided it, or None when it is not registered.

        Raises:
            ValueError: ``execution_profile_ref_invalid`` for a malformed reference.
            ProfileQualificationIntegrityError: a row that decides the status does not verify.
        """
        if not is_sha256_ref(profile_ref):
            raise ValueError("execution_profile_ref_invalid")
        async with self._operation() as (db, now_ms):
            profile = await _load_profile(db, profile_ref)
            return None if profile is None else await _assess(db, profile_ref, profile, now_ms)

    async def find_slot_candidates(
        self, slot: WorkerSlot, *, limit: int = 16, after: str | None = None,
    ) -> CandidateQueryResult:
        """Qualified profiles meeting ``slot``'s declared constraints, ascending by reference, with evidence.

        Examines at most ``_MAX_SCAN`` stored profiles with the slot's role and task class, in ascending
        reference order after ``after``, all assessed at one "now", and returns at most ``limit``
        (1..``MAX_CANDIDATES``) whose status is ``qualified`` and that ``slot_refusal`` accepts. It ranks and
        chooses nothing; the process owner decides. ``complete`` is False when it stopped at ``limit`` or at
        the scan bound with profiles left to examine; ``next_after`` then resumes after the last one examined.

        Raises:
            TypeError: ``profile_slot_type_invalid``.
            ValueError: ``profile_query_invalid`` for a bad ``limit`` or ``after``.
            ProfileQualificationIntegrityError: an examined row does not verify.
        """
        if type(slot) is not WorkerSlot:
            raise TypeError("profile_slot_type_invalid")
        slot = WorkerSlot.model_validate(slot)
        if (
            type(limit) is not int
            or not 1 <= limit <= MAX_CANDIDATES
            or (after is not None and not is_sha256_ref(after))
        ):
            raise ValueError("profile_query_invalid")
        async with self._operation() as (db, now_ms):
            rows = await _query(
                db,
                f"SELECT {_PROFILE_COLUMNS} FROM execution_profiles WHERE role_id = ? AND task_class = ? "
                "AND profile_ref > ? ORDER BY profile_ref LIMIT ?",
                (slot.role_id, slot.task_class, after or "", _MAX_SCAN + 1),
            )
            candidates: list[ProfileQualification] = []
            examined = 0
            for row in rows[:_MAX_SCAN]:
                examined += 1
                profile = _verified_profile(row)
                if slot_refusal(slot, profile) is None:
                    assessed = await _assess(db, row[0], profile, now_ms)
                    if assessed.status == "qualified":
                        candidates.append(assessed)
                        if len(candidates) == limit:
                            break
            complete = examined == len(rows)
            next_after = None if complete else rows[examined - 1][0]
        return CandidateQueryResult(tuple(candidates), examined, complete, next_after)


async def check_slot_qualification(
    qualifications: ProfileQualificationReader, spec: ElasticTeamSpec, slot_id: str, profile_ref: str,
) -> ProfileQualification:
    """The slot boundary's qualification check: the qualifying evidence, or ``SlotAdmissionRefused``.

    Refuses, in this order: ``slot_unknown``; ``profile_unknown``; ``profile_evidence_mismatch`` (the reader
    answered for another profile); the first ``slot_refusal`` code; ``profile_status_<status>`` for any status
    other than ``qualified``. Every slot requires a qualified profile; ``qualification_ids`` and
    ``pinned_profile_refs`` only narrow which. Reads only; grants nothing.

    Raises:
        TypeError: ``profile_slot_type_invalid`` when ``spec`` is not an ``ElasticTeamSpec``.
    """
    if type(spec) is not ElasticTeamSpec:
        raise TypeError("profile_slot_type_invalid")
    slot = spec.slot(slot_id)
    if slot is None:
        raise SlotAdmissionRefused("slot_unknown")
    qualification = await qualifications.get_qualification(profile_ref)
    if qualification is None:
        raise SlotAdmissionRefused("profile_unknown")
    if qualification.profile_ref != profile_ref or qualification.profile.content_ref() != profile_ref:
        raise SlotAdmissionRefused("profile_evidence_mismatch")
    refusal = slot_refusal(slot, qualification.profile)
    if refusal is not None:
        raise SlotAdmissionRefused(refusal)
    if qualification.status != "qualified":
        raise SlotAdmissionRefused(f"profile_status_{qualification.status}")
    return qualification


async def admit_qualified_attempt(
    qualifications: ProfileQualificationReader, teams: TeamAttemptRecorder, attempt: WorkerAttempt,
) -> WorkerAttempt:
    """Record ``attempt`` only when its exact execution profile is qualified for its slot (the slot boundary).

    Loads the stored spec through ``teams``, runs ``check_slot_qualification``, then calls
    ``teams.record_attempt``, which applies AD-1286's own admission rules. A refusal records nothing. The
    check runs on every call, including an identical replay of an attempt already recorded, so a replay
    after the profile stopped qualifying is refused (recovery reads ``get_attempt`` instead). Admission is
    decided as of the qualification read: the two stores share no transaction, so an invalidation recorded
    after that read does not undo an attempt already recorded (AD-1288 owns stopping running attempts).

    Raises:
        TypeError: ``elastic_attempt_type_invalid``.
        SlotAdmissionRefused: ``slot_spec_unknown`` or any ``check_slot_qualification`` code.
        Whatever ``teams.record_attempt`` raises, unchanged.
    """
    if type(attempt) is not WorkerAttempt:
        raise TypeError("elastic_attempt_type_invalid")
    attempt = WorkerAttempt.model_validate(attempt)
    spec = await teams.get_team_spec(attempt.team_spec_ref)
    if spec is None:
        raise SlotAdmissionRefused("slot_spec_unknown")
    try:
        await check_slot_qualification(qualifications, spec, attempt.slot_id, attempt.execution_profile_ref)
    except SlotAdmissionRefused as refused:
        logger.info(
            "AD-1287: slot %s refused execution profile %s (%s); no worker attempt was recorded",
            attempt.slot_id,
            attempt.execution_profile_ref,
            refused,
        )
        raise
    return await teams.record_attempt(attempt)
```

## Section 4 (M2): store declaration (`src/probos/cognitive/storage_declarations.py`)

Insert this entry between `:192` (`    ),`, the end of the `cognitive.repair-evidence` entry) and `:193` (`)`). Edit that anchor only.

```python
    StoreDeclaration(
        id="cognitive.profile-qualifications",
        title="Execution profiles, evaluation evidence and invalidations (AD-1287 S1)",
        owner_module="probos.cognitive.profile_qualification_store",
        owner_symbol="ProfileQualificationStore",
        canonical_path="profile_qualifications.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="unowned",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Insert-only by design: nine triggers abort every UPDATE, every DELETE and every replacing "
            "INSERT on the three WITHOUT ROWID tables, and the module has no delete path. Growth is one row "
            "per registered profile, one per evaluation run and one per invalidation; this slice does not "
            "bound evaluation runs per profile. Archival belongs to a later lifecycle slice; this one adds none."
        ),
        notes=(
            "Not wired: nothing constructs or starts the store in production until AD-1288 commission "
            "admission calls admit_qualified_attempt, so a default runtime never creates the file "
            "(lifecycle_owner is the 'unowned' sentinel). start() refuses a file whose schema is not exactly "
            "this store's and issues no schema or data write to it. Each row the store uses to decide or return a result is re-verified and one that "
            "does not verify is refused; a missing row, or a store stamp rewritten within range, is not "
            "detected, and evaluators are not authenticated."
        ),
    ),
```

## Section 5 (M2): `tests/test_ad1287_profile_qualification_store.py` (new)

Use `tmp_path / "profile_qualifications.db"`, a `_Clock` with a settable `now` (seconds, default `1000.0`), and `_started(path, **kwargs)`. Reuse `_PROFILE`, `_profile`, `_record` and `_observations` from `tests.test_ad1287_execution_profile`. Direct `sqlite3` is allowed in tests only. `_tamper(path, drop_trigger, statement, params)` follows `tests/test_ad1286_elastic_team_store.py:158`. For #21 and #22, a `_ProxyFactory` wraps `SQLiteConnectionFactory`. Its connection proxy delegates `execute`, `executescript`, `commit` and `close`, counts `commit` calls, and, when armed with `fail_on` or `park_on` (an SQL prefix), runs the real statement and then either raises `RuntimeError("injected")` or does the following: `await cursor.close()`, sets `parked` and awaits an `asyncio.Event` that is never set. It stores no cursor or result. The proxy's docstring states only what was measured (orchestrator probe `probe_1287_r1_cursor.py`, round 1): a retained cursor of a completed INSERT does **not** keep the write lock after the connection closes; an un-exhausted SELECT cursor does. Closing the cursor is defensive, not load-bearing for the INSERT park.

**Raw-SQL note (round 1).** `role_id`, `task_class` (profiles) and `profile_ref`, `evaluation_id` (evaluations) are generated columns: a raw INSERT must omit them, and a raw UPDATE of one is a SQLite error, not the trigger's. Tamper and refusal cases that wrote them must target a stored column instead (for example `recorded_at_ms`, `issued_at_ms`, `canonical_json`).

| # | Test | Asserts |
|---|---|---|
| 1 | `test_constructor_refuses_bad_paths` (`""`, `":memory:"`, `None`, `5`) | `ValueError("profile_qualification_store_path_invalid")` |
| 2 | `test_unstarted_and_stopped_store_raise_unavailable` | each of the six data methods raises `ProfileQualificationStoreUnavailable("profile_qualification_store_unavailable")` before `start()` and after `stop()`; `start`/`stop` idempotent; `start` after `stop` works |
| 3 | `test_register_profile_is_idempotent_and_survives_restart` | returns `content_ref()`; second call -> one row; NEW instance on the same file -> `get_profile` equals the profile |
| 4 | `test_get_profile_unknown_and_malformed` | unknown ref -> `None`; `"x"` -> `ValueError("execution_profile_ref_invalid")` (same for `get_qualification`) |
| 5 | `test_record_evaluation_stamps_issue_expiry_and_sequence` | clock `1000.0` -> `issued_at_ms == 1_000_000`, `expires_at_ms == 87_400_000`, `seq == 1`, `record` equal; raw row `canonical_json == record.canonical_bytes().decode()` |
| 6 | `test_identical_evaluation_is_idempotent` | move the clock, repeat -> equal `RecordedEvaluation` (same seq, same issue time); one row |
| 7 | `test_conflicting_or_unregistered_evaluation_writes_nothing` | same `evaluation_id`, different observations -> `ProfileQualificationConflict("profile_evaluation_conflict")`; unregistered profile -> `("profile_unknown")`; row counts unchanged |
| 8 | `test_registered_unevaluated_profile_reports_unevaluated` | `status == "unevaluated"`, `deciding is None`, `invalidation_reasons == ()` |
| 9 | `test_statuses_from_stored_evidence` (parametrize 4/4, 3/4, 2/4, 3/3, structurally invalid) | `qualified`, `qualified`, `failed`, `insufficient_sample`, `structurally_invalid` |
| 10 | `test_latest_evaluation_decides` | pass (`eval-1`) then fail (`eval-2`) -> `failed`, `deciding.seq == 2`; pass (`eval-3`) -> `qualified`, `deciding.seq == 3` |
| 11 | `test_expiry_survives_restart` | qualify at `1000.0`; new instance with clock `87399.5` -> `qualified`; clock `87400.0` -> `expired` |
| 12 | `test_invalidation_applies_to_earlier_evaluations_and_survives_restart` | qualify; `invalidate_profile(ref, "inv-1", "evaluator_revoked")` -> `invalidated`, reasons `("evaluator_revoked",)`; restart -> still `invalidated`; `eval-2` -> `qualified`, reasons `()` |
| 13 | `test_invalidation_is_idempotent_and_conflicts_on_another_reason` | repeat -> equal `RecordedInvalidation`, one row; same id, reason `manual` -> `ProfileQualificationConflict("profile_invalidation_conflict")` |
| 14 | `test_invalidation_refuses_bad_input_and_unknown_profile` | bad ref, id `"bad id"`, reasons `"Bad"`, `""`, `"a"*65`, `5` -> `ValueError("profile_invalidation_invalid")`; unregistered -> `("profile_unknown")`; zero rows |
| 15 | `test_sequence_is_store_wide` | evaluation seq 1, invalidation seq 2, an evaluation of a second profile seq 3 |
| 16 | `test_component_drift_starts_unevaluated_across_restart` (parametrize 7: skill resource, model version, prompt revision, tool schema, tool implementation, policy, suite dataset) | base qualified; drifted registered -> `unevaluated`; raw `COUNT(*)` of evaluations for the drifted ref is 0; restart -> both statuses unchanged |
| 17 | `test_database_refuses_update_delete_and_replace` (parametrize: 3 tables x UPDATE/DELETE/`INSERT OR REPLACE` by key; plus evaluations replaced through `seq` and through `(profile_ref, evaluation_id)`, and invalidations through `seq`) | premise: the row exists; `sqlite3.IntegrityError` containing `profile_qualification_immutable`; rows unchanged. **R1:** every UPDATE targets a stored column (profiles: `recorded_at_ms`); every replacing INSERT omits generated columns |
| 18 | `test_schema_version_check_refuses_other_versions` (parametrize 3 tables) | raw INSERT of a fresh key with `schema_version=2` -> `sqlite3.IntegrityError` containing `CHECK constraint failed`; premise: the same INSERT with `1` and another fresh key succeeds (foreign keys off on the raw connection, asserted `PRAGMA foreign_keys` reads `0`) |
| 19 | `test_tampered_rows_are_integrity_errors` (parametrize) | via `_tamper`: profile `canonical_json` re-indented (`json.dumps(json.loads(x), indent=1)`); evaluation `canonical_json` with one `passed` flipped; evaluation `expires_at_ms` plus `10**9`; evaluation `seq` set to text `'x'`; invalidation `reason_code` `'Bad Reason'`; **R1 (replaces the removed "cached `role_id`" case):** `moved_evaluation` -- profiles P and Q registered, P evaluated; P's evaluation `canonical_json` rewritten (`json.loads`, set `profile_ref` to Q, `canonicalize_projection(...).decode()`), `evidence_ref` unchanged; premise: raw `SELECT profile_ref FROM profile_evaluations` now returns Q, read by `get_qualification(Q)` (the edited row is detected where it now lands; for P it is missing, R-2, and no assertion pins P's status) -> the read path (`get_profile` / `get_qualification`) raises `ProfileQualificationIntegrityError("profile_qualification_integrity")`, an ERROR record in `caplog` |
| 20 | `test_invalid_clock_refuses_every_call` (**R1:** `nan`, `inf`, `-inf`, `-1.0`, `-1`, `253402300800`, `253402300799.5`, `10**1000`, `-10**1000`, `"1"`, `True`, `None`) | `ProfileQualificationStoreUnavailable("profile_qualification_clock_invalid")` from each of the six data methods (no `OverflowError`); no rows. **R1 boundary control:** clocks `0`, `0.0`, `253402300799`, `253402300799.0` each -> on a fresh file `register_profile` + `record_evaluation` succeed and `get_qualification` returns `qualified` with `deciding.issued_at_ms == int(clock * 1000)` (at the maximum this is `253402300799000`, the stamp bound itself) |
| 21 | `test_failed_write_records_nothing` | `fail_on="INSERT INTO profile_evaluations"` -> `RuntimeError("injected")`; count 0; disarm; retry -> `seq == 1` |
| 22 | `test_cancel_before_commit_records_nothing_and_retry_is_safe` | `park_on="INSERT INTO profile_evaluations"`; start the task; `await asyncio.wait_for(factory.parked.wait(), 5)`. Premises: `not task.done()`; `factory.commits` equals its value before the call (no COMMIT was called by it). `task.cancel()`; `pytest.raises(CancelledError)` on `await task`; `task.cancelled()`; raw count 0; disarm; retry under `asyncio.wait_for(..., 5)` -> `seq == 1` (N1, N3, implementation note). No timing assertion |
| 23 | `test_store_is_declared` | `load_default_store_registry().get("cognitive.profile-qualifications")`: owner symbol, `canonical_path == "profile_qualifications.db"`, `lifecycle_owner == "unowned"`, and the declaration names this class's module and name |
| 24 | `test_store_module_imports_only_its_owners` | AST, all depths: `probos.*` imports are exactly `{"probos.cognitive.elastic_team", "probos.cognitive.execution_profile", "probos.protocols", "probos.storage.sqlite_factory"}`; negative control as M1 #14 |
| 25 | `test_store_result_types_carry_no_authority_fields` | `dataclasses.fields` of the four result dataclasses: no name contains the D8 substrings; negative control on `AuthorityCeiling` |
| 26 | **R1** `test_out_of_range_stamps_are_integrity_errors` (parametrize) | via `_tamper` (UPDATE trigger dropped): evaluation `issued_at_ms` = `253402300799001` with `expires_at_ms` recomputed as `issued + validity_seconds*1000`; evaluation `issued_at_ms` = `-1` (expiry recomputed); evaluation `seq` = `2**53`; invalidation `invalidated_at_ms` = `253402300799001`, read by `get_qualification` AND by replaying the identical `invalidate_profile`; profile `recorded_at_ms` = `'not-a-number'` and = `253402300799001`, read by `get_profile` -> each `ProfileQualificationIntegrityError("profile_qualification_integrity")`. **Premise control:** evaluation `issued_at_ms` = `253402300799000` with expiry recomputed -> `get_qualification` returns a status (no error) |
| 27 | **R1** `test_rowid_replacement_is_refused_on_every_table` (parametrize 3, ids `rowid-replace-profiles/-evaluations/-invalidations`) | follows `tests/test_ad1286_elastic_team_store.py:1234-1293`: populated file (each table holds a row, asserted); raw default-pragma connection (`PRAGMA foreign_keys` and `recursive_triggers` read `0`); `INSERT OR REPLACE INTO <t> (rowid, <stored columns>) VALUES (1, ...)` whose primary key, `seq` and `(profile_ref, evaluation_id)` collide with NOTHING stored -> `sqlite3.DatabaseError` matching `_refusal_message(statement)` (`"rowid"` when the statement names `(rowid,`); all three tables unchanged |
| 28 | **R1** `test_every_table_is_without_rowid` | `sqlite_master` `type='table'`: names exactly the three tables; each `sql.rstrip().upper().endswith("WITHOUT ROWID")` |
| 29 | **R1** `test_raw_genuinely_new_rows_are_accepted` | negative control for #17 and #27, same raw connection: plain INSERT of one fresh row per table (fresh key, fresh `seq`, valid JSON naming fresh ids) succeeds; each count rises by exactly 1 |
| 30 | **R1** `test_next_seq_work_does_not_grow_with_rows` | raw `sqlite3` on a started store file; `steps(sql)` = number of `set_progress_handler(cb, 1)` callbacks while running `sql` once (a VM-step count; no wall clock, no plan string). Populate to 10, then 1000 rows per table with raw INSERTs (foreign keys off). **Premise:** the round-0 scan literal `"SELECT MAX(seq) FROM (SELECT seq FROM profile_evaluations UNION ALL SELECT seq FROM profile_invalidations)"` (kept in the test) has `steps_1000 > 10 * steps_10`. **Assert:** `module._NEXT_SEQ_SQL` has `steps_1000 <= steps_10 + 2`, and both SQL return the same maximum at both sizes |
| 31 | **R1** `test_selection_columns_are_generated_and_refuse_writes` (parametrize: profiles `role_id`, `task_class`; evaluations `profile_ref`, `evaluation_id`) | `PRAGMA table_xinfo(<t>)` reports the column `hidden` = 2 (VIRTUAL generated); with all three triggers of that table dropped, `UPDATE <t> SET <col> = 'x'` -> `sqlite3.OperationalError` containing `generated column`; the row and `get_qualification`/`get_profile` are unchanged (this is the round-1 A1 reproduction: it can no longer be set up) |
| 32 | **R1 (B3)** `test_clock_is_read_once_per_data_call_and_never_otherwise` | `_Clock` counts its reads (`reads` attribute, incremented in `__call__`). Read-count deltas: `start()` 0; `stop()` 0; each of the six data methods with a malformed argument (bad ref `"x"`, slot as dict, bad invalidation id) 0; each of the six on an unstarted store and on a stopped store 0; each of the six with valid arguments on a started store exactly 1 (`register_profile`, `get_profile`, `record_evaluation`, `get_qualification`, `invalidate_profile`, `find_slot_candidates`). **R2 (C3b):** on a started store whose clock returns `float("nan")`, each of the six raises `ProfileQualificationStoreUnavailable("profile_qualification_clock_invalid")` with a delta of exactly 1. **Premise:** the counter works (one direct `clock()` call raises it by 1) |
| 33 | **R1 (renumbered from the Builder's "26")** `test_close_failure_is_logged_and_the_operation_result_stands` | with `_ProxyFactory.fail_close` armed: the injected close failure fired (premise, asserted from the proxy); `register_profile` returns the ref and a NEW raw connection sees the row (committed); `caplog` holds a WARNING from the store module's logger containing `closing a profile qualification connection failed`; a conflicting `record_evaluation` still raises `ProfileQualificationConflict` (not the close error); after disarming, a normal call succeeds |

| 34 | **R2 (C1)** `test_start_refuses_the_pre_round_1_layout_and_leaves_the_file_unmodified` | `_OLD_LAYOUT_SCHEMA` (a literal in the test, below) run by raw `sqlite3` `executescript` on a new file in the default journal mode, plus one raw profile row (stored `role_id`/`task_class` given). **Premises:** `PRAGMA table_xinfo(execution_profiles)` reports `role_id` with `hidden` 0; raw `PRAGMA journal_mode` is `delete`. Record the file's sha256. `start()` -> `ProfileQualificationStoreUnavailable("profile_qualification_layout_mismatch")`; exactly one ERROR record from the store logger whose message contains `execution_profiles` and `profile_evaluations` (subset: do not assert the trigger names); each of the six data methods -> `profile_qualification_store_unavailable`; a second `start()` on the same instance refuses again; after all calls the file's sha256 is unchanged, raw `PRAGMA journal_mode` is still `delete`, no `-wal` sibling exists |
| 35 | **R2 (C1)** `test_start_accepts_only_this_layout` (parametrize) | **Accepted:** `fresh` (no file) -> started; raw catalog premise: 15 objects outside `sqlite_*` (3 table, 3 index, 9 trigger) AND at least one `sqlite_autoindex_%` object (the filter's premise); a NEW instance on the same file starts. `module_statements_rollback` (raw `sqlite3` runs each of `module._SCHEMA_STATEMENTS` in one transaction, default journal mode) -> started, and raw `PRAGMA journal_mode` is then `wal` (premise that an accepted start writes, so #34's unchanged file discriminates). **Refused**, each on a file the store created and then raw-edited, each -> `profile_qualification_layout_mismatch`, an ERROR record naming the object, `sqlite_master` rows and table row counts unchanged, `get_profile` -> `profile_qualification_store_unavailable`: `missing_trigger` (`DROP TRIGGER profile_evaluations_no_update`); `extra_trigger` (`CREATE TRIGGER profile_extra AFTER INSERT ON profile_invalidations BEGIN SELECT 1; END`); `extra_table` (`CREATE TABLE unrelated (x)`); `weakened_trigger` (drop `profile_evaluations_no_replace`, recreate it without `OR seq = NEW.seq`); `changed_index` (drop `profile_evaluations_latest`, recreate it on `(profile_ref)`); `generated_expression` (a NEW file built raw from `module._SCHEMA_STATEMENTS` with `'$.role_id'` replaced by `'$.task_class'` in the profiles statement; premise: `table_xinfo` still reports `role_id` `hidden` 2, so only the expression differs) |
| 36 | **R2 (C2)** `test_sequence_bound_is_refused_before_any_write` (parametrize writer `record_evaluation`, `invalidate_profile`) | registered profile; raw INSERT of one valid invalidation of it (`inv-0`, `evaluator_revoked`, a valid stamp, version 1) with `seq = _MAX_SEQ - 1` (`2**53 - 2`; the test's own constant, premise `== 2**53 - 2`); the writer (new id) -> returns `seq == 2**53 - 1`; snapshot; the writer again with another new id -> `ProfileQualificationConflict("profile_sequence_exhausted")`; the OTHER writer with a new id -> the same; snapshot unchanged; the identical replay of the first write -> returns the stored row (`seq == 2**53 - 1`); `get_qualification` returns a status without an integrity error |
| 37 | **R2 (C4)** `test_foreign_keys_are_on_before_the_first_statement_of_every_connection` | `_ProxyFactory` with `foreign_keys = []` armed (below). For `start()` and each of the six data methods with valid arguments on a populated store: clear the list; call; the list is non-empty and every entry is `1`. **Premise:** a raw `sqlite3.connect` of the same file reads `PRAGMA foreign_keys` as `0`, so the `1`s come from the store |

**R2 proxy addition (#37).** `_ProxyFactory.foreign_keys: list[int] | None = None`. When it is a list, each `_ProxyConnection`, on its FIRST `execute` whose SQL does not start with `PRAGMA` (case-insensitive, after `lstrip`), first runs `PRAGMA foreign_keys` on the real connection, appends the value read, and closes that cursor, then runs the statement. Off by default, so no other test changes. No private store access.

**R2 `_OLD_LAYOUT_SCHEMA` (#34).** Before installing the R2 Section 3, copy the `_SCHEMA` string from the installed R1 module verbatim into the test as `_OLD_LAYOUT_SCHEMA`, then change exactly four lines: `    role_id TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.role_id')) VIRTUAL,` -> `    role_id TEXT NOT NULL,`; `    task_class TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.task_class')) VIRTUAL` -> `    task_class TEXT NOT NULL`; `    profile_ref TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.profile_ref')) VIRTUAL` -> `    profile_ref TEXT NOT NULL`; `    evaluation_id TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.evaluation_id')) VIRTUAL,` -> `    evaluation_id TEXT NOT NULL,`. It must not import or derive from the module.

**R2 wording (C3), exact replacements in the test file:**
- `_Clock` docstring second paragraph -> `The store reads it exactly once per data-method call that passes argument checks on a started store, including a call it then refuses because the value read is not a valid time, and never in ``start``, ``stop``, an argument refusal or a call on a store that is not started.`
- `_stamp_plan` docstring last sentence (`The read paths are every way the store reads the rewritten row back.`) -> `The read paths are the ones this test runs, not every path that uses the row: evaluation replay and ``find_slot_candidates`` also use an evaluation and are not asserted here.`

**R2b addition (continues the table above).**

| # | Test | Asserts |
|---|---|---|
| 38 | **R2b** `test_store_tables_are_visible_to_the_store_registry_detector` | load `scripts/check_store_registry.py` exactly as `tests/test_ad1256_store_registry.py:81-86` does (`importlib.util.spec_from_file_location("check_store_registry", ...)`, registered in `sys.modules` before `exec_module`). **Assert:** `checker.detect_tables(Path(module.__file__).read_text(encoding="utf-8")) == ("execution_profiles", "profile_evaluations", "profile_invalidations")` (exact tuple; the function sorts). **Premise (negative control, so the assertion cannot pass vacuously):** with three literals in the test, `_T = ("CREATE TABLE execution_profiles (x)", "CREATE TABLE profile_evaluations (x)", "CREATE TABLE profile_invalidations (x)")`, a scratch source holding them ONLY as elements of a tuple bound to one name and executed through a loop variable (`"S = (\n" + "".join(f"    {t!r},\n" for t in _T) + ")\nfor s in S:\n    db.execute(s)\n"`) -> `detect_tables(...) == ()`; and the same three bound to their own names (`"".join(f"_T{i} = {t!r}\n" for i, t in enumerate(_T))`) -> the three names. No private module attribute is read |

**R2b note (#38).** Round 2's `_SCHEMA_STATEMENTS` tuple, executed through a loop variable, matched neither detection rule of `check_store_registry.py` (a named constant bound to a `CREATE TABLE` string; a literal passed to `execute`), so `--check` still passed on the declaration but reported 67 store modules instead of 68, and deleting the declaration later would have gone unnoticed (measured by the orchestrator, `probe_1287_r2_registry_detect.py`). Section 3 now binds each `CREATE TABLE` to its own `Final` name; statement texts and order are unchanged.

**R2b total:** 38 test functions (#1-#38).

**R3 amendments to #35 (round 3, D2.2 and D2.4).** `fresh`: assert `not db_path.exists()` before `start()` (premise: no pre-existing file). Add a refused case `extra_index` to the parametrize list and to `_raw_edit`: `("CREATE INDEX profile_extra_index ON profile_invalidations (reason_code)",), "profile_extra_index"`.

**R3 additions (continue the table).**

| # | Test | Asserts |
|---|---|---|
| 39 | **R3 (D2.1)** `test_a_start_failing_while_creating_leaves_no_layout_and_a_later_start_creates_it` | **Premise:** exactly one of `module._SCHEMA_STATEMENTS` starts with `CREATE TRIGGER execution_profiles_no_delete `, and it is index 7 (the 8th). `_ProxyFactory` with `fail_on` = that prefix: `start()` -> `RuntimeError("injected")`, `factory.fired == 1`; `get_profile(<valid ref>)` -> `profile_qualification_store_unavailable`; raw catalog holds no object whose name does not start with `sqlite_`. Disarm; `start()` on the same instance succeeds; raw catalog holds the 15 objects |
| 40 | **R3 (D2.3)** `test_an_invalid_stored_maximum_sequence_is_an_integrity_error` (parametrize writer `record_evaluation`, `invalidate_profile`) | registered profile; raw INSERT of one otherwise valid invalidation of it (`inv-0`, `evaluator_revoked`, stamp `1_000_000`, version 1) with `seq = 0`; premise: raw `SELECT MAX(seq)` over both tables is `0`; snapshot; the writer (new id) -> `ProfileQualificationIntegrityError("profile_qualification_integrity")` and an ERROR record from the store logger; snapshot unchanged |
| 41 | **R3 (H1)** `test_the_wal_switch_is_tried_again_while_another_connection_holds_the_lock` | fresh file; `_ProxyFactory` with `pause_after_commit = True`. Start `start()` as a task; `await asyncio.wait_for(factory.committed.wait(), 5)`; a raw `sqlite3.connect(db_path, isolation_level=None)` runs `BEGIN IMMEDIATE`; `factory.resume.set()`; `await asyncio.wait_for(factory.wal_refused.wait(), 5)`; raw `ROLLBACK`; `await asyncio.wait_for(task, 10)`. **Premise:** `factory.wal_busy >= 1` (the race was hit; this is reviewer D1's reproduction). **Assert:** the task returned None; `factory.wal_tries >= 2`; raw `PRAGMA journal_mode` is `wal`; no WARNING record from the store logger; `get_profile(<valid ref>)` -> None. No wall-clock assertion |
| 42 | **R3 (H1)** `test_a_wal_switch_still_busy_after_every_try_starts_with_a_warning` | `monkeypatch.setattr(module, "_WAL_ATTEMPTS", 3)`, `monkeypatch.setattr(module, "_WAL_RETRY_DELAY_S", 0)`; as #41, but the raw lock is held until `start()` has returned. **Assert:** `start()` returned; `factory.wal_tries == 3 == factory.wal_busy`; exactly one WARNING record from the store logger containing `not in WAL mode` and `busy on every try`; after raw `ROLLBACK`: raw `PRAGMA journal_mode` is `delete`, and `register_profile` then `get_profile` round-trip (the store serves in rollback mode) |
| 43 | **R3 (H1)** `test_a_wal_switch_answered_with_another_mode_starts_with_a_warning` | fresh file; `_ProxyFactory` with `wal_answer = "delete"`. **Assert:** `start()` returned; `factory.wal_tries == 1`; exactly one WARNING record containing `not in WAL mode` and `delete`; raw `PRAGMA journal_mode` is `delete` (the statement was not run); `get_profile(<valid ref>)` -> None |
| 44 | **R3 (H1)** `test_two_concurrent_fresh_starts_both_succeed_in_wal` | two instances on one fresh file, `await asyncio.wait_for(asyncio.gather(a.start(), b.start()), 15)`; both serve `get_profile(<valid ref>)` -> None; raw catalog holds the 15 objects; raw `PRAGMA journal_mode` is `wal`. Holds in every interleaving; it names no mutant |

**R3 proxy addition (#39-#43).** `_ProxyFactory` gains: `pause_after_commit: bool = False`, `committed = asyncio.Event()`, `resume = asyncio.Event()` (when armed, `_ProxyConnection.commit` runs the real commit, disarms the flag, sets `committed`, then awaits `resume`); `wal_tries: int = 0`, `wal_busy: int = 0`, `wal_refused = asyncio.Event()`, `wal_answer: str | None = None`. In `_ProxyConnection.execute`, for SQL starting with `PRAGMA journal_mode=WAL`: count `wal_tries`; if `wal_answer` is set, return a `_FakeCursor` whose `fetchall()` returns `[(wal_answer,)]` and whose `close()` does nothing, without running the statement; otherwise run it, and on `sqlite3.OperationalError` count `wal_busy`, set `wal_refused`, and re-raise. **Remove `executescript` from `_ProxyConnection`** (D2.4: the store no longer calls it, and without it any store call to it fails every proxy test, so #37 observes every statement); its class docstring then names `execute` / `commit` / `close` only and describes the WAL hooks in one sentence. Off by default: no other test changes.

**R3 wording (D2.4), exact replacements in the test file:**
- #20, `assert _snapshot(db_path) == before  # no rows` -> `assert _snapshot(db_path) == before  # unchanged: the registered profile, and no evaluation or invalidation`
- #38, the comment sentence `the detector reads a named constant bound to a CREATE TABLE string and a literal passed to execute, and nothing else.` (it spans two comment lines) -> `the detector reads a named constant bound to a CREATE TABLE string and a CREATE TABLE text passed to execute (a literal, or an f-string with dynamic parts); it does not follow a tuple element run through a loop variable.`
- Any other comment in #34 or #36 that says `no rows` where `_counts` is `(1, 0, 0)`: say `unchanged rows (1, 0, 0)`. (Architect grep found `# no rows` only at #20; `# creates the schema; no rows` at #18 and #29 is true and stays.)

**R3 total:** 44 test functions (#1-#44).

**R4 additions (round 4, reviewer E; continue the table).**

| # | Test | Asserts |
|---|---|---|
| 45 | **R4 (E1)** `test_the_wal_switch_runs_with_the_busy_handler_off` | fresh file, uncontended; `factory.statements = []`. `start()`. **Premise:** exactly one recorded connection list contains a statement starting `PRAGMA journal_mode=WAL`. **Assert, in that list:** `PRAGMA busy_timeout=5000` occurs before `PRAGMA busy_timeout=0`, which occurs before the first `PRAGMA journal_mode=WAL`; every statement after `PRAGMA busy_timeout=0` starts with `PRAGMA journal_mode=WAL` (the handler is off for the switch only). Then `register_profile` once: every list added since contains `PRAGMA busy_timeout=5000` and none contains `PRAGMA busy_timeout=0`. Raw `PRAGMA journal_mode` is `wal`. No timing |
| 46 | **R4 (E1)** `test_an_exclusive_lock_holder_does_not_stretch_the_wal_switch_by_the_busy_timeout` | `_WAL_ATTEMPTS` = 2, `_WAL_RETRY_DELAY_S` = 0 (monkeypatch). `_write_lock_taken_after_the_commit(..., begin="BEGIN EXCLUSIVE")`; `t0 = time.monotonic()`; `factory.resume.set()`; `await asyncio.wait_for(starting, 30)`; `elapsed = time.monotonic() - t0`; then raw `ROLLBACK`. **Premise:** `factory.wal_busy == 2 == factory.wal_tries` (both tries met the EXCLUSIVE lock). **Assert:** `elapsed < 2.5`; one WARNING containing `busy on every try`; raw `PRAGMA journal_mode` is `delete`. **Margin:** fixed, two tries answer at once and no sleep runs (milliseconds). Unfixed, each try runs the 5 s handler (measured 7.45 s), so >= 10 s. 2.5 s is half of ONE handler run, so even one unfixed try fails; it leaves > 2 s for a loaded runner. The 30 s `wait_for` lets the unfixed run end and fail on the assertion, not on a timeout |
| 47 | **R4 (E3)** `test_an_operational_error_without_an_sqlite_code_propagates_unchanged` | fresh file; `err = sqlite3.OperationalError("injected wal failure")`; **premise:** `not hasattr(err, "sqlite_errorcode")`; `factory.wal_raise = err`. **Assert:** `start()` raises, and `excinfo.value is err`; `factory.wal_tries == 1` (not retried); no WARNING from the store logger; `get_profile(<valid ref>)` -> `ProfileQualificationStoreUnavailable("profile_qualification_store_unavailable")` (left stopped); disarm (`wal_raise = None`); `start()` succeeds |

**R4 proxy changes (E3, E4a, #45).** `_ProxyFactory` gains `statements: list[list[str]] | None = None` (a list arms recording: each new `_ProxyConnection` appends its own list in `__init__` and records every SQL passed to `execute`, first thing, before running it) and `wal_raise: BaseException | None = None`. `_ProxyConnection.execute` becomes, after the recording and the foreign-keys probe:

```python
        if sql.startswith("PRAGMA journal_mode=WAL"):  # the store's WAL switch (review rounds 3 and 4)
            factory.wal_tries += 1
            if factory.wal_raise is not None:  # raised as given, without running the statement (round 4, E3)
                raise factory.wal_raise
            if factory.wal_answer is not None:  # answered here: the real statement is not run
                cursor = _FakeCursor([(factory.wal_answer,)])
            else:
                try:
                    cursor = await self._real.execute(sql, parameters)
                except sqlite3.OperationalError:  # the real switch was refused: SQLITE_BUSY while another lock is held
                    factory.wal_busy += 1
                    factory.wal_refused.set()
                    raise
        else:
            cursor = await self._real.execute(sql, parameters)
        if factory.fail_on is not None and sql.startswith(factory.fail_on):
```

(the `fail_on` / `park_on` blocks and `return cursor` follow unchanged, so they now apply to the WAL statement too: E4a). The class docstring's WAL sentence adds "or raises the factory's ``wal_raise``" and "the armed ``fail_on`` / ``park_on`` apply to it as to any statement"; the factory docstring adds "record each connection's statements".

**R4 helper change (E4b).** `_write_lock_taken_after_the_commit` gains a keyword parameter `begin: str = "BEGIN IMMEDIATE"` (run by the holder instead of the literal), and its `finally` becomes:

```python
    finally:
        if holder is not None:
            holder.close()  # a transaction still open is discarded
        if not starting.done():
            starting.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):  # the test's own failure is already propagating
                await starting
        elif not starting.cancelled():
            starting.exception()  # retrieve a failure the test did not await, so asyncio reports nothing at teardown
```

Docstring: "leaving the block closes the holder, cancels a start that is still running and retrieves the outcome of one that already ended". `import time` if the file lacks it.

**R4 total:** 47 test functions (#1-#47).

## Section 6 (M3): `tests/test_ad1287_slot_qualification.py` (new)

The real stores are `ProfileQualificationStore` and `ElasticTeamStore` on two `tmp_path` files, started, and restarted where stated. Spec: `tests.test_ad1286_elastic_team_contract._spec()` (its `review` slot: role `reviewer`, task `finding_review`, ids `["finding_review"]`, no pins, `max_attempts` 2). For pinned cases use `_spec(slots=[_slot(qualification={"qualification_ids": ["evidence_analysis"], "pinned_profile_refs": [<x ref>]}), _review_slot()])` with analyst profiles. Attempt: `tests.test_ad1286_elastic_team_contract._attempt(team_spec_ref=spec.content_ref(), slot_id="review", execution_profile_ref=<ref>)`.

| # | Test | Asserts |
|---|---|---|
| 1 | `test_candidates_are_only_qualified_profiles_meeting_the_slot` | stored: Q1, Q2 qualified; U unevaluated; E expired (suite `validity_seconds=1`, clock moved 2 s); I invalidated; F failed; S structurally invalid; N insufficient; R role `auditor` qualified; T task `finding_audit` qualified; X `qualification_id` `other` qualified. `find_slot_candidates(review_slot)` -> refs exactly `sorted([Q1, Q2])`, each `status == "qualified"` with `deciding` set, `complete is True`, `next_after is None` |
| 2 | `test_candidates_are_in_reference_order_not_ranked` | two qualified profiles, 3/4 and 4/4: order equals sorted refs whichever has more passes |
| 3 | `test_query_is_bounded_and_resumable` | `monkeypatch.setattr(module, "_MAX_SCAN", 3)`, 5 qualified: first call examined 3, 3 candidates, `complete False`, `next_after` = 3rd sorted ref; resume -> 2 candidates, `complete True`; `limit=1` -> 1 candidate, `complete False`, `next_after` = 1st ref; `limit=5` with the scan bound restored -> 5, `complete True` |
| 4 | `test_query_is_deterministic` | same clock, two calls -> equal results |
| 5 | `test_query_refuses_bad_arguments` | slot as dict -> `TypeError("profile_slot_type_invalid")`; `limit` `0`, `65`, `True`; `after` `"x"` -> `ValueError("profile_query_invalid")` |
| 6 | `test_pinned_slot_narrows_candidates` | analyst X and Y qualified, slot pins X -> only X |
| 7 | `test_unevaluated_catalog_skill_is_discoverable_but_not_qualified` | write `skills/code-review/SKILL.md` (frontmatter `name: code-review`, a description; `tests/test_ad596e_skill_validation.py:26` shape); `CognitiveSkillCatalog(skills_dir=...)`, `await start()`; premises: `get_entry("code-review")` is not None and `(await validate_skill("code-review")).valid`. A profile naming `code-review` is registered with no evaluation: `get_qualification` -> `unevaluated`; `find_slot_candidates` excludes it; the catalog still returns the entry |
| 8 | `test_check_slot_qualification_refusal_codes` (parametrize) | real store: `slot_unknown`, `profile_unknown`, `profile_role_mismatch`, `profile_task_class_mismatch`, `profile_qualification_id_mismatch`, `profile_not_pinned`, and `profile_status_<s>` for each non-qualified status; the qualified case returns the `ProfileQualification` |
| 9 | `test_check_slot_qualification_refuses_mismatched_reader_evidence` | `_FakeReader` returns a real qualified `ProfileQualification` of profile A when asked for B -> `profile_evidence_mismatch` |
| 10 | `test_slot_boundary_refuses_unqualified_and_admits_the_exact_qualified_profile_across_restart` (**milestone seam**) | `put_team_spec(spec)`; register A and B; `record_evaluation(_record(A))`; stop both stores, start NEW instances on the same files; `admit_qualified_attempt(q, teams, attempt_B)` -> `SlotAdmissionRefused("profile_status_unevaluated")`, `teams.get_attempt(id)` is None; `admit_qualified_attempt(q, teams, attempt_A)` -> returned, `get_attempt(id).execution_profile_ref == A` (same ordinal-1 id: the refused call wrote nothing, or AD-1286 would raise `elastic_attempt_conflict`) |
| 11 | `test_slot_boundary_refuses_each_disqualifying_profile_and_records_nothing` (parametrize `expired`, `invalidated`, `insufficient_sample`, `failed`, `structurally_invalid`, `unevaluated`, and `drifted`: A qualified, attempt names A with `model.version` changed, registered) | `SlotAdmissionRefused("profile_status_<s>")` (`drifted` -> `profile_status_unevaluated`); `get_attempt` None; `list_slot_attempts` empty |
| 12 | `test_refusal_never_calls_record_attempt` | `_FakeTeams` returns the spec and records calls; refused -> `record_attempt` never called, spec lookup called once |
| 13 | `test_record_attempt_errors_propagate_unchanged` | `_FakeTeams.record_attempt` raises `ElasticTeamConflict("elastic_attempt_budget_exhausted")` -> the same exception reaches the caller |
| 14 | `test_unknown_spec_is_refused` | `_FakeTeams.get_team_spec` -> None -> `SlotAdmissionRefused("slot_spec_unknown")`; wrong attempt type -> `TypeError("elastic_attempt_type_invalid")` |
| 15 | `test_identical_replay_after_expiry_is_refused` | admit A; move the clock past expiry; replay the identical attempt -> `profile_status_expired`; `get_attempt` still returns the first record |
| 16 | `test_nothing_in_src_constructs_the_store_or_calls_the_gate` | AST scan of `src/probos/**/*.py` excluding the two S1 modules: **no direct syntactic reference** -- no import of `profile_qualification_store` or `execution_profile` (any form, including `import ... as`), and no call whose callee is `ProfileQualificationStore`, `admit_qualified_attempt` or `check_slot_qualification` by name or as an attribute (including `m.ProfileQualificationStore(...)` after `importlib.import_module`). **Not covered (R1, B2), stated in the docstring and never asserted as a contract:** a call through a plain alias (`S = ProfileQualificationStore; S(...)`, `admit = admit_qualified_attempt; admit(...)`, an attribute chain assigned to a name), and lookup by string (`getattr(sys.modules[...], "...")`). One positive control per covered shape (`_FORBIDDEN_SHAPES`, adding the `import_module` attribute call); a bare string is not flagged (S1b `:1111-1123` pattern). AD-1288 changes this test deliberately |

---

## Mutation table (campaign of record: run ONCE, by M4, on the committed tree)

Baseline first, unmutated, and abort if it is red. Mutate in place with a `.mutbak` sibling and restore in `finally`. Single-line anchors only (this is a CRLF tree), and count each anchor first: it must occur exactly once in the named file. An anchor that is not found is INERT, not killed; a timeout is INVALID. Record the base commit and the sha256 of the six pinned files: the two modules, the three test files and `storage_declarations.py`. A later edit to a pinned file invalidates only the mutants pinned to it.

| Id | File | Anchor (exact line) -> mutant | Killed by |
|---|---|---|---|
| P1 | `execution_profile.py` | `    if record.pass_count * BASIS_POINTS < suite.min_pass_bp * record.sample_size:` -> `    if record.pass_count * BASIS_POINTS <= suite.min_pass_bp * record.sample_size:` | M1 #8 (3/4 boundary) |
| P2 | `execution_profile.py` | `    if now_ms >= expires_at_ms(profile, issued_at_ms):` -> `    if now_ms > expires_at_ms(profile, issued_at_ms):` | M1 #8 (now = expiry) |
| P3 | `execution_profile.py` | `    if record.sample_size < suite.min_samples:` -> `    if False:` | M1 #8, #9 |
| P4 | `execution_profile.py` | `    if not record.structurally_valid:` -> `    if False:` | M1 #8 |
| P5 | `execution_profile.py` | `    if invalidated:` -> `    if False:` | M1 #9 |
| P6 | `execution_profile.py` | `    if pinned and profile.content_ref() not in pinned:` -> `    if False:` | M1 #11; M3 #6 |
| P7 | `execution_profile.py` | `    if wanted and profile.evaluation_suite.qualification_id not in wanted:` -> `    if False:` | M1 #11; M3 #1 (X) |
| P8 | `execution_profile.py` | `    if profile.task_class != slot.task_class:` -> `    if False:` | M1 #11 |
| P9 | `execution_profile.py` | `    if record.profile_ref != profile.content_ref():` -> `    if False:` | M1 #10 |
| P10 | `execution_profile.py` | `        return tuple(entry for _, entry in sorted(keyed, key=lambda pair: pair[0]))` -> `        return tuple(entry for _, entry in keyed)` | M1 #1, #4 |
| P11 | `execution_profile.py` | `        if len(set(names)) != len(names):` -> `        if False:` | M1 #6, #7 (duplicates) |
| P12 | `execution_profile.py` | `PROFILE_DOMAIN: Final = b"probos.execution_profile/profile/v1\x00"` -> `PROFILE_DOMAIN: Final = b"probos.execution_profile/profile/v2\x00"` | M1 #1 |
| P13 | `execution_profile.py` | `        return hashlib.sha256(PROFILE_DOMAIN + self.canonical_bytes()).hexdigest()` -> `        return hashlib.sha256(self.canonical_bytes()).hexdigest()` | M1 #1 |
| S1 | `profile_qualification_store.py` | `            if any(item.evidence_ref != evidence_ref for item in stored):` -> `            if False:` | M2 #7 |
| S2 | `profile_qualification_store.py` | `        f"SELECT {_EVALUATION_COLUMNS} FROM profile_evaluations WHERE profile_ref = ? ORDER BY seq DESC LIMIT 1",` -> same with `ORDER BY seq ASC LIMIT 1` | M2 #10 |
| S3 | `profile_qualification_store.py` | `        f"SELECT {_INVALIDATION_COLUMNS} FROM profile_invalidations WHERE profile_ref = ? AND seq > ? "` -> same with `AND seq < ? ` | M2 #12 |
| S4 | `profile_qualification_store.py` | `            and type(expires) is int and expires == expires_at_ms(profile, issued)` -> `            and type(expires) is int` | M2 #19 (expires case) |
| S5 | `profile_qualification_store.py` | `            and profile.canonical_bytes().decode("utf-8") == stored` -> `            and True` | M2 #19 (re-indented case) |
| S6 | `profile_qualification_store.py` | **(re-anchored R1; the cached-column check is gone)** `            and _is_stamp(recorded_at)` -> `            and True` | M2 #26 (`recorded_at_ms` cases) |
| S7 | `profile_qualification_store.py` | `            complete = examined == len(rows)` -> `            complete = True` | M3 #3 |
| S8 | `profile_qualification_store.py` | `                    if assessed.status == "qualified":` -> `                    if True:` | M3 #1 |
| S9 | `profile_qualification_store.py` | `    if qualification.status != "qualified":` -> `    if False:` | M3 #10, #11 |
| S10 | `profile_qualification_store.py` | `    refusal = slot_refusal(slot, qualification.profile)` -> `    refusal = None` | M3 #8 (role case) |
| S11 | `profile_qualification_store.py` | `    if qualification.profile_ref != profile_ref or qualification.profile.content_ref() != profile_ref:` -> `    if False:` | M3 #9 |
| S12 | `profile_qualification_store.py` | `        await check_slot_qualification(qualifications, spec, attempt.slot_id, attempt.execution_profile_ref)` -> `        pass` | M3 #10, #12 |
| S13 | `profile_qualification_store.py` | **(re-anchored R2)** `    """CREATE TRIGGER profile_evaluations_no_update BEFORE UPDATE ON profile_evaluations` -> same ending `ON profile_invalidations` (the trigger name stays distinct, so the schema is valid) | M2 #17 |
| S14 | `profile_qualification_store.py` | `    schema_version INTEGER NOT NULL CHECK (schema_version = 1), -- profile_evaluations` -> `    schema_version INTEGER NOT NULL, -- profile_evaluations` | M2 #18 |
| S15 | `profile_qualification_store.py` | `WHEN EXISTS (SELECT 1 FROM profile_evaluations WHERE evidence_ref = NEW.evidence_ref OR seq = NEW.seq` -> `WHEN EXISTS (SELECT 1 FROM profile_evaluations WHERE evidence_ref = NEW.evidence_ref` | M2 #17 (replace through `seq`) |
| S16 | `profile_qualification_store.py` | `    return latest + 1` -> `    return latest` | M2 #15 |
| S17 | `profile_qualification_store.py` | `                "AND profile_ref > ? ORDER BY profile_ref LIMIT ?",` -> `                "AND profile_ref > ? ORDER BY profile_ref DESC LIMIT ?",` | M3 #1, #3 |
| S18 | `profile_qualification_store.py` | **(re-anchored R2b: no trailing comma)** `) WITHOUT ROWID"""  # end execution_profiles` -> `)"""  # end execution_profiles` | M2 #27 (`rowid-replace-profiles`), #28 |
| S19 | `profile_qualification_store.py` | **(re-anchored R2b: no trailing comma)** `) WITHOUT ROWID"""  # end profile_evaluations` -> `)"""  # end profile_evaluations` | M2 #27 (`rowid-replace-evaluations`), #28 |
| S20 | `profile_qualification_store.py` | **(re-anchored R2b: no trailing comma)** `) WITHOUT ROWID"""  # end profile_invalidations` -> `)"""  # end profile_invalidations` | M2 #27 (`rowid-replace-invalidations`), #28 |
| S21 | `profile_qualification_store.py` | `    "SELECT MAX(m) FROM (SELECT MAX(seq) AS m FROM profile_evaluations "` -> `    "SELECT MAX(m) FROM (SELECT seq AS m FROM profile_evaluations "` | M2 #30 |
| S22 | `profile_qualification_store.py` | `    return type(value) is int and 0 <= value <= _MAX_TIMESTAMP_MS` -> `    return type(value) is int and 0 <= value` | M2 #26 (`issued_at_ms` above maximum) |
| S23 | `profile_qualification_store.py` | `    return type(value) is int and 1 <= value <= _MAX_SEQ` -> `    return type(value) is int and 1 <= value` | M2 #26 (`seq = 2**53`) |
| S24 | `profile_qualification_store.py` | `    if type(now) not in (int, float) or not 0 <= now <= _MAX_TIMESTAMP:` -> `    if type(now) not in (int, float) or not 0 <= now:` | M2 #20 (`253402300800`) |
| S25 | `profile_qualification_store.py` | `    profile_ref TEXT GENERATED ALWAYS AS (json_extract(canonical_json, '$.profile_ref')) VIRTUAL` -> `    profile_ref TEXT` | M2 #31 (evaluations `profile_ref`), #10 |
| S26 | `profile_qualification_store.py` | `            now_ms = _checked_now_ms(self._clock)` -> `            now_ms = max(_checked_now_ms(self._clock), _checked_now_ms(self._clock))` (same value, two reads) | M2 #32 |
| S27 | `profile_qualification_store.py` | `            except Exception:  # noqa: BLE001 -- log-and-degrade: the operation's own result or error stands` -> `            except OSError:  # noqa: BLE001 -- log-and-degrade: the operation's own result or error stands` (the injected `RuntimeError` escapes) | M2 #33 |
| S28 | `profile_qualification_store.py` | `                logger.warning(` -> `                logger.debug(` | M2 #33 (WARNING record) |
| S29 | `profile_qualification_store.py` | **R2** `    differences = sorted(name for _kind, name in set(found) ^ set(_LAYOUT))` -> `    differences: list[str] = []` | M2 #35 (`missing_trigger`, `extra_trigger`, `extra_table`) |
| S30 | `profile_qualification_store.py` | **R2** `    differences += sorted(key[1] for key, sql in found.items() if key in _LAYOUT and sql != _LAYOUT[key])` -> `    differences += []` | M2 #34; #35 (`weakened_trigger`, `changed_index`, `generated_expression`) |
| S31 | `profile_qualification_store.py` | **R2** `                if not found:` -> `                if True:` (creation runs on an existing layout and fails: no `IF NOT EXISTS`) | M2 #3 (restart); #35 (`fresh` restart) |
| S32 | `profile_qualification_store.py` | **R2** `                    if differences:` -> `                    if False:` | M2 #34 |
| S33 | `profile_qualification_store.py` | **R2** `                await db.execute("BEGIN IMMEDIATE")` -> `                await (await db.execute("PRAGMA journal_mode=WAL")).fetchall(); await db.execute("BEGIN IMMEDIATE")` (the file is modified before the check; **R2b:** the PRAGMA's rows must be fetched, because an un-fetched PRAGMA is still pending when `BEGIN IMMEDIATE` runs and the switch is rolled back with the refused start, which left the round-2 text inert: 229 passed) | M2 #34 (sha256, journal mode) |
| S34 | `profile_qualification_store.py` | **R2** `    return {(kind, name): sql for kind, name, sql in catalog if not str(name).lower().startswith("sqlite_")}` -> `    return {(kind, name): sql for kind, name, sql in catalog}` (SQLite's autoindexes count as extra) | M2 #3 (restart); #35 (`fresh` restart) |
| S35 | `profile_qualification_store.py` | **R2** `    if latest == _MAX_SEQ:` -> `    if False:` | M2 #36 |
| S36 | `profile_qualification_store.py` | **R2** `            await db.execute("PRAGMA foreign_keys=ON")` -> `            await db.execute("PRAGMA foreign_keys=OFF")` | M2 #37 |
| S37 | `profile_qualification_store.py` | **R2b** `_PROFILES_TABLE: Final = """CREATE TABLE execution_profiles (` -> `_PROFILES_TABLE: Final = "" + """CREATE TABLE execution_profiles (` (same string at runtime; a `BinOp` escapes detection rule (a), as `tests/test_ad1256_store_registry.py:671-686` pins, so `detect_tables` returns two names) | M2 #38 |

| S38 | `profile_qualification_store.py` | **R3 (D2.1)** `                await db.execute("BEGIN IMMEDIATE")` -> `                pass` (DDL then autocommits statement by statement; the same anchor as S33) | M2 #39 |
| S39 | `profile_qualification_store.py` | **R3 (D2.2)** `    differences = sorted(name for _kind, name in set(found) ^ set(_LAYOUT))` -> `    differences = sorted(name for kind, name in set(found) ^ set(_LAYOUT) if kind != "index" or (kind, name) in _LAYOUT)` (an extra index is ignored; the same anchor as S29) | M2 #35 (`extra_index`) |
| S40 | `profile_qualification_store.py` | **R3 (D2.3)** `    if not _is_seq(latest):` -> `    if False:` | M2 #40 |
| S41 | `profile_qualification_store.py` | **R3 (H1), anchor R4** `            if not isinstance(code, int) or code & 0xFF != sqlite3.SQLITE_BUSY:` -> `            if True:` (no retry: the first BUSY propagates out of `start()`) | M2 #41 |
| S42 | `profile_qualification_store.py` | **R3 (H1)** `    return None  # every try found the file busy` -> `    raise RuntimeError("wal_busy")  # every try found the file busy` (a lapsed budget fails the start) | M2 #42 |
| S43 | `profile_qualification_store.py` | **R3 (H1)** `        if mode != "wal":` -> `        if False:` (no WARNING) | M2 #42, #43 |
| S44 | `profile_qualification_store.py` | **R3 (H1)** `        return str(rows[0][0]).lower()` -> `        return "wal"` (the answered mode is not read) | M2 #43 |
| S45 | `profile_qualification_store.py` | **R4 (E1)** `    await db.execute("PRAGMA busy_timeout=0")  # the loop owns the budget (review round 4, E1)` -> deleted (the switch runs under the 5 s handler) | M2 #45, #46 |
| S46 | `profile_qualification_store.py` | **R4 (E3)** `            code = getattr(exc, "sqlite_errorcode", None)  # set only on errors the sqlite3 library raised (E3)` -> `            code = exc.sqlite_errorcode` (`AttributeError` replaces the original error) | M2 #47 |
| S47 | `profile_qualification_store.py` | **R4 (E3)** `            if not isinstance(code, int) or code & 0xFF != sqlite3.SQLITE_BUSY:` -> `            if isinstance(code, int) and code & 0xFF != sqlite3.SQLITE_BUSY:` (a code-less error is retried, then degraded) | M2 #47 |

**M4 total (R4):** P1-P13 and S1-S47 = **60** mutants. S41 and S47 share one anchor; each is applied alone.

**Note on S13-S14, S18-S20, S25 (round 2).** `start()` compares a file with the module's own `_SCHEMA_STATEMENTS`, so such a mutant changes the created layout and the expected one together and the store still starts; each test uses a fresh `tmp_path` file, so the mutant schema is what gets created and the named behavioural test kills it. **Anchor uniqueness (R2):** `BEGIN IMMEDIATE` occurs at 16 spaces only in `start()` (the writers use 12); `logger.warning(` at 16 spaces only in `_open` (**R3:** the WAL WARNING's `logger.warning(` is at 12 spaces, in `start()`); count each anchor before mutating, as the table header requires. **R3:** S38 shares S33's anchor and S39 shares S29's; each mutant is applied alone.

---

## What this does NOT change

- `elastic_team.py`, `elastic_team_store.py`, `crew_session.py`, the AD-1286 tests and wiring. `WorkerSlot` gains no field. `qualification_ids` acquires meaning (suite ids) by documentation only.
- `QualificationStore`, `QualificationHarness`, `QualificationSkillBridge`, `SkillBridge`, `CognitiveSkillCatalog`, `ModelRegistry`, `ToolRegistry`, `TrustNetwork`.
- Runtime, startup, config, routers, events, HXI. Store-registry and architecture baselines: a declared store needs no baseline row.

## Do not build

- No runtime wiring: no construction in `startup/`, no data-dir path, no config field, no API route, no event, no shell command.
- No component-digest producers: no skill-directory hashing, tool-schema hashing, model or policy digest computation, no `validate_skill` call in `src/` (S2).
- No drift detection, `component_drift_*` invalidation producer or currency check in the gate (S2).
- No outcome learning, Beta parameters, `TrustNetwork` write or outcome table (S3).
- No migration or evidence-copy path between profile references, and no "accept", delete, reset, list-all or archival API.
- No ranking, scoring, sorting by quality, or selection in the query. No Wilson or Jeffreys bound.
- No edit to `ElasticTeamStore._admit_attempt` or any AD-1286 file. No shared connection helper extracted from S1b (R-1).
- No signing, attestation envelope or key material (AD-1047).
- No worker provisioning, agent-authored composition, model fallback change, marketplace, Dataverse or Copilot Studio work (issue "Do Not Build").
- No wording that claims authentication, prevention or authority. Say "records", "refuses", "detects".
- No broad gate run by the Builder, and no `git add -A`.

## Tracking (M5)

- `PROGRESS.md`: insert one bold paragraph directly under `# ProbOS Progress` (`:1`), in the `:5` style: `**AD-1287 slice S1 BUILT (<date>), #1334, built and unwired -- ...**`. It states the files, the per-file test counts measured, "no file under `src/` imports the S1 modules or calls the store or gate directly (M3 #16)", and "S2 (component producers, drift) and S3 (outcome learning) remain; #1334 stays open".
- `DECISIONS.md`: a new `### AD-1287 S1 -- Evidence-bound execution-profile qualification` section directly above `### AD-1286` (`:13`). It has one line each for D1-D9 and the slicing decision, obligations O-1 to O-3, residuals R-1 to R-3, and the M4 campaign of record: base commit, sha256 of the six pinned files, and per-mutant KILLED, INERT or INVALID with its killing test.
- `docs/development/roadmap.md:527`: append `(S1 built <date>, unwired; S2/S3 remain)` to the AD-1287 title cell.
- No edit to `open-ads-report.md` or `ad-ledger-snapshot.json` (regenerated separately).

## Obligations handed on

- **O-1 (AD-1288):** commission admission must record attempts only through `admit_qualified_attempt` (or `check_slot_qualification` immediately before `record_attempt`). It must change M3 #16 deliberately. Recovery reads `get_attempt` rather than re-admitting (M3 #15).
- **O-2 (S2):** add live component sources and a currency check to the gate. Until then a qualified reference stays admissible after a live component changes.
- **O-3 (S3):** outcome learning keys on `execution_profile_ref` and the profile's `task_class`, is idempotent by `worker_attempt_id`, stores integer raw counts, returns `(alpha, beta)` with a prior of `(2, 2)` (TrustNetwork's default, `trust.py:66-67`), does not count `cancelled`, writes nothing to `TrustNetwork`, and gates nothing.
- **R-1 (residual, for the orchestrator to file):** extract the per-operation `_open` shared by `repair_evidence_store` and `profile_qualification_store` once AD-1299 S2 has landed.
- **R-2 (residual, round 1, documented not filed):** a row missing from a selection (deleted, or edited so no selection reaches it, including an invalidation moved to another key) is indistinguishable from one never written. Per-row verification cannot see absence; detecting it needs an anchored chain or signature (AD-1047's Captain decision). Carried in: module docstring, D9, the store declaration `notes`, DECISIONS (M5).
- **R-3 (residual, round 1, documented not filed):** store stamps (`seq`, `issued_at_ms`, `recorded_at_ms`, `invalidated_at_ms`) rewritten within type and range are not detected; `seq` decides which evaluation is latest. Carried in: module docstring, D4, D9, DECISIONS (M5).

## Acceptance criteria (S1)

1. M1, M2 and M3 focused runs are green with `-n 0 -p no:randomly`, and `probos.__file__` resolves inside this worktree's `src`.
2. `scripts/check_store_registry.py --check` and `scripts/check_architecture_principles.py --check` exit 0 with the new files **staged** (both read tracked files).
3. M3 #10 crosses the seam in ONE test: the evaluation producer on a real file, a restart of both stores, refusal of the unqualified profile with no attempt row, and admission of the exact qualified profile into a real `ElasticTeamStore` file.
4. The #1334 acceptance items S1 covers each have a named test: deterministic identity across restart (M1 #1, #3; M2 #3); one-component drift gives a new profile with no inherited credential (M1 #5; M2 #16; M3 #11); expired, invalidated, insufficient, failed and structurally invalid profiles cannot satisfy a slot (M3 #1, #11); an unevaluated skill stays discoverable but unqualified (M3 #7); queries are bounded, deterministic and return evidence without choosing (M3 #1-#4); a record names no authority (M1 #13, M2 #25); restart persistence, expiry, invalidation and drift run on real stores (M2 #3, #11, #12, #16); slot-boundary refusal and admission (M3 #10, #11). Outcome learning (S3) and drift detection (S2) remain, and #1334 stays open.
5. Every mutant in the table is KILLED by the named test, none INERT or INVALID, in the single M4 campaign of record.
6. No file under `src/probos/` except the two S1 modules holds a direct syntactic reference to them: an import of an S1 module, or a call of the store or a gate function by name or attribute (M3 #16). Calls through a plain alias and lookups by string are not covered by that scan.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Prior Art and Blind Spots (2026-10-12)

| Source | Idea | Decision |
|---|---|---|
| [in-toto Statement v1](https://in-toto.io/Statement/v1), [SLSA verification summary](https://slsa.dev/spec/v0.2/verification_summary), [in-toto and SLSA](https://slsa.dev/blog/2023/05/in-toto-and-slsa) | Attestations are bound to a subject purely by digest, and test results are a separate attestation from provenance | **Adopted:** an evaluation is a separate record bound to the profile digest, with exact reference match and no name matching. **Rejected:** DSSE signing (AD-1047 keys are a Captain decision) |
| W3C VC `validUntil` + Bitstring Status List ([EBSI](https://hub.ebsi.eu/docs/use-cases/verifiable-credentials/trust-chains/credential-status-and-revocation/credential-status-vcs), [walt.id](https://docs.walt.id/community-stack/verifier/capabilities/credential-lifecycle)) | Expiry lives on the credential and revocation is a separate, independently checked list | **Adopted:** expiry from issue time plus validity, with invalidations as separate insert-only rows. **Adapted:** invalidation is sequence-scoped, so the same profile can be requalified, rather than a permanent bit |
| Harness reproducibility ([HarnessOpt-Bench](https://arxiv.org/pdf/2608.06301), [MLflow evaluation harness](https://mlflow.org/articles/llm-evaluation-harness/)) | Harness configuration shifts scores; datasets are pinned by immutable reference; immutable run manifests | **Adopted:** dataset digest, prompt, tool and policy digests are all in the identity |
| Jeffreys and Wilson lower bounds ([best-agent identification](https://arxiv.org/pdf/2507.00451)) | A small-sample-aware pass rule | **Considered, deferred:** an integer `min_samples` + `min_pass_bp` rule is exact and reviewable with no floats; a lower-bound rule can be a suite schema v2 |
| Internal: AD-1286 identity (`elastic_team.py:56-73`), AD-1299 S1b store (`repair_evidence_store.py:219-362`), TrustNetwork raw Beta + `record_outcome_once` idempotency (`trust.py:55-67`, `:612`), MASS absorption note (`docs/research/mass-self-supervision-absorption.md:43`, "services check shape, agents judge content") | Identity scheme, store shape, Beta convention, evidence-not-choice | **Adopted** (D1, D3, D7, O-3, D5 query semantics). `QualificationStore` and `qual_skill_bridge` were **rejected as owners** (agent-keyed) |

**Blind spots named (not in the issue):**

1. **Self-evaluation.** An agent could evaluate its own profile. `evaluator_id` is recorded provenance only. Evaluator independence belongs to AD-1290 trials or the AD-1327 verifier tier. Considered, deferred.
2. **A provider changes weights under the same version label.** The profile cannot see it. S3 outcome learning surfaces it; the profile identity does not.
3. **Clock moved backwards.** It lengthens an evaluation's effective window by the jump (D4, non-normative); invalidation ordering is unaffected.
4. **Line endings (S2).** A checkout with different line endings changes a skill's resource digest. That is the conservative direction: requalification is needed.
5. **TOCTOU between stores.** An invalidation after the gate's read does not undo a recorded attempt (documented; O-1).
6. **Replay after expiry is refused** (M3 #15). AD-1288 recovery must read rather than re-admit.
7. **Unbounded evaluation runs per profile.** Each run is a row. Declared in the store registry; archival is a later slice.
8. **Self-reported `structurally_valid` in S1.** S2 derives it from `CognitiveSkillCatalog.validate_skill`.

---

## Review round 1 (2026-10-12, store scope, Reviewer A GPT-6.1 Sol: NOT READY, 2 High)

All six reproduced by the orchestrator's probe before this ruling. Identity/gate scope (Reviewer B) is ruled separately.

| Id | Finding | Ruling |
|---|---|---|
| A1 High | Selection and uniqueness filter on stored cache columns that only a selected row verifies | Fixed by schema: those columns are now `VIRTUAL` generated from the canonical text (D3), so a column-only edit cannot be set up (M2 #31) and a canonical-text edit fails verification wherever the row is read (M2 #19 `moved_evaluation`). Wording narrowed to "verifies each row it reads"; absence and re-stamping named as R-2/R-3 (docstring, D4, D9, notes) |
| A2 High | Out-of-range stamps accepted | `_is_stamp`/`_is_seq` bounds on every stamp read, `recorded_at_ms` now selected and verified (D4, M2 #26) |
| A3 Med | Huge-int clock raises `OverflowError` | `math.isfinite` removed; exact range comparison only (M2 #20 widened) |
| A4 Med | `WITHOUT ROWID` removal survived | AD-1286 rowid-replace pattern, `sqlite_master` check, negative control (M2 #27-#29; S18-S20) |
| A5 Med | `_next_seq` scans both tables | Per-table `MAX(seq)` from the unique index (`_NEXT_SEQ_SQL`), VM-step test with a discriminating premise (M2 #30; S21) |
| A6 Low | Wording | `_operation` docstring, D7 N1, proxy docstring (Section 5 intro) |

### Reviewer B (identity and gate scope, GPT-6.1 Sol: READY, four Low) -- rulings

| Id | Finding | Ruling |
|---|---|---|
| B1 Low | Huge-int clock | Same as A3: exact range comparison, no `math.isfinite`; M2 #20 includes `10**1000` and `-10**1000` (S24) |
| B2 Low | Absence scanner overstates its coverage (four missed shapes reproduced) | **(a) wording**, ranked over (b) alias-following. (b) still misses lookup by string, so the claim would still need a stated limit, and it adds scanner logic for shapes that already need a static import, which is flagged in the file that imports it. Claim narrowed to "no direct syntactic reference" in the scanner docstrings, M3 #16, Acceptance #6 and Tracking; missed shapes named as not covered and never pinned as a contract; positive control for the `import_module` attribute call added |
| B3 Low | "once per call" clock wording unmeasured | **Add M2 #32** (read counts) and mutant S26, ranked over removing the claim: the store's "now" is the time base for expiry, and the count is cheap to pin. `_Clock` docstring states exactly what #32 measures |
| B4 Low | "No `profile_qualifications.db` can exist" | Scoped to what was run: the live directory was not inspected; source checked only |
| Numbering | Builder's close-failure test labelled "26" | Renumbered **#33**, given a Section 5 row and mutants S27 (narrowed `except`) and S28 (`warning` -> `debug`) |

**Mutants:** P1-P13 and S1-S28 = **41** (round 1 added S18-S28). Section 3 is unchanged by these rulings (726 lines).

### Round 2, reviewer C (GPT-6.1 Sol, fresh read of the round-1 design: NOT READY, 1 High, 1 Medium, 2 Low) -- rulings

All four reproduced by the orchestrator (`probe_1287_r2_findings.py`, premises asserted first).

| Id | Finding | Ruling |
|---|---|---|
| C1 High | `start()` accepted a file holding another layout (`IF NOT EXISTS` kept the old tables; stored selection columns; A1 reproduced on it) | **Exact catalog match against the module's own statements, before any write** (D3a option 1, ranked over a semantic subset, `user_version`, a reference fingerprint and narrowing). `_SCHEMA` becomes `_SCHEMA_STATEMENTS` without `IF NOT EXISTS`; `start()` runs `BEGIN IMMEDIATE`, reads `sqlite_master`, creates on an empty catalog, refuses any other difference with `ProfileQualificationStoreUnavailable("profile_qualification_layout_mismatch")` (ERROR log naming the objects, store stopped, file untouched), and sets WAL only after the commit. Generated-column expressions are checked (they are inside the compared table text). Not checked: `sqlite_*` objects, page integrity, a layout changed while started. M2 #34, #35; S29-S34 |
| C2 Med | Sequence exhaustion committed `seq = 2**53` | `_next_seq` refuses at `_MAX_SEQ` with `ProfileQualificationConflict("profile_sequence_exhausted")` before either writer's INSERT; nothing written; rows stay readable (D4, D9). M2 #36; S35 |
| C3 Low | Quantifiers | (a) "reads" -> "uses to decide or return a result", with fetched-beyond-`limit` rows named as unverified: module docstring, D3, D4, D9 (two rows), `notes`, `_stamp_plan` docstring. (b) `_Clock` docstring counts the invalid-clock read; #32 measures it. (c) `_stamp_plan` says "the paths this test runs". Exact text in Section 5 "R2 wording". The round-1 A1 ruling keeps its historical wording |
| C4 Low | `foreign_keys=OFF` survived | Behavioural, not a string match: the proxy reads `PRAGMA foreign_keys` on the real connection just before each connection's first non-PRAGMA statement; #37 asserts `1` for `start()` and all six data methods, with a raw-connection `0` premise. S36 |

**Mutants:** P1-P13 and S1-S36 = **49**. Section 3 is **795 lines** (between its fences). Unverified here (no interpreter under the bridge), each a Brief R2 stop condition: that `sqlite_master.sql` equals each statement exactly on SQLite 3.50.4; that `sqlite_autoindex_*` objects exist for these tables; that a refused `start()` leaves a rollback-mode file's bytes unchanged. **Pre-build execution (2026-10-12):** the orchestrator executed Section 3 on SQLite 3.50.4 and found one defect, `_layout_differences` used undefined `name` in its second generator (NameError out of `start()` on a same-name, different-definition file), corrected to `key[1]` (S30's quoted line follows); with that token the premises above then ran and held: exact `sqlite_master.sql` equality for all 15 statements, three `sqlite_autoindex_*` objects present and excluded, WAL after fresh start, restart accepted, old-layout rollback file refused with bytes/journal mode unchanged and no sidecars, failed 8th CREATE leaves no objects, #35 variants refused, #36 and #37 as specified (`probe_1287_r2_layout_premises.py`, `probe_1287_r2_variants.py`).

### Round 3, reviewers D1 and D2 (GPT-6.1 Sol, frozen R2b tree: D1 NOT READY, 1 High, 1 Medium, wording; D2 READY, 3 Medium test gaps) -- rulings

D1's H1 and M1 reproduced by the orchestrator (`probe_1287_r3_d1.py`, premises asserted). D2's mutants each reached their behaviour.

| Id | Finding | Ruling |
|---|---|---|
| H1 High | The WAL switch after the layout commit fails at once with a raw `database is locked` when another connection takes the lock in between (no busy handler for it); the answered mode was never read | **Bounded retry, then log-and-degrade** (D3b, ranked over retry-then-refuse, no-retry best effort and WAL-first). `_set_wal`: up to 50 tries 0.1 s apart on `SQLITE_BUSY` only, returns the answered mode; not `wal` or busy on every try -> one WARNING, store starts in the current mode. Tier: log-and-degrade (WAL is a concurrency property; no claim depends on it). M2 #41-#44; S41-S44 |
| M1 Med | "Refused before anything is written" overstates for WAL-mode files (SQLite's recovery and checkpoint change the bytes and remove sidecars) | Narrowed to **"the store issues no schema or data write to a file it refuses"**, with the WAL caveat and the rollback-journal byte-identity (#34) stated: module docstring, `start()` docstring, ERROR log text, D3a, D9, `notes`. No test pins the WAL-file behaviour |
| L1 Low | (a) "seen at the next start()"; (b) "any failure leaves it stopped"; (c) the `_SCHEMA_STATEMENTS` comment | (a) "seen only when a stopped store is next started"; (b) `start()` docstring and a D9 row name the started-store return, the cancelled waiter and the logged close failure; (c) the comment names TEMP and the database qualifier and says the statements are already normalised |
| D2.1 Med | Startup atomicity untested | M2 #39 (fail on the 8th CREATE; empty catalog; later start creates); D3a now claims it; S38 |
| D2.2 Med | Extra index alone untested | #35 `extra_index`; S39 |
| D2.3 Med | `_next_seq`'s invalid-maximum guard untested | M2 #40 (`seq = 0`, both writers); S40 |
| D2.4 Low | `fresh` premise; proxy `executescript`; comment wording | #35 `fresh` asserts no file first; `executescript` removed from the proxy; exact wording in Section 5 "R3 wording" |

**Audit of `start()` and `stop()` (round 3, item 4), the H1 class:** (1) `PRAGMA busy_timeout`/`synchronous`/`foreign_keys` in `_open`: need no lock and run outside a transaction; their answers are not needed (`foreign_keys` is pinned behaviourally by #37). (2) `BEGIN IMMEDIATE`: takes RESERVED from no lock, so the busy handler runs (a lock held past 5 s propagates `sqlite3.OperationalError` and the store stays stopped, as for every data method; unchanged). (3) Catalog read and CREATEs: inside that transaction. (4) `COMMIT`: lock escalation runs the busy handler. (5) Commit -> WAL switch: the one window between two lock holds; fixed by `_set_wal`. On a file already in WAL mode the switch is a no-op after the transaction's read (SQLite source reading, not measured; #44 covers two starters). (6) The answered mode: now read. (7) Refusal path: raises inside the open transaction; closing discards it. (8) `stop()`: no SQL. Nothing else found.

**Mutants:** P1-P13 and S1-S44 = **57**. Section 3 is **840 lines** between its fences. Unverified (no interpreter under the bridge), each a Brief R3 stop condition: that `exc.sqlite_errorcode & 0xFF == sqlite3.SQLITE_BUSY` for D1's error; that #44 holds; that S38 persists objects (D2 measured 8/15 with its own mutant).

### Round 4, reviewer E (GPT-6.1 Sol, delta review of R3: no Critical or High; 2 Medium, 2 Low, each executed) -- rulings

E1 and E3 reproduced by the orchestrator (`probe_1287_r4_e.py`).

| Id | Finding | Ruling |
|---|---|---|
| E1 Med | The WAL retry is not a ~5 s budget: under an EXCLUSIVE holder the busy handler runs per try (7.45 s at `busy_timeout=5000`), so 50 tries is minutes with the store's lock held | Ranked: (1) **`PRAGMA busy_timeout=0` before the loop** -- chosen: one statement, the loop alone owns the budget (~5 s), and the connection closes when `start()` ends, so nothing else runs without the handler; (2) monotonic deadline that also shrinks the per-attempt timeout -- rejected: a PRAGMA per try, clock arithmetic and more mutants for the same bound; (3) document a count-only budget -- rejected: `stop()` and every call wait on the store's lock for minutes. `_set_wal` docstring and D3b state both lock cases. M2 #45 (statement order, no timing), #46 (EXCLUSIVE holder, < 2.5 s); S45 |
| E2 Med | "A refused rollback-journal file is byte-identical" is false for a file with a hot journal (SQLite recovers it on open) | Narrowed: a refused file **that needs no recovery** stays byte-identical; SQLite's own hot-journal or WAL recovery can still change a file; the store issues no schema or data write either way. Module docstring, `start()` docstring, D3a, D9. The ERROR log ("the store wrote no schema or data to it") and `notes` ("issues no schema or data write to it") are already true and unchanged. No test pins recovery |
| E3 Low | `exc.sqlite_errorcode` raises `AttributeError` for an `OperationalError` not built by the library | `getattr(exc, "sqlite_errorcode", None)`; a non-int code re-raises the original. Justified `getattr`: Python documents the attribute as library-origin only, and the factory is injected. M2 #47; S46, S47 |
| E4 Low | (a) proxy WAL branch skips `fail_on`/`park_on`; (b) helper leaves "Task exception was never retrieved" | (a) the WAL branch sets `cursor` and falls through to the generic hooks; (b) `finally` retrieves a completed failure and suppresses `Exception` while awaiting a cancelled task. Section 5 "R4 proxy changes", "R4 helper change" |

#44 surviving the complete R3 code is expected (it names no mutant); no action. **Section 3 is 848 lines** between its fences (+1 docstring, +7 `_set_wal`). **Mutants: 60** (S45-S47). Unverified (no interpreter under the bridge), each a Brief R4 stop condition: that an EXCLUSIVE holder answers the switch with `SQLITE_BUSY` (code 5) at once under `busy_timeout=0`; #46's elapsed time; that a Python-built `OperationalError` lacks `sqlite_errorcode` on this interpreter. Reviewer E's follow-up on the R4 tree found a single Low (a close checkpoints a WAL-mode file only when it is the last connection; wording corrected in the module docstring, D3a and D9) and no other finding.

## Verified Against Codebase (2026-10-12, base `f85cd42c`)

Round 3 (read this round):
```
grep -n "def connect" src/probos/storage/sqlite_factory.py
  16: async def connect(self, db_path: str) -> DatabaseConnection:   23: conn = await aiosqlite.connect(db_path)   (no PRAGMA)
grep -n "requires-python" pyproject.toml
  9: requires-python = ">=3.12"   (sqlite3.Error.sqlite_errorcode exists from 3.11)
grep -n "sqlite3" scripts/check_architecture_principles.py
  192: {"sqlite3.connect", "aiosqlite.connect"}   (only connect calls are flagged; importing sqlite3 for its error class is not)
grep -n "executescript\|no rows\|and nothing" tests/test_ad1287_profile_qualification_store.py
  135: async def executescript(...)   837: ... == before  # no rows   1696: ... and a literal passed to execute, and nothing
```


Round 1 additions (read this round):
```
Read tests/test_ad1286_elastic_team_store.py:1225-1319
  1234-1266: rowid-replace-{specs,slots,attempts,outcomes}: (rowid, ...) VALUES (1, ...) with keys colliding with nothing
  1270: def _refusal_message(statement: str) -> str:   1272: return "rowid" if "(rowid," in statement else ...
  1296: async def test_every_table_is_without_rowid   1309: definition.rstrip().upper().endswith("WITHOUT ROWID")
  1312: async def test_triggers_still_accept_genuinely_new_rows
Read execution_profile.py:185-191  canonical_bytes = canonicalize_projection(self.model_dump(mode="json"))  (top-level keys = field names)
Grep execution_profile.py  41: _MAX_VALIDITY_SECONDS = 31_622_400   167: role_id   168: task_class   211: profile_ref   212: evaluation_id   239-241: def expires_at_ms ... issued_at_ms + validity_seconds * 1_000
Grep json_extract src/probos  workforce.py:1678, :3537 (SQLite JSON functions already in production use)
Grep tests/test_ad1287_profile_qualification_store.py (staged candidate)
  56: cached-column list incl. "role_id", "task_class", "qualification_id"   91: class _ProxyConnection   97: "...could then not release the write lock..."
  575, 584, 635: raw SQL writing role_id   672, 693-696: case "profile_role_id_cached"   875: test_close_failure_is_logged_and_the_operation_result_stands
WebFetch sqlite.org/gencol.html  §2.2 UNIQUE / foreign keys / indexes allowed on generated columns; §2.3 not PRIMARY KEY; added 3.31.0
```

Base verification (round 0):

```
git log --oneline -1                                   -> f85cd42c Merge pull request #1519 ...
scripts/ad_ceiling.py                                  -> CEILING: AD-1327 (GitHub issue titles, all states); NEXT AD-1328 (not used)

Grep elastic_team.py
  56:  def canonicalize_projection(value: object) -> bytes:
  76:  def is_sha256_ref(value: object) -> bool:
  132: ElasticId = Annotated[str, BeforeValidator(_id)]
  133: Sha256Ref = Annotated[str, BeforeValidator(_sha)]
  138: Revision = Annotated[int, BeforeValidator(_int_range(1, _MAX_REVISION, "elastic_team_revision_invalid"))]
  161: model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")
  195-199: class QualificationRequirement ... qualification_ids: IdSet / pinned_profile_refs: RefSet
  240-244: class AuthorityCeiling ... tool_scopes: ScopeSet / data_scopes: ScopeSet
  247-258: class WorkerSlot: slot_id, role_id, task_class, capacity, qualification, ..., authority
  297: class ElasticTeamSpec(_Frozen):     332: def slot(self, slot_id: str) -> WorkerSlot | None:
  350-362: class WorkerAttempt ... execution_profile_ref: Sha256Ref
  353: ``execution_profile_ref`` is a reference only; AD-1287 defines how it is computed.
  424-427: class TeamSpecLookup(Protocol): async def get_team_spec(...) -> ElasticTeamSpec | None

Grep elastic_team_store.py
  610: async def get_team_spec(self, team_spec_ref: str) -> ElasticTeamSpec | None:
  625: async def record_attempt(self, attempt: WorkerAttempt) -> WorkerAttempt:
  731-733: pinned = slot.qualification.pinned_profile_refs / ... raise ElasticTeamConflict("elastic_attempt_profile_not_pinned")
  767: async def get_attempt(self, worker_attempt_id: str) -> WorkerAttempt | None:
  785: async def list_slot_attempts(

Grep repair_evidence_store.py
  239: if type(db_path) is not str or not db_path or db_path == ":memory:":
  277-297: @contextlib.asynccontextmanager async def _open ... await db.close() ... except Exception: # noqa: BLE001
  341: await db.execute("BEGIN IMMEDIATE")      361: await db.commit()  # not shielded ...

Grep storage_declarations.py
  141-167: StoreDeclaration(id="cognitive.elastic-teams", ...)
  168-192: StoreDeclaration(id="cognitive.repair-evidence", ..., lifecycle_owner="unowned", ...)   193: )
Grep storage/declarations.py   109: UNOWNED_LIFECYCLE: Final[str] = "unowned"
Grep storage/sqlite_factory.py 10: class SQLiteConnectionFactory:   28: default_factory = SQLiteConnectionFactory()
Grep protocols.py              362: class ConnectionFactory(Protocol):   369: async def connect(self, db_path: str) -> DatabaseConnection:

Grep skill_catalog.py
  53-71: class CognitiveSkillEntry: name, description, skill_dir, ...
  194: if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", entry.name):
  233-238: def __init__(self, skills_dir: Path | None = None, db_path: str | None = None, connection_factory=None)
  337: def get_entry(self, name: str) -> CognitiveSkillEntry | None:
  550: async def validate_skill(self, name: str, validation_context: dict | None = None) -> SkillValidationResult:
Grep qualification.py   122-136: CREATE TABLE qualification_results (id, agent_id, test_name, tier, score REAL, ...)   146: class QualificationStore:   177-182: ALTER TABLE ... except Exception: pass
Grep qual_skill_bridge.py  43: class QualificationSkillBridge:   67: async def process_qualification(
Grep skill_bridge.py       22: class SkillBridge:
Grep model_registry.py     33-43: class ModelDescriptor: name, provider, tier, capabilities, cost..., context_window_tokens, available
Grep config.py             320-322: llm_model_fast/standard = "claude-sonnet-4-6", llm_model_deep = "claude-sonnet-5.5"
Grep tools/protocol.py     95: class Tool(Protocol):   127: def input_schema   132: def output_schema   219: class ToolRegistration:
Grep consensus/trust.py    55: class TrustRecord:   66: alpha: float = 2.0   67: beta: float = 2.0   612: async def record_outcome_once(
Grep startup/finalize.py   2041: async def _wire_elastic_team_store(*, runtime: Any) -> bool:   2068: db_path = Path(data_dir) / "elastic_teams.db"
Grep check_architecture_principles.py  187: SRP_MAX_BODY_LINES = 500   188: SRP_MAX_DIRECT_METHODS = 15  (store class: 11 methods)
Grep tests/test_ad1286_elastic_team_contract.py  51: _PROFILE_A   52: _KAT_SPEC   104: def _independent_jcs   134: def _independent_digest   145: def _spec   150: def _slot   157: def _review_slot   179: def _attempt
  63-78: analyse slot pins _PROFILE_A; review slot: role "reviewer", task "finding_review", ids ["finding_review"], pins [], max_attempts 2
Grep tests/test_ad1286_elastic_team_store.py  37: from tests.test_ad1286_elastic_team_contract import _PROFILE_A, _review_slot, _slot, _spec   158: def _tamper(
Grep tests/test_ad596e_skill_validation.py   26: def _write_skill(tmp_path, name, content)
Grep tests/test_ad1299_s1b_repair_evidence_store.py  57: load_default_store_registry  58: SQLiteConnectionFactory  1111: def test_nothing_in_src_constructs_the_store
Glob site-packages  pydantic-2.12.5.dist-info, aiosqlite-0.22.1.dist-info
git ls-files --eol  elastic_team.py, repair_evidence_store.py, storage_declarations.py, test_ad1286_elastic_team_store.py: i/lf w/crlf
```

## Absence Verified (2026-10-12, base `f85cd42c`)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A1 | No owner computes a skill or resource digest | Grep `hashlib\|digest` in `skill_catalog.py`; Grep `sha256` in `src/probos/**/*skill*`; Grep `(skill\|resource)_digest\|resource_hash\|skill_hash` in `src/probos` | 0; 0; only `content_hash` in `api_models.py`, `artifacts/`, `attachments/` (attachment bytes, unrelated) | yes |
| A2 | No production caller of `ElasticTeamStore.record_attempt` / `put_team_spec` | Grep `record_attempt\b\|put_team_spec\b` in `src/probos` | `elastic_team_store.py` (definitions and docstrings), `crew_development/discovery/confidence.py:10,58,78` (an unrelated `record_attempt(agent_id, capability, success)`) | yes |
| A3 | `ModelDescriptor` has no version field | Read `model_registry.py:32-43` | fields name, provider, tier, capabilities, two costs, context window, available | yes |
| A4 | The `Tool` protocol has no implementation version | Grep `version` in `tools/protocol.py` | 0 | yes |
| A5 | The S1 names are free | Glob `src/probos/cognitive/*{profile,qualif}*.py`; Grep `ExecutionProfile\|ProfileQualification\|profile_qualifications\.db\|execution_profile\b` in `src`; Glob `tests/test_ad1287*` | `qualification.py`, `qualification_tests.py` only; 0; 0 | yes |
| A6 | `QualificationRequirement` is not evaluated anywhere | Grep `elastic_team\|ElasticTeam\|WorkerSlot\|execution_profile_ref` (files) in `src/probos` | 7 files: `elastic_team.py`, `elastic_team_store.py`, `crew_session.py`, `storage_declarations.py`, `runtime.py`, `startup/finalize.py`, `startup/shutdown.py`; the only qualification read is the pin check at `elastic_team_store.py:731-733` | yes (for `qualification_ids`) |

## Not verified

- No Python interpreter under the bridge, so none of this was executed: the module code, the known-answer vectors (the Builder computes them), the SQL (an in-column `CHECK` followed by a `--` comment; a `UNIQUE` column constraint on a `WITHOUT ROWID` table; the trigger `WHEN` clauses; SQLite's `CHECK constraint failed` message text), or the mutation table. M2 #17-#19 and M4 test exactly these. **If any premise fails, stop and report rather than weaken the assertion.**
- That pydantic 2.12.5 raises no protected-namespace warning for the field named `model`. The component fields avoid the `model_` prefix; M1 runs under the repository's warning filters.
- That `TypeAdapter(ElasticId)` raises a `ValueError` subclass for a non-string. Pydantic documents `ValidationError` as a `ValueError` subclass, and M2 #14 (`5` as the id) asserts it.
- The live data directory was not inspected, so whether a `profile_qualifications.db` exists there is unknown. What was checked is source only: this slice adds no construction of the store under `src/` (M3 #16, direct references).
- **Round 1 (no interpreter again):** that SQLite 3.50.4 accepts `VIRTUAL` generated columns in a `WITHOUT ROWID` table with a column `REFERENCES` clause and a table `UNIQUE` over two generated columns (sqlite.org/gencol.html §2.2 says generated columns "may have NOT NULL, CHECK, and UNIQUE constraints, and foreign key constraints"; it says nothing about `WITHOUT ROWID`); the exact text of the generated-column UPDATE error (asserted only as containing `generated column`); `PRAGMA table_xinfo` `hidden = 2` for a VIRTUAL generated column; that `set_progress_handler(cb, 1)` counts are size-independent for `_NEXT_SEQ_SQL` (the orchestrator measured 38 VM steps at 10/1000/10000 rows); that the `--` comment after `WITHOUT ROWID;` is outside the `sqlite_master.sql` text. The trigger reads `json_extract(NEW.canonical_json, ...)` rather than `NEW.profile_ref` on purpose: the value of a generated column in a `BEFORE INSERT` trigger was not verified. **Any failing premise: stop and report (Brief R1).**

---

## Later slices (scoped here, drafted separately after S1 lands)

- **S2: component producers and drift.** Pure digest functions: a skill directory (sorted relative POSIX paths, per-file sha256 and size, symlinks and paths outside the directory refused, bounded), tool schemas (RFC 8785 over `input_schema`/`output_schema`), model (`ModelDescriptor` plus a configured version label), and policy. Also: `structurally_valid` from `validate_skill`, a `ProfileComponentSource` protocol, drift detection that records `component_drift_<component>` invalidations, and a gate currency check (O-2). The chain test: build a profile from a real catalog and tool, evaluate it, change one skill file, detect drift, and see the gate refuse. Prior art to check then: SLSA resolved-dependency digests and OCI content digests.
- **S3: outcome learning (O-3).** An insert-only `profile_outcomes` table in the same store (additive `CREATE TABLE IF NOT EXISTS`). A producer reads AD-1286 attempt outcomes, and `ProfileQualification` gains `alpha`/`beta` as raw integers. The chain test: admit through the gate, record the AD-1286 outcome, learn, restart, see the Beta parameters in the query evidence, and replay idempotently.

=== BUILDER BRIEFS ===

### Brief M1 — pure contract (effort: max)

**Prompt:** `prompts/ad-1287-s1-execution-profile-qualification.md`, Sections 1-2 and D2/D8. Read them by range; do not read the whole prompt.
**May touch:** new `src/probos/cognitive/execution_profile.py` (copy Section 1 verbatim); new `tests/test_ad1287_execution_profile.py`.
**Import root:** `$env:PYTHONPATH="$PWD\src"` (Bash: `PYTHONPATH="$PWD/src"`); `python -c "import probos; print(probos.__file__)"` must print a path inside this worktree. Stop if it does not.
**CRLF:** tracked files are `w/crlf`. New files may be LF. Never rewrite an existing file whole.
**Steps:**
1. Create the module exactly as Section 1.
2. Compute the two KAT literals ONCE, with a scratch script outside `src/` and `tests/` that imports only `tests.test_ad1286_elastic_team_contract._independent_digest` and hand-sorted fixture dicts (never the module). Paste them, then delete the scratch.
3. Write the 15 tests of Section 2. Export `_PROFILE`, `_profile`, `_record`, `_observations` for M2 and M3.
**Focused run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1287_execution_profile.py tests/test_ad1286_elastic_team_contract.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`
**Stop and report if:** a KAT disagrees with the module (do not edit the literal to match); pydantic warns about the `model` field; you need any change to `elastic_team.py`.
**Report:** test counts, sha256 of both files.

### Brief M2 — store and declaration (effort: max)

**Prompt:** Sections 3-5, D3/D4/D7/D9. M1 must be in the tree.
**May touch:** new `src/probos/cognitive/profile_qualification_store.py` (copy Section 3 verbatim); `src/probos/cognitive/storage_declarations.py` (insert Section 4 between `:192` `    ),` and `:193` `)`; nothing else in that file); new `tests/test_ad1287_profile_qualification_store.py`.
**Import root / CRLF:** as M1.
**Steps:**
1. Create the module; insert the declaration.
2. Write the 25 tests of Section 5. #22 makes no timing assertion. Proxies hold no cursor (`await cursor.close()` before parking).
3. Stage the three files by explicit path, then run `d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check` and `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check`.
**Focused run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1287_profile_qualification_store.py tests/test_ad1287_execution_profile.py tests/test_ad1256_store_registry.py tests/test_ad1270b_architecture_fitness.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`
**Stop and report if:** SQLite rejects any schema construct; a CHECK, trigger or message premise of #17-#19 fails (report it, do not weaken it); a checker fails; you need a `src/` change outside the three files.

### Brief M3 — query, gate, seam (effort: max)

**Prompt:** Section 6, D5. M1 and M2 must be in the tree.
**May touch:** new `tests/test_ad1287_slot_qualification.py` only. A defect found in Section 3 code: stop and report (Architect triage); do not patch the module.
**Steps:** write the 16 tests. #10 is the milestone seam: real files for both stores and NEW instances after the restart. Fakes are `_FakeReader` and `_FakeTeams` (no `MagicMock`). #16 is AST-based with negative controls.
**Focused run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1287_slot_qualification.py tests/test_ad1287_profile_qualification_store.py tests/test_ad1287_execution_profile.py tests/test_ad1286_elastic_team_store.py tests/test_ad596e_skill_validation.py -q -n 0 -p no:randomly`
**Stop and report if:** #10 cannot be made to pass without changing a module; `ElasticTeamStore` refuses the KAT spec's review-slot attempt for a reason other than the gate.

### Brief M4 — mutation campaign of record (effort: high)

**Prompt:** the Mutation table only. Run on the COMMITTED tree after all review repairs, once.
**Steps:** run the unmutated baseline of the three AD-1287 test files (abort if red). For each of P1-P13 and S1-S44 (**57 mutants**; S6 as re-anchored in round 1, S13 and S18-S20 as re-anchored in rounds 2/R2b; S41-S43 with `-p no:randomly` and a per-test timeout of 60 s): count the anchor (exactly 1); create a `.mutbak` sibling; replace in place; run the killer files `-q -n 0 -p no:randomly -x`; restore in `finally`; confirm the sha256 is restored. Classify each as KILLED (and the first failing test id), INERT or INVALID.
**Report:** the base commit, the sha256 of the six pinned files (both modules, the three test files, `storage_declarations.py`), and the per-mutant table. M5 copies it.
**Stop if:** any mutant survives. First check that the mutant reaches the behaviour it claims to break, then report.

### Brief M5 — trackers (effort: high)

**Prompt:** "Tracking (M5)" and "Obligations handed on". **May touch:** `PROGRESS.md` (insert after `:1`), `DECISIONS.md` (new section above `:13`), `docs/development/roadmap.md:527`. Grep anchors first; ranged reads only; no code or test edits. Recompute the six sha256s and stop if any differs from the M4 report. Wording: "records/refuses/detects", never "authenticates/prevents/grants". Run `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad1287-s1` on the staged candidate and repair cheap failures. No broad gate.

### Brief R1 — review round 1 repairs, both reviewers (effort: max, at most 150 calls)

**Prompt:** "Review round 1" (both tables), D3/D4/D7/D9, Section 3 (extract it whole: it must be **726 lines, sha256 `361ec37afcc634abfe691be884e3871d289f6378a5b6247036e19a8bbc5708d6` (CRLF)**), Section 4 `notes`, Section 5 (intro, raw-SQL note, rows #17-#20 and #26-#33, the total), Section 6 row #16, Mutation table S6 and S18-S28, "Not verified" round-1 bullet. Ranged reads only.
**May touch:** `src/probos/cognitive/profile_qualification_store.py` (replace whole with the Section 3 block, byte-exact); `src/probos/cognitive/storage_declarations.py` (the AD-1287 entry's `notes` string only); `tests/test_ad1287_profile_qualification_store.py` (edit: helpers and raw SQL that name generated columns, #17-#20, the proxy docstring, the `_Clock` docstring and a `reads` counter, the section comment `# 26. A failed close` -> `# 33. A failed close` with #33's assertions per its row; add #26-#32); `tests/test_ad1287_slot_qualification.py` (ruling B2 only, three wording sites plus one forbidden shape, below). Nothing else.
**B2 wording (exact):**
- `_gate_references` docstring (search `"""Every construction of the store, call of a gate function`) -> `"""Direct syntactic references in ``tree``: an import of an S1 module, or a call whose callee is a gate name or an attribute named one. Not found here: a call through a plain alias (``S = ProfileQualificationStore; S()``) or a lookup by string (``getattr``, ``sys.modules``)."""`
- `_scan_tree` comment (search `cannot call or import them`) -> `# names no S1 module or gate name, so it holds no direct syntactic reference: not worth a parse`
- test docstring first line (search `nothing in ``src`` constructs or calls them`) -> `"""Pins D5: no file under ``src/probos`` except the two S1 modules holds a direct syntactic reference to them (an import of an S1 module, or a call of the store or a gate function by name or attribute).` and append to its body: `Calls through a plain alias and lookups by string are not covered; this test does not assert them either way.`
- add to `_FORBIDDEN_SHAPES`: `"m = importlib.import_module('probos.cognitive.profile_qualification_store')\nm.ProfileQualificationStore('x.db')"`. Add no test that asserts a missed shape is unflagged.
**Steps:** 1. Extract Section 3; check lines and sha256; install it and `notes`. 2. Run the focused M2 command once before editing tests; list the failures (expected: raw SQL naming generated columns). 3. Repair those; add #26-#32 and renumber/extend #33, each premise asserted first. 4. Apply the B2 edits. 5. Re-stage the four files by explicit path; run both `--check` scripts.
**Focused run:** the Brief M2 command, plus `tests/test_ad1287_slot_qualification.py`.
**Stop and report if:** the extracted Section 3 is not 726 lines with the sha256 above; SQLite refuses the schema (generated column with `REFERENCES`, `UNIQUE`, or in `WITHOUT ROWID`); the generated-column UPDATE error lacks `generated column`; `table_xinfo` `hidden` is not 2; #30's premise fails or `_NEXT_SEQ_SQL` steps grow by more than 2; the `sqlite_master.sql` text does not end with `WITHOUT ROWID`; #32 measures any count other than its row; any M3 test fails; you need a change to `execution_profile.py`, any other M3 test line or any AD-1286 file. Do not weaken an assertion to pass.
**Report:** per-file test counts, sha256 of the four files, the measured VM steps for both SQL at 10 and 1000 rows, and #32's measured counts. M4 (campaign of record, P1-P13 and S1-S28) runs after this brief is committed.

### Brief R2 — review round 2 repairs, reviewer C (effort: max, at most 150 calls)

**Prompt:** "Round 2, reviewer C" (in the review record), D3a, D4 "Sequence bound", D9, Section 3 (extract it whole: **795 lines** between its fences; the orchestrator records its sha256), Section 4 `notes`, Section 5 (rows #32 and #34-#37, "R2 proxy addition", "R2 `_OLD_LAYOUT_SCHEMA`", "R2 wording", the total), Mutation table S13, S18-S20, S29-S36 and the round-2 note. Ranged reads only.
**May touch:** `src/probos/cognitive/profile_qualification_store.py` (replace whole with the Section 3 block, byte-exact, AFTER step 1); `src/probos/cognitive/storage_declarations.py` (the AD-1287 entry's `notes` string only); `tests/test_ad1287_profile_qualification_store.py` (the two R2 wording sites, `_ProxyFactory`/`_ProxyConnection` per "R2 proxy addition", #32's extension, new #34-#37, `_OLD_LAYOUT_SCHEMA`). Nothing else: no edit to `execution_profile.py`, the M3 test file or any AD-1286 file.
**Steps:**
1. Copy `_SCHEMA` from the installed R1 module into the test as `_OLD_LAYOUT_SCHEMA` with the four line changes. 2. Extract Section 3; check 795 lines; install it and the `notes` text. 3. Run the focused command once before editing tests; every existing test must pass (none depends on `IF NOT EXISTS` or `executescript`); list any failure and stop if one is not explained by the rulings. 4. Apply the wording, the proxy addition and #32's extension; add #34-#37, each premise asserted first. 5. Re-stage the three files by explicit path; run both `--check` scripts.
**Focused run:** the Brief M2 command, plus `tests/test_ad1287_slot_qualification.py`.
**Stop and report if:** the extracted Section 3 is not 795 lines; a NEW instance on a file the store created is refused (report `sqlite_master.sql` of each differing object next to its statement; do not normalise or loosen the comparison); #35's autoindex premise fails; #34's file sha256 or journal mode changes on refusal, or its `hidden` 0 premise fails; #35 `generated_expression`'s `hidden` 2 premise fails; #36 cannot insert its raw row; #37's raw `0` premise fails; any M3 test fails; you need any change outside the three files. Do not weaken an assertion to pass.
**Report:** per-file test counts; sha256 of the three files; the stored `sql` of `execution_profiles` and `profile_evaluations_no_replace` on a fresh file, each compared with its statement (equal / not); the names #34's ERROR log listed; #37's list for each call. M4 (campaign of record, P1-P13 and S1-S36, 49 mutants) runs after this brief is committed.

### Brief R2b — registry detection repair (fresh Builder; effort: max, at most 60 calls)

**Prompt:** Section 3 (extract it whole: **799 lines** between its fences; the orchestrator records its sha256), Section 5 "R2b addition" (#38), "R2b note" and "R2b total", Mutation table S18-S20, S33 and S37. Ranged reads only.
**May touch:** `src/probos/cognitive/profile_qualification_store.py` (replace whole with the Section 3 block, byte-exact; the only difference from R2 is the schema block from `# One statement per schema object` to the `_SCHEMA_STATEMENTS` tuple's close, module lines 79-143: each `CREATE TABLE` bound to its own `Final` name, a comment line, the tuple listing the names); `tests/test_ad1287_profile_qualification_store.py` (add #38 only). Nothing else.
**Steps:** 1. Extract Section 3; check 799 lines; install it. 2. Add #38, negative control asserted first. 3. Re-stage both files by explicit path; run both `--check` scripts; `check_store_registry.py --check` must report `store modules=68`. 4. Focused run: the Brief R2 command.
**Stop and report if:** the extracted Section 3 is not 799 lines; `--check` reports anything other than 68 store modules; #38's negative control does not return `()`; a NEW instance on a file the store created is refused; any previously passing test fails; you need any change outside the two files. Do not weaken an assertion to pass.
**Report:** per-file test counts (M2 file: 38); sha256 of both files; the `store modules=` line. M4 (campaign of record, P1-P13 and S1-S37, 50 mutants) runs after this brief is committed.

### Brief R3 — round 3 repairs, reviewers D1 and D2 (fresh Builder; effort: max, at most 150 calls)

**Prompt:** "Round 3, reviewers D1 and D2" (review record), D3a, D3b, D7 N1, D9, Section 3 (extract it whole: **840 lines** between its fences; the orchestrator records its sha256), Section 4 `notes`, Section 5 ("R3 amendments to #35", "R3 additions" #39-#44, "R3 proxy addition", "R3 wording", "R3 total"), Mutation table S28-S44. Ranged reads only.
**May touch:** `src/probos/cognitive/profile_qualification_store.py` (replace whole with the Section 3 block, byte-exact); `src/probos/cognitive/storage_declarations.py` (the AD-1287 entry's `notes` string only); `tests/test_ad1287_profile_qualification_store.py` (#35 amendments, the proxy addition and `executescript` removal, the R3 wording, new #39-#44). Nothing else: no edit to `execution_profile.py`, the M3 test file or any AD-1286 file; no new public API.
**Steps:** 1. Extract Section 3; check 840 lines; install it and the `notes` text. 2. Focused M2 command once before editing tests; every existing test must pass. 3. Proxy addition; #35 amendments; #39-#44, each premise asserted first; wording. 4. Run #41 and #42 five times each with `-p no:randomly` (flake check, not a timing assertion). 5. Re-stage the three files by explicit path; run both `--check` scripts (`store modules=68`).
**Focused run:** the Brief M2 command, plus `tests/test_ad1287_slot_qualification.py`.
**Stop and report if:** the extracted Section 3 is not 840 lines; #41's `wal_busy >= 1` premise fails (the race is not reproduced: report what the switch answered); the BUSY error's `sqlite_errorcode & 0xFF` is not 5 (report `sqlite_errorcode` and `sqlite_errorname`); #44 fails in any run; #39's empty-catalog assertion fails; #40's raw row is refused; any previously passing test fails; you need a change outside the three files. Do not weaken an assertion to pass.
**Report:** per-file test counts (M2 file: 44); sha256 of the three files; #41's `wal_tries`/`wal_busy` and the error's `sqlite_errorcode`/`sqlite_errorname`; #42's WARNING text; the five-run results of #41/#42; the `store modules=` line. M4 (campaign of record, P1-P13 and S1-S44, 57 mutants) runs after this brief is committed. **Superseded by Brief R4: M4 runs 60 mutants after R4.**

### Brief R4 — round 4 repairs, reviewer E (fresh Builder; effort: max, at most 100 calls)

**Prompt:** "Round 4, reviewer E" (review record), D3a, D3b, D9, Section 3 (extract it whole: **848 lines** between its fences; the orchestrator records its sha256), Section 5 ("R4 additions" #45-#47, "R4 proxy changes", "R4 helper change", "R4 total"), Mutation table S41 and S45-S47. Ranged reads only.
**May touch:** `src/probos/cognitive/profile_qualification_store.py` (replace whole with the Section 3 block, byte-exact); `tests/test_ad1287_profile_qualification_store.py` (proxy and helper changes, #45-#47). `storage_declarations.py` `notes` needs no change in R4 (its wording is already true); touch it only if the orchestrator says otherwise. Nothing else: no edit to `execution_profile.py`, the M3 test file or any AD-1286 file; no new public API.
**Steps:** 1. Extract Section 3; check 848 lines; install it. 2. Focused M2 command once before editing tests; all 44 must pass. 3. Proxy changes, helper change; #45-#47, each premise asserted first. 4. Run #41, #42 and #46 five times each with `-p no:randomly`; report #46's elapsed each run. 5. Apply S45 alone, run #46 once and report its elapsed (expect >= 10 s), revert (premise check of the margin, not the campaign). 6. Re-stage the two files by explicit path; run both `--check` scripts (`store modules=68`).
**Focused run:** the Brief M2 command, plus `tests/test_ad1287_slot_qualification.py`.
**Stop and report if:** Section 3 is not 848 lines; #46's premise fails (the holder's `BEGIN EXCLUSIVE` did not succeed, or `wal_busy != 2`: report the error's `sqlite_errorcode`/`sqlite_errorname`); #46's elapsed is >= 2.5 s in any run; S45 alone does not make #46 fail; #47's `not hasattr(err, "sqlite_errorcode")` premise fails; "Task exception was never retrieved" appears in any run of #41-#47; any previously passing test fails; you need a change outside the two files. Do not weaken an assertion or widen the 2.5 s bound to pass.
**Report:** per-file test counts (M2 file: 47); sha256 of the touched files; #46's five elapsed times and the S45 elapsed; #45's recorded statement list for the switching connection; #47's raised object identity check; five-run results of #41/#42/#46; the `store modules=` line. M4 (campaign of record, P1-P13 and S1-S47, **60** mutants) runs after this brief is committed.
