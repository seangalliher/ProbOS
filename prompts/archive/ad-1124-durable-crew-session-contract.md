# AD-1124 - Durable CrewSession contract on WorkItem and task-linked room

**Verdict:** APPROVED FOR BUILDER HANDOFF, CONDITIONAL ON THE ISSUE-BODY AMENDMENT BELOW
**One-line:** Add one strict, versioned `crew_session` contract on an existing draft WorkItem, bind it fail-closed to exactly one existing task-linked room, and preserve the established workforce state vocabulary by keeping the fine session state in metadata.

**Parent epic:** [#1041](https://github.com/seangalliher/ProbOS/issues/1041) - Durable Crew Work Sessions
**GitHub issue:** [#1043](https://github.com/seangalliher/ProbOS/issues/1043) - AD-1124
**Dependency:** [#1042](https://github.com/seangalliher/ProbOS/issues/1042) / BF-673 is `CLOSED/COMPLETED`
**Repository:** OSS `D:\ProbOS`
**Exact base HEAD / `origin/main` / remote `main`:** `00884a6148aeac6167f2025795e475281aa6de1f`
**Exact base subject:** `BF-673: correct group trigger provenance`
**Exact base status before Architect artifacts:** clean `main`; no staged, modified, deleted, or untracked paths
**Numbering:** current top-level ceiling **AD-1123**; current bug-fix ceiling **BF-673**; build **AD-1124** only
**License disposition:** no external code, dependency, model, or asset
**Estimated tests:** one new red-first module, approximately 40-50 cases; report the exact collected count

## Scope

AD-1124 delivers only the durable collaboration contract and its storage/service boundary:

1. one built-in `crew_session` WorkType;
2. one strict `CrewSessionContract` persisted at `WorkItem.metadata["crew_session"]`;
3. one `CrewSessionService` over the existing `WorkItemStore` and `ChatThreadStore` APIs;
4. one exact legal fine-state machine;
5. one store-owned runtime-local atomic top-level metadata merge, with optional validated coarse-status projection and compare-before-write protection;
6. exactly one draft parent bound to exactly one existing `ChatThread.task_id == parent.id` room;
7. server-owned timestamps, strict field/list/ref/total-byte bounds, and version/revision checks;
8. default-off startup composition under the existing `agentic_dispatch.orchestrator_enabled` gate;
9. migration of the two live parent-metadata writers (`input_attachments` and `crew_synth`) to the shared merge primitive.

This AD creates no parent, room, child task, execution, async work, verifier call, artifact, event-log row, trust update, notification, endpoint, intent, or UI state. Provisioning and ingress remain later issues in epic #1041.

---

## Required issue #1043 amendment before Builder start

The current issue body says the fine states (`discussing`, `executing`, `verifying`, `blocked_needs_captain`) are stored directly in `WorkItem.status` and that this column is the single authority. That wording is incompatible with the live generic workforce consumers:

- `WorkItemStatus` defines the shared vocabulary `draft/open/scheduled/in_progress/review/done/failed/cancelled/blocked`;
- generic board, claim, reconciliation, status, snapshot, task-room, notifier, and route code compares the shared values directly;
- `WorkTypeRegistry` technically accepts arbitrary per-type strings, but that does not make the rest of the system understand them;
- the generic workforce PATCH/transition routes accept and project `WorkItem.status` directly.

Before the Builder starts, the orchestrator must replace the entire current `## Decision` section of issue #1043, through the line immediately before `## Acceptance`, with this exact Markdown:

```markdown
## Decision

Add a built-in `crew_session` work type to the existing `WorkTypeRegistry`, but do **not** add session-specific strings to the shared `WorkItemStatus` vocabulary or generic workforce routes.

An unbound `crew_session` WorkItem starts in generic `draft`. `CrewSessionService.initialize_session(...)` validates and binds the existing parent to exactly one existing `ChatThread` whose `task_id` equals the parent id, then atomically installs the contract and advances the generic status to `open`.

The authoritative fine session state lives in the strict, versioned `WorkItem.metadata["crew_session"]["state"]` contract:

`discussing -> executing -> verifying -> done`

with bounded alternate transitions to `blocked_needs_captain` and `failed`. `done`/`failed` are terminal. `blocked_needs_captain` may resume to `discussing` or `executing`, or transition to `failed`.

`WorkItem.status` remains a coarse compatibility projection, updated atomically with the metadata state:

- `discussing -> open`
- `executing -> in_progress`
- `verifying -> review`
- `blocked_needs_captain -> blocked`
- `done -> done`
- `failed -> failed`

Store a versioned, bounded `CrewSessionContract` in `WorkItem.metadata["crew_session"]` containing:

- goal;
- origin (`captain` or `agent`) and originator id;
- facilitator/owner ids;
- success criteria;
- expected deliverable;
- linked `thread_id` and parent `task_id`;
- state, previous state, revision, and transition timestamp;
- timestamps (`created`, `started`, `first_result`, `verified`, `completed`);
- last concrete result summary;
- blocked reason/since/accumulated duration;
- evidence refs and result artifact/ref;
- duplicate-resume count.

Add one narrow `CrewSessionService` that owns contract validation, fine-transition legality, link checks, compare-before-write revision handling, coarse-status projection, metadata merge, and server-generated timestamps. Reuse `WorkItemStore` and `ChatThreadStore`; do not add a database, table, column, or index.

Add a store-owned runtime-local atomic top-level metadata merge so `crew_session`, existing `origin`, `input_attachments`, and `crew_synth` keys cannot clobber one another through whole-column replacement. The primitive may update a validated generic status in the same SQL statement. It must preserve unrelated keys, support expected-value conflict detection, and make no cross-process or cross-database atomicity claim.

The existing `agentic_dispatch.orchestrator_enabled` flag remains the master composition gate. When false (the default), no CrewSessionService is constructed and no store read/write occurs. The built-in work-type descriptor is additive and discoverable, but an uninitialized parent remains `draft` and no execution path is activated.
```

Then insert these exact bullets in `## Acceptance` after the current round-trip bullet:

```markdown
- Fine session state is authoritative in `metadata["crew_session"]`; `WorkItem.status` remains the exact generic projection above. No new global WorkItem status value is introduced.
- A legacy workforce SQLite database reopens without DDL migration; ordinary WorkItems and metadata remain unchanged.
```

No other issue or epic text needs amendment. The Builder must verify this wording read-only and must not mutate GitHub.

---

## Live compatibility finding

### Decision

Use metadata state plus an atomic coarse projection. Do not use session-specific strings in the global `status` column.

### Why this is the smallest correct architecture

1. `WorkItem.status: str` is extensible at the dataclass/registry level, but generic consumers are not dynamically typed by WorkType.
2. Existing generic values already map exactly to the requested phases: `open`, `in_progress`, `review`, `blocked`, `done`, `failed`.
3. A metadata authority avoids changing existing routes, board queries, reconciler logic, task notifiers, and snapshots.
4. Keeping an atomic coarse projection preserves current indexing/filtering and lets later ADs reuse the existing executor/synthesizer state vocabulary.
5. A `draft` pre-bind state prevents a raw, incomplete `crew_session` row from appearing as dispatchable open work before its room/contract exists.
6. No schema migration is needed. Rollback before future ingress is a code-only rollback; persisted metadata remains ordinary JSON.

---

## Pinned design decisions

### DD-1 - Fine state is metadata authority; WorkItem status is a generic projection

Define the exact fine states:

```python
CrewSessionState = Literal[
    "discussing",
    "executing",
    "verifying",
    "blocked_needs_captain",
    "done",
    "failed",
]
```

The projection is fixed:

| Fine state | Generic `WorkItem.status` |
|---|---|
| `discussing` | `open` |
| `executing` | `in_progress` |
| `verifying` | `review` |
| `blocked_needs_captain` | `blocked` |
| `done` | `done` |
| `failed` | `failed` |

`CrewSessionService` validates the persisted fine state and exact projection on every load/transition. A mismatch fails closed with a stable `ValueError` reason; it is never silently repaired in AD-1124.

Do not edit `WorkItemStatus`. Do not teach generic API/HXI consumers the fine strings.

### DD-2 - Built-in `crew_session` uses only existing workforce states

Add `BUILTIN_WORK_TYPES["crew_session"]` in `src/probos/workforce.py`:

- `initial_status="draft"`;
- `terminal_statuses=frozenset({"done", "failed"})`;
- `supports_children=True`;
- `auto_assign_eligible=False` (declarative policy only; do not widen claim/reconciler scope here);
- `verification_required=True`;
- `required_fields=["title"]`;
- default priority 2.

Exact coarse transitions:

| From | Allowed targets |
|---|---|
| `draft` | `open` (requires assignment) |
| `open` | `in_progress` (requires assignment), `blocked`, `failed` |
| `in_progress` | `review`, `blocked`, `failed` |
| `review` | `done`, `blocked`, `failed` |
| `blocked` | `open`, `in_progress` (requires assignment), `failed` |
| `done` | none |
| `failed` | none |

Do not add `cancelled` to the fine state or WorkType transition graph. Cancellation semantics belong to the lifecycle-runner issue, not this contract AD.

`draft -> open` is the one activation edge used by `initialize_session`; no unbound row is a live session.

### DD-3 - Exact fine-state transition matrix

Same-state with no metadata additions is an idempotent read: no DB write, revision, timestamp, event, or log transition.

| From | Allowed different target states |
|---|---|
| `discussing` | `executing`, `blocked_needs_captain`, `failed` |
| `executing` | `verifying`, `blocked_needs_captain`, `failed` |
| `verifying` | `done`, `blocked_needs_captain`, `failed` |
| `blocked_needs_captain` | `discussing`, `executing`, `failed` |
| `done` | none |
| `failed` | none |

Expose one pure, fully annotated `is_valid_crew_session_transition(old, new) -> bool` helper. It returns `True` for an exact same-state idempotent request and for only the edges above. Unknown/non-string states never pass model validation.

### DD-4 - Exact contract key allowlist and bounds

Create `src/probos/cognitive/crew_session.py`. Use a strict frozen Pydantic v2 model (`extra="forbid"`, `strict=True`) or an equivalently strict immutable model. No extra key, coercion, nonfinite number, `bool`-as-`int`, malformed list, or unknown version/state is accepted. Persisted JSON uses arrays, but the in-memory contract must not retain mutable caller/list aliases: use tuple-backed fields or defensive immutable copies plus fresh-list serialization. `frozen=True` with caller-owned mutable list fields is not sufficient.

The exact v1 top-level key allowlist is:

| Key | Exact v1 rule |
|---|---|
| `version` | exact integer `1` |
| `state` | exact fine-state literal |
| `previous_state` | fine-state literal or `None` |
| `revision` | exact non-boolean int, `1..2_147_483_647` |
| `goal` | trimmed non-empty str, max 4,096 code points |
| `origin` | exact `captain` or `agent` |
| `originator_id` | canonical bounded id below |
| `facilitator_id` | canonical bounded id; must occur in `owner_ids` |
| `owner_ids` | exact list, 1..16 unique canonical ids |
| `success_criteria` | exact list, 1..16 unique trimmed non-empty strings, max 512 code points each |
| `expected_deliverable` | trimmed non-empty str, max 2,048 code points |
| `thread_id` | canonical bounded id |
| `task_id` | canonical bounded id and exact parent WorkItem id |
| `created_at` | server-owned finite timestamp |
| `transitioned_at` | server-owned finite timestamp |
| `started_at` | server-owned finite timestamp or `None` |
| `first_result_at` | server-owned finite timestamp or `None` |
| `verified_at` | server-owned finite timestamp or `None` |
| `completed_at` | server-owned finite timestamp or `None` |
| `last_result_summary` | trimmed str max 4,096 code points; empty means no result |
| `blocked_reason` | trimmed non-empty str max 2,048 only while blocked; otherwise `None` |
| `blocked_since` | server-owned timestamp only while blocked; otherwise `None` |
| `blocked_duration_seconds` | finite nonnegative float, max 315,576,000 (10 years) |
| `evidence_refs` | exact list of 0..32 unique canonical lowercase SHA-256 refs |
| `result_artifact_id` | canonical bounded id or `None` |
| `result_ref` | canonical lowercase SHA-256 ref or `None` |
| `duplicate_resume_count` | exact non-boolean int, `0..1_000_000`; initialized to 0 and not incremented by AD-1124 |

Canonical bounded ids match exactly `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`. SHA refs match exactly `^[0-9a-f]{64}$`. All text rejects NUL and is normalized by trim only; do not silently truncate.

Every timestamp is a finite non-boolean int/float in `0..253_402_300_799`, normalized to float. The service accepts no timestamp parameter from callers. The injected clock is the sole transition-time source; `created_at` comes from the server-owned parent `WorkItem.created_at`. A new clock value must be greater than or equal to `created_at`, the prior `transitioned_at`, and any active `blocked_since`; clock regression fails before mutation. Optional milestone timestamps must be chronologically consistent, and `completed_at` cannot precede any populated milestone.

The complete compact UTF-8 JSON for the `crew_session` object must be at most **32,768 bytes** using deterministic compact encoding. Validate this after every construction/update and before storage. Do not put large provenance, tool traces, artifact bytes, or result bodies in metadata; v1 stores refs and bounded summaries only.

### DD-5 - One service, three public methods, no provisioning

`CrewSessionService` depends on narrow local Protocols for the methods it uses, not on `ProbOSRuntime`. Production injects the real `WorkItemStore` and `ChatThreadStore`. Its public API is exactly:

```python
async def initialize_session(
    self,
    parent_id: str,
    thread_id: str,
    *,
    goal: str,
    origin: CrewSessionOrigin,
    originator_id: str,
    facilitator_id: str,
    owner_ids: list[str],
    success_criteria: list[str],
    expected_deliverable: str,
) -> CrewSessionContract:
    ...

async def get_session(self, parent_id: str) -> CrewSessionContract | None:
    ...

async def transition_session(
    self,
    parent_id: str,
    new_state: CrewSessionState,
    *,
    expected_revision: int,
    last_result_summary: str | None = None,
    blocked_reason: str | None = None,
    evidence_refs: list[str] | None = None,
    result_artifact_id: str | None = None,
    result_ref: str | None = None,
) -> CrewSessionContract:
    ...
```

No `create_parent`, `create_thread`, `open_or_resume`, `schedule`, `start`, `stop`, `run`, `verify`, `notify`, or dedup method belongs here.

For a new binding, `initialize_session` requires:

- existing parent;
- `work_type == "crew_session"`;
- generic `status == "draft"`;
- non-empty `assigned_to == facilitator_id`;
- no valid pre-existing different contract;
- exact room invariant from DD-6.

It installs v1/revision 1/state `discussing`, sets `task_id=parent.id`, uses parent `created_at`, stamps `transitioned_at` from the injected clock, then atomically writes metadata plus `status="open"` through DD-7.

Before applying the new-binding `draft` check, inspect any existing `crew_session` object. An exact replay against an already-valid contract with the same immutable initialization inputs and valid coarse projection returns the existing contract unchanged. A conflicting or malformed replay fails closed. This is bind idempotency, not semantic goal dedup.

`transition_session` requires exact current revision. A stale revision fails with no mutation. It:

- validates the fine edge;
- computes the coarse target;
- sets `started_at` on first entry to `executing`;
- sets `first_result_at` when the first non-empty result summary is accepted;
- requires non-empty `blocked_reason` when entering `blocked_needs_captain`, sets `blocked_since`, and preserves accumulated duration;
- on leaving blocked, adds `now - blocked_since` to `blocked_duration_seconds` and clears current blocked reason/since;
- sets `verified_at` and `completed_at` on `done`;
- sets `completed_at` on `failed`;
- appends newly supplied evidence refs in first-seen order, deduped and bounded;
- accepts `result_artifact_id`/`result_ref` only on transition to `done`;
- increments revision once for any actual change;
- updates `previous_state`/`transitioned_at` only when the fine state changes;
- performs one compare-before-write store call.

A same-state call with no effective additions is an idempotent read. A same-state `executing` or `verifying` call with a genuinely new bounded result summary/evidence ref is a progress update: revision advances, but `previous_state` and `transitioned_at` do not change.

Validation, link, projection, stale-revision, and illegal-transition failures are fail-fast `ValueError`s with stable non-secret reason strings. Missing parent/session returns `None` only from `get_session`; initialize/transition fail explicitly. Storage and data-integrity errors propagate. Log no goal, criterion, result, blocker, evidence value, or serialized metadata.

### DD-6 - Exactly one parent and one existing task-linked room

The service never creates or relinks a room. For initialize, load, and transition:

1. fetch the parent through the injected WorkItem protocol;
2. call the synchronous `ChatThreadStore` APIs through `asyncio.to_thread`;
3. require `get_thread(contract_or_input.thread_id)` to exist;
4. require its exact `task_id == parent.id`;
5. require `list_threads(task_id=parent.id, include_archived=True, limit=2)` to return exactly one row and that row's id to equal the contract thread id.

Zero, two, wrong-task, wrong-thread, and archived-duplicate cases fail closed before mutation. Do not add a unique index or claim cross-database atomicity. Historical databases may already contain duplicates; a new index could make startup fail. AD-1128 owns reconstructable provisioning, admission locking, create failure recovery, and dedup.

### DD-7 - Store-owned runtime-local merge and atomic projection

Add this fully annotated public method to `WorkItemStore`:

```python
async def merge_work_item_metadata(
    self,
    work_item_id: str,
    patch: dict[str, Any],
    *,
    expected: dict[str, Any] | None = None,
    expected_work_type: str | None = None,
    expected_status: str | None = None,
    expected_assigned_to: str | None = None,
    new_status: str | None = None,
    source: str = "system",
) -> WorkItem | None:
    ...
```

Contract:

- one runtime-local `asyncio.Lock` owned by `WorkItemStore` serializes this merge method with every existing same-store path that can mutate a WorkItem's `metadata`, `work_type`, `status`, or `assigned_to`; at minimum this includes `update_work_item`, `transition_work_item`, the WorkItem-row portion of `assign_work_item`, `unassign_work_item`, and `start_booking`;
- load the current row inside the lock;
- shallow-merge exact top-level patch keys into a fresh metadata dict;
- `expected`, when supplied, compares only its listed top-level keys against the current metadata before mutation; mismatch raises exact `ValueError("work_item_metadata_conflict")`;
- each non-`None` `expected_work_type`, `expected_status`, and `expected_assigned_to` compares against the row loaded inside the shared lock; mismatch raises exact `ValueError("work_item_state_conflict")` before validation or mutation;
- keep the shared lock held from the authoritative row load and all expected-value checks through the SQL update and commit, so a same-store writer cannot enter between validation and commit; do not hold it across event emission or snapshot refresh;
- `new_status`, when different, uses the same WorkType/terminal/steps/assignment validation as `transition_work_item`; extract a private shared validator rather than copy a divergent state machine;
- serialize/size-check before SQL mutation;
- one SQL `UPDATE` writes metadata, optional status, and `updated_at` together; one commit follows;
- ordinary DB errors propagate after best-effort SQL rollback through `DatabaseConnection.execute("ROLLBACK")` when a transaction is active; cancellation propagates. Do not call a phantom `DatabaseConnection.rollback()` method (the live Protocol does not define one);
- refresh snapshot once after commit;
- emit existing `WORK_ITEM_UPDATED`; when status changed, also emit existing `WORK_ITEM_STATUS_CHANGED` with old/new values. Add no `EventType`;
- return the reloaded WorkItem; missing row returns `None`;
- empty patch plus unchanged/no status returns the current item without write/event.

This is **runtime-local atomic merge**, not distributed compare-and-swap. Do not claim safety across multiple processes or independent store instances. The shared lock closes same-store coroutine interleavings only; the explicit expected row fields carry the service's earlier validation into that linearization point. It is cloud-ready because it uses the injected `ConnectionFactory`/`DatabaseConnection`; never call `aiosqlite.connect()` or `sqlite3.connect()` from the new path.

For initialization, the service supplies `expected={"crew_session": None}`, `expected_work_type="crew_session"`, `expected_status="draft"`, and `expected_assigned_to=facilitator_id`. For transition, it supplies the exact loaded contract, `expected_work_type="crew_session"`, and `expected_status=<projection of the loaded fine state>`. It also supplies the projected `new_status`, so validated parent invariants, fine state, and coarse status reach one runtime-local linearization point and the metadata/status mutation commits in one statement.

### DD-8 - Migrate the two live parent metadata writers

The no-clobber claim is false if only the new service uses the merge primitive. Migrate exactly these two live parent writers:

1. `routers/workforce.py::attach_work_item_inputs` - preserve its validation, ref dedup, return shape, and one-request behavior, but write only `{"input_attachments": existing}` through `merge_work_item_metadata` instead of caller-side whole-column replacement.
2. `cognitive/crew_synth.py::_complete_parent` - write only `{"crew_synth": {...}}` through `merge_work_item_metadata` instead of replacing all metadata.

The existing `origin` key is created with the parent and needs no writer migration; both migrated writers must preserve it and `crew_session`.

Do not sweep every historical `update_work_item(metadata=...)` caller. Child assignment, capability-gap, Quartermaster, and ground-truth metadata have separate ownership/risk and are outside issue #1043. The guarantee in this AD is the explicit `crew_session` / `origin` / `input_attachments` / `crew_synth` parent contract.

### DD-9 - Existing default-off orchestrator flag owns composition

Add a narrow `_wire_crew_session_service(*, runtime, config) -> bool` next to `_wire_crew_orchestrator` in `startup/finalize.py` and invoke it immediately before the orchestrator wirer.

- First operation: read `config.agentic_dispatch.orchestrator_enabled`; false/missing returns `False` before store lookup or module import.
- Enabled path requires real `runtime.work_item_store` and `runtime.chat_thread_store`; a missing dependency logs WARNING with what is missing, why the enabled contract is unavailable, and that no service was attached.
- Lazy-import and attach exactly one `runtime.crew_session_service`.
- If the exact service is already attached, return `True` without replacing it.
- Add the public type annotation and `None` initialization in `runtime.py`.
- No start/stop method, task, shutdown edit, event subscription, or background scan.

The built-in WorkType is always discoverable. With the default gate false, however, no service object is constructed, no store is read/written, no row is created, and no execution path is activated. An uninitialized `crew_session` parent remains `draft`.

---

## Build

### Section 0 - Event types and database schema

**None.** Add no `EventType`, table, column, index, migration version, config field, YAML key, dependency, endpoint, intent, or protocol-global widening.

### Section 1 - Red-first tests

Create `tests/test_ad1124_crew_session_contract.py` before production edits. The module must use:

- real `WorkItemStore` on `tmp_path`, started/stopped per test or isolated fixture;
- real `ChatThreadStore` on `tmp_path`;
- real `SystemConfig` for the default-off gate;
- deterministic narrow clocks/recorders/barriers, not `MagicMock`, `Mock`, or `AsyncMock`;
- no live model, network, GitHub, EventLog, trust, notifier, or UI.

Run the headline test before production edits. Expected RED is import/collection failure because `probos.cognitive.crew_session` does not exist and the built-in type/merge method are absent. Record the exact output; do not weaken tests.

Required test families:

1. built-in descriptor exact fields, initial `draft`, coarse legal/illegal matrix, terminal refusal, and proof no fine state was added to `WorkItemStatus`;
2. pure fine-state all-pairs matrix, including same-state idempotency;
3. real initialize happy path with exact projection/link/metadata;
4. strict contract all-field round-trip through executing/progress/blocked/resume/verifying/done;
5. deterministic server timestamps, first-write semantics, blocked-duration accumulation, caller inability to inject timestamps, and clock-regression/chronology rejection without mutation;
6. exact same-state no-op leaves revision/timestamps/updated_at/events unchanged;
7. same-state progress additions update once, dedup evidence, and set first-result time once;
8. stale revision conflict and two concurrent same-revision transitions: exactly one commits, one conflicts, no unrelated key is lost; deterministic barriers must also force (a) reassignment/work-type/status change after service load but before merge admission and (b) a generic status writer attempting to enter after merge admission, proving pre-admission changes conflict without mutation and post-admission writers cannot interleave before commit;
9. exact empty/None, malformed-id/ref, unknown state/version/key, duplicate list, excessive list/text/total-byte, bool-number, nonfinite/negative timestamp/duration, terminal-update rejection, and mutation of caller/output lists proving no alias reaches the frozen contract;
10. missing/wrong-type/wrong-status/unassigned/facilitator-not-owner parent failures before mutation;
11. missing room, wrong `task_id`, wrong requested thread, zero room, two rooms (including archived duplicate) all fail closed;
12. projection mismatch fails on get/transition without repair;
13. concurrent real-SQLite top-level merges for `origin`, `input_attachments`, `crew_synth`, and `crew_session` preserve all keys;
14. input-upload path preserves existing `origin`, `crew_session`, and `crew_synth` while appending/deduping input refs;
15. crew-synth metadata path preserves existing `origin`, `crew_session`, and `input_attachments`;
16. pre-AD database compatibility: create ordinary rows/metadata, stop, reopen under AD-1124, assert the `work_items` column list is unchanged and bytes/values survive; then create/bind a session and reopen again;
17. default-off wirer returns before touching absent stores/importing/attaching; real enabled wiring attaches exactly one service and a repeated wire preserves identity;
18. no production/test path uses a raw SQLite connection for the new service/merge.
19. injected `DatabaseConnection` recorders force SQL-update failure, commit failure, and cancellation; ordinary failures propagate after an attempted SQL `ROLLBACK`, cancellation remains `CancelledError`, and the shared row-write lock is released in every branch.

### Section 2 - Built-in type and store merge

Modify only `src/probos/workforce.py` per DD-2 and DD-7.

Preserve all existing public CRUD return shapes and existing WorkType behavior. Existing `transition_work_item` tests must remain green unchanged.

### Section 3 - Strict contract and service

Add only `src/probos/cognitive/crew_session.py` per DD-1, DD-3 through DD-6.

The module may import stdlib, Pydantic, and narrow type-only/live store dataclasses needed for typing. It must not import runtime, orchestrator, executor, verifier, EventLog, trust, notifier, UI, API routers, or config.

### Section 4 - Existing metadata-writer migration

Modify only:

- `src/probos/routers/workforce.py` at `attach_work_item_inputs`;
- `src/probos/cognitive/crew_synth.py` at `_complete_parent`.

Keep every response/result/status/trust/episode/artifact behavior otherwise unchanged. This section does not integrate CrewSynthesizer with CrewSessionService; AD-1126 owns fine-state finalization.

### Section 5 - Default-off startup composition

Modify only:

- `src/probos/runtime.py` for one public optional attribute declaration/initialization;
- `src/probos/startup/finalize.py` for the gated narrow wirer and one call immediately before `_wire_crew_orchestrator`.

Do not pass the service into `CrewOrchestrator` and do not edit the orchestrator. Later epic children own integration.

### Section 6 - Gates, review, and closeout

Run the exact commands in the execution prompt. After all gates and three Builder review passes are green:

1. prepend an AD-1124 shipped block to `PROGRESS.md` with exact new/focused/blast/full counts, the metadata-authority/coarse-projection decision, one-room invariant, runtime-local merge, default-off inert behavior, no schema/YAML/API/execution, AD-1124 as top-level ceiling, and BF-673 unchanged;
2. prepend `### AD-1124 (2026-07-17) - durable CrewSession contract (#1043)` under Era V in `DECISIONS.md`, with Context / Decision / Tests and the exact compatibility finding;
3. add one row immediately after AD-862 in the existing Crew Autonomy table of `docs/development/roadmap.md`: AD-1124, durable `crew_session` WorkItem contract and task-linked room, epic #1041 / issue #1043, priority 1, marked shipped/closed on push;
4. move both prompt files byte-for-byte to `prompts/archive/`, verifying pre/post SHA-256 equality;
5. stage explicit allowlisted paths only;
6. commit exactly `AD-1124: add durable crew session contract (closes #1043)`;
7. do not push and do not mutate GitHub.

Issue #1043 closes only after the orchestrator/Captain pushes the local commit.

---

## Exact file allowlist

### Production

- `src/probos/workforce.py`
- `src/probos/cognitive/crew_session.py` - new
- `src/probos/routers/workforce.py`
- `src/probos/cognitive/crew_synth.py`
- `src/probos/runtime.py`
- `src/probos/startup/finalize.py`

### Tests

- `tests/test_ad1124_crew_session_contract.py` - new

### Architect documents - active until closeout, then hash-preserving move

- `prompts/ad-1124-durable-crew-session-contract.md`
- `prompts/ad-1124-durable-crew-session-contract-execution.md`

### Conditional closeout only

- `PROGRESS.md`
- `DECISIONS.md`
- `docs/development/roadmap.md`

No other path is authorized. In particular, do not edit `config/system.yaml`, `src/probos/config.py`, `src/probos/threads/__init__.py`, `src/probos/cognitive/crew_orchestrator.py`, `src/probos/cognitive/crew_executor.py`, `src/probos/cognitive/crew_verifier.py`, `src/probos/events.py`, `src/probos/protocols.py`, any API model/router beyond the one metadata-writer call, any UI/desktop file, any existing test file, or any dependency manifest.

---

## Exact base hashes

All existing allowlisted files must match before Builder edits:

| Path | SHA-256 |
|---|---|
| `src/probos/workforce.py` | `8f11696d7dd686fc40cd0da2a478a85a664640d599f608740450dc0469136820` |
| `src/probos/routers/workforce.py` | `517179a1b6ed5daa06f11ffd77e7c48c18d5416e00762bb6d7088fbea3aa9573` |
| `src/probos/cognitive/crew_synth.py` | `150145bfbb34d354eef6e7c12345749416adf30b42c25d2138966bb0203077e1` |
| `src/probos/runtime.py` | `bcf757c8c61762f5ea431e8f3503ad3c1e69e5ec376c277d3e9fe55b24475d23` |
| `src/probos/startup/finalize.py` | `211f7428270b82660cbd35fd8efee026e9a9f070511315967392ae998ee1992b` |

These frozen reference surfaces must remain unchanged:

| Path | SHA-256 |
|---|---|
| `src/probos/threads/__init__.py` | `88fe637aca2475b74a53fb934a30feff01ba84acd6516a2c8f277ddc367f29ff` |
| `src/probos/config.py` | `aa7a67269da3f34cb43bb2210921211ad22e57dfbfd1f6e8117327ad02247c10` |
| `src/probos/cognitive/crew_orchestrator.py` | `f77ca5adfae7e7abccc46a37fba824e8dfd126afe80f9eeba757266a02c5f575` |
| `src/probos/cognitive/crew_executor.py` | `499e5f7397a0599091e838444a907e33a7ada4ed8cfe3c3d7e2c4db7f3661936` |
| `tests/test_workforce.py` | `0c617a9f576865e5c192d091bec8661f9759dd28467e7558dee2f789ebfbe530` |
| `tests/test_ad791_chat_threads.py` | `a7d7dfba4962aacdc3f207cffa1dfcf982bc177c555d9fac332e0da1798cdd56` |
| `tests/test_ad859_crew_executor.py` | `b629c7704d932a948c15220b8d6d4c71faba748840033882c86d3740f8280797` |
| `tests/test_ad861_crew_synth.py` | `d709520aec16c388629ab23db79c00acbdee02ee80f5343787d25830423c3bf0` |
| `tests/test_ad862_crew_tasks_api.py` | `dab18b608b0ab0e22f0e952b38ea7db96e701f1bf16d306ab5a577239f7633d6` |
| `tests/test_ad867_crew_orchestrator.py` | `7de99f6069c66e32ac25c4fece79d3de0d8923a93b62245df28023acc06344aa` |
| `tests/test_ad868_self_originated_crew.py` | `7276f23f7fd5102de39c9edf36d926af8d27986eb259a45ec3b0b0e31dd03cf4` |
| `tests/test_ad925_auto_task_room.py` | `b9cb9c2069818c999c8a9c33ccbdb7ad2a6b62c585fe1d48bc42885bf6e378de` |
| `tests/test_ad926a_task_file_upload.py` | `3a12cfa262d090ef3ec4aa1dd1c9d4ff278f9f0220aa9ad656f6f01e6f3cc90a` |

`src/probos/cognitive/crew_session.py` and `tests/test_ad1124_crew_session_contract.py` must not exist before build. Any mismatch is a hard stop for Architect re-verification.

---

## Recorded exact-base gate baselines

Measured on clean `00884a6148` with isolated temporary data and Python 3.12.13:

| Gate | Exact base result |
|---|---:|
| Workforce/metadata serial baseline | **164 passed**, no warnings under `-W error::RuntimeWarning` |
| Crew/thread/runtime serial baseline | **104 passed**, no warnings under `-W error::RuntimeWarning` |
| Full parallel `-n 4 --dist=loadfile` | **19,585 passed / 33 skipped / 1 failed / 453 warnings** |
| Serial triage of the one full-gate failure | **92 passed** (`tests/test_ward_room.py`) |

The lone full-gate failure was `TestEndorsementActivation::test_browse_threads_sort_recent`; it passed in full-file serial isolation and is classified as pre-existing parallel ordering/environment noise. Post-build, the new module count is additive. No changed-path warning is allowed.

The execution prompt contains exact commands and triage rules.

---

## Acceptance criteria

1. `crew_session` is a built-in WorkType with initial `draft` and only the exact existing coarse status graph in DD-2.
2. `WorkItemStatus` and every generic route/status vocabulary remain unchanged.
3. A strict v1 contract accepts exactly the 27 keys and bounds in DD-4; malformed, oversized, extra, coerced, nonfinite, and unknown values fail before mutation.
4. The exact fine state and projection matrices pass for all pairs; terminal states cannot leave.
5. Parent draft + assigned facilitator + exactly one task-linked room initializes atomically to metadata `discussing` plus generic `open`.
6. Every load/transition validates one-parent/one-room cardinality and exact `thread.task_id`; mismatch fails closed.
7. Every timestamp is server-owned and deterministic under an injected clock; blocked duration and first-result semantics are exact.
8. Same-state/no-change is a true no-op; stale revision, concurrent same-revision writers, and a parent work-type/status/assignment change between service load and merge admission cannot be overwritten by the service.
9. `merge_work_item_metadata` preserves unrelated keys under real concurrent SQLite calls, can atomically update one validated coarse status with metadata, and shares one runtime-local row-write lock with every existing same-store writer of metadata/work-type/status/assignment.
10. `origin`, `crew_session`, `input_attachments`, and `crew_synth` survive each authorized writer in any tested order.
11. Legacy workforce SQLite reopens with an unchanged `work_items` column list and no DDL migration; ordinary data survives.
12. Default `orchestrator_enabled=False` creates no service and performs no store I/O; enabled composition attaches exactly one service using real stores.
13. No service/runtime task, lifecycle method, scan, subscription, execution, verifier, ingress, dedup, EventLog, trust, notifier, endpoint, UI, YAML, dependency, table, column, or index is added.
14. New public classes/functions/methods have full parameter and return annotations. Protocol signatures match the real methods exactly.
15. Logs identify parent id/state/revision and what happens next without logging goal/result/blocker/ref values. Data-integrity errors propagate.
16. Tests use real `WorkItemStore` and `ChatThreadStore`; no `MagicMock`, `Mock`, or `AsyncMock` at substrate boundaries or anywhere in the new module.
17. Focused, workforce, blast, and full gates meet the formulas/baselines in the execution prompt; any full-gate parallel failure is rerun serially before classification.
18. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Do not build here

- No parent/room creation, provisioning marker, rollback/repair flow, admission lock, exact/semantic dedup, or `open_or_resume` (AD-1128).
- No child execution, room id threading, AgenticLoop changes, tool trace, token/artifact persistence, or failure-state repair (AD-1125).
- No verifier convergence, synthesis acceptance rule, final artifact generation, or CrewSynthesizer-to-service integration (AD-1126).
- No async session runner, task registry, recovery scan, start/stop, scheduling gate, cancellation lifecycle, or shutdown edit (AD-1127).
- No EventLog query tool/endpoint (AD-1129).
- No trust/Hebbian/conversation policy (AD-1130).
- No notification, delivery metric, or event type (AD-1131).
- No HXI/API projection, passive-rail removal, or live push (AD-1132/1133).
- No global WorkItem status string, route model, generic status-filter, reconciler, board, claim, booking, or notifier redesign.
- No unique thread index, cross-database transaction claim, new database, schema migration, or raw SQLite connection.
- No config field or tracked `config/system.yaml` edit.
- No commercial/pricing/enterprise content.
- No new AD/BF number.

---

## Hard stops

Stop and return to the Architect if:

1. HEAD, origin, remote main, status shape, issue amendment, or any pinned hash differs;
2. issue #1043 still says fine state is stored directly in `WorkItem.status`;
3. an existing test file must change;
4. the build requires a file outside the allowlist;
5. a fine session string must enter `WorkItemStatus`, a generic API route, board/reconciler, or persisted status column;
6. one-room correctness appears to require a unique-index migration or cross-database transaction;
7. metadata merge requires raw `aiosqlite.connect()`/`sqlite3.connect()` or a Protocol widening;
8. default-off composition touches a store, creates a row/task, or imports/constructs the service;
9. execution, verification, lifecycle, ingress, dedup, EventLog, trust, notifier, UI, YAML, or new event work becomes necessary;
10. red tests pass unexpectedly or fail for a reason other than the missing AD-1124 surface;
11. a focused/serial regression persists outside AD-1124;
12. a log/test exposes bounded contract content rather than identifiers/types;
13. the Builder is asked to push or mutate GitHub.
14. a same-store WorkItem status/assignment/work-type writer can enter between the merge primitive's authoritative reload and commit, or the service cannot carry its earlier parent invariants into merge admission without widening the global database Protocol.

---

## Verified against live codebase (2026-07-17)

- `workforce.py:41` - global `WorkItemStatus` has only the established generic values.
- `workforce.py:110-245` - built-in WorkTypes define per-type edges over generic statuses.
- `workforce.py:248-310` - `WorkTypeRegistry` validates per-type strings but does not update generic consumers.
- `workforce.py:581-629` - `WorkItem.status` is a string; metadata is one JSON dict.
- `workforce.py:966-1015` - `WorkItemStore` already uses injected `ConnectionFactory`/`DatabaseConnection`.
- `workforce.py:1169-1202` - `update_work_item(metadata=...)` replaces the complete JSON column.
- `workforce.py:1276-1356` - transition validation owns terminal, step-completion, WorkType, and assignment gates.
- `workforce.py:1859-1932` - TTL/overdue/snapshot SQL recognizes only generic terminal/open states.
- `threads/__init__.py:204-320` - real synchronous `ChatThreadStore` exposes create/get/list/update; list has `task_id` and `include_archived` filters.
- `threads/__init__.py:283-310` - `list_threads(task_id=..., limit=...)` is the existing AD-925 room lookup.
- `crew_executor.py:300-319` - current task-room idempotency is a caller-side list-then-create check and does not return/bind a contract.
- `crew_orchestrator.py:363-421` - current pipeline uses generic `open/in_progress` and whole-column child metadata writes; it is not changed here.
- `crew_synth.py:287-319` - parent completion uses validated transition, then currently replaces metadata with only `crew_synth`.
- `routers/workforce.py:317-385` - task-input upload currently performs caller-side read-merge-whole-column replacement.
- `config.py:6088-6113` - `AgenticDispatchConfig.orchestrator_enabled` exists and defaults false.
- `startup/finalize.py:1716-1830` - `_wire_crew_orchestrator` is the established gate/wiring neighborhood.
- `startup/finalize.py:2770` - finalize invokes the orchestrator wirer.
- `runtime.py:279,821` - `work_item_store` has a public optional declaration and explicit `None` initialization; use the same pattern for the service.
- `routers/workforce.py:169-185` - generic transition API writes the shared status directly, confirming fine-state strings must not be added there.
- `agents/quartermaster.py`, `work_reconciler.py`, `naval/*`, `routers/crew.py`, `task_completion_notifier.py`, and snapshots compare generic statuses directly.
- Real-store test precedents: `test_workforce.py`, `test_ad861_crew_synth.py`, `test_ad867_crew_orchestrator.py`, `test_ad925_auto_task_room.py`, `test_ad926a_task_file_upload.py`.
- GitHub read-only: #1041 OPEN, #1043 OPEN, #1042 CLOSED/COMPLETED.
- No active prompt, source, test, tracker entry, or implementation for AD-1124/`crew_session` exists at the exact base.

---

## Three-pass Architect self-review

### Pass 1 - Requirements and issue reconciliation

**Verdict:** APPROVED WITH ONE REQUIRED PRE-BUILD GITHUB BODY AMENDMENT.

- Every user requirement maps to a build section and acceptance item.
- The issue's global-status wording was compared against live route/board/reconciler consumers and corrected, not followed literally.
- One service, one metadata contract, one built-in type, one room invariant, one merge primitive, and one test module remain the only feature surface.
- Real SQLite round-trip/reopen/concurrency and no-MagicMock requirements are explicit.

### Pass 2 - Verify-first and technical consistency

**Verdict:** APPROVED.

- All named paths/classes/methods/signatures/config gates and metadata writers were read at exact HEAD.
- The WorkType graph uses only live generic statuses.
- `draft` pre-bind closes the accidental-open/default-path gap.
- The service consumes public store APIs and uses `asyncio.to_thread` for the synchronous room store.
- The merge uses the existing cloud-ready connection abstraction and is explicitly runtime-local.
- Input and synth writers migrate to the same primitive, making the no-clobber claim testable.
- No schema/index migration is needed; historical duplicate rooms fail closed rather than blocking startup.

### Pass 3 - Scope, safety, and execution readiness

**Verdict:** APPROVED FOR BUILDER AFTER ISSUE AMENDMENT.

- The dependency DAG is satisfied by closed BF-673/#1042.
- No execution/verifier/lifecycle/ingress/dedup/EventLog/trust/notifier/UI/YAML work leaked in.
- Default-off composition is inert; the additive WorkType remains undispatched as `draft` until service initialization.
- Exact hashes, allowlist, red-first order, four gate levels, closeout trackers, archival, commit subject, no-push, and no-GitHub rules are pinned.
- Every public API has happy/error/empty/boundary/concurrency coverage.

## Pre-dispatch checklist

- [x] Current highest verified: AD-1123 / BF-673; AD-1124 is unused.
- [x] Correct OSS repository and boundary.
- [x] Issue #1043 and parent #1041 read in full; #1042 dependency closed.
- [x] Every concrete API/path/signature verified against exact live base.
- [x] Fine/global state compatibility decision resolved.
- [x] Every build item maps to acceptance/tests.
- [x] Real SQLite round-trip, reopen, migration-compatibility, and concurrency tests specified.
- [x] Existing default-off gate reused; no config/YAML addition.
- [x] Exact do-not-build and hard-stop fences present.
- [x] Full annotations, log quality, cloud-ready storage, and compliance line present.

## Implementation re-review (2026-07-17) - blocking CAS correction

**Verdict:** BLOCKED until the revised DD-7 row preconditions, shared write-lock boundary, and deterministic race/rollback/cancellation tests above are implemented and all gates are rerun.

- A real-store interleaving reassigned the draft parent after `initialize_session` loaded it but before merge admission; initialization still committed a facilitator contract for the old assignee.
- A second real-store interleaving moved the bound parent through the legal generic `open -> blocked` edge after `transition_session` validated projection but before merge admission; the service accepted `blocked -> in_progress` and overwrote the concurrent decision.
- The current merge-only lock protects the three AD-1124 merge callers from one another, but it does not protect the service's parent invariants from existing same-store row writers. The correction remains runtime-local and does not claim room/work-item cross-database atomicity.

## Final implementation re-review (2026-07-17) - exact JSON CAS blocker

**Verdict:** BLOCKED. The shared writer lock and row preconditions are corrected, but metadata expected-value comparison is not JSON-type-exact.

### Required

1. `WorkItemStore.merge_work_item_metadata` currently compares expected values with Python `!=`. Python treats JSON booleans as their numeric aliases (`True == 1`, `False == 0`), including inside nested dictionaries. A generic metadata writer can therefore replace a loaded valid contract's `version`, `revision`, `duplicate_resume_count`, or `blocked_duration_seconds` with a Python-equal but contract-invalid boolean/integer value after the service load; the service merge then overwrites that concurrent write instead of raising `ValueError("work_item_metadata_conflict")`.
2. Make non-missing expected metadata comparison JSON-type-exact at every nested level. A deterministic compact JSON comparison or an equivalently strict recursive comparator is acceptable. Preserve the initialization contract that an absent top-level `crew_session` key satisfies `expected={"crew_session": None}`; do not make missing equivalent to any other value.
3. Add a deterministic real-store service load-to-merge barrier test that writes a Python-equal/JSON-different malformed `crew_session` value through the live generic writer before merge admission. Require `work_item_metadata_conflict`, preserve the concurrent bytes/value without service repair, and prove no status/session transition committed. Add a direct nested expected-value test covering boolean/numeric aliases.
4. Rerun Gate 0 through Gate 3 and all three Builder reviews. Re-report the new exact module count `N`; the previous 55/219/159/full counts remain evidence for the superseded implementation, not closeout evidence.

### Verified

- The revised service passes the required work-type/status/assignee preconditions into merge admission.
- The shared non-reentrant writer lock covers generic update, transition, assignment, unassignment, and booking-start WorkItem row writes without nested acquisition.
- SQL update/commit failure and cancellation attempt rollback, propagate, release the lock, and permit a subsequent merge.
- Snapshot refresh and event emission occur after lock release; default-off wiring remains inert.