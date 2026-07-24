# AD-1131: CrewSession Outcome Delivery and Metrics

**Status:** READY after three prompt-only reviews
**Issue:** #1050
**Type:** Enhancement; build AD-1131 only
**Required build base:** `d463a114`
**Authorized input hashes:** main `d8405c1eecbd857155fd9c8d068ffd3c959098da824fe118df927ef28864798b`; execution `cfeb75b2afd7a3d332399e839953cf6024597ab42182edadd5d53c95cc2c13ff`
**Planning ceilings:** AD-1130 / BF-673
**Execution authority:** `prompts/ad-1131-crew-session-delivery-metrics-execution.md`
**Prompt binding:** the execution prompt embeds this final main-prompt SHA-256. Both final prompt hashes and byte lengths are frozen before code and their combined size is `< 50000` bytes.

## Decision

Every committed CrewSession transition into `done`, `failed`, or
`blocked_needs_captain` owns exactly one safe Captain notification identity for
that exact `(session_id, session_revision, outcome)`. A blocked session that is
later resumed and completed owns one blocked notice and one later done notice;
redelivery of either revision never creates another logical notice.

Reuse `EventType.WORK_ITEM_STATUS_CHANGED`. All three CrewSession outcomes
project to distinct existing WorkItem statuses (`done`, `failed`, `blocked`),
and the live store already emits that event after commit. Add no EventType and
no CrewSession-specific event. The event is a wake-up hint, not authority: the
delivery service reads and validates the durable outbox row before notifying.

Commit a bounded safe delivery row in the existing `workforce.db` transaction
that commits the CrewSession outcome. The row is the durable delivery outbox,
never metric authority. Deliver through the existing in-memory
`NotificationQueue` using a new deterministic exact-id API; then mark the exact
row delivered. Queue insertion followed by acknowledgement is not a
cross-resource transaction, so the sink must be idempotent: a
crash/cancellation after queue insertion but before the mark retries the same
notification id and payload, never a second entry.

AD-1130 added a separate terminal-trust pipeline. One CrewSession outcome
revision can own zero, one, or many `CrewTrustEffect` rows; the store commits
them with the terminal contract, `CrewSessionTrustRecorder` drains them, and
`TrustNetwork.record_outcome_once` serializes exact receipt/replay handling.
Those effect rows, receipt rows, trust-delivered flags, and trust-writer results
are neither delivery evidence nor metric samples. AD-1131 commits exactly one
delivery fact per outcome revision beside any AD-1130 effects, and each pipeline
retries independently.

AD-846 remains the non-session Yeo task-completion DM path. Its dispatchable +
`yeo-delegated` gate, DM channel naming, wording, Yeo resolution, and honest
degrade behavior remain unchanged. Add an explicit `work_type ==
"crew_session"` rejection and accept the live dict event envelope; this keeps
the two consumers disjoint and corrects the current test-only object-envelope
assumption without redesigning AD-846.

## Pinned Design Decisions

### DD-1 - One immutable delivery fact per outcome revision

Add a strict frozen `CrewSessionDeliveryRecord` in a focused new module such as
`src/probos/crew_session_delivery.py`. It contains only:

- `version=1`, `delivery_id`, `session_id`, `session_revision`, and `outcome`
  (`done`, `failed`, or `blocked_needs_captain`);
- existing `thread_id`, `origin`, `originator_id`, `author_id`, and ownership
  (`captain` or `self`);
- exact notification envelope fields: `notification_type`, `title`, `detail`,
  `action_url`, and `occurred_at`;
- finite non-negative `elapsed_seconds`; and delivery state/timestamps owned by
  the store, not caller-selected prose.

Canonicalize identity as compact sorted-key UTF-8 JSON with exact JSON types,
no NaN/Infinity. `delivery_id` is lowercase SHA-256 of every immutable field
except itself and delivery acknowledgement. Recompute at construction, store
read, queue boundary, and acknowledgement. Same id/different payload is
`crew_delivery_identity_conflict`; Python-equal bool/int aliases conflict.
Do not reuse a `CrewTrustEffect.outcome_id` or `evidence_sha256`: one terminal
revision may own multiple effects or none, while it always owns one delivery
identity.

Use a new `crew_delivery_outbox` table in the existing `workforce.db`, never a
new database. Primary key is `delivery_id`; also enforce uniqueness of
`(session_id, session_revision, outcome)`. Store the exact canonical payload,
`delivered`, `created_at`, and `delivered_at`, with a pending index. Reject
oversize rows; never truncate. Do not reuse `crew_trust_outbox`: blocked and
infrastructure-failure outcomes may intentionally have no trust effect.

Every CrewSession outcome commit inserts its delivery row in the same store
transaction:

- ordinary blocked/generic failed transitions through the CrewSession metadata
  CAS;
- verified `done` publication alongside the child barrier and AD-1130 trust
  effects;
- verified `failed` publication alongside the terminal contract and AD-1130
  trust effects.

Compose with the live AD-1130 signatures rather than replacing them:

- extend `merge_work_item_metadata(..., new_status=..., source=...)` with one
  optional typed delivery record for ordinary blocked/generic-failed commits;
- extend `publish_work_item_metadata_with_child_barrier(...,
  crew_trust_effects=(), source=...)` with one optional typed delivery record;
- extend `transition_crew_session_terminal_with_trust(...,
  crew_trust_effects=..., source=...)` with one required delivery record; and
- add an exact delivery-row proof parallel to, not folded into,
  `has_exact_crew_trust_outcomes(...)`.

`CrewSessionService.transition`, `publish_verified_result`, and
`fail_verified_outcome` build the record from the validated candidate contract
and pass it into the owning transaction. Preserve AD-1130 effect validation,
cardinality, payloads, and recorder behavior byte-for-byte outside the minimal
signature composition.

Precommit cancellation produces neither outcome nor delivery row. If commit
ambiguity reconciliation proves the exact outcome committed, it must also
prove the exact delivery row, plus the exact trust rows whenever that outcome
has effects, before treating the transition as authoritative. Do not insert
after a transition returns.

### DD-2 - Deterministic notification sink; ordinary queue behavior unchanged

Add a fully annotated `NotificationQueue.notify_once(...)` (or equivalently
narrow public API) accepting the complete deterministic notification record.
It inserts and emits when the id is absent, returns the existing object without
another event when all immutable fields match, and raises an identity conflict
when the id exists with different immutable content. Ignore mutable
`acknowledged` when checking identity and preserve its current value.

Do not change `NotificationQueue.notify(...)`, UUID generation for ordinary
notifications, acknowledgement, snapshot ordering, or pruning. AD-846 keeps
using its Ward Room DM primitive, not `notify_once`.

The delivery service validates that `thread_id` names an existing,
non-archived thread whose `task_id == session_id`; otherwise it logs why the
row remains pending and what will retry it. It calls `notify_once`, then marks
the row delivered using exact `delivery_id + session_id + revision + outcome`
CAS. `notify_once` inserts before invoking its callback: if that callback
raises, the exact queue entry remains authoritative, the outbox remains
pending, and retry finds that one entry without another notification event.

Treat every delivered-mark return as commit-ambiguous. After exactly one mark
attempt, whether it returns `True`, `False`, or `None`, raises an ordinary
exception, or raises `CancelledError`, perform one cancellation-deferred
authoritative reread through
`get_exact_crew_session_delivery(record, *, session_id, session_revision,
outcome) -> CrewSessionDeliveryOutboxEntry | None`. It queries one row under the
store lock, parses/recomputes the complete delivery identity, and returns only
an exact entry; missing returns `None` and malformed/conflicting identity
raises. Preserve `has_exact_crew_session_delivery(...)` for outcome-commit
ambiguity and implement both from the same exact-row decoder. Count delivery
success only when the reread entry has `delivered=True`.

An ordinary post-commit error is therefore success when the reread proves the
acknowledgement; an ordinary error/false/None result with an exact still-pending
row logs and returns no success so a later bounded drain retries. Missing,
malformed, or identity-conflicting rows fail closed. Preserve the first
`CancelledError`, finish the authoritative reread despite later cancellation,
then re-raise that first cancellation even when the row is proven delivered.
Never issue a second mark in the same pass. This is reconciliation, not a
second write, and retry cannot create a second logical queue entry.

### DD-3 - Safe content and ownership

Both Captain-originated and agent-self-originated CrewSessions surface in the
Captain notification queue. Attribution differs and must use the immutable
contract, never `owner_ids` inference:

- `origin="captain"`, `originator_id="captain"`: ownership `captain`, author
  is the facilitator who reports the result;
- `origin="agent"`: ownership `self`, author is exactly `originator_id`.

`owner_ids` is the crew roster, not Captain ownership. Never resolve current
rank/trust/registry state to rewrite historical authorship.

Use fixed safe content only:

| Outcome | Type | Title | Detail |
|---|---|---|---|
| `done` | `info` | `Crew session completed` | `Open the existing crew room for details.` |
| `failed` | `error` | `Crew session failed` | `Open the existing crew room for details.` |
| `blocked_needs_captain` | `action_required` | `Crew session needs Captain input` | `Open the existing crew room for details.` |

Set `agent_type="crew_session"`, `department="operations"`,
`action_url="thread:<thread_id>"`, `suggested_action=None`, and notification
`created_at=occurred_at`. Do not include goal, result summary/body, blocked
reason, critique, evidence, token usage, filenames, artifact ids/refs/bytes,
attachment ids, secrets, roster, or trust values in the outbox, notification,
event, metric, or log.

### DD-4 - Minimal CrewSession events and exact AD-846 compatibility

The runtime emits local and NATS events as a dict envelope:
`{"type": ..., "data": ..., "timestamp": ...}`. At the WorkItemStore event
serialization boundary, every `WORK_ITEM_CREATED`, `WORK_ITEM_UPDATED`, and
`WORK_ITEM_STATUS_CHANGED` path must project a CrewSession parent as exactly
`{"id": <id>, "work_type": "crew_session", "status": <status>}`. This applies
to admission, metadata CAS, plan install/adoption, verified publication,
verified failure, and every other store path that emits one of those three
events. Keep existing event-level keys such as `old_status`, `new_status`, and
`source`; only the nested CrewSession `work_item` projection is minimized.
No title, description, metadata, result, blocked reason, artifact, owner, or
sentinel may enter a CrewSession WorkItem event.

For every non-session WorkItem, preserve the existing full `WorkItem.to_dict()`
projection byte-for-field so AD-846 still receives `title`, `tags`, and
`metadata.dispatchable`. Centralize the conditional projection in one private
WorkItemStore helper and route all three event families through it; do not fix
only the terminal paths.

The AD-1131 listener accepts the exact dict envelope, requires only
`data.work_item.id`, ignores all other event-carried content, and loads pending
delivery rows from the store. A malformed event or a late event after delivery
service closure is a bounded no-op.

AD-846 currently reads attribute-style `event.data`, while its live registration
receives the dict envelope. Add only the minimal dual-shape extraction needed
for the real dict and existing compatibility fixtures, plus the explicit
CrewSession rejection. Preserve every non-session gate and DM effect. Prove
that dict and object envelopes produce exactly equivalent non-session channel,
thread, author, title, and body effects, using a real full WorkItem projection.

### DD-5 - Deterministic bounded session metrics from CrewSession WorkItems

The old outcome-sample metrics are superseded. Remove the delivery-outbox metric
query and do not retain compatibility aliases for its outcome, delivery-rate,
or outcome-latency fields. Expose a fully typed internal method on the existing
`CrewSessionService`:

`metrics(*, days: int = 30, limit: int = 1000) -> CrewSessionMetrics`

Use the service's already injected server clock. Capture it exactly once per
call; do not accept caller-supplied `now` and do not call `time.time()` from the
metric calculator. Do not add an API/router/HXI surface in AD-1131.

Bounds are exact: `days` is a real int in `[1, 365]`; `limit` is a real int in
`[1, 10_000]`; bools and `None` are invalid. The one captured clock value must
be a finite non-negative timestamp. Add a dedicated WorkItemStore query that
selects only `work_type = 'crew_session'` rows whose WorkItem `created_at` is
in the inclusive window `[now - days*86400, now]`, ordered newest first by
`(created_at DESC, id DESC)`, with SQL `LIMIT limit+1`. The service passes at
most `10_001`; no generic `list_work_items`, offset paging, outbox join,
post-query unbounded scan, or current-state rescan is permitted. Report
`truncated=True` when the extra row exists and compute only over the first
`limit` sessions.

Return this exact zero-safe projection:

- `days`, `limit`, `window_start`, `window_end`, `sessions_started`,
  `truncated`;
- `done_count`, `failed_count`, `artifact_count`, `verified_count`;
- `done_rate`, `failed_rate`, `artifact_rate`, `verified_rate`;
- `duplicate_resume_count`;
- `time_to_first_result_p50_seconds`,
  `time_to_first_result_p95_seconds`;
- `blocked_duration_seconds`.

The denominator for all four rates is `sessions_started`, the number of valid
selected CrewSession WorkItems, never outcomes, revisions, delivery rows,
trust effects, or only-terminal sessions. `done_count` and `failed_count` use
the current strict contract state. `artifact_count` counts non-None
`result_artifact_id`; `verified_count` counts non-None `verified_at`. Rates are
rounded to six decimals and are `0.0` when no session started.

Sum each contract's `duplicate_resume_count` exactly. For each session with a
`first_result_at`, calculate `first_result_at - created_at`; sort those finite
non-negative values and use nearest-rank
`max(0, ceil(p*n)-1)` for `p=.50/.95`, rounded to three decimals. An empty
first-result subset returns `0.0` for both percentiles. Do not interpolate.

For blocked duration, sum every contract's accumulated
`blocked_duration_seconds`; for a session currently in
`blocked_needs_captain`, also add `captured_now - blocked_since`. The captured
clock must not precede `blocked_since`; reject clock regression rather than
subtracting a negative duration. Round the final sum to three decimals. A
non-blocked contract contributes no live increment.

Validate every returned WorkItem and strict `metadata.crew_session` contract,
including exact task id, created timestamp, facilitator assignment, and status
projection. A missing/malformed contract, bool/int alias, non-finite value,
future live-block timestamp, query result exceeding `limit+1`, or row/order
contract violation raises a stable `crew_session_metrics_*` `ValueError`; do
not skip a bad row and silently change the denominator. The empty window
returns `sessions_started=0`, `truncated=False`, integer counts/sums at zero,
and every rate/duration/percentile as `0.0`.

Never inspect `crew_delivery_outbox`, `crew_trust_outbox`, trust receipts,
current trust scores, notifications, event payloads, or room messages for a
metric. Delivery identity/outbox semantics remain unchanged and independent.

### DD-6 - Dual startup drain error precedence

The existing startup seam must invoke both `CrewSessionTrustRecorder` and
`CrewSessionDeliveryService` drains exactly once in the fixed trust-then-
delivery order even when the first raises. Capture errors rather than exiting
early. After both attempts, re-raise the first `CancelledError` in call order
if either drain was cancelled; otherwise re-raise the first ordinary exception
in call order. A later ordinary error must never mask an earlier or later
cancellation. Successful drain results remain independent and neither drain
acknowledges the other pipeline.

### DD-7 - Delivery callback ownership and shutdown barrier

Wire one `CrewSessionDeliveryService` beside the existing CrewSession services
in `startup/finalize.py`, register one listener for
`work_item_status_changed`, and invoke one awaited bounded pending drain from
the existing AD-1127 startup/recovery seam after WorkItemStore and thread store
are ready. Hold no new background task, timer, poller, daemon, or retry loop.

Wire and drain it independently of AD-1130's `CrewSessionTrustRecorder`.
Failure, cancellation, pending state, or successful acknowledgement in either
pipeline must not gate, acknowledge, or synthesize evidence for the other.

The delivery service, not the runtime's generic listener-task set, owns every
event callback task. Register a synchronous listener that calls one public
non-awaiting service admission method. While open, that method creates one
task, stores a strong reference before returning, observes/logs its ordinary
failure without payloads, and removes it on completion. This finite task is
allowed; no timer, poller, daemon, or retry loop is.

Add an idempotent async `close()` owned by the service. It synchronously closes
callback admission before taking the task snapshot, then cancellation-
deferred drains every admitted task. Preserve and re-raise the first
`CancelledError` only after all tasks finish; ordinary callback failure is
already observed and leaves durable rows pending. A callback invoked after the
gate closes is a no-op and cannot touch the WorkItemStore or queue.

In production shutdown, remove the exact registered listener, clear the
runtime listener reference, await service `close()`, and clear the service
reference before `WorkItemStore.stop()` can close its database. Repeated or
partial shutdown remains idempotent. A stale local/NATS callback that races
listener removal reaches the closed gate and does nothing.

An admitted event drains its exact pending session/revision and may perform one
bounded pending pass. Startup drains at most the explicit service limit and
logs a bounded backlog count/overflow without payloads. Restart with a fresh
queue and real reopened stores retries pending rows with the same notification
ids. Already-delivered rows do not re-notify. Listener wiring must not duplicate
on restart or repeated finalize calls.

## Implementation Surface

Allowed production paths only:

- `src/probos/crew_session_delivery.py` - strict records, service, and
  delivery lifecycle/reconciliation only;
- `src/probos/notifications.py` - deterministic exact-id insertion only;
- `src/probos/workforce.py` - existing-DB outbox, atomic enqueue, minimal event
  projection, exact delivered CAS/reread, and bounded CrewSession WorkItem
  metric query;
- `src/probos/cognitive/crew_session.py` - pass typed delivery records through
  existing outcome commits/reconciliation and calculate session metrics from
  validated WorkItems using its injected clock;
- `src/probos/startup/finalize.py` and its sole existing awaited CrewSession
  recovery caller - construct, register, dual-drain, and bounded-drain only;
- `src/probos/startup/shutdown.py` - remove the delivery listener and await the
  service close barrier before `WorkItemStore.stop()` only;
- `src/probos/runtime.py` only if its structural/public service annotation is
  required;
- `src/probos/task_completion_notifier.py` - actual dict envelope support and
  explicit CrewSession exclusion only.

Allowed tests only:

- `tests/test_ad1131_crew_session_delivery_metrics.py` (new, primary);
- `tests/test_notifications.py`;
- `tests/test_ad846_completion_dm.py`;
- existing AD-1126/1127/1130 CrewSession files only for exact fixture,
  signature, cancellation, or static-guard changes forced by the implementation.

The shutdown-order regression lives in the primary AD-1131 test file; no
additional shutdown test path is authorized.

If an outcome path cannot enqueue inside its existing transaction, or startup
cannot await a bounded drain through the live recovery seam, hard stop for
Architect review. Do not solve either with post-hoc writes or a task loop.

## Required Tests

Use real `WorkItemStore` databases under `tmp_path`, real CrewSession contracts
and transitions, real thread store/room records, and real `NotificationQueue`.
Narrow probes are allowed for startup error ordering. Strict fault adapters may
delegate to a real public store/queue method and then raise to model the
specified post-commit, callback, and shutdown boundaries. Do not replace the
authoritative store, queue identity, CrewSession contract, or production
composition path with a mock.

These exact test names are mandatory and use real public boundaries:

1. `test_metrics_real_19_session_fixture_reports_zero_completion_and_six_resumes`
  creates 19 real CrewSession parent WorkItems through the public admission and
  CrewSession service APIs, performs six real equivalent resumes through
  `open_or_resume`, and leaves every session nonterminal with no artifact or
  verification. Assert `sessions_started == 19`, all done/failed/artifact/
  verified counts and rates are zero, `duplicate_resume_count == 6`, empty
  first-result percentiles are `0.0`, and delivery/trust rows cannot affect it.
2. `test_metrics_session_window_boundaries_and_nearest_rank_percentiles`
  proves inclusive start/end, outside exclusion, `(created_at DESC, id DESC)`
  ties, `limit+1` truncation, denominator semantics, nearest-rank p50/p95, and
  accumulated plus current blocked duration from one captured injected clock.
3. `test_crew_session_events_are_minimal_and_sentinel_free` captures real
  created/updated/status events from public CrewSession operations and asserts
  every nested item is exactly `{id, work_type, status}` with no sentinel.
4. `test_delivery_mark_postcommit_error_reconciles_authoritative_ack` delegates
  to the real store mark, raises afterward, and proves the exact reread returns
  success with one queue entry/event.
5. `test_delivery_mark_postcommit_cancellation_propagates_without_duplicate`
  delegates to the real mark, raises `CancelledError` afterward, proves the
  exact reread completed before the first cancellation propagated, then proves
  retry creates no queue duplicate or event.
6. `test_startup_dual_drain_never_masks_cancellation` covers ordinary/cancel
  combinations in both positions, proves both drains ran, and asserts the
  cancellation-first/otherwise-first-ordinary precedence rule.
7. `test_delivery_shutdown_waits_for_inflight_drain_before_store_close` uses
  the production shutdown path, blocks one admitted callback, closes admission,
  proves a late callback is a no-op, and proves store stop occurs only after
  the original callback finishes and service close completes.
8. `test_notify_once_callback_failure_retains_one_logical_queue_entry` uses a
  real queue callback that raises after insertion, then proves replay observes
  one id/entry/event and acknowledges the durable row.
9. `test_ad846_dict_and_object_envelopes_are_exactly_equivalent` runs the same
  non-session full projection through both envelope shapes and compares exact
  channel/thread side effects.

Retain the existing delivery/outbox matrix: all three outcomes and both origin
types; blocked-resume-done revision identity; repeated/concurrent real events;
exact duplicate versus bool/int conflict; ordinary `notify()` parity; invalid
room repair; real-store restart replay; transaction rollback/commit ambiguity
with zero-to-many AD-1130 effects; and sentinel/privacy/static-scope guards.

Explicitly cover queue failure before insertion, callback failure after one
logical insertion, and cancellation before/after outcome commit. Normal
`True`/`False`/`None`, ordinary error, and cancellation around delivered marking
all perform the same exact reread; only authoritative `delivered=True` counts
as success, and first cancellation then propagates. DD-5 tests include empty and
one-row windows, invalid bounds/clock, malformed contracts and bool aliases,
projection mismatch, clock regression, over-return, and no row skipping.

The nine named tests must not seed outcome rows with private SQL, call private
insert helpers, hand-build primary CrewSession contracts, or test a wrapper
that production does not call. Strict fault adapters may delegate to real
public methods and then raise to model post-commit ambiguity. Direct corruption
is permitted only in a narrowly named malformed-row test where no public API
can create invalid state.

## What This Does Not Change

- No external Discord/Slack/Teams/email/desktop delivery and no new DM for a
  CrewSession. No new room/thread/post; link the existing room only.
- No billing, pricing, commercial overlay, HXI/dashboard, API/router/shell,
  WebSocket/live push, config/YAML, dependency, episode, trust/Hebbian/Shapley,
  result publication, or CrewSession state-machine redesign.
- No new EventType. Existing generic WorkItem events remain the only trigger.
- No AD-1132 projection/dashboard and no AD-1133 trackers/archive/broad gate/push.
- No tracker, decision-log, roadmap, prompt archive, GitHub, or push operation.
- No AD-846 non-session policy/content/channel change beyond accepting the live
  dict envelope; no automatic every-task or every-chat notification.

## Acceptance Criteria

- Each committed done/failed/blocked outcome revision has one exact durable
  delivery identity, one safe notification, and the existing room link.
- Captain versus self origin is derived only from immutable CrewSession
  provenance; attribution is correct for both.
- Outcome + outbox commit is atomic; queue + delivered mark is replay-safe and
  idempotent without claiming a cross-resource transaction.
- AD-1130 trust effects/receipts and AD-1131 delivery facts remain independent:
  neither pipeline's retry or acknowledgement controls the other or metrics.
- Repeated/concurrent events, failures, cancellation, and real restart satisfy
  the required no-loss/no-duplicate tests.
- Metrics implement the exact bounded session window, sessions-started
  denominator, four rates, duplicate-resume sum, nearest-rank time-to-first-
  result, live blocked-duration, truncation, malformed, and empty semantics.
- AD-846 non-session behavior is preserved against the empirical live event
  shape; CrewSession event items are minimal and CrewSession delivery never
  creates a DM or room.
- Delivered-mark reconciliation proves the exact authoritative row after every
  return/error/cancellation and never masks the first cancellation.
- Both startup drains always run with cancellation precedence; delivery close
  drains its owned callback tasks before WorkItemStore closes.
- The exact build base is `d463a114`.
- Both prompt SHA-256 values and byte lengths are mechanically frozen, with
  combined size below 50,000 bytes, before code.
- All coding/tests precede one scoped `-n 16 --dist=worksteal` batch; three
  Architect implementation reviews approve before the exact local unpushed
  commit; broad gate remains AD-1133.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Live Codebase (2026-07-22)

- `events.py:99-101`: reuse the three generic WorkItem event values.
- `workforce.py:619-685,2132-2177`: WorkItem carries `created_at`, type, status,
  metadata; generic listing has the wrong priority ordering for #1050.
- `crew_session.py:1781-2010,2238-2266`: the strict contract has all metric
  fields and `CrewSessionService` already injects a clock.
- `crew_session.py:2122-2152,4335-4749` and `workforce.py:3327-3731`: live
  AD-1130 transaction/proof signatures carry zero-to-many trust effects.
- `crew_trust.py:110-227,606-690` and `trust.py:588`: trust identity, drain, and
  serialized receipt writing are a separate pipeline.
- `workforce.py` has 19 `work_item: *.to_dict()` event projections; all three
  CrewSession event families need one minimizing helper.
- `notifications.py:97-139`: `notify_once` inserts before callback emission.
- `workforce.py:3962-4066` and `crew_session_delivery.py:527-650`: mark lacks an
  exact post-call reread and metrics still use delivery rows.
- `runtime.py:1289-1422`: add/remove listener APIs exist; async listeners use
  the runtime's generic task set.
- `task_completion_notifier.py:34-137`: AD-846 needs full non-session fields and
  supports the established Yeo DM behavior.
- `startup/finalize.py:1935-2040`: listener is async and dual-drain precedence
  currently lets a trust ordinary error mask later delivery cancellation.
- `startup/shutdown.py:785-788`: WorkItemStore stops before AD-1131 service
  removal/close; insert the barrier here.

## Prompt Review Record

### Pass 1 - Session metric authority and bounds

**Verdict: APPROVED.** Issue #1050 now reads bounded CrewSession WorkItems,
uses sessions started as the sole denominator, captures one injected clock,
defines exact rates/resumes/percentiles/blocked time, and removes the
superseded delivery-outcome metric model rather than appending a second model.

### Pass 2 - Reconciliation, cancellation, and lifecycle

**Verdict: APPROVED.** Mark return/None/error/cancellation all end in an exact
authoritative reread; post-commit success is recognized, first cancellation is
preserved, both startup drains run, and service-owned callback admission closes
and drains before WorkItemStore shutdown.

### Pass 3 - Event privacy, compatibility, and scope

**Verdict: READY.** CrewSession created/updated/status events expose only the
three-key item projection, non-session AD-846 dict/object effects remain exact,
the nine named public-boundary regressions are mandatory, and delivery
identity/outbox/privacy plus AD-1130 trust isolation remain unchanged. No new
EventType, AD-1132, AD-1133, config, tracker, archive, or commercial work is in
scope.
