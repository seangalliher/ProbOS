# AD-1130: Outcome-Only CrewSession Room Trust

**Status:** CONTENT-READY - mechanical hash/size binding pending
**Issue:** #1049
**Type:** Enhancement; build AD-1130 only
**Code-review/repair base:** supplied `5f008fcc` plus the live uncommitted AD-1130 implementation; preserve those production/test bytes until the prompt-authorized repair
**Repair-tree rule:** do not reset, stash, rebase, rebuild, or discard the live AD-1130 tree. Before repair, verify its dirty production/test paths are an exact subset of this prompt's allowlist plus these two active AD-1130 prompts. Ignore every AD-1131 prompt.
**Planning ceilings before AD-1130:** AD-1129 / BF-673
**Primary dependencies:** AD-1126 verified finalization and AD-1127 lifecycle recovery; AD-1128 supplies ingress; AD-1129 is the required sequencing base but not a behavioral dependency
**Execution authority:** `prompts/ad-1130-outcome-only-room-trust-execution.md`
**Code-review base:** supplied local base `5f008fcc`; this prompt-only compaction does not mutate or certify production/test bytes
**Prompt binding placeholder:** main SHA-256 `<MEASURED_AT_REPAIR_HANDOFF>`, bytes `<MEASURED_AT_REPAIR_HANDOFF>`; execution SHA-256 `<MEASURED_AT_REPAIR_HANDOFF>`, bytes `<MEASURED_AT_REPAIR_HANDOFF>`; combined bytes `<MEASURED_AT_REPAIR_HANDOFF>` and must be `< 50000`
**Binding step:** before any repair, mechanically report and freeze all placeholder values. Never transcribe or predict them; any later prompt-byte change is a hard stop.

## Decision

CrewSession trust is evidence-derived, terminal-outcome-only, and exactly-once.
No conversational agreement, role, rank, assignment, participation, attempted
governance bypass, or unverified assertion changes trust.

Use the existing `TrustNetwork` and its raw Beta `(alpha, beta)` records. Add a
durable idempotent outcome-receipt API inside the existing `trust.db`; do not
create another trust store and do not persist derived means. Couple each
CrewSession terminal transition to a bounded outbox in the existing
`WorkItemStore` transaction. Delivery uses the TrustNetwork receipt as an
inbox: a crash after trust application but before outbox acknowledgement is a
duplicate no-op on replay.

The finalizer derives effects only from AD-1126/1127 evidence it has already
validated. Session-specific `verify_for_session()` and
`synthesize_for_session()` remain free of learning writes. The legacy
non-session `verify()` and `synthesize()` behavior is not redesigned here; add
static and behavioral guards proving CrewSession never reaches those immediate
side effects.

AD-1129 is the sequencing base only. Its TrustNetwork use is read-only
`get_score()` for rank; do not edit/review its Tool or identity behavior.

The binding repair has three parts: receipt post-state migration plus durable
raw-state reconciliation before acknowledgement; deterministic configured
$O(n)$ Shapley attribution for large accepted vote sets; and exact pre-mutation
`RuntimeError("trust_write_in_progress")` for synchronous overlap, with only
the audited caller guards below. No stale score or equal-share replacement is
allowed.

## Binding Outcome Policy

An effect exists only when the named producer action or independent verifier
judgment actually ran and the durable evidence below adjudicates it. Effects
are immutable, individually identified, and never inferred from prose.

| Durable terminal evidence | Producer effect | Verifier effect |
|---|---|---|
| Parent reaches `done`, child final revision is accepted | One success for that child producer; intermediate corrected revisions do not separately penalize it | One success for the final accepting verifier; each earlier valid refutation followed by an actual correction revision is also a correct-rejection success |
| Parent reaches `done`, final synthesis is accepted and published | One success for the facilitator | One success for the final verifier |
| Child ends `convergence_exhausted` after a valid final refutation and parent reaches `failed` | One failure for that child producer; no success for other producers because parent completion failed | Every valid refuting verifier in the admitted history receives success |
| Final synthesis is validly refuted and parent reaches `failed` with `final_verification_refuted` | One failure for the facilitator; no child/facilitator success | The final refuting verifier receives success; never failure |
| A refutation is followed by a valid corrected revision that is later accepted and the parent reaches `done` | The producer receives the one final success, not an intermediate failure | The refuting verifier receives success because the correction proves the rejection useful/correct |
| `independent_verifier_unavailable`, malformed/error verdict, verification defect, producer unavailable, invalid child, synthesis defect, result-publication failure | No effect | No effect |
| Governance denial, `blocked_needs_captain`, correction capability denial, budget block, no attempted correction, no attempted verifier | No effect | No effect |
| Cancellation before the terminal session/outbox transaction commits | No effect and no outbox row | No effect and no outbox row |

Cancellation after a terminal transaction commits is delivery interruption,
not a cancelled outcome. It must propagate immediately; the committed pending
effects are applied exactly once by restart reconciliation.

Correct rejection always rewards the verifier. A verifier is never penalized
because it returned `accepted=False`. A verifier with status `unavailable`,
`malformed`, or `error` receives nothing. A producer receives failure only for
a validly verified terminal failure, never for governance or infrastructure
failure.

Successful producer weights reuse the existing
`compute_shapley_values(...)` path over exactly one final accepted Vote per
child producer plus one accepted facilitator Vote. Use the live quorum policy.
For at most `MAX_EXACT_SHAPLEY` votes, preserve that exact path. Above that
bound, do not call its unseeded Monte Carlo branch and do not blanket equal-
share. This CrewSession game contains only accepted votes, so compute its exact
policy-equivalent result in $O(n)$ over unique, sorted synthetic vote keys:
with confidence weighting, each strictly positive-confidence vote receives
raw `1 / positive_count` and each zero-confidence vote receives raw `0`; if
all confidences are zero, preserve the shared API's all-zero fallback `1 / n`.
Without confidence weighting, every vote receives `1 / n`. Positive confidence
magnitude does not change pivotality in this all-approved utility; zero versus
positive does. Then apply `max(shapley_value, 0.1)` once to every admitted
producer/facilitator, including a zero-confidence voter, and do not renormalize
the floored effects. Verified producer failures and correct verifier judgments
use weight `1.0`. Never perform exponential exact enumeration above the bound.
Before either size path, sort validated children by exact `work_item_id`; use
that order for vote construction and child producer/verifier effects, followed
by facilitator and final-verifier effects. Repeat derivation and persisted
restart reconstruction therefore return the same ordered effect payloads and
ids even if the input tuple order differs.
All weights still pass through existing TrustNetwork dampening/floor/cascade
rules. Shapley determines strength only; it creates no rank, score store, or
Hebbian edge.

## Exact Durable Contract

### 1. Typed effects

Add frozen, strictly validated boundary records (location may be
`cognitive/crew_trust.py`, with TrustNetwork input type in `consensus/trust.py`):

- `CrewTrustEffect`: `outcome_id`, `session_id`, terminal `session_revision`,
  `evidence_sha256`, `agent_id`, `role` (`child_producer`, `child_verifier`,
  `facilitator`, `final_verifier`), `work_item_id`, `result_revision`,
  `success`, finite `weight`, `intent_type`, `verifier_id`, and
  `source="crew_session_outcome"`.
- `TrustOutcomeWriteResult`: exact disposition `applied` or `duplicate` plus
  resulting raw `alpha` and `beta`; do not return or persist a mean.

Canonicalize the effect with exact JSON types, sorted keys, compact UTF-8, and
no NaN/Infinity. `outcome_id` is lowercase SHA-256 of all identity/semantic
fields except itself. Recompute at every boundary. Python-equal but JSON-type-
different payloads conflict; `True` must never alias `1`.

Identity includes the resulting terminal session revision and exact evidence
hash, so a retry of the same outcome is duplicate while a different payload
under the same id is `trust_outcome_identity_conflict`. Child effects bind the
persisted `ChildVerificationRecord` hash and its exact result revision. Final
effects bind the final-verdict/provenance evidence hash. Never key on thread
title, summary text, timestamp, or current trust mean.

### 2. Existing TrustNetwork as inbox authority

Extend `_SCHEMA` in `src/probos/consensus/trust.py` with one receipt table in
the same existing database as `trust_scores`. It stores the outcome id,
canonical payload hash/identity fields, and creation time. It is an idempotency
receipt, not another trust ledger. The live receipt plus its current
`trust_scores` row does not by itself preserve the effect's exact historical
post-state after later updates or removal. Extend this existing table in place
with nullable `result_alpha REAL` and `result_beta REAL`; new databases declare
them `NOT NULL`, while startup performs the smallest idempotent SQLite migration
for existing tables. This is receipt metadata, not a new trust store. Never add
a second table/database or before-state columns.

Add one fully annotated async public API such as
`record_outcome_once(effect) -> TrustOutcomeWriteResult`. It must:

1. Reject invalid/unbounded fields before DB or in-memory mutation and require
   the durable TrustNetwork DB to be started.
2. Under the existing async lock, use `BEGIN IMMEDIATE`. A new outcome persists
  its planned `trust_scores` row and exact receipt, commits, and only then
  publishes cache/dampening/event/callback/floor/cascade effects.
3. Every new receipt atomically stores the plan's exact finite positive
  `result_alpha/result_beta`. Every duplicate reads that exact receipt and a
  left-joined current `trust_scores(alpha, beta)` row on the same connection in
  one transaction snapshot. Validate canonical identity and receipt result.
  If the current row exists, validate it and reconcile `_records[agent_id]` to
  that current pair; if absent, remove any cached record because durable
  removal is authoritative. `TrustOutcomeWriteResult` returns the receipt's
  exact historical result pair in either case. End the DB transaction before
  changing cache, but retain the async lock throughout. Never replay dampening,
  events, callbacks, floor counts, or cascade effects on an ordinary duplicate.
  Duplicate reconciliation is read-only and never writes cache back to the
  database. A newer durable current row always wins; durable row absence is an
  authoritative removal.
4. Receipt lookup is tri-state: authoritative absence, exact receipt plus raw
  row, or raised storage/corruption error. Remove the live helper's
  exception-to-`None` normalization. A read failure is never absence or
  success and leaves the workforce outbox pending. Existing migrated receipt
  rows whose result columns are null are `trust_outcome_receipt_result_missing`;
  do not infer/backfill them from a later current trust row. They fail closed
  for explicit operator repair because exact historical post-state is lost.
5. A commit exception is ambiguous until the same receipt+raw snapshot proves
  absence or exact durability. Proven absence clears ambiguity and re-raises
  the original error with no publication; a later retry performs a normal new
  write. Proven exact durability reconciles raw cache, publishes only the
  retained plan's transient dampening/event/callback/floor/cascade effects once
  in that live process, and returns `applied`, except cancellation is re-raised
  after reconciliation/publication so the outbox remains pending. Transient
  publication must not assign the retained plan's alpha/beta over the
  just-reconciled current raw pair.
  If that immediate read also fails, retain the exact effect and unpublished
  plan as a single bounded reconciliation reservation, propagate the original
  `BaseException`/cancellation, and gate all trust mutations. Only a retry of
  that exact outcome may read authority: exact durability reconciles and
  publishes only those retained transient effects once without replacing the
  reconciled current raw pair; proven absence clears the reservation and
  performs one normal write; another read failure retains it. A different
  outcome raises exact `RuntimeError("trust_outcome_reconciliation_required")`.
  No unresolved path permits outbox acknowledgement.
6. While that reservation exists, `_save_to_db()` raises exact
  `RuntimeError("trust_outcome_reconciliation_required")` before `DELETE` or
  any write. `stop()` must not save stale cache over the durable row; it closes
  the connection and propagates the reconciliation failure. Fresh restart
  loads authoritative `trust_scores`, and pending outbox replay acknowledges
  only after exact duplicate validation. Same-process recovery publishes the
  retained plan at most once; restart does not recreate transient events.
7. Preserve healthy synchronous `record_outcome()` behavior, signature, and
  result, but remove `_queued_sync_outcomes` and all flush/deferred-success
  behavior. Because it cannot await the async lock, any call while an async
  outcome transaction or reconciliation reservation owns shared trust state
  raises exact `RuntimeError("trust_write_in_progress")` before planning,
  cache/dampening/event/cascade mutation, persistence, or return. Do not
  convert it to async and do not block the event loop waiting for ownership.
8. Audit every direct TrustNetwork caller. Existing catch-and-degrade boundaries
  remain. Add busy-only log-and-degrade around currently unguarded noncritical
  observations so unrelated completed work is not falsely failed. Match the
  exact message only; any other `RuntimeError` must continue through the
  caller's pre-existing outer catch or propagation boundary. Do not queue/retry
  or claim a skipped adjustment occurred. The exact caller allowlist is below.
9. Share one internal calculation path so successful writes retain hard floor,
  dampening, tier filtering, event emission, and cascade detection.

### 3. WorkItemStore terminal outbox

Add a bounded `crew_trust_outbox` table to the existing `workforce.db`, not to a
new database. One immutable row holds the exact effect payload and delivery
state. Primary key is `outcome_id`; duplicate exact enqueue is idempotent and a
different payload conflicts.

The `done` publication transaction and every eligible verified-failure
transition must insert all derived effects in the same `BEGIN IMMEDIATE`
transaction that validates the expected parent revision/row invariants and
commits the resulting terminal session revision. No generic post-transition
`insert` is acceptable. Generic failures/blocks pass an empty tuple.

Bound effects to `(_MAX_WORK_ITEM_DIRECT_CHILDREN * 10) + 2`: at most nine
verifier rounds plus one producer effect per child, then facilitator and final
verifier. Reject overflow; never truncate. Add narrow typed store methods to
list pending rows in deterministic order and mark one delivered using exact
`outcome_id + session_id + session_revision + evidence_sha256` CAS. Use the
existing row-write lock and exact JSON comparison.

### 4. Delivery and restart

Add one focused `CrewSessionTrustRecorder` service. It accepts narrow
WorkItemStore outbox methods and the TrustNetwork idempotent API. For each
pending row: validate/recompute identity, await `record_outcome_once`, then CAS
the outbox row delivered. Ordinary trust storage failure logs what failed, why
the pending row remains, and that restart will retry; it must not roll back a
completed/failed parent. Cancellation propagates and leaves the row pending.

The live finalizer drains effects only after the terminal session transaction.
The existing AD-1127 awaited startup/lifecycle recovery seam must also drain a
bounded batch before recovery reports complete. Do not create an unreferenced
task, loop, timer, daemon, or retry storm. A second explicit bounded pass may be
invoked by the next CrewSession finalization. Restart with a fresh
WorkItemStore and TrustNetwork must prove pending replay and delivered/receipt
duplicate no-op behavior.

### 5. Finalizer evidence

In `crew_finalizer.py`, derive effects from validated
`SessionConvergenceOutcome`, persisted `ChildVerificationRecord`, validated
final verdict, and the exact terminal transition candidate. Pass effects into
the specialized session/store terminal CAS; never inspect free-form critique
text. Generic `_fail(...)` branches have no effects unless they receive a
typed verified-failure adjudication. Parent success effects are constructed
only for `_publish(...)` and become deliverable only if
`publish_verified_result(...)` commits `done`.

Resume must reconstruct the same effects from AD-1127 checkpoints/persisted
verification and produce identical ids. Observation of an already-terminal
session may drain pending effects but must not derive a new effect from current
memory.

### 6. Social-room boundary

Preserve the existing default-off bounded AD-958 policy exactly when
`group_chat.conversation_trust_enabled=True` in a social room. In
`_record_conversation_trust(...)`, return before facilitator/extraction/trust
work whenever `thread.task_id is not None`. A task-linked room is a work room;
linguistic convergence there is not outcome evidence. Do not change social
weights, cap, peer-ring attribution, correction observation, or config/YAML.

## Implementation Surface

Allowed production paths only:

- `src/probos/consensus/trust.py`
- `src/probos/cognitive/crew_trust.py`
- busy-only caller compatibility, with no other behavior edit:
  `src/probos/avatars/divergence_detector.py`,
  `src/probos/cognitive/counselor.py`,
  `src/probos/cognitive/crew_verifier.py`,
  `src/probos/cognitive/dreaming.py`,
  `src/probos/cognitive/feedback.py`, `src/probos/proactive.py`,
  `src/probos/federation/peer.py`, `src/probos/ward_room_router.py`, and
  `src/probos/runtime.py`

Allowed tests only:

- `tests/test_ad1130_outcome_only_room_trust.py` (primary durability,
  sync-busy, analytic attribution, and static guards)
- for the exact busy-only caller branches only:
  `tests/test_ad722a_divergence_detector.py`,
  `tests/test_ad860_crew_verifier.py`,
  `tests/test_ad489_code_of_conduct.py`,
  `tests/test_bf206_confab_feedback.py`, `tests/test_dreaming.py`,
  `tests/test_feedback_engine.py`, `tests/test_proactive.py`,
  `tests/test_ad480_federation_mcp_a2a.py`,
  `tests/test_ward_room.py`, `tests/test_consensus_integration.py`, and
  `tests/test_system_qa.py`

`crew_finalizer.py`, `crew_session.py`, `workforce.py`, `thread_fanout.py`,
startup/recovery, and every other AD-1130 production/test surface are regression
inputs only and must remain byte-identical. Needing any path outside this exact
repair allowlist is an Architect hard stop.

Busy-only caller behavior is exact:

- avatar divergence still records divergence/history and Hebbian interaction;
- severe-conduct/confabulation counseling still sends/persists the response,
  but its DM and logs must say the trust adjustment was skipped, never applied;
- legacy verifier still returns its verdict; dreaming increments its adjustment
  count only for successful trust writes;
- feedback still applies Hebbian/episodic work, and its trust-update event names
  only successfully written agent ids and is omitted when none were written;
- proactive posts, duty accounting, and episodes continue; federation peer
  outcome timestamps continue; Ward Room endorsement remains committed but its
  trust-signal success log is omitted;
- runtime consensus verification still records the verification result,
  Hebbian edge, and completion event; runtime QA still returns/persists the QA
  report and continues episode/flag/removal policy. Busy skips are contextual
  warnings, not generic verification/QA failures.

## Required Tests

Use real `TrustNetwork` with a temporary `trust.db`, real `WorkItemStore` with
a temporary `workforce.db`, real CrewSession contracts/store CAS, and real
Shapley. Fakes are allowed only at LLM/registry/artifact edges.

Cover at minimum:

1. accepted child + accepted final publication: producer/facilitator/verifiers
   increase raw alpha, not stored means;
2. refuted then corrected-and-accepted: one producer success, correct rejecting
   verifier success, final accepting verifier success, no producer beta;
3. convergence exhausted: failed producer beta and rejecting verifier alpha;
4. final synthesis refuted: facilitator beta, final verifier alpha, no success;
5. no verifier, malformed/error, governance denial, blocked, no attempt,
   producer unavailable, publication failure, and precommit cancellation: no
   effect/outbox/raw change;
6. trust storage failure leaves pending, changes no raw values, and later retry
   applies once;
7. outbox acknowledgement failure after TrustNetwork commit replays as exact
   duplicate with no second alpha/beta/event/dampening change;
8. cancellation during delivery propagates and restart applies once;
9. duplicate finalize, duplicate drain, concurrent drainers, and full process
   restart produce one effect per outcome id;
10. same id/different exact JSON payload, including bool/int aliases, conflicts;
11. session revision/evidence change yields a different valid identity;
12. parent completion failure produces no success effects;
13. work room (`thread.task_id` set) produces no linguistic-convergence trust;
14. ordinary social room with feature enabled preserves the existing bounded
   AD-958 outcomes exactly; feature off remains byte-equivalent;
15. static guards: no mean persistence/rank/Hebbian/HXI/config/YAML; session
   path does not call legacy immediate trust writers.
16. migrate an old receipt table idempotently without a new table/store; new
  receipts persist exact result alpha/beta. A migrated legacy receipt with null
  result columns fails closed and is never inferred from the current row;
17. force a commit that durably writes raw+receipt and then raises, followed by
  a failed immediate receipt/raw reread: no outbox acknowledgement, no cache
  publication, save is blocked, repeated reread failure stays fail-closed,
  and exact same-outcome retry reconciles one raw update and one event;
18. repeat that ambiguity through `stop()` and a fresh TrustNetwork: stale
  cache never overwrites the committed row, the connection closes while the
  reconciliation error propagates, restart loads the durable pair, and the
  pending duplicate acknowledges without recreating an event;
19. stale the cache before an ordinary duplicate and prove receipt+current raw
  row repairs it. A durably removed current row removes stale cache while
  returning the receipt result; malformed/non-finite current or receipt values
  remain pending. Advance the durable current row after the ambiguous receipt
  commit and prove same-process recovery publishes the retained transient event
  once without replacing that newer current raw pair;
20. barrier-test synchronous `record_outcome()` during async transaction and
  reconciliation ownership: exact
  `trust_write_in_progress`, no stale return/queue, and no cache/dampening/
  event/cascade/persistence mutation. Healthy no-inflight calls preserve their
  existing results. Each newly allowlisted caller catches only that exact busy
  error, logs the skipped trust observation, and continues its already-
  completed non-trust work; another `RuntimeError` follows its prior boundary;
21. use at least 12 accepted votes with skewed positive and zero confidences.
  Prove weighted positive-only `1 / positive_count`, zero raw contribution,
  all-zero fallback, unweighted `1 / n`, post-normalization 0.1 floor without
  renormalization, stable child/effect ordering, and identical weights/effect
  ids on repeat and reconstructed input. Also prove <=10 still delegates to
  the live exact Shapley path and no large-set exponential/Monte Carlo/equal-
  share branch runs.

## What This Does Not Change

- No new trust store/database/table, before-state receipt field, shared Shapley
  API, derived mean persistence, rank/promotion policy, Hebbian update, episode,
  EventType, notification, metric, HXI/API/shell, or commercial behavior. Only
  the two exact post-state receipt columns and their idempotent migration are
  authorized.
- No generic conversation-correction penalty and no work-room trust from
  agreement, speaking count, assignment, or participation.
- No AD-1131+ work, tracker edit, prompt archive, push, GitHub mutation, or
  broad suite. AD-1133 owns consolidated trackers/archive/gate/push.
- No redesign of legacy non-session AD-860/861 or other trust semantics beyond
  exact `trust_write_in_progress` log-and-degrade at the audited noncritical
  boundaries and proof CrewSession uses side-effect-free session APIs.
- No AD-1129 EventLog Tool or authoritative-identity edit. AD-1129 is the exact
  local build base only, not an AD-1130 behavioral dependency.

## Acceptance Criteria

- The outcome matrix above is implemented exactly and only durable attempted
  outcomes affect raw alpha/beta.
- Correct rejection rewards the verifier and never penalizes it.
- Parent completion failure emits no producer/facilitator success.
- Terminal session CAS + outbox is atomic; TrustNetwork raw mutation + receipt
  is atomic; replay/restart is exactly-once without cross-database atomicity
  claims.
- Duplicate success requires one-snapshot receipt/current-raw validation and
  under-lock cache reconciliation. Ambiguous/repeated read failure blocks all
  trust mutation, save, shutdown persistence, and outbox acknowledgement until
  exact same-outcome retry or restart proves authority.
- Above ten all-approved votes, exact policy-equivalent $O(n)$ attribution
  preserves configured confidence weighting and zero/all-zero behavior; no
  Monte Carlo, blanket equal-share replacement, or unbounded enumeration runs.
- Synchronous writers never queue or return stale scores. Exact pre-mutation
  `trust_write_in_progress` is honest-degraded only at the allowlisted
  noncritical caller boundaries, without false update/applied claims.
- Existing enabled social-room bounded policy is preserved; every task-linked
  work room is excluded.
- The repair preserves the supplied `5f008fcc`-rooted live AD-1130 tree; no
  reset/rebase/rebuild, AD-1129 amendment, or AD-1131 prompt review occurs.
- Both compacted prompt SHA-256 values and byte lengths are mechanically
  frozen before coding; content approval alone does not authorize a build.
- One optimized changed-surface `-n 16 --dist=worksteal` batch passes after all
  coding; no per-AD full suite runs.
- Three Architect implementation-review passes approve contract, durability,
  and closeout evidence before the exact local unpushed commit.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Code-Review Verification Against Live Tree (2026-07-22)

- `consensus/trust.py:41` creates the existing receipt with identity fields but
  no raw-pair columns. Lines 283-311 queue a synchronous outcome and return
  `get_score()` while `_outcome_transaction_inflight`; lines 580-586 later
  flush that queue.
- `consensus/trust.py:588-704` owns the async transaction. The duplicate branch
  rolls back and returns the cache without reading `trust_scores`; the
  exception branch relies on `_read_outcome_receipt`; line 734 begins that
  helper and it normalizes every ordinary read failure to `None`. `_save_to_db`
  at line 895 begins with a full `DELETE FROM trust_scores` rewrite.
- `cognitive/crew_trust.py:337` derives completed effects; lines 395-402 call
  shared Shapley and then replace every >10-vote result with `1 / len(votes)`.
  `consensus/shapley.py:37` has no seed/RNG parameter; lines 108-124 use
  module-global `random.shuffle` for large sets, while lines 76-77 define its
  normalized all-zero equal fallback.
- Direct synchronous TrustNetwork writes are live at
  `avatars/divergence_detector.py:597,605`,
  `cognitive/counselor.py:1459,1721`,
  `cognitive/crew_verifier.py:1119`,
  `cognitive/dreaming.py:2535,2546`,
  `cognitive/feedback.py:112,192`, `proactive.py:1166,1385`,
  `federation/peer.py:100`, `ward_room_router.py:1079`, and
  `runtime.py:3280,5160`. Existing nearby log-and-degrade callers in
  capability/skill requests, ground truth, bridge, social fanout, device, and
  legacy synthesis require no compatibility edit.
- Existing focused tests are present at
  `test_ad860_crew_verifier.py:138,152`,
  `test_ad722a_divergence_detector.py:263-341`,
  `test_ad489_code_of_conduct.py:48-132`,
  `test_bf206_confab_feedback.py:364-427`,
  `test_trust_concurrency.py:216-323`,
  `test_feedback_engine.py:152-192`, `test_proactive.py:939-1075`,
  `test_ad480_federation_mcp_a2a.py:193-199`,
  `test_ward_room.py:1387-1481`,
  `test_consensus_integration.py:80-125`, and
  `test_system_qa.py:540-610`.