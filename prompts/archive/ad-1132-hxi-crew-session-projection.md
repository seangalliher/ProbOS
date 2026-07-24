# AD-1132: HXI CrewSession Projection

**Status:** READY after three final prompt-only reviews
**Issue:** #1051
**Type:** Enhancement; build AD-1132 only
**Required build base:** `57e94656b5834ff59bc02e93140137c94f5aa959`
**Expected origin/main:** `e33955a8f7aa6810e8f2d2e2db3a329fadb8e4da` (intentional local divergence)
**Planning ceilings:** local AD-1131 / BF-673
**Execution authority:** `prompts/ad-1132-hxi-crew-session-projection-execution.md`
**Prompt binding:** the execution prompt embeds the final SHA-256 of this file. Freeze both prompt hashes and byte lengths before coding; combined size must remain below 50,000 bytes.

**Repair standing order:** apply one batched repair to the existing AD-1132
candidate. Preserve every prior projection/privacy/a11y/meaningful-motion/
reduced-motion/legacy/no-AD-1133 contract unless tightened below. Complete all
repair code and tests before one backend batch, six targeted Vitest files, and
one production UI build.

## Decision

Extend the existing `GET /api/crew-tasks/{parent_id}` and `GET
/api/threads/summaries` surfaces. Do not add an endpoint. A CrewSession parent
gets a strict, bounded, secret-minimizing projection built only from:

1. a `CrewSessionContract` returned by `CrewSessionService.get_session()` and
   therefore validated against its parent WorkItem, status projection,
   facilitator assignment, recovery invariant, and unique bound room;
2. absent synthesis metadata, or a separately validated
   `CrewSynthesisMetadata`; and
3. a bounded set of direct child `WorkItem` objects loaded by `parent_id`.

For a non-session parent, `GET /api/crew-tasks/{parent_id}` must return exactly
the existing top-level `parent`, `children`, and `count` keys and preserve the
existing full AD-862 values. For a CrewSession parent, return exactly
`{"session": <CrewSessionDetailProjection>}`. Do not return the generic parent
or child serializers on that branch: they include raw metadata and are not the
HXI projection.

Every generic thread summary remains exactly the four current keys
`outputs`, `steps_total`, `steps_done`, and `topic`. A valid CrewSession member
adds one `session` key containing the compact summary below. One malformed or
inconsistent CrewSession member degrades to that member's four-key legacy
summary only; it must not fail or suppress any other member.

The existing AD-1128 `POST /api/threads/{thread_id}/start-work` response adds
the same detail projection under required key `session`. Existing ingress
status/error mapping remains unchanged; a post-admission projection conflict
is the stable 409 described below.

## 1. Pure Backend Projection

Add `src/probos/crew_session_projection.py`. It imports the existing strict
CrewSession and synthesis models plus `WorkItem`, but no runtime, router,
store, artifact service, notification service, event bus, trust service,
clock, or configuration.

Expose fully annotated pure APIs equivalent to:

```python
def validate_synthesis_metadata(value: object) -> CrewSynthesisMetadata: ...

def build_crew_session_detail(
    *,
    session: CrewSessionContract,
    synthesis: CrewSynthesisMetadata | None,
    children: Sequence[WorkItem],
) -> CrewSessionDetailProjection: ...

def build_crew_session_summary(
    detail: CrewSessionDetailProjection,
) -> CrewSessionSummaryProjection: ...
```

Use immutable typed projection values with one explicit wire serializer. No
projection API accepts raw parent metadata. `validate_synthesis_metadata`
must either return the strict existing model or raise the module's single
bounded conflict error; it must never return or log the raw value.

Validate at this boundary:

- at most 1,000 direct children; routers query `limit=1001` and reject the
  overflow rather than silently truncating;
- every child is a real `WorkItem`, has `parent_id == session.task_id`, has a
  unique bounded id, and uses a known `WorkItemStatus` value;
- `done` requires synthesis; every other state requires synthesis absence;
- for `done`, synthesis `result_artifact_id` equals session
  `result_artifact_id`, synthesis `provenance_ref` equals session `result_ref`,
  and that ref occurs in session `evidence_refs`;
- no nonterminal or failed projection invents result or verification data.

Normalize every validation/type/ref/child failure to one error code:
`crew_session_projection_invalid`. Do not expose a Pydantic error body, raw
metadata value, result body, provenance body, or child metadata.

### 1.1 Exact detail wire shape

`CrewSessionDetailProjection` serializes exactly:

```text
task_id: string
thread_id: string
goal: string
origin: "captain" | "agent"
originator_id: string
facilitator_id: string
owner_ids: string[]
state: "discussing" | "executing" | "verifying" |
       "blocked_needs_captain" | "done" | "failed"
revision: integer
success_criteria: string[]
expected_deliverable: string
timestamps:
  created_at: number
  transitioned_at: number
  started_at: number | null
  first_result_at: number | null
  verified_at: number | null
  completed_at: number | null
progress:
  total: integer
  done: integer
  failed: integer
  active: integer
  active_child: null | { id, title, status, owner_id }
last_result_summary: string
blocker: null | {
  reason: string
  since: number
  duration_seconds: number
  action: "retry_start_work"
}
result: null | {
  artifact_id: string
  content_hash: lowercase SHA-256
  result_ref: lowercase SHA-256
  evidence_refs: lowercase SHA-256[]
}
verification: null | {
  verifier_agent_id: string
  confidence: number
  critique: string
  accepted_count: integer
  total_count: integer
  convergence_rounds: integer
}
duplicate_resume_count: integer
```

`failed` counts direct children whose status is `failed` or `cancelled`.
`done` counts exact `done`; `active` counts every remaining direct child.
Select at most one `active_child` deterministically by status rank
`in_progress`, `review`, `blocked`, `scheduled`, `open`, `draft`, then
`priority`, `created_at`, and `id`. The active child contains no description,
dependencies, tags, capabilities, steps, verification, schedule, metadata,
token values, or provenance.

`blocker` exists only for `blocked_needs_captain`; its duration is the strict
persisted `blocked_duration_seconds` and its action is the fixed literal above.
`result` and `verification` exist only for `done`. `content_hash` comes from
validated synthesis `result_content_hash`; `result_ref` comes from the
cross-checked session/synthesis provenance ref. Include no synthesis token
counts or producer field.

### 1.2 Exact compact summary

The `session` member added only to valid CrewSession thread summaries is:

```text
task_id: string
thread_id: string
goal: string
state: exact six-state value
facilitator_id: string
owner_ids: string[]
progress: { total, done, failed, active }
last_result_summary: string
blocker: null | { reason, since, duration_seconds }
needs_attention: boolean
result_artifact_id: string | null
verified_at: number | null
```

`needs_attention` is true exactly for `blocked_needs_captain`. The compact
summary omits active-child detail, criteria, deliverable, critique, confidence,
evidence refs, originator, revision, and all raw metadata.

### 1.3 Forbidden projection content

Neither projection may contain raw WorkItem/session/synthesis/recovery
metadata; free-form result or provenance bytes; secret/token/key/password
fields; descriptions; full child lists; AD-1131 delivery ids, rows, outbox
state, notification fields, metrics, or event payloads; trust effects/receipts;
or attachment bytes. Add a recursive sentinel test over both projections.

## 2. Existing Router Extensions

### 2.1 Crew-task detail

In `src/probos/routers/crew_tasks.py`, preserve the store-unavailable 503 and
missing-parent 404 checks before branching.

- If `parent.work_type != "crew_session"`, execute the existing AD-862 path
  unchanged and return its exact legacy shape.
- If it is a CrewSession, require `runtime.crew_session_service`; absence is
  503 without changing the existing store/missing-parent behavior.
- Call `service.get_session(parent.id)`. `None`, any service `ValueError`,
  malformed/present synthesis metadata, child overflow, or projection mismatch
  maps to HTTP 409 with exact detail `crew_session_projection_invalid`.
- Validate `crew_synth` only when that key is present. Load direct children
  with `parent_id=parent.id, limit=1001`, build the pure projection, and return
  exactly `{"session": detail.to_wire()}`.
- Log only parent id plus bounded internal error code and that a stable 409 is
  returned. Do not log metadata, goal, result, blocker, critique, refs, or ids
  other than the parent id.

Do not dereference AD-861 provenance for the CrewSession branch. The existing
generic AD-862 provenance behavior remains unchanged.

### 2.2 Thread summaries

In `src/probos/routers/threads.py`, build each four-key legacy summary first.
For a member whose bound WorkItem has `work_type == "crew_session"`, attempt
the same service-validation, synthesis-validation, direct-child load, detail
build, and compact-summary build inside that member's bounded error boundary.
On success:

- retain the four legacy keys;
- set legacy `topic` to the validated session goal; and
- add only `session: summary.to_wire()`.

If the service is absent or this one member is invalid/inconsistent, return the
already-built four-key entry unchanged. Log only thread id, parent id, bounded
error code, and that the member fell back. Never fail the batch.

### 2.3 Start Work response

After `CrewSessionService.open_or_resume()` returns, call
`service.get_session(result.parent_id)` and require its task/thread/state to
match the open result. Load that returned parent and its direct children,
validate any synthesis metadata, and build the detail projection. Add `session`
to the existing response; preserve every existing key and the current
404/409/422/503 mapping. Projection inconsistency maps to 409
`crew_session_projection_invalid`. Do not call another mutation endpoint and
do not create a second session, room, or task.

## 3. Typed UI State and Fetches

Move the Crew task/session wire types out of
`CrewCollaborationPanel.tsx` into `ui/src/store/types.ts`. Add exact types for
the legacy AD-862 tree, detail projection, compact summary, room-summary union,
Start Work result, and one-shot rail commands. Avoid open index signatures on
the new session projection.

In `ui/src/store/useStore.ts`, add clone-on-write state only:

```text
crewSessionsByParent: ReadonlyMap<parent_id, CrewSessionDetailProjection>
crewSessionSummariesByThread: ReadonlyMap<thread_id, CrewSessionSummaryProjection>
hydrateCrewSession(parent_id, projection)
hydrateCrewSessionSummaries(record keyed by thread_id)
```

Each action constructs a new `Map`; callers cannot mutate the stored map or
projection through the declared types. These are explicit one-shot GET/POST
response hydration actions and the AD-1133 live-update target. Do not add a
WebSocket handler, event reducer branch, timer, interval, poller, subscription,
background fetch, persistence key, or automatic invalidation.

Hydration is fail-closed: detail stores only when `projection.task_id` equals
the supplied parent key; summary hydration drops, without re-keying, any entry
whose `projection.thread_id` differs from its outer thread key. Valid siblings
still hydrate. Tests prove rejected values appear under neither key.

In `ui/src/components/sidebar/threadApi.ts`, type the additive session summary
and add a strict GET wrapper for `/api/crew-tasks/{parent_id}` that distinguishes
success, 404/empty, and error so the panel can render loading/empty/error/cached
retry states. Keep generic summary keys exact.

The detail wrapper accepts `session` only when `session.task_id` equals the
requested parent. Summary parsing accepts additive `session` only when its
`thread_id` equals the outer response-record key; mismatch degrades that member
to its validated four-key generic summary without suppressing valid siblings.

The legacy detail parser is equally strict. Validate the exact key sets and
declared field types of `LegacyCrewWorkItemView`, `LegacyCrewChildView`, and
`LegacyCrewVerdict`, not merely the three tree keys, recordness, and count.
WorkItem strings are `id/title/description/work_type/status/created_by`; finite
numbers are `priority/created_at/updated_at/actual_tokens/trust_requirement`;
nullable finite numbers are `due_at/estimated_tokens/ttl_seconds`; nullable
strings are `parent_id/assigned_to/template_id`; `depends_on`,
`required_capabilities`, and `tags` are string arrays; `metadata`,
`verification`, and `schedule` are non-array records; and `steps` is an array
of non-array records. A child has exactly those fields plus `verdict` and
`rounds`. `verdict` is null or exactly `accepted:boolean|null`,
`confidence:finite number|null`, `critique:string`, and
`verifier_agent_id:string`; `rounds` is a finite number or null. `count` is a
non-negative integer equal to child length. Replace the partial legacy test
fixture with a complete real AD-862 wire fixture, then reject missing or
additive parent, child, and verdict keys and representative wrong nested field
types. Never return a partial/additive legacy object as success.

In `ui/src/components/workspace/todosApi.ts`, consume the shared Start Work
request/result types and require a valid returned `session` whose task/thread
ids equal the returned parent/thread ids. Keep the one existing POST.

In `ui/src/components/artifacts/artifactApi.ts`, add only the missing metadata
wrapper for existing `GET /api/artifacts/{artifact_id}`. It returns a typed
`ArtifactView` or `null`; it never fetches content or mutates/pins anything.

## 4. HXI Room Projection

### 4.1 CrewCollaborationPanel

Enrich the existing `CrewCollaborationPanel`; do not create another card,
dashboard, sidebar, viewer, or route. It accepts owning thread and parent ids,
a stable programmatic session-band focus target, and typed callbacks for retry
blocked work and opening the result artifact. Retry also carries the connected
invoking button for cancel focus restoration.

On parent change, perform one GET through the typed wrapper. Hydrate the
parent-keyed store map once on valid session success. Never poll. If a Start
Work response already hydrated this parent, render the cached value
immediately while the one GET refresh runs.

Subscribe reactively to `state.crewSessionsByParent.get(parentId)`, not an
imperative mounted-cache snapshot. Assign the current `{threadId,parentId}` ref
synchronously every render. Each load captures it plus request generation and
rechecks both after every `await` before hydrate, callback, or state mutation.
Test switching room/parent and resolving the old deferred response before
effect cleanup; stale completion mutates nothing.

Render all six exact states with `data-state` and meaningful HXI semantics:

- `discussing`: low-amplitude breathing boundary;
- `executing`: active progress pulse tied to the active child;
- `verifying`: bounded scan/sweep over the verification region;
- `blocked_needs_captain`: attention pulse plus the explicit retry action;
- `done`: settled check glyph and static verified result;
- `failed`: static stopped/failure glyph and no false activity.

All icons are inline geometric SVG, `fill="none"`, stroke width 1.5, rounded
caps; no emoji or Unicode icon substitutes. A `prefers-reduced-motion: reduce`
rule removes animation and transition while preserving state color, label,
glyph, and focus visibility.

The panel is an unframed room band, not a card containing cards. Use stable
min/max dimensions and a responsive internal grid: desktop columns and local
host-width stacking via `ResizeObserver` or container query, with viewport
fallback. Behavioral tests drive 420px and 320px hosts, including an expanded
sibling rail, and assert stacked metadata/stable dimensions/no overlap; source-
text media-query assertions are insufficient. Long goal, criterion,
deliverable, blocker, result, owner, and critique use `min-width: 0`,
`overflow-wrap: anywhere`, and normal white-space; no viewport-scaled fonts or
negative letter spacing.

Show goal, state, facilitator/owners, criteria, deliverable, progress and one
active child, last result, blocker, duplicate resumes, result/evidence, and
verification when applicable. The blocked action has an explicit accessible
name and emits the typed retry callback. The final artifact action emits the
artifact callback. Do not render raw hashes as the primary label; evidence refs
may be shown in a bounded disclosure with wrapping and accessible labels.

State handling is explicit:

- initial uncached load: stable placeholder with `aria-busy="true"`;
- empty/404: stable empty state, no alert;
- error with no cache: `role="alert"` plus keyboard-focusable Retry;
- error with cache: retain cached content, show a bounded stale/error alert and
  Retry; never blank the panel;
- retry performs one GET and cannot overlap itself.

Preserve the existing generic AD-862 tree rendering for a legacy detail
response. Session rendering uses only the sanitized projection.

### 4.2 Existing task-bound room layout

In `ProfileChatTab.tsx`, keep the outer `display:flex; flex-direction:row`
container and the primary chat column's `flex:1; minWidth:0; minHeight:0`
contract. Mount `CrewCollaborationPanel` as an unframed child of that existing
chat column only when the active workspace thread has a non-null `task_id`.
Keep `WorkspaceFilesRail` as the existing sibling. Do not nest or replace the
rail, transcript, meeting gallery, header, or composer.

Use parent-owned, typed one-shot command values with monotonically increasing
request ids to relay panel commands to the one existing rail:

- retry only when projection `thread_id` still equals the mounted active room;
- artifact open only under the same ownership check; and
- changing active thread invalidates outstanding command values.

Also accept one typed `onSessionBound` callback from the rail. When a matching
Start Work result is still owned by the mounted room, retain its parent id in
`ProfileChatTab` and use `workspaceThread.task_id ?? boundParentId` as the panel
parent. Clear the binding on active-room change. This makes a newly started
taskless workspace room render its already-hydrated session immediately; it
does not PATCH the thread or trigger another fetch/mutation from the profile.

Retain the binding as `{threadId,parentId}`, never a bare parent. Update the
render-current room ref synchronously each render; every async/deferred focus
completion checks that token after each await/scheduling boundary before
command, binding, callback, focus, or state mutation. Room change invalidates
commands/binding immediately, not only in effect cleanup.

No command dispatch performs network I/O in `ProfileChatTab`.

### 4.3 Existing Start Work dialog

Extend `WorkspaceFilesRail` props with the typed one-shot commands. A matching
retry command expands the existing rail if needed, pre-fills its existing Goal,
Success Criteria, and Expected Deliverable controls from the projection, sets
`retry_blocked=true`, opens the existing accessible dialog, and focuses Goal.
It does not submit until the Captain activates the existing confirmation.

Capture the connected blocked-retry button as the dialog opener; cancel/Escape
restores it. Do not substitute the ordinary Start Work opener or `null`.

Keep the ordinary Start Work 409 retry test distinct from blocked-session
focus tests. After the first 409, assert the dialog remains open and focus is
still inside it. A second successful confirmation closes the dialog and
restores focus to the still-connected ordinary Start Work opener. Keep blocked
cancel restoration and successful blocked-retry session-band focus as separate
tests; neither may stand in for this ordinary-opener error/retry contract.

One confirmation still performs exactly one call to the existing
`startRoomWork()` POST. On success, only when both the request generation is
current and `result.thread_id == mounted threadId`:

- bind `result.parent_id` locally;
- call `hydrateCrewSession(result.parent_id, result.session)` once; and
- notify the room owner's typed `onSessionBound` callback once; and
- close the dialog and restore focus.

A stale room, different returned authority room, or old generation must not
bind or hydrate the mounted room. Preserve pending Escape/focus trap, validation,
bounded errors, and retry behavior. Do not add another POST/PATCH/DELETE route.

Tag local started-parent state with its owning thread and update a current-room
ref during render. Initial room GETs, existing async refresh completions, Start
Work, artifact lookup, callbacks, focus, and all state writes recheck room plus
generation after every `await`; keep the existing 5-second cadence unchanged.
Tests switch rooms and resolve deferred old-room responses before cleanup with
zero stale mutation. Successful retry that removes its trigger focuses the
owned session band after hydration renders; test separately from cancel focus.

### 4.4 Existing artifact rail/viewer

A matching artifact command expands the existing rail and opens its current
`ArtifactViewer`. Prefer metadata already in the rail's thread artifact list.
If absent, perform only existing `GET /api/artifacts/{artifact_id}` through the
new metadata wrapper, require returned `id` and `thread_id` to match the command
and mounted room, add that one typed metadata row locally, then select it.
Missing/mismatched/error metadata produces a bounded `role="alert"` with Retry
and does not fetch content until a valid ArtifactViewer is mounted.

Apply the room check to preloaded rows too: reject a matching-id artifact whose
`thread_id` differs from the current rail before selection. Derive selection
only from current-thread rows, so a cross-room row cannot mount the viewer or
start its content GET.

Do not create another viewer, drawer, browser tab, pin, upload, or artifact
mutation.

### 4.5 Chats summaries and Needs You

Hydrate the thread-keyed session-summary map once from the existing summary
GET. For a valid CrewSession row:

- use `session.goal` as the primary row title/topic instead of generic room
  text;
- show exact state, facilitator/owner context, compact progress, last result,
  and result artifact/verified time when present;
- mark blocked rows as needing Captain attention; and
- in the Needs You filter, include both blocked sessions and the existing
  unjoined agent-created rooms, with blocked sessions first and stable recency
  ordering within each priority.

Use a numeric priority (`blocked=2`, existing unjoined alert=1, ordinary=0)
before the existing selected sort. Generic rows retain their existing display,
filter, and four-key summary behavior. Long session goals wrap; do not restore
single-line ellipsis for the session title.

Use one shared compact session-context renderer in both session-backed row
branches, including a one-owner/generic-shaped 1:1 and a group row. Include
state, facilitator, owners, total/done/failed/active progress, last result,
result artifact, and verification context (`verified_at`) when present. Generic
non-session 1:1 DOM, labels, display, sort, filter, and click behavior remain
exact; test all three.

Session-only markup must not leak into either generic branch. Add attention
attributes, session wrappers, `minWidth:0`, and session title wrapping only in
session-backed 1:1/group branches. Generic 1:1 and generic group rows retain
their original attributes and row/title style objects exactly: no
`data-needs-attention`, no session wrapper, no session-only `minWidth`, and no
session-conditioned title style. Component tests assert the attribute is
absent and the original row/title styles are unchanged for both generic forms.

The legacy generic room badge remains unchanged, including its U+2713
checkmark. Session-backed rows must not render U+2713 through that badge:
omit it there or use plain text/an inline stroke SVG. Exercise a session
summary with nonzero `steps_total`/`steps_done` and assert its row contains no
U+2713; separately retain the generic legacy-badge regression.

Treat `verified_at=0` as present session data. Session rendering checks
`verified_at !== null` and uses a session-specific formatter that accepts epoch
zero. Do not change generic `fmtAgo` or its legacy behavior. Add a session-row
test with `verified_at: 0` and assert the verification/epoch text renders.

## 5. Read-Only and Refresh Boundaries

A passive task-bound room mount may issue GETs only. Assert zero POST, PATCH,
or DELETE across the panel, profile mount, and rail until the Captain confirms
Start Work or an existing unrelated control is explicitly activated.

Do not change the existing Artifact and Todo 5-second polling in
`WorkspaceFilesRail`. Add no CrewSession polling. AD-1133 owns live WS/SSE or
other refresh transport and updates the two new store maps later.

### 5.1 Independent repair conflicts

In `tests/test_ad1132_crew_session_api.py`, independently test:

1. synthesis `provenance_ref` differing from session `result_ref` -> exact 409.
  Isolate equality with distinct refs A/B: session `result_ref=A`, synthesis
  `provenance_ref=B`, and session `evidence_refs` contains both A and B. Assert
  those three setup facts before calling the route, keep artifact/hash inputs
  otherwise matching, then assert 409. Because B passes evidence membership,
  the failure discriminates only provenance/result-ref equality;
2. session `result_ref` absent from `evidence_refs` -> exact 409; and
3. Start Work admission succeeding, followed by authoritative reload/detail
   projection conflict -> exact 409 `crew_session_projection_invalid`, one
   admission mutation, and no second mutation.

Do not combine these with the existing artifact-id mismatch. Exercise the real
route/final projection boundary so each test discriminates its own invariant.

## 6. Tests After Coding

All production and test edits must be complete before any pytest, Vitest, or
build command.

### 6.1 Backend

Add `tests/test_ad1132_crew_session_api.py` using real bounded models and real
store seams where applicable. Cover named behaviors:

1. parameterized detail for all six states and exact top-level/session keys;
2. direct-child total/done/failed/active counts and deterministic one active
   child, including nested-grandchild exclusion;
3. blocked reason/since/duration/fixed `retry_start_work` action;
4. done artifact/hash/ref/evidence and verification fields;
5. terminal missing/malformed/artifact-mismatched synthesis -> stable 409;
6. the three independent provenance/evidence/post-admission conflict tests in
  Section 5.1;
7. malformed contract/status/room/child and child overflow -> stable 409;
8. existing missing parent 404, unavailable workforce 503, and session-service
  unavailable 503;
9. non-session AD-862 response exact keys and values;
10. generic thread summary exact four keys;
11. valid compact summary uses actual goal and exact bounded keys;
12. mixed summary batch where one invalid session falls back to its legacy
    entry while valid/generic siblings remain;
13. Start Work returns matching detail projection without a second mutation;
14. recursive forbidden/sensitive/AD-1131-field sentinel scan.

Run the unchanged `tests/test_ad862_crew_tasks_api.py` in the same
changed-surface batch. Minimally update only the thread-route fixtures and
additive success assertions in
`tests/test_ad1128_crew_session_ingress_dedup.py`: its live `_thread_api_app`
runtime currently omits `work_item_store`, and its auth recorder implements
`open_or_resume` but not the newly required authoritative `get_session` seam.
Provide real bounded parent/contract/store inputs while preserving every
existing auth, validation, conflict, and ingress assertion. Do not rewrite the
AD-1128 service behavior to make AD-1132 pass.

### 6.2 Targeted Vitest

Use the existing test files where named and add only focused AD-1132 files:

- `ui/src/store/__tests__/crewSessionProjection.test.ts`: both clone-on-write
  one-shot hydration actions, both key/payload mismatch rejections, valid
  sibling isolation, and no WS/event mutation path;
- `ui/src/components/sidebar/__tests__/threadApi.crewSession.test.ts`: typed
  detail/summary ownership mismatches, strict complete AD-862 legacy nested
  parsing, and generic/session shapes;
- `ui/src/components/crew/CrewCollaborationPanel.test.tsx`: six states,
  progress, blocker/result commands, loading, empty, error, cached retry,
  reactive external hydration, pre-cleanup stale response, 420/320 host-width
  stacking, reduced motion, wrapping, no emoji, aria-busy/alerts/focus;
- `ui/src/components/chats/__tests__/ChatsPanel.test.tsx`: actual goal and
  shared one-owner/group session context, blocked-first Needs You ordering,
  exact generic non-session 1:1/group markup and styles, session nonzero-step
  U+2713 exclusion with unchanged generic badge, and `verified_at=0` rendering;
- `ui/src/components/profile/__tests__/ProfileChatTab.crewSession.test.tsx`:
  task-bound mount/ownership, thread-tagged taskless binding, pre-cleanup room
  switch, separate successful blocked-retry session-band focus, and passive
  zero writes;
- `ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx`: retry
  prefill/blocked-cancel focus, ordinary 409 focus containment then successful
  retry/opener restoration, matching/stale Start Work and pre-cleanup room
  switching, exactly one POST, cross-room preloaded-artifact rejection,
  metadata GET/open/error retry, expanded-rail narrow host, and passive zero
  writes.

Run targeted Vitest with its normal thread pool; do not set a custom pool or
worker count. Then run production `npm run build` because store and wire types
change. Run no Playwright; DOM/component evidence is final for AD-1132.

## 7. Exact Allowlist

Production:

```text
src/probos/crew_session_projection.py
src/probos/routers/crew_tasks.py
src/probos/routers/threads.py
ui/src/store/types.ts
ui/src/store/useStore.ts
ui/src/components/sidebar/threadApi.ts
ui/src/components/artifacts/artifactApi.ts
ui/src/components/crew/CrewCollaborationPanel.tsx
ui/src/components/chats/ChatsPanel.tsx
ui/src/components/profile/ProfileChatTab.tsx
ui/src/components/workspace/todosApi.ts
ui/src/components/workspace/WorkspaceFilesRail.tsx
```

Tests:

```text
tests/test_ad1132_crew_session_api.py
tests/test_ad1128_crew_session_ingress_dedup.py
ui/src/store/__tests__/crewSessionProjection.test.ts
ui/src/components/sidebar/__tests__/threadApi.crewSession.test.ts
ui/src/components/crew/CrewCollaborationPanel.test.tsx
ui/src/components/chats/__tests__/ChatsPanel.test.tsx
ui/src/components/profile/__tests__/ProfileChatTab.crewSession.test.tsx
ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
```

Permit only these frozen-SHA-256 `??` dirty-tree exceptions; they are never
AD-1132 edit/stage/commit paths:

- `prompts/ad-1133-live-crew-session-thread-refresh.md` = `0199b70bdad6a578239cc99d6003d1703a1c1b397b83b8826850509cb8768ff4`
- `prompts/ad-1133-live-crew-session-thread-refresh-execution.md` = `d556b22de5d66759d06ae53a1e392f79a30096b6b3c938f49ef7bee71ad2191d`

Before/after staging, hard-stop on status/hash drift, staged inclusion, or
another dirty path. Architect-approved production/test expansion may name only
a directly affected existing file/test, never helper/config/tracker/archive/
AD-1133.

## 8. What This Does Not Change

- No AD-1131 delivery module, notifications, outbox, task-completion notifier,
  metrics, startup/shutdown wiring, event payload, or tests.
- No new endpoint, EventType, schema/table/migration, configuration,
  `config/system.yaml`, dependency, trust update, metric, or notification.
- No raw metadata/provenance/result bytes, secret-bearing content, commercial
  code, pricing, or private-repo material.
- No new dashboard, landing page, sidebar, nested card stack, artifact viewer,
  drawer, workstation, route, or app surface.
- No WS/SSE/live handler, polling, timer, subscription, background task, or
  AD-1133 transport. Existing Artifact/Todo polling stays byte-for-behavior.
- No full backend suite, full Vitest, Playwright, tracker edit, decision
  log, prompt archive, push, or GitHub mutation. AD-1133 owns the consolidated
  end gate and closeout.

## 9. Acceptance Criteria

- Existing endpoints extend safely; non-session detail and generic summary
  shapes are exact regressions, and invalid summary members isolate locally.
- CrewSession detail/summary/Start Work expose only the exact bounded typed
  projections and stable 409 conflict behavior above.
- All six states, meaningful/reduced motion, wrapping, responsive layout,
  loading/empty/error/cached retry, aria-busy, alerts, keyboard focus, and
  inline stroke SVG/no-emoji rules have component coverage.
- Passive room mount performs zero POST/PATCH/DELETE; explicit Start Work
  performs exactly one POST and hydrates only its still-owned mounted room.
- Detail/summary/store keys fail closed, stale pre-cleanup room responses cause
  zero mutation, retry focus follows the two explicit outcomes, session context
  is complete in both row branches, and 420/320 hosts stack without overlap.
- Provenance-ref mismatch, missing evidence membership, and post-admission
  Start Work projection conflict each have independent backend route coverage.
- Legacy detail parsing validates every nested AD-862 field/key contract;
  generic chat markup remains exact, session rows omit U+2713, epoch-zero
  verification renders, and ordinary 409 retry focus remains dialog-contained
  before successful connected-opener restoration.
- Final artifacts open only through the existing rail and ArtifactViewer;
  missing metadata uses only the existing artifact metadata GET.
- The exact allowlist holds and AD-1131/AD-1133/excluded surfaces are untouched.
- Local commit subject after three implementation reviews is exactly
  `AD-1132: add HXI CrewSession projection (closes #1051)` and remains unpushed.
- Verify all changes comply with the Engineering Principles in .github/copilot-instructions.md.

## Verified Against Codebase (2026-07-22)

Live candidate anchors: `crew_tasks.py:123-146` and `threads.py:190-213,
283-297,319-401` own the three backend projections; `threadApi.ts:227-268`
owns strict parsing; `types.ts:590-632` declares the full AD-862 legacy shape;
`ChatsPanel.tsx:242-269,440-550` owns badge/time and both row branches;
`WorkspaceFilesRail.test.tsx:490-519` is the ordinary 409 retry seam; and
`ProfileChatTab.crewSession.test.tsx:233-260` separately owns session-band
focus. Existing allowlisted repair anchors for keyed hydration, reactive room
ownership, responsive layout, and artifact selection remain as previously
verified against required base `57e94656b5834ff59bc02e93140137c94f5aa959`.