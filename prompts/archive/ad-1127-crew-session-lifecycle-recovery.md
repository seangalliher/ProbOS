# AD-1127: CrewSession Lifecycle Recovery

**One-line:** Promote `CrewOrchestrator` to the single lifecycle owner for bounded asynchronous CrewSession execution and phase-aware restart recovery, using only the existing WorkItem, room, Attachment, and Artifact stores.

**Status:** Architect-adjudicated binding prompt; partial Group A tree preserved; Builder resume pending
**Issue:** #1046; parent #1041
**Dependencies:** AD-1124 (#1043), AD-1125 (#1044), AD-1126 (#1045), all landed
**Base:** `8a7bd9805b38b303bb0598d1be102d4e7ec4c610` (`AD-1126: add verified CrewSession finalization (closes #1045)`)
**Ceilings at base:** AD-1126, BF-673
**Estimated new tests:** 72-96; let `N` be the final net-new collected passing count

## Decision

`CrewOrchestrator` is the only lifecycle owner. Do not add a runner service, queue, scheduler, daemon, worker, or second orchestration engine. It owns one parent-keyed strong task map, one parent-level semaphore, startup recovery, retry/backoff inside the same owner task, synchronous admission close, and cancellation-deferred shutdown drain.

The change is default-off under the existing `agentic_dispatch.orchestrator_enabled`. When false, construction may remain available, but `start()` performs no scan and creates no task; `schedule()` remains closed.

AD-1127 recovers only an already authoritative CrewSession parent/room/contract. It may install or adopt the child plan for that bound session, but it must not create, deduplicate, repair, or expose ingress for a parent, room, or session. AD-1128 owns `open_or_resume`, Captain/agent ingress, provisioning repair, semantic dedup, explicit retry authorization, and the Start Work UI/API.

## Public Contract

Implement these fully annotated methods on `CrewOrchestrator`:

```python
async def start(self) -> None: ...
def schedule(self, parent_id: str) -> asyncio.Task[SynthesisResult]: ...
def close_scheduling(self) -> None: ...
async def stop(self) -> None: ...
```

1. Construction starts closed and taskless. `start()` is idempotent. When enabled, it opens admission synchronously before its first await, performs exactly one globally bounded combined-state scan, and schedules eligible rows. A repeated successful `start()` does not scan again.
2. `schedule()` is synchronous. It validates the bounded parent id and the open gate before creating work. A live duplicate returns the identical task object. A post-close call raises exact `RuntimeError("crew_session_scheduling_closed")` and creates no coroutine/task/map entry.
3. `_tasks_by_parent: dict[str, asyncio.Task[SynthesisResult]]` is the sole parent owner map. The done callback captures `(parent_id, task)`, calls `task.result()` to observe every outcome, handles `CancelledError` separately, logs ordinary failure with parent and next durable disposition, and removes only when `map.get(parent_id) is task`.
4. One `asyncio.Semaphore(max_active_crew_sessions)` bounds active parents. AD-1125's child semaphore continues to bound children; do not replace or merge the two limits.
5. `close_scheduling()` only closes admission and is synchronous/idempotent. `stop()` calls it before its first await, cancels one stable task snapshot, and drains that same snapshot in one held cleanup task. Outer cancellation is deferred until the drain finishes, then re-raised. Concurrent/repeated stops share the cleanup and do not cancel twice.
6. Existing `maybe_dispatch_crew()` delegates task ownership to `schedule()` after its existing enabled/multi-child decision. Preserve its return type and legacy behavior. Do not convert AD-868/AD-1128 ingress in this AD.
7. Serialize `start()` with one lifecycle lock. A completed start is an idempotent no-op; a failed/cancelled start closes admission, drains tasks it admitted, resets to the pre-start state, and may be retried. `stop()` is terminal for that instance; `start()` after a completed stop raises exact `RuntimeError("crew_session_lifecycle_stopped")` and never reopens admission.

## Configuration

Add bounded Pydantic fields to `AgenticDispatchConfig`; do not edit `config/system.yaml`:

| Field | Default | Bound | Meaning |
|---|---:|---:|---|
| `max_active_crew_sessions` | 2 | `ge=1, le=32` | concurrent parent owners |
| `crew_resume_scan_limit` | 100 | `ge=1, le=1000` | one global startup result cap |
| `crew_recovery_max_retries` | 3 | `ge=0, le=10` | consecutive transient retries per checkpoint |
| `crew_recovery_initial_backoff_seconds` | 5.0 | `ge=0.0, le=3600.0` | first retry delay |
| `crew_recovery_max_backoff_seconds` | 300.0 | `ge=0.0, le=86400.0` | delay ceiling; validate `max >= initial` |

Also tighten the existing `max_parallel_subtasks` declaration to `Field(default=3, ge=1, le=64)`; this is the child-level hard concurrency bound used by `interrupted_child_ids`. Inject `clock: Callable[[], float] = time.time` and `sleep: Callable[[float], Awaitable[None]] = asyncio.sleep` into `CrewOrchestrator`. Tests use deterministic fakes; production uses defaults.

## Recovery Persistence

Keep `CrewSessionContract` v1 and `duplicate_resume_count` semantics unchanged. Add one strict, bounded top-level parent metadata sibling owned only by `CrewSessionService`:

```text
metadata["crew_recovery"] = {
  "version": 1,
  "phase": "unplanned" | "planned" | "executing" |
           "verifying_children" | "children_verified" |
           "synthesized" | "final_verified" |
           "artifact_bound" | "provenance_bound" | "published",
  "plan": null | {
    "version": 1,
    "plan_seed_hash": <64-lowerhex>,
    "plan_hash": <64-lowerhex>,
    "children": [<bounded exact child plan rows>]
  },
  "attempt_count": <exact int 0..1000000>,
  "retry_count": <exact int 0..10>,
  "last_attempt_at": null | <finite server timestamp>,
  "next_attempt_at": null | <finite server timestamp>,
  "last_error_code": null | <stable bounded machine code>,
  "interrupted_child_ids": [<sorted unique bounded ids>],
  "synthesis_ref": null | <64-lowerhex>,
  "final_verification_ref": null | <64-lowerhex>,
  "result_artifact_id": null | <bounded id>,
  "provenance_ref": null | <64-lowerhex>
}
```

### Deterministic Two-Stage Plan Identity (2026-07-21 Adjudication)

The preferred single semantic `plan_hash` cannot also serve as a final manifest commitment for both newly derived child ids and adopted pre-AD-1127 arbitrary child ids. Use the minimum explicit two-stage contract: `plan_seed_hash` binds ordered child semantics without ids; `plan_hash` is the final parent-bound manifest hash after ids and row hashes exist. The plan has exact keys `version`, `plan_seed_hash`, `plan_hash`, and `children`. `children` is an ordered list of 1..1,000 exact three-key commitments `child_id`, `spec_id`, and `row_hash`. Do not add another seed, hash, mode, generation, or metadata field.

Use this one canonical JSON encoder for every hash input in this subsection:

```python
json.dumps(
    value,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
```

Hash inputs admit only exact built-in JSON values: `dict` with exact built-in `str` keys, `list`, exact built-in `str`, exact non-bool `int`, finite exact `float`, exact `bool`, and `None`. Reject subclasses, tuples/sets, non-string keys, integers outside signed 64-bit range, non-finite floats, NULs, lone surrogates/invalid UTF-8, excessive recursion, and serialization errors before hashing or mutation. JSON booleans are not integer aliases. Object insertion order is irrelevant because keys sort lexicographically; every list order named below is identity-bearing.

Each semantic child-spec projection has exactly these eleven keys:

```text
spec_id,title,description,work_type,priority,depends_on,resources,
spec_metadata,expected_output,capability,department
```

After canonical key sorting, its object keys encode in this exact order: `capability,department,depends_on,description,expected_output,priority,resources,spec_id,spec_metadata,title,work_type`. Normalize and bound each value once before any hash or insert:

- `spec_id`: existing bounded-id normalization, trimmed, 1..128 code points; duplicate normalized ids reject the whole plan before hashing.
- `title`: exact string, trimmed once, fallback to normalized `spec_id` when empty, no NUL/surrogate, at most 4,096 code points. `description`: exact string, otherwise byte-for-byte preserved, no NUL/surrogate, at most 32,768 code points.
- `work_type`: trimmed non-empty exact string or literal `task`, no NUL/surrogate, at most 128 code points. `priority`: exact non-bool integer 1..5.
- `depends_on`: exact list of 0..64 unique normalized `spec_id` values in declared order. Every value names another spec in the same plan. Self, duplicate, dangling, and cyclic edges reject. This semantic field never contains generated WorkItem ids.
- `resources`: exact list of 0..64 strings in declared order; trim each once, then require non-empty, unique normalized values, no NUL/surrogate, and at most 4,096 code points.
- `spec_metadata`: detached exact JSON object. Depth starts at 1 for the root; each nested dict/list increments depth by one; maximum depth is 8. Node count starts at 1 for the root and adds one for every nested container and scalar value; dict keys do not add nodes but each must be 1..128 code points. Maximum node count is 4,096, maximum string-value length is 32,768 code points, and maximum canonical UTF-8 size is 65,536 bytes. A new spec containing a reserved top-level key rejects rather than silently stripping it; nested keys with the same spelling are ordinary semantic content.
- `expected_output`: `None` or a trimmed non-empty exact string of at most 4,096 code points. `capability`: `None` or a trimmed non-empty exact string of at most 256 code points. `department`: `None` or a trimmed non-empty exact string of at most 128 code points. Empty optional strings normalize to `None`.

The exact reserved metadata-key set is `spec_id`, `resources`, `expected_output`, `capability`, `department`, `chief_agent_id`, `order_id`, `delegated`, `delegation_reason`, `assigned_capability`, `assigned_department`, `crew_execution`, `crew_execution_output`, and `crew_verification_recovery`. For adoption/validation, `spec_metadata` is the live child metadata with exactly those keys removed. Unknown keys, including unknown `crew_*` keys, remain semantic and immutable. Each canonical semantic projection is at most 131,072 UTF-8 bytes and the complete canonical ordered projection array is at most 524,288 UTF-8 bytes.

For an adopted row, `spec_id` must exist. Missing `resources` normalizes to `[]`; missing `expected_output`, `capability`, or `department` normalizes to `None`. If present, each must validate to the same exact type/bounds as a new spec; do not coerce a scalar to a list or a non-string to text. The six assignment/delegation siblings are all-or-none. When present, `chief_agent_id` and `order_id` are `None` or bounded ids, `delegated` is exact bool, `delegation_reason` is an exact non-empty string of at most 128 code points, and `assigned_capability`/`assigned_department` are `None` or exact non-empty strings bounded as their semantic counterparts. `assigned_to` must equal the effective worker represented by that complete group when the landed delegation result supplies one. The three recovery/runtime siblings validate under their exact contracts before removal. Any malformed or partial known runtime group is an integrity conflict.

For a new child, persist metadata as the exact merge of detached `spec_metadata` with these five reserved semantic siblings: `spec_id`, `resources`, `expected_output`, `capability`, and `department`, including explicit `None` for each absent optional sibling. Reject a collision before merge. Do not initially write any assignment/delegation, execution, or verification reserved key. Adoption accepts those runtime keys only when their landed strict contracts validate independently; removing them must expose the exact semantic `spec_metadata` that is subsequently hashed. A malformed known runtime sibling rejects rather than disappearing from hash validation.

The identity sequence is exact:

```text
plan_seed_hash = sha256(
  canonical_json(ordered_semantic_projections)
).hexdigest()

child_id = "crew-" + sha256(canonical_json({
  "parent_id": parent_id,
  "plan_seed_hash": plan_seed_hash,
  "spec_id": spec_id
})).hexdigest()

row_hash = sha256(canonical_json(persisted_row_projection)).hexdigest()

plan_hash = sha256(canonical_json({
  "version": 1,
  "child_id_policy": "derived_v1" | "adopted_v1",
  "parent_id": parent_id,
  "plan_seed_hash": plan_seed_hash,
  "children": ordered_three_key_commitments
})).hexdigest()
```

The child-id input has exactly the shown three keys and encodes in sorted order `parent_id,plan_seed_hash,spec_id`. `child_id` uses the complete lowercase 64-hex digest; length 69 already satisfies the existing WorkItem id predicate, so never truncate it. Do not add an index or random salt. Reject a derived-id collision with another planned child or any existing WorkItem before mutation.

The persisted row projection has exactly twelve keys: `child_id` plus the eleven semantic keys. Its sorted key order is `capability,child_id,department,depends_on,description,expected_output,priority,resources,spec_id,spec_metadata,title,work_type`. Its `depends_on` value is the corresponding ordered list of child ids; every other semantic value is exact. Each canonical row projection is at most 131,072 UTF-8 bytes and the canonical ordered row-projection array is at most 524,288 UTF-8 bytes. Each commitment encodes in sorted order `child_id,row_hash,spec_id`. `child_id_policy` exists only in this hash input and is never persisted as a sibling field. The final manifest encodes in sorted order `child_id_policy,children,parent_id,plan_seed_hash,version` and is at most 524,288 UTF-8 bytes. `row_hash` and final `plan_hash` run only after `plan_seed_hash` and the complete child-id map exist; neither feeds back into child-id derivation.

`WorkItemSpec.agent`/live `assigned_to` is routing/execution state, not immutable plan identity. Exclude it from both projections and all three hashes. For new insertion, trim the exact string once: empty becomes `None`; non-empty must satisfy the existing bounded id predicate and becomes initial `assigned_to`; malformed values reject before mutation. Adoption preserves the live assignee; later assignment follows the exact CAS below. Status, parent id outside the final manifest, creator, timestamps, token counters, trust/resource-requirement rows, execution evidence, verification, and all other runtime fields remain outside row semantics and retain their independent validators/CAS barriers.

New decomposition preserves normalized decomposer list order and computes final `plan_hash` with `child_id_policy="derived_v1"`. Existing-child adoption loads at most 1,001 rows, proves bounds/cardinality, orders them by exact child id ascending, and computes final `plan_hash` with `child_id_policy="adopted_v1"`. Adoption requires one exact unique `metadata["spec_id"]` per child and maps each live dependency child id back to its unique spec id while preserving dependency-list order. Missing/duplicate spec ids, dependencies outside the direct set, duplicate/self edges, or cycles reject without mutation. Once persisted, commitment order is authoritative and is never sorted or rewritten.

Contextual validation against the exact bounded direct-child set is mandatory; Pydantic shape validation alone is insufficient. In order: (a) require commitment/live child-id cardinality and set equality plus unique commitment child/spec ids; (b) build the complete exact child-id-to-spec-id bijection, reverse-map every live `depends_on` id to a spec id in its stored list order, and reject outside-set/duplicate/self/cyclic edges; (c) reconstruct semantic projections in commitment order and recompute `plan_seed_hash`; (d) reconstruct every persisted row projection with live child-id dependencies and recompute its `row_hash`; (e) compute the two possible final manifest hashes using exact policies `derived_v1` and `adopted_v1`, require exactly one to equal stored `plan_hash`, and thereby recover the committed policy without a schema field; and (f) only for the committed `derived_v1` policy, independently recompute every child id from parent id, stored seed, and commitment spec id and compare it with commitment/live row. The committed `adopted_v1` policy instead requires exact commitment/live ids without applying the derivation formula. Any mismatch is a deterministic integrity conflict, never transient. Leave all stores untouched.

A final hash using policy `adopted_v1` may be created only by the no-recovery-plus-existing-children adoption CAS; policy `derived_v1` may be created only by the zero-child transactional install. A committed policy is never switched or repaired. This validator applies equally to plans created after adjudication and any plan installed by the unreleased partial AD-1127 tree. There is no legacy arbitrary-hash acceptance, migration, rewrite, or best-effort repair: an exact committed plan is reused idempotently only after full validation; an old partial plan missing `plan_seed_hash` or carrying placeholder hashes fails closed for Builder repair before resume.

The recovery model is `extra="forbid"`, strict, frozen, JSON-type-exact, and at most 524,288 bytes in canonical UTF-8 (below the existing 1 MiB parent-metadata ceiling while admitting the landed 1,000-child bound). `interrupted_child_ids` is sorted/unique and capped at `max_parallel_subtasks`; it is non-empty only with a child-interruption cancellation/integrity code and is cleared only by an authorized later retry. Phase invariants are monotonic: a plan is required from `planned`; `synthesis_ref` from `synthesized`; `final_verification_ref` from `final_verified`; Artifact id from `artifact_bound`; provenance ref from `provenance_bound`; all are required at `published`. Earlier phases forbid later refs. `attempt_count` increments once per admitted owner attempt. `retry_count` is consecutive transient failures at the current checkpoint and resets only when the durable phase advances. Cancellation sets a stable `last_error_code`, clears `next_attempt_at`, and does not increment `retry_count`.

Adoption maps exactly: `discussing` + plan -> `planned`; `executing` -> `executing`; `verifying` + zero populated child verifications -> `verifying_children`; `verifying` + all exact populated child verifications and recovery blobs -> `children_verified`; a mixed verifying set resumes at `verifying_children` and skips each exact completed child. A populated child verification without its exact recovery blob blocks as non-reconstructable. `published` appears only in the same CAS that makes the session `done`; startup never manufactures it for a pre-existing done row.

Use these exact additive public APIs; retain existing methods/signatures unless listed:

```python
# WorkItemStore
async def list_crew_session_recovery_candidates(self, *, limit: int) -> list[WorkItem]: ...
async def install_child_plan_with_parent_metadata(
  self, parent_id: str, *, expected_parent_metadata: dict[str, Any],
  expected_status: str, expected_assigned_to: str,
  parent_patch: dict[str, Any], children: tuple[WorkItemPlanInsert, ...],
  source: str = "crew_session_plan_install",
) -> tuple[WorkItem, tuple[WorkItem, ...]]: ...
async def adopt_child_plan_with_parent_metadata(
  self, parent_id: str, *, expected_parent_metadata: dict[str, Any],
  expected_status: str, expected_assigned_to: str,
  parent_patch: dict[str, Any], expected_children: tuple[WorkItem, ...],
  source: str = "crew_session_plan_adoption",
) -> WorkItem: ...
async def compare_and_set_work_item_assignment(
  self, work_item_id: str, *, expected_parent_id: str,
  expected_status: str, expected_assigned_to: str | None,
  expected_depends_on: list[str], expected_metadata: dict[str, Any],
  new_assigned_to: str, metadata: dict[str, Any],
  source: str = "crew_session_assignment",
) -> WorkItem | None: ...

# CrewSessionService
async def get_recovery(self, parent_id: str) -> CrewRecoveryContract | None: ...
async def compare_and_set_recovery(
  self, parent_id: str, recovery: CrewRecoveryContract, *,
  expected_session: CrewSessionContract,
  expected_recovery: CrewRecoveryContract | None,
) -> CrewRecoveryContract: ...
async def install_recovery_plan(
  self, parent_id: str, *, expected_session: CrewSessionContract,
  expected_recovery: CrewRecoveryContract | None,
  plan: CrewRecoveryPlan,
  children: tuple[WorkItemPlanInsert, ...],
) -> tuple[CrewRecoveryContract, tuple[WorkItem, ...]]: ...
async def adopt_recovery_plan(
  self, parent_id: str, *, expected_session: CrewSessionContract,
  expected_recovery: None, plan: CrewRecoveryPlan,
  expected_children: tuple[WorkItem, ...],
) -> CrewRecoveryContract: ...
```

`WorkItemPlanInsert` is a frozen fully typed generic dataclass in `workforce.py`; it carries the validated caller-supplied `id` plus only validated WorkItem creation fields and does not import cognitive types. `install_child_plan_with_parent_metadata()` inserts that exact id, so no DB-generated-id override or second public create-with-id seam is needed. The plan transaction creates normal `ResourceRequirement` rows exactly as `create_work_item()` does.

`adopt_child_plan_with_parent_metadata()` is the sole existing-child adoption write. Before lock admission, detach the exact child-id-sorted `WorkItem.to_dict()` snapshots through strict canonical JSON: exact 24-key shape, at most 1,572,864 bytes per child, at most 33,554,432 aggregate bytes, and at most 1,000 children. Under `_work_item_row_write_lock` plus one `BEGIN IMMEDIATE`, revalidate exact parent type/status/assignee/full metadata, query direct children once ordered by id with `LIMIT 1001`, and require JSON-type-exact equality of every complete live snapshot to the detached expected tuple. Then write only the parent recovery patch and commit once. It never writes a child or ResourceRequirement. Roll back on every `BaseException`; emit only the parent update after commit. This new general nonterminal barrier is required because the landed publication barrier accepts only assigned `done` children and cannot safely adopt discussing/executing rows.

`CrewSessionService.adopt_recovery_plan()` is the only caller of that store primitive and the only creator of a final hash using policy `adopted_v1`. It requires `expected_recovery=None`, exact session/room/coarse projection, a non-empty exact child-id-sorted tuple, and a fully contextualized plan computed from those same detached rows. It writes `phase="planned"` when the session is discussing and the phase mapped from the current fine state when adopting executing/verifying recovery; it never regresses fine or coarse state. The orchestrator never calls the store adoption primitive directly.

`install_recovery_plan()` accepts only a plan whose final hash validates under policy `derived_v1`; `adopt_recovery_plan()` accepts only one whose final hash validates under policy `adopted_v1`. `compare_and_set_recovery()` and paired `transition_session()` reject a candidate that introduces a plan where the expected recovery has none, removes a plan, or changes any plan byte. They may advance fine checkpoint fields only while preserving the exact contextualized plan. Publication preserves that same plan into `published`. Thus no generic CAS, retry path, or finalizer can create, infer from row shape, switch, or rewrite identity policy/hashes.

If either plan-install or plan-adoption commit raises or is cancelled, hold/defer cancellation through one authoritative parent/direct-child reread. Return/reconcile success only when the complete contextual validator proves the exact expected mode, seed, ids, row hashes, final hash, and child snapshots. On an ordinary post-commit exception, return that authority. On `CancelledError`, finish reconciliation/checkpointing and re-raise the original cancellation even when the commit is proven. If no exact commit is proven, propagate the original error/cancellation with the precommit state intact. A hard crash before commit leaves zero derived children for install or leaves existing children with no recovery for adoption; retry may repeat decomposition/adoption. A crash after commit validates and reuses the exact plan without another LLM call or parent write.

`CrewSessionService.publish_verified_result(...)` gains required keyword `expected_recovery: CrewRecoveryContract`; it builds and commits the `published` recovery record itself in the existing final parent/child-barrier transaction. `transition_session(...)` gains optional paired `expected_recovery`/`recovery` keywords that must be both omitted or both supplied; supplied values update fine state and recovery in the same metadata/status CAS. Existing callers omit both and remain behaviorally unchanged.

Every service mutation carries exact expected `crew_session`, exact expected `crew_recovery` presence/value, work type, coarse status, facilitator assignment, and room validation into the existing store-owned row lock. No caller reaches into service/store private attributes.

Add one public WorkItemStore combined-state query that performs one SQL query for `work_type="crew_session"` and coarse statuses `open`, `in_progress`, `review`, ordered deterministically by oldest `created_at`, then id, with one global `LIMIT`. Do not run one limit per status. `blocked`, `done`, and `failed` are not startup candidates.

## Durable Plan

`discussing` recovery follows this exact order:

1. Validate parent, v1 contract, coarse projection, facilitator, and exactly one bound room through public APIs.
2. List at most 1,001 direct children. Duplicate ids, overflow, wrong parent, or malformed rows fail closed without replacing anything.
3. If exact direct children already exist and no plan is recorded, construct one plan whose final hash commits policy `adopted_v1` from the exact child-id-sorted rows, then call `CrewSessionService.adopt_recovery_plan()` so its store transaction revalidates every complete child snapshot and writes the parent plan. A parent-only recovery CAS and direct orchestrator-to-store call are forbidden for adoption. Do not decompose, derive replacement ids, or recreate children.
4. If a plan exists, run the complete contextual seed/id/row/final-manifest validator above. Missing/conflicting rows fail closed; do not synthesize replacements outside the store transaction.
5. Only when there are zero direct children and no plan, run the existing injected decomposer on `session.goal` through one held `asyncio.to_thread` task, normalize at most its existing 200-spec hard ceiling, reject an empty/oversize/cyclic/duplicate plan, compute the ordered semantic `plan_seed_hash`, derive deterministic child ids from `(parent_id, plan_seed_hash, spec_id)`, translate dependency spec ids to child ids, compute every `row_hash`, compute final `plan_hash` with policy `derived_v1`, and install the exact commitments plus all child/resource-requirement rows in one new public WorkItemStore transaction under `_work_item_row_write_lock`.
6. The transaction revalidates exact parent session/recovery/type/status/assignee, requires zero direct children, inserts every child and requirement, writes `crew_recovery.phase="planned"`, and commits once. Raised/cancelled commit calls follow the authoritative reconciliation and cancellation policy pinned above; no partial child set is legal. Emit normal work-item events only after commit.

Graceful cancellation while decomposition is running drains the one decomposition task, installs the resulting plan transactionally, checkpoints cancellation, then re-raises. A hard process crash before plan commit may repeat the LLM decomposition after restart, but cannot duplicate children because no child is visible without the one plan transaction. This is the explicit crash limit; do not claim provider-level exactly-once LLM calls.

## Durable Child Execution

Preserve the exact fourteen-key AD-1125 `crew_execution` record. Add this exact same-transaction sibling only for a successful CrewSession child:

```text
metadata["crew_execution_output"] = {
  "version": 1,
  "content_hash": <64-lowerhex>,
  "mime": "text/plain",
  "size_bytes": <exact int 1..1048576>
}
```

Before the terminal child CAS, encode final output as UTF-8, write by SHA-256 to the existing AttachmentStore with exact `origin="agent_artifact"`, read it back, and require byte/hash equality. The terminal WorkItem CAS writes both metadata siblings, status, and token delta atomically. Failed/blocked children must not carry this sibling. Legacy non-session execution remains byte-equivalent and does not require the ref.

Add public `CrewTaskExecutor.resume(parent_id: str) -> list[SubtaskResult]`. For a CrewSession it validates the exact room/session/plan and:

| Durable child state | Resume action |
|---|---|
| `done` + exact execution/output records | read/hash/decode exact output and reconstruct one `SubtaskResult`; never rerun or add tokens/artifacts |
| `failed` | reconstruct terminal failure; never rerun; orchestrator moves parent to `failed` |
| `blocked` | reconstruct terminal blocker; never rerun; orchestrator moves parent to `blocked_needs_captain` |
| untouched legal initial state | assign only if still eligible, then run once under the existing child semaphore |
| `in_progress` or partial/malformed evidence | ambiguous external side effect; do not rerun; move parent to `blocked_needs_captain` with stable `child_execution_interrupted`/integrity reason |

Seed dependency completion from reconstructed `done` children. Never overwrite assignment/delegation metadata on a terminal or in-progress child. Any pre-AD-1127 done child missing an exact output ref is non-replayable and blocks; it is not guessed from `output_summary`.

The CrewSession branch in `CrewOrchestrator.run_crew_task()` no longer runs the landed unconditional `_assign_child()` loop. For a planned child in its legal initial status, preserve an existing assignee; only an unassigned child may run resolver/delegator, and its assignment plus delegation metadata commit through `compare_and_set_work_item_assignment()` with exact parent/status/dependencies/full-metadata expectations. Terminal, `in_progress`, verification-populated, or recovery-conflicting children receive zero assignment mutation. The legacy non-session `_assign_child()` path remains unchanged.

Refactor `CrewTaskExecutor` so each `run()`/`resume()` invocation owns its own local strong child-task set. The current instance-wide `_tasks` set must not be shared by concurrent parents: one parent's wait/finally must never consume, cancel, discard, or return another parent's child. The parent owner task remains the cancellation boundary and each local set is fully gathered in its own `finally`.

When graceful cancellation reaches child execution, stop admitting children, cancel/drain the exact held child-task snapshot, reload the direct children, collect every still-`in_progress` child id, checkpoint sorted `interrupted_child_ids` and `last_error_code="child_execution_cancelled"`, and transition the parent `executing -> blocked_needs_captain` with reason `child_execution_interrupted` before re-raising the original cancellation. Do not mutate those children to failed/blocked and do not claim their external tool side effects rolled back. With no admitted/in-progress child, leave the parent executing and checkpoint `child_execution_cancelled_before_admission`; startup may resume untouched work automatically.

Once an `WorkItemAgenticOutcome` has returned, terminal output write/read-back and the WorkItem terminal CAS are one cancellation-deferred checkpoint: complete or authoritatively prove that checkpoint before re-raising cancellation. Cancellation before an outcome exists uses the interrupted-child rule. If drain shows all admitted children safely terminal and no ambiguous child remains, leave the parent `executing`, record `child_execution_cancelled_at_safe_boundary`, and let restart reconstruct terminal results plus run only untouched children.

## Durable Finalization

Add public `CrewSessionFinalizer.resume(parent_id: str) -> CrewSessionFinalizationResult`. Production lifecycle calls this method; the landed `finalize(parent_id, results)` remains compatible and delegates to the same checkpoint engine after exact validation.

`resume()` accepts `executing` or `verifying`. For `executing`, it reconstructs all exact done child results and performs the landed `executing -> verifying` claim. For already `verifying`, it resumes without a second claim. Terminal/blocked states return an observation and perform no work.

For each child verification, write one bounded canonical full convergence blob (full revision texts plus the exact landed verdict/token/trace/artifact fields; maximum 1,048,576 canonical UTF-8 bytes) to AttachmentStore with exact `origin="chat_attachment"`, read it back, and atomically add this metadata sibling with the existing verification/token CAS:

```text
metadata["crew_verification_recovery"] = {
  "version": 1,
  "convergence_ref": <64-lowerhex>
}
```

An empty child verification has no sibling. A populated verification must have exactly one valid sibling. Resume reads the blob, verifies SHA/schema/child/producer/room/execution binding, and cross-checks every bounded persisted verification field before reconstructing the outcome. It never reruns a verified child or reapplies correction tokens. Missing, duplicate, malformed, or contradictory state fails closed.

Checkpoint these finalization units through `CrewSessionService`:

1. all child convergence records -> `children_verified`;
2. exact canonical `SessionSynthesisDraft` blob -> `synthesized` and `synthesis_ref`;
3. exact canonical accepted final-verdict blob bound to synthesis/result descriptor -> `final_verified` and `final_verification_ref`;
4. result Artifact identity -> `artifact_bound` and `result_artifact_id`;
5. exact provenance blob -> `provenance_bound` and `provenance_ref`;
6. existing direct-child barrier publication -> session `done` plus recovery `published` in the same final parent CAS.

The child convergence blob has exact top-level keys `version,parent_id,work_item_id,thread_id,producer_agent_id,execution_output_ref,outcome`; `outcome` is the canonical detached `SessionConvergenceOutcome` shape and must reproduce the landed child verification document exactly. The synthesis blob has exact keys `version,parent_id,thread_id,producer_agent_id,final_text,tokens_used,child_convergence_refs`, where refs are sorted by child id and equal the complete direct-child set. The final-verification blob has exact keys `version,parent_id,thread_id,synthesis_ref,result_content_hash,candidate,verdict`; `candidate` is the landed exact result descriptor and `verdict` is the detached seven-field `SessionVerificationPass`. All schemas are strict, bounded, content-hashed, byte-read-back, and cross-checked against current session, plan, children, agents, and prior checkpoint refs before reuse.

Every LLM unit whose response has returned under graceful cancellation is cancellation-deferred through its content-addressed blob and metadata/verification checkpoint, then the original `CancelledError` is re-raised. Cancellation while awaiting an LLM response leaves the preceding phase plus a stable cancellation code and may repeat that LLM call after restart; provider-level exactly-once is not claimed. Result blobs use `agent_artifact`; synthesis/verdict/provenance recovery documents use `chat_attachment`; all writes are hash-idempotent and byte-verified. Before final CAS, the durable checkpoint is sufficient to resume. Preserve landed publication cancellation semantics exactly: a publication call that raises cancellation after the exact commit is reconciled by authoritative reread and returns done; cancellation during that authoritative reread propagates even if the row committed, and restart observes terminal done without creating work. A precommit cancellation propagates with `verifying` durable. Never translate `CancelledError` to failed.

For a landed pre-AD-1127 session with no `crew_recovery`, create the sibling only by exact CAS after inspection. `discussing` and `executing` may adopt an exact live plan/execution state. A `verifying` parent is resumable only when each already-populated child verification has the matching new recovery blob; a legacy partial verification without that blob is non-reconstructable and moves to `blocked_needs_captain` without rerunning or adding tokens. `done`, `failed`, and blocked rows are observed only and never migrated by startup.

Add a narrow public `ArtifactStore.reconcile_exact_version(...) -> Artifact`, leaving `add_version()` unchanged. Under `BEGIN IMMEDIATE`, query the complete `(thread_id, name)` chain:

- zero rows: insert version 1 and return it;
- exactly one row matching exact `content_hash`, `mime`, `size_bytes`, and `created_by`: return that identity without writing;
- one conflicting row: raise exact `ValueError("artifact_exact_match_conflict")` without writing;
- more than one row, even if one matches: raise exact `ValueError("artifact_exact_match_ambiguous")` without writing.

The finalizer uses it only for `crew-result.md`. This closes the crash after Artifact insertion but before parent checkpoint without schema changes or duplicate versions. It then revalidates the exact returned room/name/hash/MIME/size/creator/id/version. A room mismatch, duplicate-room state, projection mismatch, conflicting checkpoint, ambiguous Artifact, or provenance mismatch fails closed; never create a replacement room or alternate Artifact.

## Retry Policy

Define shared typed `CrewRecoveryTransientError` in `crew_session.py`. Automatic retry catches only that type. Narrow boundary code may wrap only: `TimeoutError`/`ConnectionError`; `sqlite3.OperationalError` whose SQLite code is exactly `SQLITE_BUSY` or `SQLITE_LOCKED`; and `OSError` whose `errno` is one of `EAGAIN`, `EBUSY`, `ETIMEDOUT`, `ECONNRESET`, `ECONNREFUSED`, `ENETDOWN`, `ENETUNREACH`, or `EHOSTUNREACH`. Preserve the original exception as `__cause__`. `AttachmentStoreFullError`/ENOSPC, EIO, database corruption/schema errors, validation/CAS conflicts, LLM malformed/refuted/error outcomes, and unexpected exceptions are never wrapped or retried.

One owner task records a typed transient error CAS, increments consecutive `retry_count`, computes

```text
delay = min(initial_backoff * 2 ** (retry_count - 1), max_backoff)
```

with finite/clamped arithmetic, persists `next_attempt_at`, sleeps through the injected sleeper, then retries inside the same parent task. Restart honors persisted remaining delay. Advancing a durable phase resets `retry_count` and clears error/backoff. At the configured cap, transition a still-valid session to `blocked_needs_captain` with stable `recovery_retry_exhausted`; do not spawn another task.

Deterministic integrity defects, malformed/corrupt rows, duplicate room, projection/assignment drift, failed/blocked/ambiguous children, refutation, and policy/capability gaps are not transient. Use the landed blocked/failed classifications where valid. If authority is too corrupt to make a safe transition, log and leave all stores untouched. `blocked_needs_captain` never auto-resumes; only AD-1128's explicit authorized retry may move it.

The owned parent coroutine contains ordinary exceptions. A valid authoritative session uses the stable landed blocked/failed mapping or exact `recovery_unexpected_failure`; the state and recovery record commit together before a non-completed `SynthesisResult` is returned. A corrupt/unprovable authority is logged and left untouched. Only `CancelledError` escapes after its checkpoint and only an unrecoverable inability to inspect/persist authority may remain as an observed task exception.

## Startup And Shutdown

Wire the configured limits and injected collaborators into the existing orchestrator in `startup/finalize.py`. Call `await runtime.crew_orchestrator.start()` once near the successful tail of `finalize_startup`, after WorkItemStore, ChatThreadStore, AttachmentStore, ArtifactStore, registry, tools, and LLM dependencies are ready, and before `runtime._started = True`. Enabled startup dependency failure propagates through normal startup cleanup; disabled startup is inert.

At the top of `startup/shutdown.shutdown()`, immediately after the BF-598 re-entry guard is set and before the first await, call `crew_orchestrator.close_scheduling()` when present. After the existing synchronous session-record write, `await crew_orchestrator.stop()` is the first shutdown await and occurs before the partial-start `_started` return, event-log/Ward Room awaits, grace sleep, Phase 1 consolidation, and every WorkItemStore/tool/agent/AttachmentStore/ArtifactStore/LLM close. A cancelled outer shutdown waits for the same cancellation-deferred drain before re-raising. Do not place this after the AD-820 marker.

Do not alter, rewrite, or downgrade the BF-598/AD-820 `_shutdown_started` guard or clean/partial integrity-marker decision. Repeated shutdown must still preserve a prior clean/rebuilt marker.

## Crash Versus Graceful Cancellation

- Graceful `CancelledError`: finish the current bounded checkpoint/transaction, persist deterministic resumable state, reap owned child tasks, then re-raise. Never mark failed solely because of cancellation.
- Hard process loss: content-addressed result/convergence/synthesis/verdict/provenance blobs and exact Artifact reconciliation recover committed boundaries. An LLM call whose response was never checkpointed may repeat. An arbitrary child tool interrupted before terminal evidence is not provably idempotent and therefore blocks instead of replaying. Cross-store exactly-once is not claimed.
- Crash after final done CAS: restart observes `done`, validates no work, and creates no task/version/result.

## Implementation Allowlist

Production changes are limited to:

- `src/probos/config.py`
- `src/probos/workforce.py`
- `src/probos/artifacts/__init__.py`
- `src/probos/cognitive/crew_session.py`
- `src/probos/cognitive/crew_executor.py`
- `src/probos/cognitive/crew_finalizer.py`
- `src/probos/cognitive/crew_orchestrator.py`
- `src/probos/startup/finalize.py`
- `src/probos/startup/shutdown.py`

Tests are limited to new `tests/test_ad1127_crew_session_lifecycle_recovery.py` plus the minimum assertion-only compatibility edits in AD-1124/1125/1126 and existing orchestrator/shutdown tests if an additive public signature/schema requires them. Do not weaken or delete landed assertions.

## Required Tests

Use real WorkItemStore, CrewSessionService, ChatThreadStore, FilesystemAttachmentStore, ArtifactStore, CrewTaskExecutor, CrewSessionFinalizer, and CrewOrchestrator. Use protocol-faithful scripted LLM/agents/tools and deterministic barriers/clock/sleeper. No MagicMock substrate.

Cover at minimum:

1. `schedule()` returns before work completes; duplicate calls return identical task; done callback observes success/error/cancellation and owner-safe cleanup.
2. Parent concurrency cap; child cap remains independent; post-close and close-vs-register race creates no late task; stop cancellation/drain/concurrent stop/idempotency.
3. disabled start performs zero scan/task; enabled start scans once; exact global cap across open/in_progress/review; deterministic order; done/failed/blocked skip.
4. RED-first identity vectors hard-code the exact canonical bytes and hashes in the adjudication test-vector table below. Prove child ids are absent from the seed, the final hash binds parent/hash-only-policy/seed/ordered commitments, row hashes bind persisted ids/dependencies, and assignment/status/evidence changes affect none of them. Tamper each layer independently and require rejection before mutation.
5. duplicate normalized `spec_id`, duplicate/dangling/self/cyclic dependencies, duplicate resources, reserved metadata collisions, bool-vs-int aliases, hostile subclasses, invalid UTF-8/surrogates, non-finite/out-of-range numbers, depth/node/string/canonical-byte overflow, derived-id collision, policy substitution, and reordered commitments all reject before any child/requirement/parent write.
6. restart at discussing with a fully validated existing plan, exact existing-children/no-plan adoption under policy `adopted_v1`, a deterministic barrier that mutates one child between service snapshot and store lock and proves zero parent patch, strict rejection of a pre-adjudication arbitrary-hash partial plan, zero-child decomposition under policy `derived_v1`, cancellation during decomposition, atomic install, ordinary post-commit exception and commit-call cancellation reconciliation for both policies, cancellation re-raise after proven commit, caller-supplied WorkItem ids, and no duplicate child or requirement rows.
7. executing restart skips exact completed children and preserves tokens/evidence/artifacts; runs untouched children once; failed/blocked/in-progress/malformed/missing-output-ref cases never rerun.
8. verifying restart reuses persisted child convergence and correction tokens; mixed exact children resume only missing verification work; a legacy populated verification without recovery blob blocks; cancellation during child verification checkpoints then propagates.
9. restart/cancellation at synthesized, final-verified, result-blob, Artifact-row, artifact-checkpoint, provenance-write, provenance-checkpoint, immediately before done CAS, commit-call cancellation after commit, and authoritative-reread cancellation after commit.
10. every AD-1126 publication crash window yields one result content hash, at most one exact `crew-result.md` Artifact version, one provenance hash, and one done publication; exact Artifact duplicate is reused and ambiguous duplicates fail closed.
11. retry timing with injected clock/sleeper, exponential cap, restart during backoff, phase-progress reset, retry exhaustion, and no infinite/self-spawned storm.
12. corrupt session, coarse projection mismatch, reassignment, zero/two/wrong-task rooms, plan/live-child mismatch, hostile bool-vs-int JSON, oversize refs/plan/checkpoints, and cancellation at every store boundary.
13. legacy non-session orchestrator/executor behavior and all AD-1124/1125/1126 tests remain green; BF-598 marker tests prove no integrity downgrade.

### Adjudication RED Test Vector

Use exact parent `session-parent` and the one normalized semantic row below. These literals are independent expected values, not values recomputed by the helper under test.

| Value | Exact expected value |
|---|---|
| canonical semantic array (201 UTF-8 bytes) | `[{"capability":null,"department":null,"depends_on":[],"description":"Do it","expected_output":null,"priority":3,"resources":[],"spec_id":"spec-a","spec_metadata":{},"title":"Child","work_type":"task"}]` |
| `plan_seed_hash` | `8e53150cafb2837a2efa70f795703388ba91fe4ccd96563e2afe11b734108980` |
| canonical child-id input (133 UTF-8 bytes) | `{"parent_id":"session-parent","plan_seed_hash":"8e53150cafb2837a2efa70f795703388ba91fe4ccd96563e2afe11b734108980","spec_id":"spec-a"}` |
| derived `child_id` | `crew-2eea0cd19b27d9b8bb894c7a8d4d95eee3e44327a9a06c42826e5d0faa4ef543` |
| canonical row projection (282 UTF-8 bytes) | `{"capability":null,"child_id":"crew-2eea0cd19b27d9b8bb894c7a8d4d95eee3e44327a9a06c42826e5d0faa4ef543","department":null,"depends_on":[],"description":"Do it","expected_output":null,"priority":3,"resources":[],"spec_id":"spec-a","spec_metadata":{},"title":"Child","work_type":"task"}` |
| `row_hash` | `2957fda273133f8170b06197292c3aae06b1644ea572ac769f2202383b82a178` |
| canonical final manifest (352 UTF-8 bytes) | `{"child_id_policy":"derived_v1","children":[{"child_id":"crew-2eea0cd19b27d9b8bb894c7a8d4d95eee3e44327a9a06c42826e5d0faa4ef543","row_hash":"2957fda273133f8170b06197292c3aae06b1644ea572ac769f2202383b82a178","spec_id":"spec-a"}],"parent_id":"session-parent","plan_seed_hash":"8e53150cafb2837a2efa70f795703388ba91fe4ccd96563e2afe11b734108980","version":1}` |
| final `plan_hash` | `10da076213290108ff5bab846b27888cbb50be6c43e16fb61ed9f8a5a4b72d74` |

## Do Not Build

- AD-1128 ingress, semantic/exact dedup, parent/room/session provisioning, provisioning repair, authorized retry endpoint, proactive `[CREW]` conversion, or HXI Start Work.
- AD-1129 EventLog query/tool/endpoint.
- AD-1130 trust, Hebbian, Shapley, rank, or outcome credit.
- AD-1131 delivery/metrics/events/episodes/notifications or new EventType.
- AD-1132/1133 API, status/result projection, UI, WebSocket, or live refresh.
- `config/system.yaml`, a new dependency, DB, table, column, migration, scheduler, queue, daemon, chat cascade, or cross-store transaction claim.
- Any retry of a blocked session or ambiguous in-progress child without the future AD-1128 authorization boundary.

## Tracking And Closeout

After the one frozen full gate is green, update only `PROGRESS.md`, `docs/development/roadmap.md`, and `DECISIONS.md`; archive both AD-1127 documents byte-for-byte under `prompts/archive/`; stage only the approved implementation/test/tracker/archive paths; and commit exactly:

```text
AD-1127: add CrewSession lifecycle recovery (closes #1046)
```

Builder must not push, close/edit GitHub issues, or perform any GitHub mutation.

## Acceptance Criteria

1. One `CrewOrchestrator` lifecycle owns scheduling, keyed tasks, bounded active parents, restart scan, retries, and shutdown drain.
2. Admission closes synchronously before awaits; duplicates share task identity; every task result is observed; no strong reference leaks.
3. Default-off startup creates no task and performs no scan.
4. Discussing/executing/verifying recovery is phase-aware and bounded; terminal/blocked policy is exact.
5. Durable children, child verification, synthesis, final verdict, Artifact identity, provenance, and publication are reused without duplicate work/tokens/versions/results.
6. Graceful cancellation checkpoints and re-raises; hard-crash limitations are honest; ambiguous child tool execution blocks rather than replays.
7. Startup/shutdown ordering protects all dependencies and leaves BF-598/AD-820 integrity behavior unchanged.
8. No AD-1128+ feature leakage and no unapproved file/schema/config change.
9. The optimized gate and frozen-manifest protocol in the execution document is followed exactly.

Verify all changes comply with the Engineering Principles in .github/copilot-instructions.md.

## Verified Against Codebase (2026-07-21)

- `PROGRESS.md:3` declares AD-1126 shipped, the 19,923/33/429 full baseline, AD-1126 ceiling, and BF-673 ceiling.
- `src/probos/config.py:6088` defines the existing default-off `AgenticDispatchConfig`; `orchestrator_enabled` is its current final crew field.
- `src/probos/cognitive/crew_orchestrator.py:64,101,132,319-374` shows one orchestrator, the unkeyed held-task trigger, inline origin path, and executing-only finalizer call.
- `src/probos/cognitive/crew_session.py:244,525,620,632,776` defines strict v1 state, public load/transition, and exact final publication.
- `src/probos/cognitive/crew_executor.py:323,347,783,806` owns bounded child fan-out, discussing/executing admission, and exact terminal evidence.
- `src/probos/cognitive/crew_finalizer.py:629,654,742,1640-1795` rejects already-verifying entry and creates result blob, Artifact version, provenance, then done CAS.
- `src/probos/artifacts/__init__.py:82,104,163` exposes `ArtifactStore.add_version()` and latest lookup but no exact idempotent reconcile primitive.
- `src/probos/workforce.py:1501,1684,1930,2060` exposes one-status list, metadata CAS, verification CAS, and direct-child publication barrier under the store-owned lock.
- `src/probos/consultation/dispatch.py:47-61` defines `WorkItemSpec`, including ordered spec-id dependencies and routing-only `agent`.
- The preserved partial tree adds caller-supplied `WorkItemPlanInsert.id` in `src/probos/workforce.py:676` and inserts it in `install_child_plan_with_parent_metadata()` at `src/probos/workforce.py:1776`; no DB-generated-id seam is required.
- The preserved partial `CrewRecoveryPlan` at `src/probos/cognitive/crew_session.py:133-166` has only the pre-adjudication shape/uniqueness checks; Builder must add the one new exact `plan_seed_hash` field and contextual seed/id/row/final-manifest validation above.
- `src/probos/cognitive/swe_harness/agentic_loop.py:47,72-247` is in-memory only; it has no checkpoint/resume contract, so interrupted arbitrary tools cannot be replayed safely.
- `src/probos/consultation/llm_decomposer.py:72-107` is synchronous and bounded; cancellation must therefore own/drain its worker boundary before plan commit.
- `src/probos/startup/finalize.py:1716-1906,2844-2849,4831` wires session/orchestrator after stores and sets `_started` only at the successful tail.
- `src/probos/startup/shutdown.py:142-159,236,539-590,769-771,1026` pins the BF-598 guard, Phase 1/AD-820 marker, WorkItemStore close, and LLM close ordering.
- Issue #1046 requires one lifecycle owner and bounded recovery; #1047/AD-1128 explicitly owns unified ingress, parent/children/room provisioning, dedup, provisioning repair, authorized retry, and Start Work UI.

## Architect Three-Pass Review

| Pass | Scope | Status |
|---|---|---|
| 1 | live API/signature, caller-supplied-id seam, and non-circular identity contract | APPROVED |
| 2 | canonical bytes, policy/tamper validation, crash/retry idempotency, and RED coverage | APPROVED |
| 3 | partial-tree compatibility, scope, optimized gates, and cross-document consistency | APPROVED |

**Document verdict:** READY for Builder handoff, subject only to exact out-of-band SHA-256/byte values in the Architect response. Embedding a file's own hash would be self-referential. Builder must preserve those hashes until the explicit pre-gate freeze.