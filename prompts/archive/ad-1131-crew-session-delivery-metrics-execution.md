# AD-1131 Builder Execution: CrewSession Outcome Delivery and Metrics

**Status:** READY after three prompt-only reviews
**Binding specification:** `prompts/ad-1131-crew-session-delivery-metrics.md`
**Binding main SHA-256:** `8b222452451dac178d8bec4a49f0a09786959171a6ad0664e37700f3f70fbb8e`
**Required build base:** `d463a114`
**Authorized input hashes:** main `d8405c1eecbd857155fd9c8d068ffd3c959098da824fe118df927ef28864798b`; execution `cfeb75b2afd7a3d332399e839953cf6024597ab42182edadd5d53c95cc2c13ff`
**Planning ceilings:** AD-1130 / BF-673
**Scope:** AD-1131 / #1050 only

The main prompt is authoritative for event reuse and projection, delivery
identity/outbox ownership, safe notification content, mark reconciliation,
startup/shutdown lifecycle, AD-846 compatibility, session metric semantics,
allowed files, exact tests, and exclusions. This companion is authoritative
for coding-first sequencing, the single changed-surface batch, three
implementation reviews, local unpushed commit, and AD-1133 deferrals.

## 1. Handoff and Mechanical Freeze

Do not edit production/tests until all checks pass:

1. HEAD equals the supplied build base `d463a114`. Do not rebuild, amend,
  rebase, review, or narrow-validate AD-1130 here.
2. Highest planned numbers are AD-1130 and BF-673. AD-1131 is reserved for
   #1050; allocate no AD/BF and do not touch AD-1132/1133.
3. Dirty paths contain only these two active AD-1131 prompts. Mixed/uncommitted
   AD-1130 production, tests, prompts, or evidence is a hard stop.
4. Re-run the main prompt's live symbol checks. Confirm the AD-1130
  signatures still expose `crew_trust_effects` on child-barrier publication,
  the specialized verified-failure transaction, exact trust-row proof,
  `CrewSessionTrustRecorder`, and serialized `record_outcome_once`. Confirm
  the generic status event, CrewSession origin/revision contract, notification
  queue, AD-846 listener, room identity, and awaited recovery seam remain.
5. Mechanically freeze both prompt files before coding. The main SHA-256 must
  equal the literal binding value above; the execution SHA-256 and both byte
  lengths must equal the Architect handoff report:

```powershell
$paths = @(
  'prompts/ad-1131-crew-session-delivery-metrics.md',
  'prompts/ad-1131-crew-session-delivery-metrics-execution.md'
)
$rows = foreach ($path in $paths) {
  $item = Get-Item -LiteralPath $path
  [pscustomobject]@{
    Path = $path
    Bytes = $item.Length
    SHA256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
  }
}
$rows | Format-Table -AutoSize
$combined = ($rows | Measure-Object -Property Bytes -Sum).Sum
Write-Output ('COMBINED_BYTES=' + $combined)
if ($combined -ge 50000) { throw 'AD-1131 prompt pair must remain below 50000 bytes' }
```

Record both hashes/sizes and the combined count. Any mismatch or later
prompt-byte change is an Architect hard stop.

Do not run a baseline, red test, AD-1130 narrow batch, serial probe, blast/full
suite, UI test, command unrelated to the prescribed batch, GitHub operation,
or push.

## 2. Coding First

Complete all production and test edits before the first pytest invocation. Use
editor diagnostics and static inspection while coding.

Build order:

1. Preserve the strict delivery record/identity and existing-workforce-DB
  outbox. Add the public exact delivery-row reread required for post-mark
  reconciliation; do not weaken duplicate/conflict checks or AD-1130 effects.
2. Centralize WorkItem event projection. Every CrewSession created/updated/
  status event gets exact `{id, work_type, status}`; every non-session item
  keeps its full existing projection for AD-846.
3. Replace the delivery-outbox metric query/model with the dedicated bounded
  CrewSession WorkItem query and `CrewSessionService.metrics`. Use one value
  from the service's injected clock for window end and current blocked time.
  Implement exact sessions-started denominator, four rates, duplicate-resume
  sum, nearest-rank time-to-first-result, malformed/empty rules, and no
  outbox/trust/event reads.
4. Reconcile every delivered-mark True/False/None/ordinary-error/cancellation
  result with one cancellation-deferred authoritative exact-row reread. A
  proven post-commit ordinary error succeeds; the first cancellation is
  re-raised after proof; one pass never marks twice.
5. Extend the delivery service with synchronous callback admission, strong
  ownership of finite callback tasks, a closed admission gate, and idempotent
  cancellation-deferred `close()`. Keep direct awaited drain APIs for startup
  and deterministic tests.
6. Register the synchronous status listener and retain its exact handle. Make
  the startup helper run both trust and delivery drains; any cancellation wins
  over ordinary errors, otherwise the first ordinary error wins.
7. In production shutdown, remove the exact listener and await service close
  before `WorkItemStore.stop()`. Late callbacks are closed-gate no-ops.
8. Preserve the existing transaction integration for ordinary/verified outcome
  commits. Extend live AD-1130 methods without replacing or weakening
  `crew_trust_effects`.
9. Build exactly one record from the validated resulting CrewSession revision
  for blocked, generic failed, verified done, and verified failed paths. Pass
  it with zero-to-many trust effects as applicable. Reconciliation requires
  the exact delivery row and, when present, every exact AD-1130 trust row.
10. Keep deterministic `NotificationQueue.notify_once`; leave `notify` and all
   ordinary callers behaviorally unchanged.
11. Preserve room/task validation and safe notification content. A callback
  failure after queue insertion keeps one logical entry and a pending row.
12. Keep the minimal AD-846 compatibility edit for actual dict envelopes and
   explicit CrewSession rejection; preserve every non-session effect.
13. Finish all tests, including the nine exact names from the main prompt,
  through real public production boundaries before any pytest invocation.

Do not test between items. If a concrete live signature invalidates one step,
stop for Architect review instead of inventing another store/event/lifecycle.

## 3. Pre-Batch Static Audit

Before pytest, prove all of the following and fix only AD-1131 defects:

- dirty paths are an exact subset of the main allowlist; no tracker/archive,
  commercial, HXI, router/API, config/YAML, dependency, or unrelated test;
- `EventType` has no new value; every CrewSession created/updated/status event
  has exactly three nested item keys and every non-session projection is
  unchanged for AD-846;
- every outcome row is inserted in the same WorkItemStore transaction as its
  exact resulting CrewSession revision; precommit cancellation inserts none;
- one revision owns one delivery fact regardless of zero/one/many AD-1130 trust
  effects; neither pipeline's pending/delivered state gates the other;
- verified commit-ambiguity authority proves both exact outboxes when trust
  effects exist; neutral blocked/generic-failed outcomes fabricate none;
- delivery ids/payloads are exact JSON identities and every inspected row,
  byte field, days window, and query count is independently bounded;
- notification payload/outbox/log/metrics contain no goal, result body,
  blocked reason, evidence, secret, artifact/attachment id/ref/filename/bytes,
  roster, token content, trust, or free-form event metadata;
- queue duplicate is a no-op, conflict is explicit, mutable acknowledgement is
  preserved, callback failure retains one logical entry, and ordinary random-
  id `notify()` is unchanged;
- the delivery service confirms the existing room and never creates a room,
  thread, post, DM, external message, suggested action, or live push;
- AD-846's real dict envelope works for non-session Yeo tasks and its gate,
  channel, message, resolver, and degradation policy are otherwise unchanged;
- mark reconciliation performs one write attempt plus one exact authoritative
  reread for True/False/None/error/cancellation; ordinary post-commit error is
  recognized and first cancellation propagates only after proof;
- the startup helper invokes both drains and applies cancellation-first error
  precedence; neither pipeline controls the other;
- callback admission closes before task snapshot, the service strongly owns
  every finite callback task, close drains despite cancellation, and shutdown
  removes/closes delivery before WorkItemStore; no timer/poller/daemon exists;
- metrics query only CrewSession WorkItems by inclusive `created_at`, use SQL
  `limit+1` and `(created_at DESC, id DESC)`, divide all rates by sessions
  started, sum duplicate resumes and accumulated/live blocked time, and use
  nearest-rank first-result percentiles; delivery/trust/outbox/event state is
  never metric evidence;
- all public APIs are fully annotated and log messages state what failed, why
  the row remains safe, and what bounded retry occurs next without payloads.

## 4. One Scoped Changed-Surface Batch

After all coding is complete, run one logical backend batch with 16 workers and
work stealing. Include every authorized existing test file actually changed.
The minimum batch is:

```powershell
$gateId = [guid]::NewGuid().ToString('N')
$gateDir = Join-Path $env:TEMP ('probos_ad1131_batch_' + $gateId)
New-Item -ItemType Directory -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
  & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest `
    tests/test_ad1131_crew_session_delivery_metrics.py `
    tests/test_notifications.py `
    tests/test_ad846_completion_dm.py `
    tests/test_ad1126_verified_finalization.py `
    tests/test_ad1127_crew_session_lifecycle_recovery.py `
    tests/test_ad1130_outcome_only_room_trust.py `
    -p no:cacheprovider -n 16 --dist=worksteal --timeout=90 -q --tb=short
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

If another allowed existing test changed, add it before this first invocation.
Record exact passed/skipped/warning count, duration, exit code, and warning
provenance. Changed paths must emit zero warnings.

One minimal AD-1131 repair and rerun of the identical batch is allowed. Preserve
both attempts as one logical gate. Do not switch to serial/focused testing,
widen files, run AD-1130's batch, or run a broad suite.

## 5. Builder Evidence Package

Return the uncommitted tree for review with:

- base/HEAD, exact dirty paths/purposes, frozen prompt hashes/sizes/combined
  bytes, one-batch result, warnings, and per-dirty-file hashes/sizes;
- real outbox/notification evidence for all outcomes/origins, blocked-resume-
  done, repeated/concurrent events, exact duplicate/conflict, invalid-room
  repair, rollback/ambiguity, failures/cancellation, restart, and independent
  zero-to-many trust effects;
- the 19-session result (19 started, zero four outcome rates, six resumes),
  source rows, bounds/order/truncation, nearest-rank math, blocked-time math,
  empty/malformed cases, and proof the query requests only `limit+1`;
- exact minimal CrewSession events, equivalent AD-846 dict/object effects,
  authoritative mark rereads for normal/None/error/cancellation, both startup
  drains, and shutdown listener/task/store ordering;
- sentinel/privacy, scope, whitespace, and changed-path warning scans.

Do not stage, commit, edit trackers, archive prompts, push, or touch GitHub
before all three reviews approve.

## 6. Three Architect Implementation Reviews

### Review 1 - Delivery contract and compatibility

Verify every done/failed/blocked commit owns one exact revision row, notification
content is fixed/safe, room linkage is existing-only, Captain/self authorship is
correct, every CrewSession event item is the exact minimal projection, and
AD-846 dict/object non-session DM effects are exactly equivalent. Any required
fix returns to the identical batch.

### Review 2 - Transactions, restart, and metrics

Verify atomic enqueue at all outcome paths, exact JSON/collision behavior,
failure/cancellation/commit ambiguity, deterministic sink, mark-plus-reread
reconciliation, callback failure, concurrent/repeated events, and pending
restart replay. Verify the 19-session fixture and every metric bound,
sessions-started denominator, empty/malformed case, truncation, ordering,
nearest-rank index, duplicate-resume sum, and accumulated/live blocked-time
calculation. Reject a post-transition insert, caller-side `exists()` check,
unbounded scan, delivery-row metric, or cross-resource atomicity claim. Verify
AD-1130 trust effect/receipt cardinality cannot become notification identity,
delivery acknowledgement, or metric evidence. Required fixes return to the
same batch.

### Review 3 - Scope and closeout

Verify base, prompt hashes/sizes, allowlist, one-batch evidence, zero changed-
path warnings, no new EventType/sensitive content/external channel/billing/
commercial/HXI/live-push/AD-1132/1133 work, dual-drain precedence, service close
before store close, exact commit subject, AD-1133 deferrals, and unchanged
AD-1130 trust replay. Closeout begins only after all three approvals.

## 7. Local Closeout After Approval

1. Do not rerun pytest. Re-run only static scope, whitespace, secret-sentinel,
   and file/prompt hash audits.
2. Keep `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`, prompt
   archives, AD-1130 artifacts, and every unauthorized path unchanged.
3. Stage only approved AD-1131 production/tests and these two prompts at their
   frozen hashes.
4. Commit locally with the exact subject:

```text
AD-1131: add CrewSession delivery and metrics (closes #1050)
```

5. Verify exact subject/content, authorized scope, clean tree, and prompt
   hashes. Do not push and do not invoke GitHub.

AD-1133 owns consolidated trackers, prompt archive moves, broad gate, and push.

## Hard Stops

- Base/hash/size/allowlist mismatch; mixed AD-1130; split outcome/outbox;
  missing exact delivery/trust proof; trust coupled to delivery or metrics.
- Sensitive/wrong-author/missing-room notification; duplicate/lost delivery;
  mark without exact reread; masked cancellation; either startup drain skipped.
- Unowned/late callback, store closed before service, nonminimal CrewSession
  event, changed AD-846 non-session projection/effect, or non-WorkItem/unbounded/
  wrong-denominator/interpolated/caller-clock metrics.
- New EventType/channel/billing/commercial/HXI/API/router/config/dependency/
  loop/AD-1132/1133/tracker/archive/broad gate/push/GitHub work.
- The scoped batch remains red, changed paths warn, or any review is not
  approved.

## Acceptance

- Main spec passes real stores/rooms/queue/events/restart/faults/shutdown/metrics;
  delivery, trust, and one-parent session metrics stay independent.
- Base is `d463a114`; frozen prompt pair is under 50,000 bytes.
- Coding precedes one `-n 16 --dist=worksteal` batch; three reviews precede the
  local unpushed commit; broad gate/trackers/archive/GitHub/push stay AD-1133.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Protocol Review Record

### Pass 1 - Sequencing

**Verdict: APPROVED.** Exact base `d463a114`, literal main-prompt hash binding,
and mechanical prompt-pair freeze precede a coding-first build and one scoped
`-n 16` worksteal batch.

### Pass 2 - Evidence and review

**Verdict: APPROVED.** The nine exact public-boundary tests, real 19-session
fixture, minimal events, authoritative mark reread, dual-drain precedence,
service-owned shutdown, independent trust/delivery replay, and exact session
metric math are mandatory before three implementation reviews.

### Pass 3 - Closeout

**Verdict: READY.** Only the exact local unpushed AD-1131 commit follows
approval. Trackers, archives, broad gate, live push, and GitHub remain AD-1133;
execution authority is bound to base `d463a114`, the final main hash above, and
the mechanically frozen under-50KB prompt pair.
