# AD-1133: Live CrewSession and Thread Refresh

**Status:** SECOND FINAL-REVIEW AMENDMENT APPLIED 2026-07-23; CONDITIONAL ON MECHANICAL HASH/SIZE REFRESH
**Issue:** #1052
**Type:** Enhancement; build AD-1133 only
**Required build base:** `d8965f9b3038f9d5c98b7049ab990e43c99c9f80`
**Planning input only:** local `57e94656b5834ff59bc02e93140137c94f5aa959` plus the uncommitted AD-1132 candidate
**Numbering:** current local committed chain reserves AD-1133 after AD-1132; BF ceiling is BF-673; allocate no AD/BF
**Execution authority:** `prompts/ad-1133-live-crew-session-thread-refresh-execution.md`
**Freeze binding:** this pair remains bound to committed AD-1132 at `d8965f9b3038f9d5c98b7049ab990e43c99c9f80`. Reviewed inputs were main `5264987d0f31a34fd799f34c3f7785bf38a3c35f16e9339c6faeae7f15b9492b` (39,037 bytes) and execution `13f6ac6fc351c79b65a835b0eb400645bd60f0abd5358e4bf56ac07e0d528491` (8,354 bytes), combined 47,391. This amendment invalidates those hashes; final freeze records both replacements and requires combined bytes below 50,000.

## Decision

Reuse the one existing browser event path, `runtime event -> /ws/events ->
useWebSocket -> useStore.handleEvent`. Do not add a second WebSocket, SSE,
NATS browser client, polling daemon, or message replay store.

The existing path needs hardening as part of this issue before CrewSession data
can use it:

1. authenticate `/ws/events` with the existing `verify_ws_token()` helper
   before `accept()`; empty `auth.crew_scope_token` retains its current
   default-off pass-through behavior;
2. replace the unbounded client list plus per-event `create_task()` fanout with
   one bounded queue and one owned sender task per admitted client;
3. put one server generation and monotonically increasing sequence on every
   non-ping frame, with the initial state snapshot carrying the current
   sequence watermark;
4. finalize every event and snapshot through a bounded, exact-built-in JSON
   detacher and final UTF-8 byte cap; and
5. remove the runtime listener, close admission, cancel/drain owned tasks, and
   disconnect clients during app lifespan shutdown.

Final review found exactly two backend blockers: source admission must precede
WebSocket snapshot materialization, and raw-NATS release must remove the exact
source-owned tracking identity. The tightened snapshot/NATS, test, gate, and
allowlist clauses below supersede only conflicting wording. Preserve all other
implemented backend/frontend behavior and evidence.

Existing `WORK_ITEM_CREATED`, `WORK_ITEM_UPDATED`, and
`WORK_ITEM_STATUS_CHANGED` commits are sufficient invalidation authority for
CrewSession state, child progress, blockers, verification, and Todo changes.
A server-side live projector resolves the affected parent and rebuilds the
existing AD-1132 detail and compact-summary projections after the durable
commit. The WebSocket bridge suppresses raw work-item frames for a
CrewSession parent or direct child; it sends only the resulting projection,
counts, and refs. It never forwards raw WorkItem/session/synthesis/recovery
metadata or a partial row into the generic frontend `workItems` slice.

The durable chat-message and ArtifactStore commit seams currently emit no
runtime event. Add exactly the two IDs-only commit events in Section 0. They
are required so an asynchronously appended agent message and an artifact
version can invalidate an already-open room independently of a later parent
transition. Do not add a CrewSession-specific EventType: the current work-item
events plus the transport projection are sufficient.

Frames do not carry message bodies, artifact bytes, Todo notes, attachment
bytes, provenance bodies, or result bodies. Visible consumers repair through
the existing bounded GET routes. Reconnect, a sequence gap, or queue overflow
raises one repair epoch; only currently visible/open consumers refetch.

## Section 0: Event Types

Add at the existing Work items / threads area in `src/probos/events.py`:

```python
CHAT_THREAD_MESSAGE_APPENDED = "chat_thread_message_appended"
ARTIFACT_VERSION_ADDED = "artifact_version_added"
```

`ChatThreadStore.append_message()` emits only after the insert and thread
`last_active_at` update commit. Exact data keys:

```text
thread_id: bounded string
message_id: bounded string
author_id: bounded string
role: "captain" | "agent" | "system"
created_at: finite non-negative number
```

It emits no `body`, metadata, attachment refs, prompt, response, or participant
list. Add a fully typed store-owned `append_message_once()` over the existing
table; add no column/table/index. It accepts a bounded caller message id and
finite `created_at`, uses one `BEGIN IMMEDIATE`, inserts once, or returns the
existing row only after an exact JSON-type-aware comparison of all row fields.
A different-content id collision raises a stable conflict. It advances thread
`last_active_at` monotonically and emits only for the winning insert.

`ArtifactStore.add_version()` emits only after a new row commits. Any other
method that creates a new artifact row, including exact reconciliation, must
use one shared post-commit helper; reuse of an existing row emits nothing.
Exact data keys:

```text
thread_id: bounded string
artifact_id: bounded string
version: positive integer
created_at: finite non-negative number
```

It emits no name, MIME, hash, size, creator, supersedes chain, or bytes. Both
stores expose an optional fully typed post-commit callback setter. They pass
the committed typed row to that callback and do not import runtime or
EventType. `ProbOSRuntime` constructs both stores before `_event_listeners` and
its owned event-task registries exist, so install the validating runtime
adapters through those setters immediately after those registries are
initialized; do not emit through a half-constructed runtime. The adapters call
the public `runtime.emit_event`. Callback failure is log-and-degrade after
commit and cannot make a successful store write look failed. Tests instantiate
real stores with real recording callbacks, not MagicMock chains.

## 1. Bounded Existing WebSocket Path

Add a focused `src/probos/ws_event_stream.py` owner and keep the route itself in
`src/probos/api.py`. Replace `_on_runtime_event` with this hub as the sole
runtime listener, and point `app.state.broadcast_event` at the same bounded
ingress so router broadcasts cannot bypass it. It owns one generation (new per
app), one global sequence, one ordered dispatcher, closed admission, and a
bounded client registry.
Instantiate exactly one hub per `create_app()`. Keep `event_hub.ingress`
synchronous for `get_ws_broadcast()`, but do not use the legacy listener API
for this lifespan-owned stream. Preserve every existing synchronous
`add_event_listener()` / `remove_event_listener()` caller and behavior
byte-identically. In `runtime.py`, add the narrow public awaited contract
`register_live_event_listener(...) -> LiveEventListenerHandle`; its fully
typed handle exposes idempotent `async stop() -> None` and owns one exact local
registration token plus an optional exact NATS subscription.

Keep these registrations in a separate runtime-owned live registry so
`_setup_nats_event_subscriptions()` cannot retrofit them to JetStream. Local
fallback dispatch includes active live tokens. If NATS is connected, subscribe
through existing `subscribe_raw()` to the current fully-prefixed
`system.events.>` subject: this is live core NATS, with no durable consumer,
deliver policy, or retained boot replay. Create the token closed; perform the
subscribe in one retained setup task awaited under cancellation shielding;
require the returned subscription and capture its exact bus identity; then
append the token and open it synchronously. On setup failure/cancellation,
await setup to outcome, release any returned subscription through that bus,
remove the token if installed, and re-raise the original `BaseException`.

Add fully typed public `NATSBus.release_raw_subscription(subscription: object)
-> bool`. It identity-matches only `_subscriptions`; absent/wrong/already
released returns `False` untouched. Concurrent/repeated calls share one
retained shielded cleanup: exact `drain()`, fallback `unsubscribe()` on ordinary
failure, then identity-remove only after one succeeds. If both fail, retain
tracking and raise `RuntimeError("nats_raw_subscription_release_failed")`;
caller cancellation waits cleanup then re-raises. `LiveEventListenerHandle`
closes/removes its token, then invokes this method on the captured
bus+subscription without re-reading `runtime.nats_bus`; ordinary release
failure is bounded log-and-degrade after tracking is retained. Preserve
`NATSBus.stop()` and ordinary subscriptions. The callback logs no event data
or exception text. Add no config/schema field.

Start the hub inside FastAPI lifespan, await the returned runtime handle,
assign `app.state.broadcast_event` to the same ingress, and only then `yield`.
On setup failure, stop any obtained handle and the partially started hub before
re-raising. Shutdown closes hub admission, awaits handle stop, then awaits hub
stop. No `hasattr` fallback to the synchronous API is permitted.
Constants are source-level safety limits, not new configuration: at most 16
clients; 32 queued frames and 2 MiB queued bytes per client; 256 ingress items
and 8 MiB ingress bytes globally; one sender task per client; 5-second send
timeout; at most 256 KiB final UTF-8 JSON per delta/control frame and 1 MiB for
the initial state snapshot; finite container/depth/node/string scan limits;
and no arbitrary `__dict__` or iterable introspection. Worst-case retained
queue bytes are therefore finite independently of event rate.

The finalizer accepts exact JSON built-ins plus the existing enum/dataclass
values by iterating declared fields under the same budget. Reject container
subclasses, non-finite floats, overlong keys/strings, excess depth/nodes/items,
unsupported values, and final-byte overflow without invoking attacker-defined
iteration or metadata. A rejected ordinary runtime event is dropped with a
bounded type-only warning. A rejected initial snapshot closes that client with
1013; no partial snapshot is sent.

Every non-ping frame serializes exactly:

```text
type: bounded string
data: bounded object
timestamp: finite non-negative number
stream:
  generation: 32 lowercase hex characters
  sequence: non-negative integer
```

On connect, call `verify_ws_token(websocket, runtime)` and return on false
before `accept()`. Build/finalize the snapshot before exposing the client to
publish; register its queue with the snapshot first, start its sender, then
retain the receive/keepalive loop. Pings do not advance domain sequence.

The listener synchronously derives a bounded ingress item. For work-item
events it retains only the already-finalized bounded event plus the exact
`id/parent_id/work_type/status` trigger fields; it never queues a raw object.
One dispatcher preserves ingress order, performs any async parent
classification, and either suppresses/project CrewSession traffic or publishes
the finalized non-session event. Ingress count/byte saturation requests one
global resync watermark and drops the new delta without allocating a task.

Contain each ingress item independently. Around `await
projector.route_event(...)`, re-raise `asyncio.CancelledError`; catch only
ordinary `Exception`, log bounded event type and exception class (no event
data, ids, exception text, or traceback), request one current-generation
global resync, and continue the same dispatcher. The failed source event gets
no normal delta sequence. Its repair frame advances global envelope authority
exactly once, and the next valid queued item remains deliverable.

Publishing assigns one sequence once, then performs only non-blocking bounded
queue admission. `state_snapshot` carries the current watermark without
consuming a sequence. Each coalesced global `resync_required` reserves the next
global sequence once and fans that one frame to current clients; a client-only
queue-overflow marker carries the latest watermark without advancing it.
Control frames precede ordinary duplicate suppression. On first client queue
saturation, discard pending deltas and enqueue one exact repair marker;
suppress duplicates until sent. If it cannot be admitted or saturation recurs
before recovery, close 1013. A slow or broken client never creates an unbounded
task, blocks another client, or grows memory.

Do not reproduce runtime snapshot semantics in `ws_event_stream.py` and do not
call the old unbounded `build_state_snapshot()`. Extract shared typed row and
scalar projectors from its authoritative implementation. Keep the legacy
method's public schema and source behavior exact, but have it and a new public
synchronous `build_bounded_hxi_snapshot_base()` reuse those projectors. The
bounded base preserves every legacy top-level key and shape except workforce,
which is replaced only by the separately bounded Crew-safe projection:
agents, connections, pools, exact active/idle/dreaming mode,
`tc_n`/`routing_entropy` from the existing emergence summary, `fresh_boot`,
temporal, pool groups, complete authoritative `pool_to_group`, directives,
notifications, unread count, scheduled tasks, ward-room stats, skill-framework
flag, and ACM flag. This includes every field already consumed by `useStore`.
Agent rows obtain `display_name` from the callsign profile registry, retain
`isCrew`, and retain legacy trust/rank-derived `agency`; never read nonexistent
`agent.display_name` or substitute active/zero/false constants.

Reject before each full projection. Use existing properties
`AgentRegistry.count` before `all()` and `HebbianRouter.weight_count` before
`all_weights_typed()`, plus `len(runtime.pools)`. Add typed public
`PoolGroupRegistry.count`, `membership_count`, and `pool_mapping_count`
properties plus `pool_to_group_snapshot() -> dict[str, str]`; check them in
that order before `all_groups()` or the mapping copy. Add typed public
`NotificationQueue.count` before `snapshot()`. Add
`DirectiveStore.list_directives_bounded(*, include_inactive: bool = False,
limit: int) -> list[RuntimeDirective]`, validating exact non-bool positive
`int` and preserving the legacy filter/order SQL with `LIMIT limit + 1`;
`all_directives()` stays exact. Runtime reads no owner private attribute.

Exact built-in non-negative counts at/under cap proceed; malformed or over-cap
counts raise the existing source-specific
`ValueError("ws_snapshot_<source>_overflow")` before the full accessor. Caps
remain 1,000 agents, typed connections, pools, mappings, notifications,
scheduled tasks, aggregate memberships, or active directives, and 128 groups.
Never truncate or derive mappings only from instantiated pools; under-cap
ordering/shape stays legacy-exact. `build_ws_state_snapshot()`
combines this bounded base with the existing bounded Crew-safe workforce shape
before the existing exact detacher, node/depth/string budgets, and 1 MiB final
cap. Any source overflow closes 1013 with no partial frame.

Add the narrow fully typed public store seam
`WorkItemStore.list_ws_visible_work_items(*, limit: int) -> list[WorkItem]`.
Treat `limit` as the visible cap: require exact built-in `int` (not `bool`) in
`1..100`, else raise `ValueError("ws_visible_work_items_limit_invalid")`; no
open connection returns `[]`. Through the store-owned `DatabaseConnection`,
run one SQL query that, before ordering/LIMIT, excludes
`work_type = 'crew_session'` and rows whose `parent_id` names a CrewSession
parent. Use correlated `NOT EXISTS` or one-query `LEFT JOIN`; missing/non-Crew
parents remain visible. Order `priority ASC, created_at DESC, id ASC`; request
`limit + 1` inside the seam and document its at-most-`limit + 1` sentinel
return. Keep generic `list_work_items()` exact.

`build_ws_workforce_snapshot()` calls this seam once with the visible cap,
does no private/raw connection, generic-list, parent-read, Python-filter, or
N+1 work, and raises stable `ValueError("ws_workforce_source_overflow")` iff
visible rows exceed the cap; otherwise serialize in returned order. Overflow
closes 1013. Send no partial `WorkItemView`, Crew details, or history.

Shutdown order is: close admission, await the exact live-listener handle,
invalidate the live-projector generation, cancel/drain projector work, close
clients, then cancel/drain sender tasks. A completion captured by an old
app/projector generation must not publish into a restarted owner.
After hub teardown, preserve the existing `_background_tasks` cancel/gather/
clear shutdown behavior in `api.py`; AD-1133 does not orphan or replace it.

## 2. Authoritative Crew Live Projector

Add `src/probos/crew_session_live.py`. Extract one shared async loader for the
AD-1132 routers and this projector without weakening the pure APIs in
`crew_session_projection.py`. The loader accepts injected service/stores,
loads the parent, calls `CrewSessionService.get_session()`, validates optional
`crew_synth`, loads at most 1,001 direct children, and delegates to
`build_crew_session_detail()` and `build_crew_session_summary()`. Update the
two AD-1132 routers to call that shared loader; legacy non-session behavior and
all AD-1132 404/409/503/fallback contracts remain exact.

The hub routes these existing/additive runtime events through the projector;
the projector does not register a second listener:

```text
work_item_created
work_item_updated
work_item_status_changed
artifact_version_added
```

For a CrewSession parent event, use `work_item.id`. For any event with a
bounded non-null `work_item.parent_id`, load that parent once. If it is a
CrewSession, use the parent id and suppress the finalized generic child frame;
otherwise publish the finalized generic event unchanged. Parent events whose
`work_type == "crew_session"` are likewise consumed and suppressed. For an
artifact event, load the thread and require its bounded `task_id` to resolve
to that CrewSession. Malformed, unrelated, missing, or inconsistent events
produce no Crew frame and no raw-value log; a malformed generic frame is
dropped rather than guessed.

Coalesce duplicate commit events by parent id in a bounded 256-entry pending
set owned by one dispatcher/projector worker; do not create one task per
parent/event. If admission is closed or the set is full, request one stream
resync marker rather than allocate more work. Capture the projector generation
before every await and re-check it before state mutation or publish.
Cancellation cleans up and re-raises.

After authoritative loading, calculate Todo counts from at most 1,000 steps
and Artifact count through an additive `ArtifactStore.count_thread_latest()`
SQL count, not by loading every row. Load the bound thread and cross-check
`thread.id`, `thread.task_id`, detail task/thread ids, summary ids, and session
revision. Finalize one exact transport-only frame (not an EventType):

```text
type: "crew_session_projection"
data:
  parent_id: string
  thread_id: string
  revision: non-negative integer
  session: exact AD-1132 CrewSessionDetailProjection wire object
  room_summary:
    outputs: non-negative integer
    steps_total: integer 0..1000
    steps_done: integer 0..steps_total
    topic: exact validated session goal
    session: exact AD-1132 CrewSessionSummaryProjection wire object
```

`outputs` is the authoritative count, not an artifact list. The frame contains
refs already admitted by AD-1132, never dereferenced content. A projection
conflict drops this delta and requests bounded repair; it never sends partial
or legacy raw serializers.

An artifact commit also remains visible as its IDs-only runtime event so an
expanded rail can refresh immediately. The projected `outputs` count follows
once the projector resolves the room. A message append uses only
`chat_thread_message_appended`; no CrewSession projection is required for a
message body.

### 2.1 Durable async child reply

`CrewExecutor` currently commits successful AgenticLoop output into the direct
child's `crew_execution` and `crew_execution_output` but does not append it to
the room. After a winning or exactly reconciled successful terminal commit,
append the validated output through `append_message_once()`: role `agent`,
author the authoritative assignee, thread the bound room, and exact metadata
`{source: "crew_session_child_result", parent_id, work_item_id, content_hash}`.
Derive the 64-hex message id from a domain-separated SHA-256 of parent id,
child id, and committed output hash; use persisted `finished_at` as
`created_at`.

Append only after child evidence is authoritative. Failure logs/degrades and
cannot roll back or misreport the child commit. During `resume()`, after exact
terminal evidence and attachment readback validate, invoke the same append
before continuing. A crash between child commit and append repairs one row;
repeated/concurrent recovery produces no duplicate row/event. Failed, blocked,
or interrupted children append nothing. This observes durable AD-1127 work;
it makes no new agent call and starts no conversational cascade.

## 3. Frontend Stream Authority and Reducer

Extend exact types in `ui/src/store/types.ts`; do not use open index signatures
for the three AD-1133 data contracts. `useWebSocket.ts` remains the sole browser
socket owner. If the current page URL carries a non-empty `token` query value,
copy only that value into the `/ws/events?token=...` URL with
`encodeURIComponent`; otherwise use `/ws/events`. Add no token field, config,
store state, local/session storage, cookie, log, telemetry, or alternate auth
scheme.

Track and clear the reconnect timeout on unmount. Every callback captures its
socket instance and ignores work unless `wsRef.current === socket`; an old
socket cannot deliver into a replacement. The store, not components, owns:

```text
liveGeneration: string | null
liveSequence: integer
liveRepairEpoch: integer
liveThreadRefresh: null | { threadId, requestId }
liveArtifactRefresh: null | { threadId, requestId }
liveTodoRefresh: null | { parentId, requestId }
liveCrewOwnerParentId: string | null
liveRailOwner: null | { threadId, parentId }
roomSummariesByThread: ReadonlyMap<thread_id, RoomSummary>
```

Keep these volatile and bounded; do not persist them. `state_snapshot` is the
only frame allowed to install/replace generation authority. A new generation
or reconnect increments `liveRepairEpoch`, sets the snapshot watermark, and
then applies the existing snapshot. Before that snapshot, ignore deltas. For
the active generation, ignore `sequence <= liveSequence`; when
`sequence > liveSequence + 1`, advance authority, increment repair epoch, and
then apply a valid current frame. `resync_required` increments repair epoch.
A frame from another generation is ignored.

Validate the complete frame before mutation. For
`crew_session_projection`, require all repeated ids/revision/state to agree.
Clone and update `crewSessionsByParent`,
`crewSessionSummariesByThread`, and `roomSummariesByThread`. Never mutate a
stored projection or Map. Reject a detail revision below the cached revision.
A newer stream sequence with the same session revision is allowed because a
direct child's status, Todo count, or artifact count can change without a
parent revision. This rule must update progress/counts without permitting a
state/revision regression.

For `chat_thread_message_appended`, clone-update only that existing
`chatThreads` row's `last_active_at = max(existing, created_at)`. If and only
if it is the currently active open profile thread resolved from
`activeProfileAgent`, `activeProfileThreadId`, and `threadIdByAgent` with the
same ownership semantics as `resolveProfileThreadId()`, advance
`liveThreadRefresh`.
Replacement by the bounded authoritative message GET, keyed by message id,
prevents duplicates. For `artifact_version_added`, advance artifact refresh
only for the exact `liveRailOwner.threadId`. A projection advances Todo refresh
only for the exact rail owner and updates the Crew panel only for
`liveCrewOwnerParentId`. The panel and expanded rail register/clear these
volatile owners with generation-safe effects; they add no WebSocket/window
listener. Hidden/closed/collapsed panels have no owner and start no interval,
timeout, poll, or fetch. The one app-level `useWebSocket()` remains mounted as
today.

Make AD-1132 hydration race-safe. Each GET captures generation/sequence and a
component request generation. Apply it only if room ownership still matches
and no newer live sequence superseded the request. `hydrateCrewSession()` must
also refuse a lower revision. A failed/empty repair retains cached state and
surfaces the existing bounded stale/error affordance; it never clears a newer
map entry.

## 4. Visible Consumer Repair

Use existing routes only:

- open room transcript: `GET /api/threads/{thread_id}/messages?limit=200`;
- open Crew panel: `GET /api/crew-tasks/{parent_id}`;
- open Chats panel: `GET /api/threads/summaries`;
- expanded rail Todos: `GET /api/work-items/{parent_id}/steps`;
- expanded rail artifacts: `GET /api/artifacts/thread/{thread_id}`.

Every repair is singleflight/coalesced per visible owner and uses a monotonically
increasing request generation. Initial mount/open GET behavior remains. On
`liveRepairEpoch`, refetch only the currently active transcript/session,
currently open Chats summaries, and currently expanded rail. On the three
targeted refresh commands, refetch only the matching still-owned surface. No
request from an old room may apply after navigation/unmount.

Keep the message count at 200 and add count/response guards to the Todo and
artifact wrappers. A response with more than 1,000 Todos or 1,000 artifact
metadata rows, malformed ids, mismatched room ownership, or an over-budget
JSON response is rejected whole and leaves cache intact. Add optional bounded
store/router query support only if needed to avoid constructing an unbounded
artifact list; preserve the legacy no-query response shape. Never fetch
artifact content for refresh.

`threadApi.ts` keeps the existing exact `isCrewSessionDetailProjection()` and
`isRoomSummary()` parsers and adds a strict message-repair outcome
distinguishing successful `messages` (including authoritative empty) from
transport/status/shape error; legacy `listMessages()` remains exact.
`ProfileChatTab` consumes that outcome and maps successful DTOs through the
existing exported `threadDtoToMessage()` mapper. Do not edit
`profileTranscript.ts` or change legacy `loadThreadMessages()` semantics.
Targeted refresh applies only when the bounded response contains its triggering
`message_id`. Error/lag retains the current transcript; reconnect/manual repair
can recover. Never clear newer state through honest-degrade `[]`.

Remove the temporary BF-644 5-second Artifact/Todo interval only after all
focused push-parity tests pass. Retain the current initial fetches, existing
Crew panel Retry, and one accessible stroke-SVG manual Refresh command in the
existing Files rail. Manual refresh performs one matching Todo/artifact GET
pair, cannot overlap itself, preserves cached data on failure, and starts no
timer.

`ArtifactViewer` remains unchanged and content-lazy. Rail projection/event
repair refreshes bounded artifact metadata only; it must not fetch content,
replace the viewer, or disturb an already selected artifact unless the
authoritative metadata proves that selection no longer belongs to the room.

`ChatsPanel` consumes `roomSummariesByThread` so live goal/state/progress/
Todo/output changes update the existing rows and blocked-first Needs You order
without reopen. It performs its initial/reconnect summary GET only while open.
`ProfileChatTab` observes only its active room refresh command and reloads the
real thread transcript through the existing mapper. `CrewCollaborationPanel`
observes only its mounted parent. `WorkspaceFilesRail` observes only its
expanded matching room. Do not add another panel, card, rail, viewer, route,
or layout layer.

## 5. Tests After Coding

Complete all production and test edits before the first test/build/browser
command.

### Backend

Extend `tests/test_ad1133_live_crew_session_refresh.py` without external
services. Exercise the production `ProbOSRuntime` registration method with a
protocol-faithful test NATS connection whose raw core subscribe returns an
actual inspectable subscription object: a pre-subscribe retained publish is
not replayed, one post-readiness live publish is delivered, API lifespan does
not yield before readiness, setup failure/cancellation leaves no local token or
subscription, and repeated shutdown/restart drains only the returned
subscription with no owned task leak. Repeated API lifespan restart on the same
live bus must restore tracked-subscription cardinality to baseline and never
duplicate delivery. In `tests/test_ad637a_nats_foundation.py`, exercise real
`NATSBus` identity-only release, wrong/already-released no-op, concurrent
idempotency, drain fallback, both-fail retention, and cancellation completion.
Require no external NATS service. Keep legacy sync listeners exact.

Add real-runtime or faithful concrete-runtime WebSocket parity for fresh boot;
active/idle/dreaming; emergence metrics; callsign-profile display name;
trust-derived agency; complete mapping entries absent from `runtime.pools`;
every legacy top-level snapshot key/shape; every source cap; and overflow
1013/resync without partial state. Force one parent/thread/store lookup in
`route_event()` to raise once, then assert one sequenced resync, the subsequent
valid event at the next sequence, the same dispatcher task still alive, and
clean cancellation. Preserve all current auth, envelope, queue, projection,
commit-event, reply-repair, stale-generation, workforce, and AD-1132 tests.
For each count-backed source, prove over-cap raises the stable overflow before
a spy full accessor is called, exactly-cap proceeds, malformed counts fail
closed where applicable, and snapshot parity remains. Add focused owner tests
in `test_pool_groups.py`, `test_notifications.py`, and
`test_directive_store.py`, including directive cap+1 and filter/order parity.

Extend `tests/test_workforce.py` with real SQLite coverage for
`list_ws_visible_work_items()`: default empty; exact-invalid limits including
`bool`, zero, above 100, and non-`int`; over-cap Crew parents/children before
and around ordinary rows do not starve them; direct Crew children are excluded;
non-Crew and missing-parent children remain; 101 ordinary rows provide the
overflow sentinel; and priority/created-at/id order is deterministic. Create
Crew parents through the public admission port and prove one SQL query, not
N+1 parent reads. In the AD-1133 backend file, prove one public-seam router
call, stable overflow for 101 ordinary rows, no overflow from excluded Crew
rows, and no private/generic-list/parent-read reach-through.

### Targeted Vitest

The implemented store/hook/API-wrapper/component coverage is frozen. Preserve
its token/authority/reconnect, strict reducer, visible-owner repair,
authoritative-empty, bounds, stale-drop, manual-refresh, and BF-644 assertions
byte-identically. If its aggregate hash changes, stop; do not edit or rerun UI
under this backend correction.

### Focused Playwright

Preserve the implemented full-App spec and helpers byte-identically: unmatched
API abort, onboarding dismissal, in-page Map seeding, direct store open, one
mocked socket, live-state progression, stale/reconnect cleanup, and no overlap.
Reuse the prior one-spec pass only when the full UI/e2e aggregate is unchanged.

No website, Three.js, 3D canvas, screenshot, or canvas-pixel validation is
required because those surfaces are not touched.

## 6. Exact Build Allowlist

Production additions/changes are limited to:

```text
src/probos/events.py
src/probos/threads/__init__.py
src/probos/artifacts/__init__.py
src/probos/cognitive/crew_executor.py
src/probos/runtime.py
src/probos/api.py
src/probos/workforce.py
src/probos/substrate/pool_group.py
src/probos/notifications.py
src/probos/directive_store.py
src/probos/mesh/nats_bus.py
src/probos/ws_event_stream.py
src/probos/crew_session_live.py
src/probos/routers/crew_tasks.py
src/probos/routers/threads.py
src/probos/routers/artifacts.py
src/probos/routers/workforce.py
ui/src/store/types.ts
ui/src/store/useStore.ts
ui/src/hooks/useWebSocket.ts
ui/src/components/artifacts/artifactApi.ts
ui/src/components/chats/ChatsPanel.tsx
ui/src/components/crew/CrewCollaborationPanel.tsx
ui/src/components/profile/ProfileChatTab.tsx
ui/src/components/sidebar/threadApi.ts
ui/src/components/workspace/todosApi.ts
ui/src/components/workspace/WorkspaceFilesRail.tsx
ui/e2e/_helpers.ts
```

Tests are limited to the new backend/store/hook/API-wrapper/e2e files,
`tests/test_workforce.py`, `tests/test_pool_groups.py`,
`tests/test_notifications.py`, `tests/test_directive_store.py`,
`tests/test_ad637a_nats_foundation.py`, the existing backend
AD-1125/1127/1128/1132 and route/event tests named in the execution companion,
and the seven owning Vitest files above. The two active prompts are authorized.
Trackers and archive moves are authorized only in post-commit closeout after
the three final reviews and mechanical freeze. Any other path is an Architect
hard stop.

The final-review correction delta may modify only:

```text
src/probos/runtime.py
src/probos/substrate/pool_group.py
src/probos/notifications.py
src/probos/directive_store.py
src/probos/mesh/nats_bus.py
tests/test_ad1133_live_crew_session_refresh.py
tests/test_pool_groups.py
tests/test_notifications.py
tests/test_directive_store.py
tests/test_ad637a_nats_foundation.py
```

Live grep proves `tests/test_ad637d_system_events_nats.py` copies a fake
runtime, while `tests/test_hxi_events.py` owns real legacy listener/snapshot
regressions. Rerun both unchanged; do not edit them. No workforce,
API/hub/projector, UI, e2e, config, other production/test sibling, or tracker
edit is authorized by this correction. A frontend mismatch returns to
Architect rather than widening scope.

## 7. What This Does Not Change

- No AD-1131 metrics/trust/delivery/notification/outbox changes.
- No endpoint/dashboard/sidebar/viewer/replay DB/schema/dependency/config YAML.
- No second WS/SSE/NATS browser/poll daemon/cascade/group ping-pong.
- No content bytes/raw metadata/secrets in frames, logs, or persistence.
- No commercial/pricing/trust/Hebbian/episodic/agent-behavior change.
- Only BF-644 Todo/Artifact polling is removed after parity.
- No push before the post-commit final reviews and closeout review.

## 8. Acceptance Criteria

- An asynchronously produced agent message appears in an already-open room
  without Captain POST/reopen.
- Session state, last result, blocker, verification, Todo, and artifact count
  update live.
- Duplicate/out-of-order events do not duplicate messages or regress state.
- Reconnect snapshot/refetch repairs dropped events.
- Hidden/closed panels do not start polling or leak listeners.
- Shutdown/restart does not emit stale completion from an old task generation.
- API serving begins only after atomic live-only listener readiness; failure,
  cancellation, stop, and restart remove the exact local and NATS identities.
- Repeated lifespan restart on one bus restores tracked subscription count to
  baseline and cannot duplicate delivery.
- WebSocket snapshots preserve authoritative mode, fresh boot, emergence
  metrics, callsign display, agency, complete pool mapping, and all prior
  browser-consumed fields, with admission before full source projection.
- One route failure emits one authority-advancing resync, does not advance a
  failed normal delta, and cannot kill or skip the next dispatcher item.
- Vitest store/component tests and Playwright full-App work-room flow pass;
  unmatched API routes abort in the test harness.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-07-23)

Local #1052 mirror: `logs/crew-collaboration-epic-architect-report-2026-07-17.md:913-960`.
GitHub was forbidden. Live anchors:

```text
src/probos/api.py:109-132 — live lifespan starts the hub, calls synchronous
  add/remove, and can yield before fire-and-forget NATS setup completes.
src/probos/routers/deps.py:18-20 — sync app.state.broadcast_event dependency.
src/probos/routers/auth.py:77-100 — public pre-accept verify_ws_token helper.
src/probos/runtime.py:481-483,525-527,1089-1096 — stores precede listener/task
  registry initialization; callbacks therefore require late setter wiring.
src/probos/runtime.py:1357-1436,1452-1495 — legacy sync identity,
  fire-and-forget JetStream setup, local fallback, and public emit_event.
src/probos/runtime.py:2029-2099 — bounded snapshot currently materializes full
  owner projections and reads the pool mapping private attribute before caps.
src/probos/substrate/registry.py:72-78 and mesh/routing.py:348-360 — public
  count/weight_count properties precede full projections.
src/probos/substrate/pool_group.py:28-66, notifications.py:64-166, and
  directive_store.py:142-273 — exact owners/full projection APIs lack the
  required count or bounded projection seams.
src/probos/mesh/nats_bus.py:109,473-497,517-550,908-939 — raw subscribe tracks
  the returned identity; only whole-bus stop clears that tracking list.
src/probos/events.py:99-101 — existing work-item events.
src/probos/workforce.py:2045-2055,2131,2332,2507 — Crew parent-safe versus
  child-generic work-item event projections and commit-time emissions.
src/probos/workforce.py:34,1944-2017,2147-2187,4868 — public connection-backed
  store, exact generic order, and shared row decoder.
src/probos/routers/workforce.py:22-49 — current snapshot calls generic
  list_work_items(limit + 1), then performs Python/N+1 Crew filtering.
src/probos/ws_event_stream.py:223-318,462-497 — current reduced snapshot
  hardcodes mode/metrics/fresh boot and route failure escapes the dispatcher.
src/probos/crew_session_live.py:182-258 — awaited parent/thread/store lookup
  seams used by the dispatcher-containment regression.
tests/test_ad1133_live_crew_session_refresh.py:118-140,473-496 — current
  lifespan test uses a synchronous fake and cannot prove NATS readiness.
tests/test_hxi_events.py:26-116 — real runtime owns unchanged legacy
  listener and snapshot regressions.
src/probos/ws_event_stream.py:44,290-293 — workforce cap remains 100.
tests/test_workforce.py:35-53,143-190 — real SQLite owning tests remain green.
src/probos/threads/__init__.py:1237-1278 — durable append has generated id/time
  and no callback or idempotent caller-id API.
src/probos/artifacts/__init__.py:82-172,174-225,271 — constructor/add/reconcile
  have no callback, reconciliation can create or reuse exact v1, and current
  latest-per-name listing is the SQL-count sibling seam.
src/probos/cognitive/crew_executor.py:409-710 — resume reconstructs exact
  terminal evidence and validates attachment readback.
src/probos/cognitive/crew_executor.py:880-939,1092-1317 — AgenticLoop output
  becomes child evidence/attachment, not a room message.
src/probos/routers/crew_tasks.py:113-165 — inline AD-1132 detail load/build.
src/probos/routers/threads.py:190-219,258-309,490-507 — second detail loader,
  summary projection, and bounded message route.
src/probos/routers/artifacts.py:45-91 and routers/workforce.py:263 — existing
  artifact-list and Todo-step repair routes; no new endpoint is required.
src/probos/crew_session_projection.py:101-188,191-229,320-466 — exact frozen
  detail/summary types, to_wire methods, and pure builders.
ui/src/hooks/useWebSocket.ts:6-30 — sole browser socket owner.
ui/src/store/useStore.ts:350-351,1417-1435,1947 — maps/actions/reducer.
ui/src/components/sidebar/threadApi.ts:126-316,319-350,578-588 — strict
  AD-1132 detail/summary parsers and legacy []-degrading message wrapper.
ui/src/components/profile/profileTranscript.ts:17-31,107-118 — exported DTO
  mapper and legacy transcript loader that must remain exact.
ui/src/components/profile/ProfileChatTab.tsx:602-603,1018-1034 — resolved
  visible thread ownership and current load-on-open effect.
ui/src/components/crew/CrewCollaborationPanel.tsx:502-615 — keyed
  thread+parent ownership, cache, singleflight, and stale-write guards.
ui/src/components/chats/ChatsPanel.tsx:91-165 — local summaries plus AD-1132
  summary-map hydration only while the panel is open.
ui/src/components/workspace/WorkspaceFilesRail.tsx:202-251,469-478 — initial
  artifact fetch, BF-644 5-second poll, and keyed Todo refresh.
ui/src/components/artifacts/ArtifactViewer.tsx:46-116 — existing selected-row
  content-lazy viewer; metadata refresh belongs to the rail, not this file.
ui/e2e/_helpers.ts:199,217 — unmatched abort/onboarding dismissal.
```
