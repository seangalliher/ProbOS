# AD-1128: Unified CrewSession Ingress And Dedup

**One-line:** Make `CrewSessionService.open_or_resume()` the sole authority for Captain and Lieutenant+ CrewSession admission, bounded exact/semantic dedup, reconstructable room provisioning, blocked retry authorization, and handoff to the existing AD-1127 owner task.

**Status:** Final UI root cause verified; the complete live component/test pair is authorized by exact hash; the final code-review and local-commit closeout amendment below controls
**Issue:** #1047; parent #1041
**Dependencies:** AD-1124 through AD-1127 landed; #1046 closed
**Required base:** `e33955a8f7aa6810e8f2d2e2db3a329fadb8e4da` (`AD-1127: add CrewSession lifecycle recovery (closes #1046)`)
**Ceilings at base:** AD-1127, BF-673
**Baseline:** 20,032 passed / 33 skipped / 198 warnings / 0 failed

## Decision

There is one ingress authority and one runner:

```text
Captain NL intent ----\
room Start Work API ---+-> CrewSessionService.open_or_resume()
Lieutenant+ [CREW] ----/       -> CrewOrchestrator.schedule(parent_id)
                                      (existing sole AD-1127 runner)
```

`open_or_resume()` owns validation, identity/rank defense, bounded candidate search, exact-first/semantic dedup, duplicate mutation, decomposition, parent/room provisioning and repair, child-plan installation, blocked retry admission, and the synchronous schedule handoff. It never runs a child. `CrewOrchestrator.schedule()` remains the only parent task owner; do not add a runner, queue, daemon, worker, alternate scheduler, or inline await of `run_crew_task()`.

This is an extension of the landed contracts, not a rewrite. Follow the live [CrewSession service and v1 contract](../src/probos/cognitive/crew_session.py#L1357), [AD-1127 schedule owner](../src/probos/cognitive/crew_orchestrator.py#L128), [transactional plan APIs](../src/probos/cognitive/crew_session.py#L1907), and [WorkItem row lock/CAS](../src/probos/workforce.py#L1451). Do not restate or fork their plan hashes, recovery phases, execution evidence, finalization, or publication rules.

## Public Contract

Add frozen, fully typed values in [crew_session.py](../src/probos/cognitive/crew_session.py#L1700):

```python
@dataclass(frozen=True, slots=True)
class CrewSessionPrincipal:
    origin: Literal["captain", "agent"]
    originator_id: str
    created_by: str
    _authority: object = field(repr=False, compare=False)

@dataclass(frozen=True, slots=True)
class CrewSessionOpenResult:
    disposition: Literal["created", "resumed", "blocked"]
    parent_id: str
    thread_id: str
    state: CrewSessionState
    facilitator_id: str
    owner_ids: tuple[str, ...]
    duplicate_resume_count: int
    scheduled: bool
```

`CrewSessionService` owns a per-instance unexported authority object and these annotated methods:

```python
def captain_principal(self) -> CrewSessionPrincipal: ...
def agent_principal(self, agent_id: str) -> CrewSessionPrincipal: ...
def bind_scheduler(
    self,
    schedule: Callable[[str], asyncio.Task[SynthesisResult]],
) -> None: ...
async def repair_provisioning(self, *, limit: int) -> tuple[str, ...]: ...
async def open_or_resume(
    self,
    *,
    principal: CrewSessionPrincipal,
    goal: str,
    success_criteria: list[str],
    expected_deliverable: str,
    facilitator_id: str | None = None,
    owner_ids: list[str] | None = None,
    requested_thread_id: str | None = None,
    retry_blocked: bool = False,
) -> CrewSessionOpenResult: ...
```

Callers never pass `origin`, `originator_id`, or `created_by` separately. `open_or_resume()` rejects a principal whose `_authority` is not the service's exact object. `captain_principal()` accepts no caller data and fixes all three values to `captain`; `agent_principal(agent_id)` validates the id but does not make later validation optional.

This is route/server authority, not new authentication or cryptography. `IntentMessage` has no authenticated caller field ([live shape](../src/probos/types.py#L58)); Captain NL is authoritative only because the local server's `process_natural_language()` -> `DAGExecutor` path constructs and submits it. The explicit API relies on the existing local server boundary. Document that limitation. Do not add tokens, signatures, users, RBAC, or multi-Captain auth.

## Section 1: Input And Principal Validation

Run validation before acquiring/scanning, scoring, decomposition, or mutation. For an agent principal, run it again after decomposition and immediately before the first write:

1. Resolve `originator_id` through the public live `AgentRegistry.get()` ([anchor](../src/probos/substrate/registry.py#L58)); missing/replaced identity rejects.
2. Require `is_crew_agent(agent, ontology)` ([anchor](../src/probos/crew_utils.py#L21)).
3. Read the current trust score and compute `Rank.from_trust()` ([anchor](../src/probos/crew_profile.py#L30)); require Lieutenant, Commander, or Senior. Ensign rejects before every scan/scorer/decomposer/store call.
4. Validate every requested facilitator/owner as an exact live registered crew id. Only the origin agent requires Lieutenant+ for this AD.
5. Agent ingress fixes facilitator to the origin agent and includes it in owners. Captain room ingress uses an explicitly requested live facilitator; when omitted, select the first live crew participant in the stored room order. Captain NL without a requested room requires an explicit facilitator.
6. Existing facilitator always wins on resume. Owner union is `existing owners` followed by requested facilitator/owners in caller order, de-duplicated exactly, with the existing 16-owner cap. Overflow rejects without mutation.

`retry_blocked=True` is valid only for a Captain principal with a non-null `requested_thread_id`. NL intent and agent wrapper never expose or pass it.

### Canonical text

Use exact built-in strings only; reject subclasses. Reject NUL, any surrogate code point, invalid UTF-8, empty-after-normalization, more than 4,096 code points, or more than 16,384 UTF-8 bytes for a goal. Apply NFKC, collapse every whitespace run to one ASCII space, trim, then casefold for comparison. Punctuation is identity-bearing: do not strip, translate, tokenize, or ignore it.

Keep two values:

```text
display_goal = NFKC + whitespace collapse, case preserved
canonical_goal = display_goal.casefold()
goal_fingerprint = sha256(canonical_goal.encode("utf-8")).hexdigest()
```

Store `display_goal` in the v1 session. Derive fingerprints for landed rows at read time; do not migrate or add a field to `CrewSessionContract`.

Apply the same NFKC/casefold/whitespace rule, punctuation preservation, NUL/surrogate/UTF-8 validation, and the landed per-field character caps to success criteria and expected deliverable. Criteria must remain 1..16, unique after canonicalization, and compatibility is exact ordered canonical tuple equality. Deliverable compatibility is exact canonical equality. These compatibility checks apply to both exact-goal and semantic-goal resume; a matching goal with different criteria order/content or deliverable is distinct work.

## Section 2: Bounded Exact-First Dedup

Add bounded Pydantic fields to [AgenticDispatchConfig](../src/probos/config.py#L6088), with defaults only; do not edit YAML:

| Field | Default | Bound |
|---|---:|---:|
| `crew_ingress_scan_limit` | 100 | 1..1000 |
| `crew_ingress_semantic_call_limit` | 32 | 1..128 and `<= scan_limit` |
| `crew_ingress_semantic_threshold` | 0.90 | finite 0.0..1.0 |
| `crew_provisioning_repair_limit` | 100 | 1..1000 |

`CrewSessionService` has one `asyncio.Lock` admission lock. Hold it continuously from the first complete candidate scan through either resume or completed provisioning/schedule. Decomposition occurs inside this lock. The second scan protects against external/non-cooperating writers; waiting local callers naturally scan after the winner.

Add one public WorkItemStore query using one SQL statement, deterministic `created_at ASC, id ASC`, and `LIMIT limit + 1`:

```python
async def list_crew_session_ingress_candidates(
    self, *, limit: int,
) -> list[WorkItem]: ...
```

It selects `work_type="crew_session"` and coarse status `open`, `in_progress`, `review`, or `blocked`. More than `limit` is a hard bounded-overflow error; never create when the complete nonterminal set could not be inspected. Terminal rows are absent from NL/agent dedup.

Search in this exact order:

1. Parse and fully validate every candidate through `CrewSessionService.get_session()` semantics, including room and recovery context. Integrity failure aborts the request; never skip a malformed authority and create beside it.
2. Filter by exact criteria/deliverable compatibility.
3. Compare `goal_fingerprint` across all compatible candidates. Pick oldest `created_at`, then id if multiple exact matches.
4. Only when no exact match exists, require compatible-candidate count `<= crew_ingress_semantic_call_limit`; otherwise fail closed without calls or writes.
5. Score every compatible candidate exactly once. Production injects `compute_similarity` ([anchor](../src/probos/knowledge/embeddings.py#L276)) and executes the sync scorer via `asyncio.to_thread`; tests inject a deterministic scorer. No network LLM call is permitted for dedup.
6. Admit only an exact built-in `float`, finite and in `[0.0, 1.0]`; reject bool, int, subclass, NaN, infinity, and out-of-range output. Choose highest score at/above threshold, then oldest `created_at`, then id.

For `requested_thread_id`, load that exact existing room first. If it has `task_id`:

- the linked nonterminal CrewSession is the only possible candidate; incompatibility is HTTP 409;
- a linked `done`/`failed` CrewSession is HTTP 409 and is never reopened;
- a non-CrewSession task link is HTTP 409.

An unbound requested room may be provisioned only by exact task-id CAS. A missing/archived room is 404/409. A newly created room is created only inside the server-owned service flow.

## Section 3: Double Scan And Decomposition

When scan 1 has no match, run the live synchronous `LLMPlanDecomposer.decompose(goal) -> list[WorkItemSpec]` contract used by [AD-1127](../src/probos/cognitive/crew_orchestrator.py#L466). Inject the decomposer. Start one held `asyncio.create_task(asyncio.to_thread(...))`, shield/drain it on outer cancellation, and re-raise the first `CancelledError`. Cancellation during decomposition performs no store write and no schedule.

Validate/detach its result with the landed AD-1127 semantic projection, 200-spec cap, dependency checks, metadata bounds, and derived-plan helpers; do not copy those algorithms. Empty or invalid decomposition fails before writes.

After successful decomposition, revalidate an agent principal, then run the same complete exact-first/semantic scan 2 with fresh rows and fresh score calls. No parent, room, marker, child, or status write is allowed before scan 2 finishes. A scan-2 match discards the decomposition and resumes the authority.

## Section 4: Resume And Blocked Retry

For each equivalent invocation, perform exactly one parent metadata CAS that:

- validates the complete current v1 contract, recovery sibling, work type, coarse status, facilitator assignment, and bound room;
- preserves facilitator;
- writes the bounded owner union;
- increments `duplicate_resume_count` by exactly one, rejecting overflow;
- increments revision and server transition time only as required by the landed contract; and
- leaves goal, origin, originator, created_by provenance, criteria, deliverable, plan, evidence, and result identity unchanged.

Then idempotently union the authoritative owners into room participants through one narrow ChatThreadStore method. Startup provisioning repair also reconciles session owners into the room, so a crash between the two stores remains repairable. Cross-database atomicity is not claimed.

Ordinary Captain NL, agent ingress, and `retry_blocked=False` room calls return `disposition="blocked"`, `scheduled=False` for `blocked_needs_captain`. They still count the duplicate exactly once. `done`/`failed` never resume.

Explicit Captain retry is narrow:

- Require `retry_blocked=True`, bound requested room, Captain principal, current `blocked_needs_captain`, and nonterminal `previous_state`.
- Permit `child_execution_interrupted` only with recovery phase `executing`, `last_error_code="child_execution_cancelled"`, and non-empty exact interrupted-child evidence.
- Permit `recovery_retry_exhausted` only when recovery phase is exactly compatible with previous `discussing`/`executing`/`verifying` state and the persisted retry count equals the configured maximum.
- Reject integrity conflict, legacy non-reconstructable verification, child/tool block, missing/malformed recovery, terminal state, or any other code.
- Preserve the exact plan and monotonic recovery phase. Clear retry/backoff/interrupted fields only as justified by the admitted evidence, transition back to the proven previous state, and schedule once.

The live fine and coarse machines omit verifying restoration. Add only the required edges:

```text
SEARCH crew_session.py: "blocked_needs_captain": frozenset({"discussing", "executing", "failed"})
REPLACE: add "verifying" to that exact set.

SEARCH workforce.py crew_session transitions: blocked -> open, blocked -> in_progress, blocked -> failed
REPLACE: add blocked -> review; preserve every existing edge.
```

## Section 5: Strict Reconstructable Provisioning

Add a frozen, strict, `extra="forbid"`, JSON-type-exact `CrewSessionProvisioningContract` as top-level parent metadata sibling `crew_provisioning`. It is temporary and has exactly these fields:

```text
version=1
provision_id=<64 lowerhex server random>
phase=parent_created|room_bound|session_initialized|plan_installed|failed
room_policy=create|adopt
thread_id=<bounded id known before parent creation>
goal=<display goal>
goal_fingerprint=<64 lowerhex>
origin=captain|agent
originator_id=<bounded id>
created_by=<bounded id>
facilitator_id=<bounded id>
owner_ids=<1..16 exact ids>
success_criteria=<1..16 display strings>
expected_deliverable=<display string>
plan_specs=<ordered landed AD-1127 canonical semantic spec projections>
last_error_code=null|<bounded machine code>
```

Reuse the AD-1127 canonical JSON/value validators and projection caps. Cap the whole marker below the existing 1 MiB WorkItem metadata limit. Do not add a DB column/table/index or duplicate the durable session/recovery contract.

Provision in this order after scan 2:

1. Create one `crew_session` parent in `draft`, assigned to facilitator, with `created_by=principal.created_by` and metadata containing only the exact `parent_created` marker. Its title is a bounded display-goal title.
2. For `adopt`, CAS the exact existing room `task_id: None -> parent.id`. For `create`, derive `thread_id="crew-room-" + provision_id` before parent creation and call a narrow server-only ChatThreadStore create method with exact participants, task id, and metadata identifying `provision_id`/creator.
3. CAS marker phase to `room_bound` only after authoritative room reread proves exact link/ownership.
4. Call existing `initialize_session()` with marker data; CAS marker to `session_initialized` after authoritative v1 reread.
5. Build the parent-bound derived plan from stored `plan_specs` and call existing `install_recovery_plan()` ([anchor](../src/probos/cognitive/crew_session.py#L1907)). If exact children already exist during repair with no recovery, use existing `adopt_recovery_plan()` ([anchor](../src/probos/cognitive/crew_session.py#L2033)); never invent a third plan writer.
6. CAS marker to `plan_installed`, validate exact session/room/plan/children authority, remove only the `crew_provisioning` sibling through an exact store-owned CAS, call bound `schedule(parent.id)` synchronously, and return without awaiting the task.

Required narrow store APIs (names may not be broadened):

```python
# WorkItemStore
async def list_crew_session_provisioning_candidates(self, *, limit: int) -> list[WorkItem]: ...
async def clear_crew_session_provisioning(
    self, parent_id: str, *, expected_marker: dict[str, Any],
    expected_session: dict[str, Any], expected_recovery: dict[str, Any],
) -> WorkItem | None: ...
async def delete_untouched_crew_session_provisioning(
    self, parent_id: str, *, expected_marker: dict[str, Any],
    expected_assigned_to: str,
) -> bool: ...
async def fail_crew_session_provisioning(
    self, parent_id: str, *, expected_marker: dict[str, Any], error_code: str,
) -> WorkItem | None: ...

# ChatThreadStore (synchronous; service uses held to_thread calls)
def compare_and_set_task_link(
    self, thread_id: str, *, expected_task_id: str | None,
    new_task_id: str | None,
) -> ChatThread | None: ...
def create_crew_session_thread(
    self, *, thread_id: str, title: str, participants: tuple[str, ...],
    task_id: str, provision_id: str, created_by: str,
) -> ChatThread: ...
def add_crew_session_participants(
    self, thread_id: str, *, task_id: str, participant_ids: tuple[str, ...],
) -> ChatThread | None: ...
def delete_untouched_crew_session_thread(
    self, thread_id: str, *, task_id: str, provision_id: str,
) -> bool: ...
```

Every thread mutation uses `BEGIN IMMEDIATE`, validates exact built-in inputs, and returns an authoritative reread. Exact create is idempotent only when all server-owned fields match. Untouched delete requires exact provision metadata/task link and zero messages. It never deletes an adopted room.

All synchronous mutating thread calls run in held `to_thread` tasks. If cancellation arrives, drain the mutation, reconcile parent/room/marker authority, checkpoint the furthest proven phase, then re-raise the first cancellation. Apply the same post-error/post-cancel authoritative reread discipline to parent create, marker advance, session initialize, plan install/adopt, marker clear, and schedule boundary.

Compensation is allowed only before `crew_session` exists:

- created room: delete exact marker-owned untouched room first, then exact untouched marker parent;
- adopted room: CAS unlink only `parent.id -> None`, then exact untouched marker parent;
- any message, field drift, foreign link, unknown commit outcome, failed reread, or cleanup error forbids further compensation and leaves the marker discoverable.

After session authority exists, never delete parent, room, children, plan, artifact, or evidence. Repair advances from authoritative state. Deterministic irreparable authority transitions the v1 session to `failed` with bounded summary plus marker error; a pre-session irreparable marker uses `fail_crew_session_provisioning()` and remains a discoverable failed provisioning record. Do not claim cross-store atomicity.

`repair_provisioning(limit=...)` uses one globally bounded oldest-first marker query, validates every marker, reconciles actual phase, and performs the same idempotent steps. `CrewOrchestrator.start()` calls it after opening AD-1127 scheduling but before `list_crew_session_recovery_candidates()` ([start anchor](../src/probos/cognitive/crew_orchestrator.py#L128)). The normal AD-1127 scan then schedules repaired rows; repeated `schedule()` is parent-idempotent. No poller or daemon.

## Section 6: Composition And Three Ingresses

### Startup composition

Extend [finalize wiring](../src/probos/startup/finalize.py#L1716) with real registry/ontology/trust/config, injected sync `compute_similarity`, and injected `LLMPlanDecomposer`. Construct `CrewOrchestrator` as today, then one-time `bind_scheduler(orchestrator.schedule)` before the existing `await crew_orchestrator.start()` call. Duplicate/different binding fails startup. Default-off construction remains absent under `orchestrator_enabled=False`.

### Captain NL

Add a conditional `start_crew_session` descriptor and a real full `perceive -> decide -> act -> report` handler to [CoordinatorAgent](../src/probos/agents/operations/coordinator.py#L16). It accepts goal, criteria, deliverable, facilitator, and collaborators only; it rejects/ignores caller principal fields and never exposes `retry_blocked`. It obtains `service.captain_principal()`, awaits only `open_or_resume()`, and returns the typed ids/disposition, not the owner task.

The descriptor must not exist on a disabled live agent. Because planner collection reads registered template classes in [`runtime._collect_intent_descriptors()`](../src/probos/runtime.py#L4777), `runtime.py` is the one unavoidable runtime allowlist entry: export one descriptor constant from the coordinator, add it to each enabled coordinator instance only when both `operations.enabled` and `agentic_dispatch.orchestrator_enabled`, and conditionally append that same constant in `_collect_intent_descriptors()`. When either flag is false: no planner descriptor, no bus index entry, no handler side effect.

### Explicit room API

Add `POST /api/threads/{thread_id}/start-work` beside the existing strict request models/routes in [threads.py](../src/probos/routers/threads.py#L116). Use `ConfigDict(extra="forbid", strict=True)` and bounded Pydantic fields for goal, criteria, deliverable, optional facilitator/owners, and exact bool `retry_blocked=False`. Do not accept origin/created_by/originator. The route creates the server Captain principal, passes the path room id, and returns the open result.

Map missing room to 404; terminal/already-bound-incompatible/nonrecoverable blocked to 409; input/principal/owner/scorer/decomposition contract errors to 422; disabled/unwired/closed scheduler to 503. Every failure occurs before an unaccounted side effect. At least three API tests are required: happy, domain error, and Pydantic validation; also cover disabled fail-closed.

### Lieutenant+ `[CREW]`

Replace the blocking [proactive wrapper](../src/probos/proactive.py#L3468) with service `agent_principal(agent.id)` + `open_or_resume()` using exact stable defaults:

```text
success criterion: Complete the stated goal with verifiable evidence.
expected deliverable: A verified result for the stated goal.
```

It passes no requested room and no retry. Append the returned parent id to `actions_executed`; never await a runner. Preserve tag stripping. Ensign remains blocked before scan/decompose/write. `[GROUP_CHAT]` behavior and coaching are byte-identical.

Convert `CrewOrchestrator.originate_crew_task()` into a compatibility delegate to the same service authority or remove it after proving no caller remains. Delete its direct parent/child creation helper if unused. It may not decompose, create, or call `run_crew_task()` independently.

## Section 7: HXI Explicit Start Work

Modify the existing [WorkspaceFilesRail](../ui/src/components/workspace/WorkspaceFilesRail.tsx#L72) only; do not create a dashboard or session projection.

1. Remove the `ensureRoomTask` import, `localTaskId`, mount effect, and the two-call POST/PATCH helper from [todosApi.ts](../ui/src/components/workspace/todosApi.ts#L48). `effectiveTaskId` is the real `taskId` or the parent id returned by an explicit successful Start Work.
2. Mount, expand, collapse, and ordinary room viewing perform GET only. Existing explicit Attach and Todo confirmation mutations remain user commands and are not passive viewing.
3. Add a compact stroke-SVG Start Work command in the expanded rail header. It opens an accessible dialog for goal, success criteria, expected deliverable, and optional retry-blocked checkbox. No emoji. Use existing amber/dim HXI styling and <=8px radii.
4. Confirm performs exactly one `POST /api/threads/{thread_id}/start-work`. Disable confirm for invalid form or while pending; prevent double submit; show a bounded inline server error; preserve inputs on failure; Cancel performs no request. On success, close dialog and use returned parent id locally.
5. Do not start a dev server. No Playwright is required: AD-1132/1133 own projection/WebSocket interaction. Vitest component tests are mandatory.

## Candidate Allowlist

Only these paths may change during implementation; any additional production path is an Architect hard stop:

```text
src/probos/agents/operations/coordinator.py
src/probos/cognitive/crew_orchestrator.py
src/probos/cognitive/crew_session.py
src/probos/config.py
src/probos/proactive.py
src/probos/routers/threads.py
src/probos/runtime.py
src/probos/startup/finalize.py
src/probos/threads/__init__.py
src/probos/workforce.py
tests/test_ad1128_crew_session_ingress_dedup.py
tests/test_ad868_self_originated_crew.py
tests/test_ad867_crew_orchestrator.py                         (post-gate correction: one named test only)
tests/test_ad1124_crew_session_contract.py                    (post-gate corrections: three named tests only)
tests/test_ad1126_verified_finalization.py                    (post-gate correction: one named test only)
ui/src/components/workspace/WorkspaceFilesRail.tsx
ui/src/components/workspace/todosApi.ts
ui/src/components/workspace/__tests__/TodosList.test.tsx
ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
PROGRESS.md                         (green closeout only)
docs/development/roadmap.md        (green closeout only)
DECISIONS.md                       (green closeout only)
prompts/ad-1128-crew-session-ingress-dedup.md
prompts/ad-1128-crew-session-ingress-dedup-execution.md
prompts/archive/ad-1128-crew-session-ingress-dedup.md              (closeout move)
prompts/archive/ad-1128-crew-session-ingress-dedup-execution.md    (closeout move)
```

`runtime.py` is unavoidable only for default-off planner advertisement because the live collector reads class descriptors while live bus subscription reads instance descriptors. No other runtime behavior belongs there.

## Tests

Use real `WorkItemStore`, `CrewSessionService`, and `ChatThreadStore` with `SQLiteConnectionFactory`; no MagicMock at persistence, registry/rank, or lifecycle boundaries. A narrow schedule spy/protocol fake, deterministic scorer/decomposer, clocks/id factories, and barrier subclasses are allowed. Test Arrange-Act-Assert and exact outcomes.

Backend coverage in `tests/test_ad1128_crew_session_ingress_dedup.py`:

- canonical exact, NFKC/casefold/whitespace equivalence, punctuation difference, NUL/surrogate/UTF-8/char bounds;
- exact ordered criteria and deliverable compatibility;
- exact before semantic, threshold edge, deterministic tie, scan overflow, scorer-call overflow, invalid scorer type/range/non-finite;
- two concurrent equivalent calls with barriers: one parent/thread/plan/schedule and duplicate count one; three callers produce count two; distinct goals create distinct authorities;
- second scan winner while decomposition is held; no write before release; decomposition exception/cancellation drains and writes nothing;
- requested-room CAS, terminal 409, bound incompatible 409, missing/archived room, owner union/order/cap and facilitator preservation;
- Captain/agent spoof attempts, absent/unregistered/non-crew agent, real Ensign and Lieutenant+ trust fixtures, live rank drop before scan 2/write;
- blocked ordinary/agent no schedule; exact recoverable Captain retry for discussing/executing/verifying; nonrecoverable/terminal rejects; new blocked->review edge;
- marker strictness/bounds and every pre/post/cancel boundary: parent create, room create/link, marker phase, initialize, plan install/adopt, clear, schedule;
- compensation only for untouched marker-owned state; message/drift/unknown outcome prevents delete; after session authority never deletes;
- startup repair runs before normal recovery scan, adopts/installs through landed APIs, clears exact marker, schedules once, and has no background daemon;
- closed scheduling leaves durable authority and returns fail-closed; default off performs no descriptor, candidate/repair scan, scorer, decomposition, task, or schedule;
- Coordinator intent happy/error and truthful Captain provenance; proactive wrapper real rank behavior and truthful agent provenance; `[GROUP_CHAT]` unchanged;
- API happy/error/validation (minimum three) plus disabled 503 and terminal 409.

UI component coverage:

- mount taskless/bound, expand, collapse, and polling issue zero POST/PATCH/DELETE;
- opening/cancelling dialog issues zero mutation;
- invalid/pending states disable confirm and prevent double submission;
- one confirm issues exactly one correctly shaped start-work POST; success binds returned parent locally; error is visible and retryable;
- no `ensureRoomTask` call/export and no emoji; existing Attach/Todo explicit actions remain green.

## What This Does Not Change

Do not build AD-1129 EventLog, AD-1130 trust, AD-1131 delivery/metrics, AD-1132 dashboard/full session projection, AD-1133 WebSocket, global FTS/search, automatic every-chat conversion, a new DB/schema/table/column/index, alternate runner, queue/daemon, `config/system.yaml`, dependency files, commercial code/content, new auth, or `[GROUP_CHAT]` semantics.

Do not alter AD-1127 plan identity, recovery retry taxonomy, child execution, verification/synthesis, Artifact/provenance publication, task owner map, shutdown drain, or final result contract except the explicit startup repair-before-scan call and blocked retry edges above.

## Tracking And Acceptance

After frozen green gates only: update `PROGRESS.md`, `docs/development/roadmap.md`, and `DECISIONS.md`; archive both prompt bytes unchanged; commit exactly `AD-1128: add unified CrewSession ingress (closes #1047)`. Builder does not push or mutate GitHub.

Acceptance:

- All three ingress paths use one server-principal `open_or_resume()` and one AD-1127 `schedule()` owner.
- Exact and semantic concurrent duplicates return one parent/thread; each duplicate invocation increments exactly once.
- Provisioning is bounded, reconstructable, cancellation-safe, and honest about cross-store atomicity.
- Blocked work is inert unless an explicit Captain room retry passes exact evidence.
- Passive HXI viewing is GET-only; explicit confirm performs one POST.
- Disabled mode advertises and performs nothing; endpoint fails closed.
- The execution document's completed focused/PRE-GATE work plus exact post-gate correction/freeze/closeout protocol passes; the next full suite remains deferred to AD-1133.

Verify all changes comply with the Engineering Principles in .github/copilot-instructions.md.

## Verified Against Codebase (2026-07-21)

| Claim | Live evidence |
|---|---|
| v1 contract/service and duplicate field | `crew_session.py:1357,1388,1700` |
| blocked fine transition lacks verifying | `crew_session.py:57-60` |
| blocked coarse transition lacks review | `workforce.py:247-270` |
| plan install/adopt are service-owned | `crew_session.py:1907,2033` |
| orchestrator is closed at construction and owns `schedule` | `crew_orchestrator.py:128,202` |
| AD-1127 sync decomposer runs in held `to_thread` | `crew_orchestrator.py:466-565`; `consultation/llm_decomposer.py:101` |
| old agent ingress blocks and creates directly | `crew_orchestrator.py:1073`; `proactive.py:3468-3511` |
| recovery scan and metadata CAS are store-owned | `workforce.py:1664,2263` |
| thread store is synchronous and lacks task-link CAS | `threads/__init__.py:204,236,323` |
| startup wires service, orchestrator, then awaits start | `startup/finalize.py:1716,1757,4821` |
| coordinator descriptor has no handler | `agents/operations/coordinator.py:16,25`; no `handle_intent` hit |
| planner collector reads template descriptors | `runtime.py:4777-4799` |
| intent envelope has no caller principal | `types.py:58-75`; DAG submits only intent/params |
| passive UI currently creates then PATCH-links a task | `WorkspaceFilesRail.tsx:72-93`; `todosApi.ts:48-64` |
| API thread models/routes already live | `routers/threads.py:116,231,256` |
| semantic adapter is synchronous and bounded to `[0,1]` today | `knowledge/embeddings.py:276-303` |

Verification commands used during architecture (read-only):

```text
grep -n "class CrewSessionService\|async def initialize_session\|async def install_recovery_plan\|async def adopt_recovery_plan" src/probos/cognitive/crew_session.py
grep -n "async def start\|def schedule\|async def originate_crew_task\|def _get_decomposer" src/probos/cognitive/crew_orchestrator.py
grep -n "crew_session\|list_crew_session_recovery_candidates\|merge_work_item_metadata" src/probos/workforce.py
grep -n "def _wire_crew_session_service\|def _wire_crew_orchestrator\|crew_orchestrator" src/probos/startup/finalize.py
grep -n "class CoordinatorAgent\|intent_descriptors\|handle_intent" src/probos/agents/operations/coordinator.py
grep -n "def _collect_intent_descriptors" src/probos/runtime.py
grep -n "ensureRoomTask\|WorkspaceFilesRail" ui/src/components/workspace/{WorkspaceFilesRail.tsx,todosApi.ts}
```

## Architect Three-Pass Review (2026-07-21)

### Pass 1: Contract

**Verdict: APPROVED.** Every depended-on pre-build API is linked above; additive APIs are introduced explicitly. The service owns principal, dedup, provisioning, retry, and schedule handoff. The orchestrator remains the sole runner. `runtime.py` has one verified, necessary advertisement role.

### Pass 2: Safety

**Verdict: APPROVED.** The design fails closed on incomplete bounded scans, malformed authority, scorer anomalies, terminal room bindings, rank drift, and uncertain commits. The admission lock plus second scan addresses local and external races. Markers, exact CAS, held sync mutations, reconciliation, and authority-aware compensation cover cancellation/crash windows without claiming cross-DB atomicity.

### Pass 3: Scope And Gates

**Verdict: APPROVED.** The allowlist is limited to the owning service/stores, three ingress boundaries, one conditional descriptor filter, existing workspace rail, tests, and closeout trackers. Deferred AD-1129 through AD-1133, schema/YAML, global search, commercial content, and alternate runners are excluded. Execution is delegated to the companion optimized protocol.

## Post-Gate Adjudication (2026-07-21)

**Verdict: PRODUCTION CORRECT; TEST-ONLY CORRECTION REQUIRED.** Preserve every current production/UI byte. The completed optimized backend changed-surface gate collected 177 tests under `-n 16 --dist=worksteal`: 158 passed and 19 failed in 75.89 seconds. The targeted UI gate passed 23/23 in 3.34 seconds. Backend evidence is the frozen log `probos_ad1128_backend_5d2642e4c688480aa6ba9c053134f277.log`, SHA-256 `bf0ebe0f8ca44a4768e667d6a07c1077f88ff1718db22cb84090244d90b63ff6`.

Fifteen failures are one fixture defect in `tests/test_ad1128_crew_session_ingress_dedup.py`: its shared write-capable harness injects `_Clock(1_000.0)` into `CrewSessionService`, while the real `WorkItemStore.create_work_item()` stamps a newly provisioned parent with current wall time. The live service correctly calls `_server_time(parent.created_at)` and rejects the impossible chronology as `crew_session_clock_regression`. This is the intended AD-1124 safety contract, not a production regression.

Correct only that shared harness clock. Because `WorkItemStore` has no injected clock, use one documented deterministic fixed epoch that is later than contemporary persisted parent timestamps and still below the live `_MAX_TIMESTAMP = 253_402_300_799.0`; use `32_503_680_000.0` (year 3000 UTC) as the `_Clock` default. Do not use `time.time()`, `time.time() + delta`, sleeping, monkeypatching the shared stdlib `time` module, or any timing race. In `test_open_or_resume_provisions_parent_room_plan_and_clears_marker`, assert the authoritative persisted `crew_session.transitioned_at` is greater than `parent.created_at`. Keep the existing AD-1124 initialize/transition clock-regression tests unchanged and include them as negative controls in the correction gate.

The remaining four observed failures are obsolete compatibility guards. One adjacent AD-1124 exact-public-set guard is also statically guaranteed to become stale when selected. These are the only authorized legacy corrections:

| File and exact test | Required narrow correction | Safety intent retained |
|---|---|---|
| `tests/test_ad867_crew_orchestrator.py::test_maybe_dispatch_holds_task_reference` | Inject a narrow service fake whose typed async `repair_provisioning(*, limit)` records the configured limit and returns `()`; assert startup called it once. | `start()` still opens recovery before dispatch, and the test still proves the owner task is held then removed on completion. |
| `tests/test_ad1124_crew_session_contract.py::test_enabled_wirer_real_stores_attaches_once_preserving_identity` | Supply the now-mandatory non-null `registry`, `ontology`, `trust_network`, and `llm_client` dependencies in the test runtime; keep the real work/thread stores and exact identity-preservation assertions. | Enabled composition remains fail-fast and attaches exactly one service instance. |
| `tests/test_ad1124_crew_session_contract.py::test_public_service_api_and_annotations_are_exact` | Add only `captain_principal`, `agent_principal`, `bind_scheduler`, `open_or_resume`, and `repair_provisioning` to the exact public set and exact parameter map. | The test continues to reject any unplanned public API and requires full annotations on every public parameter/return. |
| `tests/test_ad1124_crew_session_contract.py::test_source_has_to_thread_and_no_raw_sqlite_schema_or_lifecycle_path` | Remove only `open_or_resume` from the forbidden strings. Replace the pre-AD-1128 exact-one-task assumption with an exact owner set for `_run_held_to_thread`, `_reconcile_cancelled_parent_create`, `_checkpoint_cancelled_provisioning`, and `_reconcile_cancelled_plan_commit`; retain the detailed plan-reconciliation target/name/shield assertions and reject any fifth task site. | Raw SQLite/schema/lifecycle paths and `ensure_future` stay forbidden; every allowed task is an awaited, shielded cancellation-reconciliation owner. |
| `tests/test_ad1126_verified_finalization.py::test_public_session_apis_and_finalizer_signature_are_fully_typed` | Add only the same five AD-1128 methods to the frozen `CrewSessionService` public set. | The AD-1126 finalizer/store signature assertions remain unchanged and the service surface remains exact. |

Do not rename, delete, skip, xfail, parameter-filter, or broadly rewrite any test. Do not edit any other pre-AD-1128 test. Test cardinality must not change, so net-new backend test accounting `N` remains unchanged. No production, UI, tracker, archive, config, Git, or GitHub mutation is authorized by this adjudication.

### Post-Gate Review Pass 1: Contract

**Verdict: APPROVED.** All 15 AD-1128 failures terminate at the live parent-time lower bound after the fixture supplies `1_000.0`; no production-generated timestamp violates the contract. The exact additive service methods and startup dependencies match the binding AD-1128 contract.

### Post-Gate Review Pass 2: Safety

**Verdict: APPROVED.** The production clock-regression rejection must remain unchanged. A deterministic year-3000 fixture clock plus an authoritative parent/session ordering assertion repairs the test without wall-clock races. Compatibility edits retain startup repair, exact public surface, full typing, raw-SQL/schema exclusion, and held-task ownership guards.

### Post-Gate Review Pass 3: Scope And Gate

**Verdict: READY.** Only the new AD-1128 test and the five exact legacy test functions above may change. Reuse the accepted targeted UI result because no UI byte may change. Run one optimized backend changed-surface correction gate; do not run the full backend or full UI suite before AD-1133. The execution companion is binding for hashes, manifest preservation, and closeout.

## Final Correction Adjudication (2026-07-21)

**Verdict: PRODUCTION CORRECT; ONE ASSERTION CORRECTION AUTHORIZED.** The completed correction batch is 176/177 backend with the accepted UI result unchanged at 23/23. Its sole failure is `tests/test_ad1128_crew_session_ingress_dedup.py::test_open_or_resume_punctuation_difference_is_not_exact`: the test expects one scorer call, while production correctly makes these two ordered identical calls:

```python
[
    ("report alpha", "report: alpha"),
    ("report alpha", "report: alpha"),
]
```

Both calls are load-bearing. The first `_find_equivalent()` performs the bounded exact-first/semantic scan before decomposition. After decomposition, while the same admission lock still owns local admission, the second `_find_equivalent()` freshly reloads and scores candidates before the first provisioning write. That second pass closes the race with external/non-cooperating writers that can commit equivalent work during decomposition. Removing or caching either call would violate Section 3's fresh-row/fresh-score requirement.

Authorize changing only that exact assertion to the ordered two-entry list above. Do not change production, any other test line, UI, trackers, archive, config, Git, or GitHub. Do not rename, add, remove, skip, xfail, or parameterize a test; collection cardinality and net-new backend test accounting `N` remain unchanged.

Run only that exact backend node plus the execution companion's static scope/hash/cardinality audits. Do not rerun the 177-test correction batch, any broader backend selection, UI, build, or full suite. Report the completed 176/177 batch, exact-node result, and accepted UI 23/23 separately.

### Final Review Pass 1: Contract

**Verdict: APPROVED.** Section 3 requires fresh scoring on both scans, and the live method calls `_find_equivalent()` before and after decomposition. The ordered two-call assertion is the exact observable contract.

### Final Review Pass 2: Safety

**Verdict: APPROVED.** The pre-decomposition call prevents avoidable decomposition for an existing equivalent authority; the post-decomposition call is the last fresh race barrier before provisioning. Neither call may be removed, cached, or coalesced.

### Final Review Pass 3: Scope And Gate

**Verdict: READY.** The allowlist is one assertion in one existing test. No count changes and no production/UI bytes are authorized. One exact-node run and static audits are sufficient because the other 176 backend cases and all 23 targeted UI cases already passed.

## Code-Review Repair Adjudication (2026-07-21)

**Verdict: FIVE REQUIRED GAPS CONFIRMED; READY FOR ONE BATCHED REPAIR.** This section supersedes every earlier status, production-correct verdict, correction-only allowlist, gate, freeze, and closeout instruction in this document where they conflict. Preserve the complete live AD-1128 implementation and change only the exact paths and contracts authorized below. The historical 176/177 correction batch, final exact-node result, and targeted UI result remain valid evidence only for unchanged paths; they do not close these five findings.

The repair has one architectural objective: make the statement "`CrewSessionService.open_or_resume()` is the sole CrewSession admission authority" true at the persistence, startup, API, provenance, and HXI boundaries. Do not redesign AD-1124 through AD-1127 lifecycle services, recovery plans, validated session transitions, child execution, finalization, or the existing single scheduler.

### Confirmed Findings

| Required finding | Live controlling evidence | Decision |
|---|---|---|
| Generic workforce writers bypass ingress admission | `WorkItemStore.create_work_item()`, `update_work_item()`, `transition_work_item()`, and `assign_work_item()` accept or mutate `work_type="crew_session"`; `_provision_new()` calls the generic creator after scan 2 | Reserve CrewSession parent creation/mutation at the store and inject one narrow admission capability into the service |
| Repaired parent ids are discarded | `CrewOrchestrator.start()` awaits `repair_provisioning()` and ignores its returned tuple before scanning recovery candidates | Ordered-union repaired ids with recovery ids under one global scheduling cap |
| Start Work is unauthenticated | `POST /api/threads/{thread_id}/start-work` has no `require_crew_scope` dependency | Add the existing configured-token dependency and its established Bearer tests |
| Provenance is not a universal loaded-row invariant | `_validate_loaded()` checks type/task/time/facilitator/status/room but not `parent.created_by` against session origin | Add one central exact provenance validator used before scoring, mutation, scheduling, and successful loaded-session return |
| Start Work dialog is pointer-complete only | The rail renders a `role="dialog"` overlay without initial focus, Escape handling, focus containment, or opener restoration | Add an explicit keyboard/focus trap without changing layout or request behavior |

## Repair Section 1: Store-Owned CrewSession Admission

### Construction-time capability, not a caller token

Add these fully typed public data/protocol shapes in `src/probos/workforce.py`; keep the concrete implementation private to that module:

```python
@dataclass(frozen=True, slots=True)
class CrewSessionParentCreate:
    id: str
    title: str
    description: str
    assigned_to: str
    created_by: str
    metadata: dict[str, Any]
    created_at: float | None = None


class CrewSessionParentReservation(Protocol):
    async def create_parent(
        self,
        request: CrewSessionParentCreate,
    ) -> WorkItem: ...


class CrewSessionAdmissionPort(Protocol):
    def reserve(
        self,
    ) -> AbstractAsyncContextManager[CrewSessionParentReservation]: ...
```

`CrewSessionParentCreate` carries only privileged parent-insert data. The concrete reservation forces `work_type="crew_session"`, `status="draft"`, `parent_id=None`, empty dependencies, and all other existing safe parent defaults. It requires exact built-in values, a valid top-level parent id, non-empty bounded title/description/assignee/creator, exact JSON metadata within the landed cap, and an omitted or exact built-in `int`/`float` `created_at` (reject bool/subclasses) that is finite and in `0.0..253_402_300_799.0`; when supplied, `updated_at` starts equal to it. It inserts through the store's existing transaction/event/cache path; extract and reuse the existing private insert implementation rather than duplicating SQL, requirement-row creation, cache refresh, or event emission.

Do not import `probos.cognitive.crew_session` into `workforce.py` or duplicate `CrewSessionProvisioningContract` validation there. Before calling `reservation.create_parent()` in production, `CrewSessionService` must prove that the request is the exact server-derived draft parent: metadata has exactly one `crew_provisioning` sibling equal by JSON type and value to the already validated marker, `created_by` and assignment match that marker, and no caller-selected status/work type/parent/dependency field exists. The lower store owns atomic admission; the cognitive service owns CrewSession meaning.

`WorkItemStore` owns one CrewSession admission lock and one concrete port. Add:

```python
def claim_crew_session_admission_port(self) -> CrewSessionAdmissionPort: ...
```

The claim is one-shot per store instance. A second claim raises `RuntimeError("crew_session_admission_port_claimed")`. The concrete port has no public constructor and closes over the exact store and admission lock. It is a capability-bearing write interface, not a value token: no public store method accepts an authority object, sentinel, source string, boolean bypass, or caller-selected secret. A structurally similar fake can support unit tests but cannot write the real store because only the real claimed port closes over it.

Each `reserve()` call returns a new private, non-reentrant async context manager. On `__aenter__`, record `asyncio.current_task()` and activate one fresh reservation generation only after acquiring the store admission lock. `create_parent()` succeeds only while that exact context is active, from that exact owning task, before its first successful create, and with the same store/generation; otherwise raise `RuntimeError("crew_session_admission_reservation_invalid")` before any row lock or write. `__aexit__` invalidates the generation before releasing the lock on success, exception, or cancellation. A retained reservation object cannot create after exit, from a child task, twice, or under another port/store. Do not use a `ContextVar`, thread-local, globally mutable current token, or caller-provided generation.

Validate and canonical-JSON-detach every request field, including metadata, before waiting for `_work_item_row_write_lock`; the detached snapshot alone reaches the insert. Caller mutation after `create_parent()` begins cannot alter the committed row.

Startup composition in `_wire_crew_session_service()` claims the port exactly once and injects it into the one production `CrewSessionService` as `admission_port`. The service stores it privately and exposes no getter. If an enabled `open_or_resume()` has no real port, reject `crew_session_ingress_unwired` before candidate scan, scorer, decomposition, room mutation, or parent write. Existing AD-1124 through AD-1127 service methods remain constructible without this port when ingress is not used. Repeated finalize wiring that finds the already attached service must preserve identity and must not claim again.

This is an in-process construction capability, not authentication or a security boundary against arbitrary Python execution. The authority guarantee is exact for supported production composition and public generic routers: they never receive or expose the claimed port. Do not add a forgeable token parameter, inspect a private store attribute from `CrewSessionService`, import the private concrete port, or use `source="crew_session_*"` as authorization.

### Reservation scope and scan-2 barrier

Keep the existing per-service `_admission_lock`. After decomposition and before the second candidate/room check, acquire `admission_port.reserve()`. Hold that store-level reservation continuously across:

1. the fresh requested-room reread;
2. the complete second ingress candidate scan;
3. every fresh exact/semantic score in scan 2;
4. either returning the scan-2 match or creating the one marker parent through `reservation.create_parent()`.

Do not hold the generic `_work_item_row_write_lock` while scoring or calling the decomposer. The concrete `create_parent()` acquires that existing row-write lock only for its normal atomic insert. Cancellation while waiting for or holding the reservation performs no parent write unless the existing parent-create reconciliation proves the insert committed; the reservation is always released.

This reservation serializes scan 2 plus insertion across any service instance sharing the claimed real port. It is the final race barrier. The live first scan remains outside it so an existing equivalent avoids decomposition. Do not cache or reuse scan-1 rows/scores.

### Generic writer boundary

The store is the final enforcement boundary. Before SQL, booking/requirement mutation, cache refresh, or event emission:

- `create_work_item()` rejects any caller-supplied `work_type="crew_session"` with `ValueError("crew_session_write_reserved")`; `create_from_template()` inherits that rejection after template expansion.
- `update_work_item()` rejects an existing CrewSession parent and rejects changing any ordinary row to `work_type="crew_session"`.
- `transition_work_item()` rejects an existing CrewSession parent, including a same-status request.
- `assign_work_item()` rejects an existing CrewSession parent before eligibility, booking, requirement, status, or assignment changes. `claim_work_item(work_type="crew_session")` rejects before scanning; an unfiltered claim excludes CrewSession rows and may continue to an ordinary eligible row.
- `unassign_work_item()` rejects an existing CrewSession parent before cancelling a booking or changing assignment/status. `start_booking()` and `complete_booking()` reject a booking linked to a CrewSession parent before changing either the booking or parent, closing the legacy pre-repair-booking path; ordinary child bookings remain unchanged. `cancel_booking()` remains booking-only and does not mutate a parent row.
- The reservation applies to the CrewSession parent work type only. Do not reserve, rename, or reroute the derived child work types (`task`, `research`, `analysis`, and other plan-defined types). A caller cannot evade the parent reservation by supplying `parent_id` with `work_type="crew_session"`; that combination is still rejected.

The exact service-owned CAS APIs already used by initialization, recovery, plan install/adoption, transition, publication, and provisioning repair remain unchanged and continue to validate work type, status, assignment, metadata, recovery, and child barriers under `_work_item_row_write_lock`. Do not replace those APIs with generic `update_work_item()`/`transition_work_item()`, and do not authorize generic writers by source-string allowlists.

In `src/probos/routers/workforce.py`, map only `crew_session_write_reserved` from create/from-template/update/transition/assign/claim to HTTP 409 with that exact detail. Reads remain unchanged. Do not add a second route into `open_or_resume()` and do not make the generic router acquire the admission port.

### Required race proof

Use a real `WorkItemStore`, real stores/service, and a narrow recording wrapper around the real claimed port. Pause the service at `CrewSessionParentReservation.create_parent()` after scan 2 but before delegation to the real insert. During that barrier, attempt generic `create_work_item(work_type="crew_session", ...)`; it must fail with `crew_session_write_reserved`, emit nothing, and create no requirement row. Release the barrier and prove exactly one parent, one room, one plan, and one schedule handoff. Retain the existing concurrent equivalent-call tests. Also prove an ordinary child work type remains generically creatable/assignable/transitionable.

## Repair Section 2: Repaired-ID Startup Handoff

`CrewOrchestrator.start()` must retain the exact tuple returned by `repair_provisioning()`. After the existing recovery query, build this deterministic ordered union:

```text
repaired parent ids in repair query order
then recovery candidate ids in recovery query order
de-duplicate by exact id, preserving first occurrence
take at most crew_resume_scan_limit ids across the combined union
```

`crew_provisioning_repair_limit` bounds repair work. `crew_resume_scan_limit` is the single global cap on owner tasks scheduled by this startup pass, not a separate cap per source. Querying remains bounded by the two existing limits; no new config field is required. Repaired ids take precedence so a just-repaired parent cannot be omitted merely because it was absent from or fell beyond the independent recovery result. Excess durable rows remain for a later startup; do not fail or start a daemon.

Before scheduling any selected id, validate the complete selected batch in order through the existing `CrewSessionService.get_session()` and `get_recovery()` paths. Missing/malformed/provenance-invalid rows fail startup before any owner task from this batch is scheduled. Schedule only `discussing`, `executing`, or `verifying`; terminal and `blocked_needs_captain` rows are inert. After the full validation pass, call the existing idempotent `schedule(parent_id)` once per selected id. Do not change `schedule()` or add another task owner.

Required tests:

- `repair_provisioning()` returns a valid parent id that is absent from `list_crew_session_recovery_candidates()`; startup validates and schedules it exactly once.
- The same id in both sources schedules once.
- Repaired-first ordering and the one global `crew_resume_scan_limit` cap are exact.
- A malformed-provenance selected row causes zero schedule calls, including for earlier valid ids in the same union.

## Repair Section 3: Existing Crew-Scope Auth On Start Work

Import `require_crew_scope` from `probos.routers.auth` and apply it to only the existing `POST /api/threads/{thread_id}/start-work` route via FastAPI `Depends`. Reuse the dependency exactly as implemented: it reads `runtime.config.auth.crew_scope_token`, passes through when the configured token is empty, and when configured accepts the existing `Authorization: Bearer <token>` contract (including the dependency's existing query fallback behavior). Do not add a token field, CSRF scheme, cookie, role, user identity, new config, HXI secret handling, or alternate auth dependency.

Extend the existing AD-1128 route harness with a real `SystemConfig` or an exact config shape containing both `agentic_dispatch` and `auth`. Add configured-token tests:

- missing Bearer returns 401 `missing_or_malformed_authorization` before Captain principal/service work;
- wrong Bearer returns 401 `invalid_token` before Captain principal/service work;
- valid Bearer reaches the existing handler and returns the current successful result.

Keep one empty-token pass-through test so default local installs remain compatible. Pydantic validation and disabled-service behavior remain separate and unchanged.

## Repair Section 4: Exact Provenance Invariants

The existing contract literals remain authoritative and case-sensitive:

```text
origin == "captain" -> originator_id == "captain" and parent.created_by == "captain"
origin == "agent"   -> parent.created_by == originator_id
```

Only lowercase ASCII `"captain"` is the Captain sentinel. Do not casefold, normalize aliases, accept `"Captain"`, derive Captain from facilitator, or add another origin literal. `CrewSessionContract.origin` and `CrewSessionProvisioningContract.origin` remain `Literal["captain", "agent"]`.

Add one shared exact provenance helper in `crew_session.py`, raising `ValueError("crew_session_provenance_invalid")`, and call it from `CrewSessionService._validate_loaded(parent, contract)` before room/recovery work. Every path that parses a persisted `crew_session` from a `WorkItem` must pass `_validate_loaded()` before semantic scoring, metadata/status mutation, owner scheduling, or successful return. Close current post-write/authoritative-return gaps as needed; do not duplicate weaker checks at individual scorers or callers.

Validate the same relation at both creation boundaries:

- `_validate_principal()` keeps its exact Captain/agent request checks before scan/decomposition.
- Add an `after` model validator to `CrewSessionProvisioningContract` enforcing `created_by` against `origin`/`originator_id` before parent creation or repair mutation. `_parse_provisioning()` must preflight the exact raw `origin`, `originator_id`, and `created_by` relation through the shared helper before `model_validate()` and must re-raise `crew_session_provenance_invalid` unchanged; do not collapse that relation failure to `crew_provisioning_contract_invalid`.
- Before `initialize_session()` writes the initial contract, validate the candidate contract against the loaded parent, so direct AD-1124 service use cannot initialize forged provenance.
- `_require_provisioning_parent()` must call the shared helper with marker provenance plus `parent.created_by`; a creator mismatch is `crew_session_provenance_invalid`, not a repairable `crew_provisioning_parent_conflict`. Marker/session reconciliation must preserve origin and originator exactly.

Because `get_session()` is the central loaded-session path used by dedup and startup validation, a malformed authority must fail before scorer, decomposer continuation, resume CAS, participant write, repair mutation, or `schedule()`. In `repair_provisioning()`, `crew_session_provenance_invalid` is a non-repairable authority error: re-raise it unchanged and do not call `_fail_irreparable_provisioning()`, transition the session, update the marker, reconcile participants, or continue to later rows. Do not repair, reinterpret, skip, or fail-transition a malformed provenance row and create beside it.

Required tests cover Captain wrong originator, Captain wrong parent creator, mixed-case Captain, agent creator/originator mismatch, malformed provisioning marker provenance, direct initialization rejection, candidate rejection before scorer/write, and startup rejection before any schedule. Include one valid Captain and one valid agent control. Assert exact row/room/event/schedule non-mutation on every rejection.

## Repair Section 5: Start Work Keyboard Contract

Keep the existing compact overlay and stable 300px rail layout. Use an explicit focus trap in `WorkspaceFilesRail.tsx`; do not depend on native `<dialog>.showModal()` because the current component tests run under jsdom and the overlay is positioned inside the rail.

Required behavior:

1. When the opener is activated, remember that exact button and focus the Goal textarea after the dialog mounts.
2. While open, Tab from the last enabled dialog control wraps to the first enabled control; Shift+Tab from the first wraps to the last. Disabled controls are excluded, so pending state remains contained.
3. Escape prevents propagation. It closes only when `startPending` is false; while pending it leaves the dialog and request ownership unchanged.
4. Cancel, successful submit, and non-pending Escape restore focus to the remembered opener after unmount when it is still connected. Thread replacement may close without focusing a detached element.
5. Preserve the existing one-request guard, disabled pending controls, bounded inline error, inputs-on-error, no-emoji stroke SVG, radii, and all GET-only passive behavior.

Give the dialog overlay a programmatically focusable container (`tabIndex={-1}`). If no enabled form control exists, including while all controls are disabled pending the POST, prevent Tab/Shift+Tab and keep focus on that container. When pending begins and the active form control becomes disabled, move focus to the container; do not move it outside the dialog or enable Cancel merely to create a tab stop.

Add component tests for initial Goal focus, forward/backward wrap, Escape close plus opener restoration, pending Escape no-op, and Cancel/success restoration. Use the existing deferred-fetch pattern for pending behavior. Do not add Playwright or a new component/file.

## Batched Repair Allowlist

This list supersedes the earlier Candidate Allowlist for the repair. No tracker, archive, config, schema, dependency, Git, GitHub, AD-1129 prompt, or unrelated source/test path may change.

```text
src/probos/workforce.py
src/probos/cognitive/crew_session.py
src/probos/cognitive/crew_orchestrator.py
src/probos/routers/workforce.py
src/probos/routers/threads.py
src/probos/startup/finalize.py
tests/test_ad1124_crew_session_contract.py
tests/test_ad1125_room_bound_execution.py
tests/test_ad1126_verified_finalization.py
tests/test_ad1127_crew_session_lifecycle_recovery.py
tests/test_ad1128_crew_session_ingress_dedup.py
ui/src/components/workspace/WorkspaceFilesRail.tsx
ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
prompts/ad-1128-crew-session-ingress-dedup.md
prompts/ad-1128-crew-session-ingress-dedup-execution.md
```

The four landed CrewSession test files are authorized only for fixture migration from generic `create_work_item(work_type="crew_session")` to the real claimed admission port, replacement of legacy Captain `originator_id="captain-1"` fixtures with the exact lowercase `"captain"` sentinel where `origin="captain"`, and assertions made obsolete by the new generic-writer rejection. A test may claim the real port, retain that exact object in its fixture, create a deterministic bare draft parent through `reservation.create_parent()`, and inject the same port only into a service that exercises ingress. Tests needing a pre-existing non-draft or malformed persisted authority must advance/mutate that seed through the existing exact store CAS helpers already under test; they may not add a test-only production bypass or reach into a private store authority attribute. Preserve test names, cardinality, and all AD-1124 through AD-1127 lifecycle assertions. Do not rewrite unrelated metadata keys whose value happens to be `"captain"`. In particular, revise `test_generic_status_writer_cannot_interleave_after_merge_admission` to assert that the generic transition waits for the shared row-write lock if already queued, then fails `crew_session_write_reserved` without a second update; the service transition remains authoritative. Do not skip, xfail, delete, rename, or weaken clock, recovery, plan, room, cancellation, publication, or finalization tests.

New repair behavior tests belong in `tests/test_ad1128_crew_session_ingress_dedup.py`. Test-only port wrappers/fakes must be narrow and must delegate to the real port for persistence behavior. No MagicMock at store, provenance, auth, or scheduling boundaries.

## Repair Execution And Acceptance

Captain optimization is binding: implement all five production/test/UI changes before running any test or validation command. Then run only the targeted changed-set validation batch specified by the companion execution document. Python selections with at least eight collected tests use `-n 16 --dist=worksteal`; tiny exact-node selections use `-n 0`. Run only the directly affected `WorkspaceFilesRail` Vitest file with its default pool. Do not run the full Python suite, full UI suite, build, compileall, Playwright, dev server, or a second confidence gate. AD-1133 owns the next consolidated gate. Reuse the historical AD-1128 evidence only for unchanged paths.

Code-review acceptance requires all of the following:

- The real store port is claimed once at composition and privately owned by the one service; no token/bypass/source string authorizes generic writers.
- Scan 2 and the one parent insert are serialized under the store reservation; the barrier test proves a generic post-scan writer cannot create a second authority.
- Generic workforce create/template/update/transition/assignment/claim/unassign and parent-mutating booking paths fail closed for CrewSession parents while child work types and all service CAS lifecycle paths remain valid.
- Startup schedules the repaired-first ordered union under one global cap, validates the complete selected batch before any schedule, and covers a repaired id absent from recovery results.
- Start Work uses the existing `require_crew_scope`; missing/wrong/valid configured Bearer behavior is exact and no new auth design exists.
- Every persisted session enforces exact Captain/agent parent provenance before scorer, write, repair, or schedule; malformed authority is never skipped.
- The Start Work dialog has initial focus, containment, guarded Escape, and opener restoration without layout/request/HXI regressions.
- Only the batched repair allowlist changed, and no AD-1129 prompt or implementation was read into scope or modified.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Live Codebase (2026-07-21 Repair Review)

| Claim | Verified live anchor |
|---|---|
| Generic parent creation is unrestricted | `src/probos/workforce.py:1541` `create_work_item(**kwargs)` accepts caller work type |
| Generic mutation paths can alter CrewSession rows | `src/probos/workforce.py:2428,3128,3229` update/transition/assign use only the generic row contract |
| Service writes the marker parent through generic creation after scan 2 | `src/probos/cognitive/crew_session.py:2390-2450,2505-2560` |
| Service-local lock cannot serialize another service/store caller | `src/probos/cognitive/crew_session.py:2187,2284` |
| Repair ids are discarded before recovery scheduling | `src/probos/cognitive/crew_orchestrator.py:167-184` |
| `schedule()` remains the synchronous idempotent owner | `src/probos/cognitive/crew_orchestrator.py:212-240` |
| Start Work lacks crew-scope dependency | `src/probos/routers/threads.py:267-321` |
| Existing configured Bearer dependency is complete | `src/probos/routers/auth.py:40-75` |
| Loaded-session validation lacks parent provenance | `src/probos/cognitive/crew_session.py:4755-4780` |
| Exact principal literals already exist | `src/probos/cognitive/crew_session.py:182-186,2191-2206,3219-3232` |
| Dedup scoring loads through `get_session()` | `src/probos/cognitive/crew_session.py:3280-3340,3669-3680` |
| Current dialog is a role overlay with no keyboard/focus contract | `ui/src/components/workspace/WorkspaceFilesRail.tsx:72-220,350-500` |
| Existing API tests omit configured Bearer cases | `tests/test_ad1128_crew_session_ingress_dedup.py:2025-2140` |

### Prompt-Only Review Pass 1: Contract

**Verdict: APPROVED FOR REPAIR.** The store port is a construction-time capability with a one-shot real implementation, not a caller-forgeable token. Its reservation spans the fresh second scan and exact parent insertion while preserving the landed service CAS lifecycle. Repaired-id union, existing auth dependency, provenance relation, and focus behavior are specified with exact inputs, ordering, error codes, and ownership boundaries.

### Prompt-Only Review Pass 2: Safety

**Verdict: APPROVED FOR REPAIR.** The design closes the post-scan external-writer race without holding the global row lock across scoring, rejects all supported generic parent mutation before side effects, validates a complete startup batch before task creation, and fails malformed provenance before scorer/write/schedule. It adds no runner, daemon, authentication scheme, private reach-through, source-string bypass, child-work reservation, or cross-store atomicity claim.

### Prompt-Only Review Pass 3: Scope And Gate

**Verdict: READY.** The allowlist contains only the owning store/service/startup/routes, the existing rail, the new repair tests, and landed CrewSession fixtures made obsolete by reservation. All five coding changes are one batch followed by one targeted Python/UI validation batch. Full Python/UI/build/Playwright remain deferred to AD-1133; trackers, archive, Git/GitHub, AD-1129, config/YAML, schema, and dependency files are excluded.

## Post-Coding Backend Gate Adjudication (2026-07-21)

**Verdict: READY FOR ONE BATCHED FIX.** This adjudication supersedes the prior
failed-gate hard stop and every earlier correction allowlist or gate instruction
where they conflict. Preserve the complete live tree. Do not weaken the
CrewSession generic-writer reservation, add a mutation token/bypass, or expose
the claimed admission port. The admission port remains a task-scoped capability
for privileged parent creation only; all later CrewSession lifecycle mutations
remain on the exact service/store CAS APIs.

The adjudicated backend gate is the frozen log
`C:\Users\seang\AppData\Local\Temp\probos_ad1128_review_repair_2b60b41eadb74088b34cef5137ce5747.log`:
535 collected, 521 passed, 14 failed under `-n 16 --dist=worksteal` in
28.87 seconds. The failures classify exactly as follows.

| Exact failures | Classification | Binding resolution |
|---|---|---|
| `test_facilitator_reassignment_between_service_load_and_real_claim_conflicts`; `test_final_publication_real_cas_races_never_overwrite_authority[assignment]`; `[status]`; `test_final_publication_sibling_deletion_conflicts_before_done`; both `test_publish_*commit_error_reread_cancellation_propagates`; `test_publish_verified_result_postcommit_sibling_deletion_returns_done`; `test_final_publication_child_barrier_is_atomic_with_parent_done`; the `claim-race` subcase of `test_failure_classification_noop_reassignment_and_startup_matrix` | Nine stale AD-1126 test-contract locations. Seven try to mutate a reserved parent through generic `update_work_item()`, one fixture omitted its real claimed admission port, and one sibling assertion expects replacement/deletion instead of shallow sibling preservation. | Migrate only the named helpers/tests below. Production reservation is correct. |
| `test_install_recovery_plan_repeated_cancel_preserves_first_and_authority`; `test_adopt_recovery_plan_repeated_cancel_preserves_first_and_authority` | Two stale AD-1127 post-reconciliation probes use the pre-operation `parent.status` snapshot after the authoritative parent has advanced. | Reread the committed parent, then use its status/assignment as the exact CAS expectations. |
| both parameters of `test_compensation_removes_only_exact_untouched_pre_session_authority`; `test_post_room_bound_error_compensates_authoritative_marker` | One production predicate contradiction exposed by three AD-1128 tests. The privileged creator stores `description=marker.goal`, but `delete_untouched_crew_session_provisioning()` requires `description == ""`; therefore exact compensation can never delete a live untouched parent. | Repair that one predicate and retain all other exact-delete barriers. |

### Compensation Policy Is Pinned

The binding Section 5 policy remains authoritative. Before `crew_session`
exists, an exact marker-owned parent and exact untouched created room, or an
exactly restorable adopted-room link, are safely reversible and must be removed.
`delete_untouched_crew_session_provisioning()` must compare the parent
description to the exact validated marker goal, matching the actual
`CrewSessionParentCreate(description=request.display_goal)` contract. Change
only the live `item.description == ""` predicate to exact equality with
`expected_marker["goal"]` (using the module's existing safe lookup grammar).

Every other proof remains mandatory: exact JSON marker, draft status, title,
assignment, creator, parent/dependency/default fields, one untouched resource
requirement, no child, and no booking. Any room message, field drift, foreign
link, failed/unknown reread, cleanup error, or non-exact parent forbids deletion
and leaves the provisioning marker discoverable for restart repair. After
`crew_session` exists, compensation never deletes authority. Do not convert the
three failing tests to failed-marker expectations and do not add another
production change.

### Exact AD-1126 Compatibility Authority

Only these existing helpers/tests in
`tests/test_ad1126_verified_finalization.py` may change:

1. `_RealMergeRaceStore` and
    `test_facilitator_reassignment_between_service_load_and_real_claim_conflicts`:
    preserve the between-load-and-CAS injection point, but treat generic parent
    reassignment as an exact `crew_session_write_reserved` rejection. The
    service-owned transition then commits, and the authoritative parent keeps
    its facilitator. Do not fabricate reassignment through a private lock, raw
    SQL, token, or fake accepted write.
2. `_RealMergeRaceStore` and
    `test_final_publication_real_cas_races_never_overwrite_authority`:
    preserve the existing `crew_synth` and `revision` conflict cases. For
    `assignment`, prove the generic attempt is rejected and publication commits
    without assignment drift. For `status`, use a real competing
    `CrewSessionService.transition_session(parent_id,
    "blocked_needs_captain", expected_revision=verifying.revision,
    blocked_reason="concurrent status transition")` call, not generic status
    update; publication must then fail with the canonical
    `work_item_(metadata|state)_conflict` from its stale exact CAS and preserve
    the complete committed blocked row/contract. Keep all four parameters and
    one test definition.
3. `_SiblingDeletionRaceStore` and
    `test_final_publication_sibling_deletion_conflicts_before_done`: replace the
    impossible generic metadata replacement with an exact
    `merge_work_item_metadata()` sibling update carrying full expected
    work-type/status/assignment/value CAS. Publication succeeds and preserves the
    concurrent sibling by shallow merge; it never recreates an older sibling
    value.
4. `_assert_publication_reread_cancellation` and its two callers: replace only
    the post-cancellation generic parent write probe with an exact
    `merge_work_item_metadata()` probe. Use the just-reread authoritative row's
    status and assignment, prove the call completes, and assert the probe sibling.
5. `test_final_publication_child_barrier_is_atomic_with_parent_done`: claim the
    real port once through `WorkItemStore.claim_crew_session_admission_port()` and
    place that exact object in the local `_Stores` fixture before `_executing_case()`.
    No MagicMock, private token, or second claim is allowed.
6. `_PostCommitSiblingDeletionStore` and
    `test_publish_verified_result_postcommit_sibling_deletion_returns_done`:
    replace the impossible generic sibling deletion with an exact post-commit
    shallow sibling merge, retain the injected `None`/authoritative-reread path,
    and assert both the original `origin` and the new sibling survive beside the
    exact done contract.
7. In `test_failure_classification_noop_reassignment_and_startup_matrix`, keep
    the existing `reassigned` subcase as the generic-reservation proof. Replace
    only local `_ReassignOnClaim` in the `claim-race` subcase with a real
    service-owned competing transition before the stale claim transition. Assert
    the canonical revision/state conflict and the complete winning authoritative
    row. Do not make a generic assignment appear successful.

These are compatibility migrations, not permission to broaden production. A
generic writer may appear only where the test explicitly asserts its rejection.
Every fixture that creates an internal CrewSession parent must use the real
one-shot port obtained from the owning public store API and the task-scoped
reservation. Preserve every existing test name, parameter, and collection
cardinality.

### Exact AD-1127 Compatibility Authority

In only the two repeated-cancellation tests named above, after reconciliation
finishes, reread `parent.id` from the real store and require a non-`None`
authoritative row. Use that row's current `status` and `assigned_to` in the
`post_reconcile_probe` metadata CAS. Keep the probe, cancellation identity,
recovery/child assertions, lock-release proof, and exact probe sibling. Do not
use the stale pre-initialization `parent` snapshot and do not replace the probe
with a generic writer.

### One-Fix Mutation Allowlist

Preserve all existing live changes. The Builder's new mutation set is an exact
subset of only:

```text
src/probos/workforce.py
tests/test_ad1126_verified_finalization.py
tests/test_ad1127_crew_session_lifecycle_recovery.py
tests/test_ad1128_crew_session_ingress_dedup.py
```

The two active AD-1128 prompts are Architect-amended frozen inputs. They must
match the handed-off hashes/sizes and are not Builder-mutable paths.

The AD-1128 test file may change only where needed to make the two exact
compensation fixtures assert the live create contract before their existing
deletion assertions; no expectation may be changed from removal to retention.
No test may be added, removed, renamed, skipped, xfailed, merged, or
parameter-filtered. The backend target remains exactly 535 collected tests. No
other production, test, UI, config/YAML, schema, dependency, tracker, archive,
prompt, commercial, Git, or GitHub path may change. Ignore AD-1129 files.

Run the one backend/Vitest batch and static audits from the execution companion
only after every authorized edit is complete. No red-first node, intermediate
run, rerun, full suite, build, compileall, lint, Playwright, Vite, or dev server
is authorized.

### Gate-Adjudication Review Pass 1: Contract

**Verdict: APPROVED.** The reservation remains the final generic-writer
boundary. Reachable lifecycle races use the existing exact service/store CAS
surface; impossible generic mutations become rejection assertions. Exact
pre-session rollback remains the sole production correction.

### Gate-Adjudication Review Pass 2: Safety

**Verdict: APPROVED.** Exact rollback is permitted only while the parent, room,
marker, requirement, child, and booking proofs establish sole untouched
ownership. Ambiguity remains durable and restart-repairable. No token, private
authority, raw SQL, replacement metadata write, or test-only bypass is added.

### Gate-Adjudication Review Pass 3: Scope And Gate

**Verdict: CONTENT READY; HANDOFF NOT READY UNTIL HASH/SIZE BINDING.** The two
active AD-1128 prompts are the only Architect edits; four implementation/test
paths are the complete Builder mutation allowlist. All fixes precede one unchanged 535-target
`-n 16 --dist=worksteal` batch, the directly affected Vitest file, and read-only
static audits. No other validation or closeout action is allowed. Supplying the
exact post-amendment SHA-256 and byte size for both active prompts is the only
remaining handoff condition and requires no content revision.

## Final AD-1128 Adjudication (2026-07-21)

**Verdict: PRODUCTION CORRECT; ONE EXISTING TEST FUNCTION NEEDS A CONTRACT
CORRECTION.** This section supersedes the 535-test rerun and failed-gate stop in
the preceding adjudication wherever they conflict. Preserve every production,
UI, and other test byte. The latest unchanged repair batch is authoritative:
535 collected under `-n 16 --dist=worksteal`, 534 passed, one failed in 26.42
seconds. The sole failure is
`tests/test_ad1126_verified_finalization.py::test_failure_classification_noop_reassignment_and_startup_matrix`.

The reported "no-op reassignment" must not be implemented as a new parent
assignment API or as a generic-writer exception. Generic CrewSession mutation
remains reserved: `WorkItemStore.update_work_item()` rejects an existing
CrewSession before considering whether `assigned_to` is equal, and the existing
different-facilitator assertion must continue to require
`crew_session_write_reserved`.

The existing service-owned no-op contract already has the correct shape.
`CrewSessionService.transition_session()` validates the loaded parent and exact
facilitator assignment, checks the expected revision, and returns the current
contract before calling the store when both state and progress are unchanged.
The lower `merge_work_item_metadata()` contract likewise returns the current
row before a DB write when metadata, status, and token delta are unchanged.
Therefore an `executing -> executing` service call against the already
authoritative facilitator is idempotent: it returns the exact current contract,
does not increment revision, does not change `updated_at`, metadata, status, or
assignment, and emits no event.

The finalizer's public race contract is also already correct. A genuine
service-owned competing transition can make its claim CAS stale, but
`CrewSessionFinalizer.finalize()` catches that ordinary exception, rereads the
authority, and returns `claimed=False`, `completed=False`,
`reason="claim_lost"`; it does not propagate the inner
`crew_session_revision_conflict`. Direct stale service CAS still raises and is
independently retained by
`tests/test_ad1124_crew_session_contract.py::test_stale_revision_conflict_has_no_mutation`.

### Exact Test Correction

Change only the body of
`test_failure_classification_noop_reassignment_and_startup_matrix`:

1. In the existing `reassigned` subcase, retain the attempted generic update to
    `other-facilitator` and its exact `crew_session_write_reserved` assertion.
    This is the true reassignment oracle and must remain before any finalizer
    work.
2. In that same subcase, capture the authoritative executing contract, parent
    row, and event count. Call
    `service.transition_session(parent.id, "executing",
    expected_revision=current.revision)` with no progress fields. Assert the
    returned contract equals the captured contract, its revision is unchanged,
    the reread parent has the same `assigned_to`, status, metadata, and
    `updated_at`, and the event count is unchanged.
3. Invoke the already constructed finalizer with the existing `results`. Assert
    the original intended fixture classification exactly:
    `claimed is True`, `completed is False`, `state == "failed"`, and
    `reason == "verification_defect"`. This proves the no-op did not steal or
    invalidate the finalizer's executing-session claim.
4. Retain `_StatusTransitionOnClaim` in the existing `claim-race` subcase. It is
    a real legal `executing -> blocked_needs_captain` service transition and must
    still advance the winning contract revision. Replace only the obsolete
    outer `pytest.raises(...crew_session_revision_conflict...)` expectation with
    the returned finalizer observation: `claimed is False`,
    `completed is False`, `state == "blocked_needs_captain"`, and
    `reason == "claim_lost"`. Keep the complete authoritative row assertions,
    including exact winner metadata, blocked coarse status, and unchanged
    facilitator.

Do not edit either helper outside this function, add a production no-op branch,
permit generic same-value CrewSession updates, add or remove a test, change a
parameter, skip/xfail, or weaken the direct stale-revision oracle. No production
fix is authorized.

### Final Mutation And Gate Binding

After this prompt handoff, the only implementation-tree mutation authorized is
the exact existing function above in
`tests/test_ad1126_verified_finalization.py`. Test name, parameters, and
collection cardinality remain unchanged. No production, other test, UI,
config/YAML, schema, dependency, tracker, archive, prompt, commercial, Git, or
GitHub mutation is authorized. Ignore AD-1129 prompts.

Run only that exact backend node with `-n 0`, then perform static scope,
cardinality, no-skip/xfail, no-op-observable, true-reassignment, claim-loss,
prompt-hash, and frozen-production/UI audits. Do not rerun the 535-test batch or
any broader Python selection. No UI byte is affected. If the directly affected
`WorkspaceFilesRail.test.tsx` gate is still pending because the failed backend
gate stopped the repair batch, run that file once with its default Vitest pool;
otherwise reuse its result for unchanged bytes and do not rerun it.

The Architect input hashes were main
`f6aa3d2401e41a1ad24d12858d285668450188087b9b845680ec422a4b84a04a`
and execution
`e09f72dbb572d51e4170787817acd780606f32cf9baff8aa4639a9a40697e9c9`.
This amendment is content-ready, but its post-edit SHA-256 values and byte sizes
must be computed mechanically over the raw files before Builder handoff because
this prompt-only session authorizes no command execution and exposes no file
hash/stat tool. Hash/size binding requires no content revision.

### Final Review Pass 1: Contract

**Verdict: APPROVED.** Same-state/no-progress service transition is the landed
idempotent contract: exact authoritative return, unchanged revision and row,
and no event. Generic CrewSession reassignment remains reserved.

### Final Review Pass 2: Safety

**Verdict: APPROVED.** A real competing service transition still advances the
authority. Direct stale CAS still raises; the finalizer correctly normalizes its
lost claim to an authoritative `claim_lost` observation instead of leaking an
internal CAS exception.

### Final Review Pass 3: Scope And Gate

**Verdict: CONTENT READY; MECHANICAL HASH/SIZE BINDING REQUIRED.** One existing
test body and one exact-node rerun are sufficient after 534/535 passed. No
production/UI change, 535-test rerun, closeout, Git, or GitHub action is
authorized.

## Final AD-1128 UI Gate Adjudication (2026-07-21)

**Verdict: PRODUCTION FOCUS TRAP CORRECT; TEST SIMULATION IS STALE.** This
section supersedes every earlier AD-1128 mutation allowlist, gate, handoff, and
closeout instruction where they conflict. Preserve the full live tree and
ignore AD-1129 prompts. The backend scoped evidence is complete: retain the
green 534/535 batch plus its corrected exact node and do not rerun any backend
test.

The sole remaining result is the directly affected
`WorkspaceFilesRail.test.tsx` gate: 21 collected, 20 passed, and one failed.
The failing existing test expects forward `Tab` from enabled Confirm to wrap to
Goal, but Confirm remains focused. The same run reports two React `act(...)`
warnings.

Architect input bindings before this amendment are:

```text
prompts/ad-1128-crew-session-ingress-dedup.md
  SHA-256 30230a1a65eb20e8e0b627baacc0ffd65f6905c23c77d4132efae8d5be76fa17

prompts/ad-1128-crew-session-ingress-dedup-execution.md
  SHA-256 f3a82812b24f504a24a21db2339add4d2e8a8914860f6d3318d120b6ba1514e0
```

After both prompt edits, mechanically compute each raw file's SHA-256 and byte
length and bind those four values before Builder handoff. This prompt-only
Architect pass authorizes no command execution and exposes no raw-file
hash/stat operation, so post-amendment hash/size binding is an explicit
mechanical step, not a content gap. Do not normalize or rewrite either prompt
while measuring it.

### Production Adjudication

Do not edit `ui/src/components/workspace/WorkspaceFilesRail.tsx`. The live
component already implements the exact required focus contract:

- opening stores the exact button and the mounted-dialog effect focuses Goal;
- the dialog is `role="dialog"`, `aria-modal="true"`, and programmatically
  focusable with `tabIndex={-1}`;
- its keydown handler intercepts `Tab`, computes the current enabled controls,
  excludes disabled controls, wraps last-to-first and first-to-last with
  `preventDefault()`, and keeps focus on the dialog when none are enabled;
- pending state disables every form control and moves focus to the dialog;
- Escape is prevented and stopped while open, but closes only when not pending;
- Cancel, successful submit, and non-pending Escape restore only a still
  connected opener.

Native `<dialog>.showModal()` is not authorized. The existing explicit trap is
the correct implementation for the rail-local overlay and jsdom contract.

The failing test does not establish a production defect. It mounts two
immediately resolving asynchronous rail fetch effects, then uses synchronous
`fireEvent.change`, direct `.focus()`, and synthetic `fireEvent.keyDown` without
first observing the fetched state or the enabled Confirm state. A jsdom
`keyDown` also does not perform browser Tab navigation. The two unobserved
fetch completions are the narrow, falsifiable source candidate for the two
`act(...)` warnings. Replace that timing-sensitive simulation with awaited
user interaction. If the exact correction below still fails or emits an act
warning, stop and return the output; do not infer permission to change the
component.

### Exact Test-Only Correction

After prompt hash/size handoff, the only mutable implementation-tree path is:

```text
ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
```

The reviewed component path is frozen. In the test file, authorize only:

1. Add the existing dependency import
    `import userEvent from '@testing-library/user-event';`.
2. Replace only the body of
    `wraps Tab forward and Shift+Tab backward across enabled dialog controls`.
3. Replace only the body of
    `pending Escape is inert and keeps focus on the dialog container`.

Do not edit a helper, another test body, a test name/parameter, setup/teardown,
mock shape, production file, or configuration. Do not add, remove, merge,
skip, xfail, or parameterize a test; collection remains exactly 21.

For the enabled-control wrap test:

1. Create `const user = userEvent.setup()` and render the expanded rail.
2. Before opening the dialog, await both stable resolved mount signals:
    `input-row-in1` and `artifact-row-art1`. These observations flush the two
    asynchronous fetch-driven state updates under Testing Library's `act`.
3. Open with `await user.click(...)`; await Goal focus.
4. Fill Goal and Expected Deliverable with `await user.type(...)`; fill Success
    Criteria with the same two lines using `{Enter}`. Do not use the synchronous
    `fillValidStartWorkForm()` helper in this test.
5. Await `workspace-start-work-confirm` becoming enabled before navigation.
6. Focus Goal with `await user.click(goal)`, then use `await user.tab()` through
    this exact enabled order, asserting each stop: Criteria, Deliverable, Retry,
    Cancel, Confirm.
7. From Confirm, one more `await user.tab()` must focus Goal. From Goal,
    `await user.tab({ shift: true })` must focus Confirm.

For the pending test:

1. Use `userEvent.setup()`, await the same two stable mount rows, open via
    `user.click`, fill the three fields via `user.type`, and await Confirm
    enabled before clicking it.
2. Keep the real deferred fetch. Await one request and await focus on the dialog
    container after pending disables all controls.
3. Send Escape with `await user.keyboard('{Escape}')`; the same dialog must
    remain mounted and focused.
4. Exercise both `await user.tab()` and `await user.tab({ shift: true })` while
    pending; each must leave focus on that same dialog container.
5. Resolve the deferred response inside async `act`, then await dialog removal
    before the test ends so no submit completion escapes the test's act scope.

Retain the separate existing tests for initial Goal focus, non-pending Escape
plus propagation/opener restoration, and Cancel/success opener restoration
unchanged. They remain independent contract oracles.

### One Authorized Gate

Run exactly once, with Vitest's default pool and no extra pool/worker flag:

```powershell
Set-Location D:\ProbOS\ui
npx vitest run src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
```

Green requires exactly 21 passed, zero failed, and zero React `act(...)`
warnings. On any failure or act warning, stop and hand the exact output to the
Architect. Do not patch, rerun, widen, run a backend node, run another Vitest
file, build, typecheck, lint, use Playwright/Vite/dev server, or perform a
confidence run.

After green, perform read-only audits only: prompt bindings match; only the
authorized import and two existing test bodies changed after handoff; the
component is byte-identical; test cardinality/name/parameters/skip state are
unchanged; AD-1129 was untouched; and no tracker/archive/Git/GitHub action
occurred. Hand back the mechanical prompt hashes/sizes and the exact Vitest
count/duration separately from the retained backend evidence.

### UI Review Pass 1: Contract

**Verdict: APPROVED TEST-HARNESS CORRECTION.** The live handler already owns
both Tab boundaries, pending fallback focus, guarded Escape, initial focus, and
connected-opener restoration. The revised test exercises those public DOM
effects through awaited browser-like interaction.

### UI Review Pass 2: Safety

**Verdict: APPROVED.** Enabled navigation proves both wrap directions across
the actual control order; pending navigation proves both directions cannot
escape when every control is disabled. Settling mount and submit effects keeps
React updates inside the test lifecycle without weakening an assertion.

### UI Review Pass 3: Scope And Gate

**Verdict: CONTENT READY; MECHANICAL HASH/SIZE BINDING REQUIRED.** Production
and backend evidence are frozen. One existing UI test file and one targeted
Vitest invocation are the complete remaining scope; failure is a hard stop,
not authorization for a production edit or rerun.

### Verified Against Live Codebase (2026-07-21 UI Adjudication)

| Claim | Live evidence |
|---|---|
| Goal and pending-container focus effects exist | `ui/src/components/workspace/WorkspaceFilesRail.tsx:102-110` |
| Opener restoration requires a connected button | `ui/src/components/workspace/WorkspaceFilesRail.tsx:202-216` |
| Escape and explicit enabled-control Tab trap exist | `ui/src/components/workspace/WorkspaceFilesRail.tsx:223-248` |
| Dialog semantics and keydown ownership are attached | `ui/src/components/workspace/WorkspaceFilesRail.tsx:442-451` |
| Two asynchronous mount fetches update component state | `ui/src/components/workspace/WorkspaceFilesRail.tsx:143-160` |
| Exact enabled-wrap and pending tests already exist | `ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx:200-267` |
| Stable mocked rows are `input-row-in1` and `artifact-row-art1` | `ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx:38-64`; `ui/src/components/inputs/InputsList.tsx:83-93`; `ui/src/components/artifacts/ArtifactList.tsx:90-96` |
| user-event is an installed test dependency | `ui/package.json:31-38` |

## Final AD-1128 Prompt Amendment And Code Review (2026-07-21)

**Verdict: APPROVED FOR LOCAL UNPUSHED COMMIT. No blocking or recommended code
finding remains.** This section supersedes the stale `Final AD-1128 UI Gate
Adjudication`, its production-frozen/test-defect conclusion, and every earlier
mutation, gate, tracker, archive, or closeout instruction where they conflict.
The complete live AD-1128 tree is frozen at the reviewed bytes. Broad validation
is deferred to the consolidated AD-1133 gate.

### Findings

**Required:** None.

**Recommended:** None.

**Residual validation risk:** The full backend suite, full UI suite, build, and
Playwright were deliberately not run under the Captain's batch-validation
directive. This is an explicit AD-1133 gate item, not an AD-1128 blocker.

### Corrected UI Root Cause And Exact Authorization

The prior adjudication is falsified and withdrawn. Three realistic/synthetic
harness attempts reproduced focus escape. A discriminating jsdom diagnostic
proved that the old comma-group `querySelectorAll()` returned enabled controls
in selector-group order (`button`, then `input`, then `textarea`), not the
required dialog document order.

The final component now enumerates `dialog.querySelectorAll('*')`, filters each
element with `.matches(focusableSelector)`, calls `preventDefault()` for every
owned `Tab`/`Shift+Tab`, and computes the next focus target with modular index
arithmetic. The pending no-control path still retains focus on the
programmatically focusable dialog container. The final test dispatches the
component-owned keydown handler at each exact focused control and proves:

```text
forward: Goal -> Criteria -> Deliverable -> Retry -> Cancel -> Confirm -> Goal
reverse: Goal -> Confirm
```

The exact focused node passed, the complete current `WorkspaceFilesRail` test
file passed 21/21, and editor diagnostics are clean. Authorize only these exact
bytes:

```text
ui/src/components/workspace/WorkspaceFilesRail.tsx
    SHA-256 9f5be91ae2feda65d68682f0d46df6a9ce3f022cc6bb7767a13b01da9ad2a998

ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
    SHA-256 74595698d786746fee41aded080176144976b3db6ee3e9a1bbbf25b8741b56c4
```

Any byte mismatch invalidates this approval. Do not restore the selector-list
implementation, substitute native jsdom Tab behavior, or reclassify this as a
test-harness-only defect.

### Findings-First Review Closure

| Prior finding / required surface | Final reviewed closure |
|---|---|
| Sole admission and reservation | `WorkItemStore` exposes one one-shot construction port; each reservation is context/task/store/generation-bound and one-use. `CrewSessionService` holds it across the requested-room reread, complete fresh scan 2, fresh semantic scores, and the one privileged parent insert. Generic create/template/update/transition/assign/claim/unassign and parent-mutating booking paths reject `crew_session_write_reserved` before their side effects. |
| Repair scheduling | Startup retains repaired ids, appends unseen recovery ids in source order, applies one global `crew_resume_scan_limit`, validates the complete selected batch before the first owner task, and schedules only active states through the existing idempotent `schedule()`. |
| Start Work auth | The existing `require_crew_scope` dependency guards only the Start Work route. Missing/wrong configured Bearer requests return the established 401 details before principal or service work; valid and empty-token local paths retain their existing contracts. |
| Exact provenance | One shared validator enforces lowercase Captain and agent creator/originator relations in principals, provisioning markers, initialization, every loaded session, repair, scoring, mutation, publication, and startup validation. Malformed provenance is re-raised and never skipped, normalized, fail-transitioned, or repaired beside. |
| Dedup and races | Bounded `limit + 1` scans fail closed; exact precedes independently capped semantic scoring; scorer output is exact finite `float`; service-local admission plus the store reservation closes local and cross-service scan-2 insertion races. Real barriers prove 2/3 equivalent callers produce one authority and one increment per duplicate, while an external winner during decomposition is resumed. |
| Compensation | Exact pre-session rollback requires marker-owned untouched parent/room authority plus requirement/child/booking proofs. The corrected parent predicate matches `description == marker.goal`. Drift or ambiguity leaves durable repair state; once session authority exists, provisioning never deletes it. |
| Cancellation and commit ambiguity | Every synchronous mutation runs in a held `to_thread` task; cancellation drains it and re-raises the first `CancelledError`. Parent-create and plan-commit ambiguity use authoritative reconciliation, and provisioning cancellation checkpoints the furthest proven phase without unsafe compensation. |
| Finalizer compatibility | Generic reassignment remains reserved; a same-state service transition is an exact no-op with unchanged revision/row/time/events; a real competing service transition advances authority and the finalizer reports `claim_lost` after reread. |
| UI accessibility | Initial Goal focus, guarded Escape, pending container focus, connected-opener restoration, exact document-order forward/reverse containment, one-request ownership, bounded errors, no emoji, and passive GET-only viewing are all present. |
| Test realism and scope | Persistence, reservation, auth, provenance, scheduling, race, and compensation tests use real SQLite-backed stores and the real claimed port with narrow delegating barriers; no MagicMock or raw-SQL authority exists at those boundaries. The AD-1128 backend module contains exactly 65 test definitions with no skip/xfail, and the current UI file contains exactly 21 tests. No AD-1129+ behavior was added. |

### Accepted Evidence

- Backend changed-surface batch: 535 collected, 534 passed, one failed; the
    exact corrected node then passed. The unchanged 534 plus the corrected node
    reconcile all 535 reviewed nodes.
- The earlier 177-node changed surface and its exact corrections are reconciled.
- Current targeted UI: 21/21 `WorkspaceFilesRail` on the authorized hashes.
- Prior UI neighborhood: 23/23 `WorkspaceFilesRail` plus `TodosList`.
- Editor diagnostics, diff checks, and static scope audits are clean.
- Net-new backend test accounting is `N=65`.
- No broad backend suite was run by Captain directive. Full backend/UI/build/
    Playwright validation remains deferred to AD-1133.

### Prompt Bindings And Closeout

Architect input bindings before this amendment were main
`af59778ad27788a874e747c83da9b67d0bfd8bf0b179bf85c5be6533c0d79deb`
and execution
`902337edca865d881f4419c7aa80724e734179b0b3c1ee267d50fa451b0b6ac8`.
This no-command Architect session cannot mechanically compute raw post-edit
hashes or byte sizes. Before the local commit, compute SHA-256 and byte length
for both amended prompts and report all four values; hashing is measurement
only and authorizes no content revision.

Approve one local commit of the frozen reviewed AD-1128 actual diff plus these
two amended active prompts, with exact message
`AD-1128: add unified CrewSession ingress (closes #1047)`. Do not update
`PROGRESS.md`, `docs/development/roadmap.md`, or `DECISIONS.md`; do not archive
the prompts; do not push or mutate GitHub. Tracker/archive work and the broad
validation gate remain deferred to AD-1133.

### Final Prompt Review Pass 1: Contract

**Verdict: APPROVED.** The amendment corrects the falsified UI adjudication and
freezes the verified document-order focus implementation without changing the
unified ingress, exact dedup, reconstruction, retry, or sole-runner contracts.

### Final Prompt Review Pass 2: Safety

**Verdict: APPROVED.** All prior required findings are closed at their owning
boundaries. Accepted evidence is reported without pretending the 535-node batch
was rerun after the exact correction, and broad validation remains explicit.

### Final Prompt Review Pass 3: Scope And Closeout

**Verdict: APPROVED.** Only the two active prompts changed in this Architect
pass. Production/tests/UI are frozen at the reviewed bytes; AD-1129+, trackers,
archive, validation commands, push, and GitHub mutation remain excluded. AD-1128
is approved for one local unpushed commit with the consolidated broad gate
deferred to AD-1133.
