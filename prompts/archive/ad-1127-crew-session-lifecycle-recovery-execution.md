# AD-1127 Builder Execution: Optimized 12-Hour Protocol

**Authority:** `prompts/ad-1127-crew-session-lifecycle-recovery.md` is binding for behavior, schemas, phase policy, files, tests, exclusions, and closeout. This document is binding for execution order and gates. A conflict is a hard stop for Architect adjudication.

**Adjudicated main-prompt binding (2026-07-21):** SHA-256 `c95b49c8c8601e7b3a160d9ec731a8b0553675dab8cb56be4fb16e8babe80d43`, 54,582 bytes. Builder must verify this exact value before resume. Any later prompt byte change requires a fresh Architect hash handoff.

**Required revision base:** `main` at `8a7bd9805b38b303bb0598d1be102d4e7ec4c610`, with local `HEAD == origin/main`, #1045 closed, #1046 open, AD ceiling 1126, BF ceiling 673; the working tree is the exact authorized partial set below, not clean.
**Authoritative base full gate:** 19,923 passed / 33 skipped / 429 warnings / 0 failed.
**Builder GitHub policy:** no push, issue/PR mutation, branch creation, or remote write.

## 0. Hard-Stop Resume Preflight

This execution resumes the same authorized partial AD-1127 tree after Architect adjudication. Preserve every current production/test byte; do not reset, stash, clean, checkout, reconstruct, stage, or commit. Before the next Builder edit, verify:

```powershell
Set-Location D:\ProbOS
git status --short
git rev-parse HEAD
git rev-parse origin/main
gh issue view 1045 --json state
gh issue view 1046 --json state
Get-FileHash -Algorithm SHA256 prompts/ad-1127-crew-session-lifecycle-recovery.md
```

The exact authorized dirty-path set at adjudication is:

```text
M  src/probos/artifacts/__init__.py
M  src/probos/cognitive/crew_session.py
M  src/probos/config.py
M  src/probos/workforce.py
?? prompts/ad-1127-crew-session-lifecycle-recovery-execution.md
?? prompts/ad-1127-crew-session-lifecycle-recovery.md
?? tests/test_ad1127_crew_session_lifecycle_recovery.py
```

Hard stop unless both revision hashes still equal the required base, #1045 is `CLOSED`, #1046 is `OPEN`, the main prompt matches the adjudicated binding above, and status contains no path outside that exact set. Existing partial bytes need not equal base and must not be reconstructed. A missing listed path or an extra dirty path returns to Architect; do not infer ownership or absorb it.

Read first:

- `.github/copilot-instructions.md`
- both AD-1127 documents
- exact allowed production files
- `tests/test_ad1124_crew_session_contract.py`
- `tests/test_ad1125_room_bound_execution.py`
- `tests/test_ad1126_verified_finalization.py`
- `tests/test_ad867_crew_orchestrator.py`
- `tests/test_ad868_self_originated_crew.py`
- `tests/test_bf598_shutdown_idempotency.py`

## 1. Build Order And Red-First Gates

Build in these independently testable groups. Do not start the next group while the current focused gate is red.

### Group A: Contracts And Store Primitives

Resume Group A from the preserved partial tree. First repair the pre-adjudication plan model/helpers/tests to the main prompt's exact two-stage contract: add only exact `plan_seed_hash`, implement shared bounded canonical projection helpers, derive new-plan ids from the seed, commit `derived_v1` versus `adopted_v1` only inside final `plan_hash`, recompute row/final manifest hashes contextually, and reject old placeholder/arbitrary hash plans. Do not add another schema field or a WorkItemStore create-with-id method; the partial `WorkItemPlanInsert.id` plus transactional insert is the approved new-plan seam. Add only the main prompt's narrow lock-held `adopt_child_plan_with_parent_metadata()` store method and service-owned `adopt_recovery_plan()` for existing-child adoption; a parent-only recovery CAS is not race-safe.

Before production repair, update the existing AD-1127 test module so the adjudication vector and independent tamper/mode/bounds cases are RED for the expected contract reason, not import/syntax/fixture failure. Existing placeholder `_SHA_A`/`_SHA_B` plans may remain only in tests whose subject is Pydantic phase shape and which do not assert contextual validity; every service/install/adoption/restart test must construct a genuinely canonical plan or deliberately assert exact rejection.

Then complete bounded config, strict recovery/plan/checkpoint models, the combined-state scan, transactional plan install, atomic child output/verification checkpoint support, and exact Artifact reconciliation. Existing partial methods are provisional, not proof that the Group A contract is complete.

Red first with named tests for the fixed semantic/seed/id/row/final-manifest vector, derived/adopted modes, every hash-layer tamper, JSON strictness/bounds, duplicate normalized spec ids/dependencies/resources, global scan bound, new-plan transaction cancellation/authoritative full-plan reread, existing-child adoption snapshot-vs-lock mutation rejection, child metadata atomicity, and Artifact 0/1/2-match behavior. Then run:

```powershell
& D:\ProbOS\.venv\Scripts\python.exe -m pytest tests/test_ad1127_crew_session_lifecycle_recovery.py -q -n 0 -k "config or recovery_contract or identity or canonical or seed or derived or adopted or scan or plan or artifact or child_checkpoint"
```

### Group B: Phase-Aware Executor And Finalizer

Implement exact result reconstruction, terminal child skip/block/fail policy, convergence checkpoint reuse, synthesis/verdict checkpoints, publication resume, and cancellation deferral. Keep landed AD-1125/1126 paths green after each slice.

```powershell
& D:\ProbOS\.venv\Scripts\python.exe -m pytest tests/test_ad1127_crew_session_lifecycle_recovery.py tests/test_ad1125_room_bound_execution.py tests/test_ad1126_verified_finalization.py -q -n 0
```

### Group C: Lifecycle, Startup, Shutdown

Implement keyed schedule ownership, semaphore, retries, bounded start scan, synchronous close, cancellation-deferred stop, startup call, and shutdown ordering. Test the real owner and real shutdown seam; no MagicMock substrate.

```powershell
& D:\ProbOS\.venv\Scripts\python.exe -m pytest tests/test_ad1127_crew_session_lifecycle_recovery.py tests/test_ad867_crew_orchestrator.py tests/test_ad868_self_originated_crew.py tests/test_bf598_shutdown_idempotency.py -q -n 0
```

### Group D: Focused Module And Blast Gates

Run all AD-1124 through AD-1127 behavior serially:

```powershell
& D:\ProbOS\.venv\Scripts\python.exe -m pytest tests/test_ad1124_crew_session_contract.py tests/test_ad1125_room_bound_execution.py tests/test_ad1126_verified_finalization.py tests/test_ad1127_crew_session_lifecycle_recovery.py -q -n 0 --timeout=90
```

Run the bounded blast radius serially:

```powershell
& D:\ProbOS\.venv\Scripts\python.exe -m pytest tests/test_ad867_crew_orchestrator.py tests/test_ad868_self_originated_crew.py tests/test_ad859_crew_executor.py tests/test_ad925_auto_task_room.py tests/test_bf598_shutdown_idempotency.py tests/test_ad820_shutdown_integrity.py tests/test_bf296_shutdown_phase_ordering.py -q -n 0 --timeout=90
```

No full `tests/` run is permitted yet.

## 2. Compile And Audits

Run before Builder handback:

```powershell
& D:\ProbOS\.venv\Scripts\python.exe -m compileall -q src/probos/config.py src/probos/workforce.py src/probos/artifacts src/probos/cognitive/crew_session.py src/probos/cognitive/crew_executor.py src/probos/cognitive/crew_finalizer.py src/probos/cognitive/crew_orchestrator.py src/probos/startup/finalize.py src/probos/startup/shutdown.py tests/test_ad1127_crew_session_lifecycle_recovery.py
git diff --check
git status --short
```

Required audits:

1. Changed paths are a subset of the prompt allowlist; `config/system.yaml`, dependency files, API/UI/EventType files, DB schema/DDL, and commercial repo are unchanged.
2. No `MagicMock` in the AD-1127 test module. Scripted fakes may model LLM/agent/tool edges; all persistence/lifecycle substrates are real.
3. No unheld `create_task`, `ensure_future`, swallowed `CancelledError`, cross-owner private access, raw SQL outside WorkItemStore/ArtifactStore, or second scheduler/queue/daemon.
4. `close_scheduling()` occurs before the first shutdown await; `stop()` precedes consolidation/dependency close; BF-598/AD-820 marker branches are textually and behaviorally preserved.
5. `orchestrator_enabled=False` performs zero recovery query, decomposition, task creation, or retry sleep.
6. Combined-state scan has one global SQL `LIMIT`; no per-status multiplication.
7. Every recovery metadata mutation carries exact session/recovery/state/assignee guards; bool-vs-int JSON aliases reject. `plan_seed_hash` binds only ordered semantics; policy `derived_v1` child ids bind parent/seed/spec; row hashes bind persisted immutable rows; final `plan_hash` binds parent/hash-only-policy/seed/ordered commitments. Policy `adopted_v1` is reachable only from no-recovery existing-child adoption; generic recovery/transition/finalization CAS paths preserve the exact plan byte-for-byte.
8. Existing `add_version()` callers and legacy non-session executor/orchestrator behavior are unchanged.
9. Full type annotations on every new public method; logs say what failed, why it matters, and what happens next without content/secrets.
10. Search all changed prompt/example text against `_CAPABILITY_GAP_RE`; do not introduce response prose that triggers it.
11. Only `CrewRecoveryTransientError` reaches automatic retry; exact SQLite/errno wrapping excludes ENOSPC/EIO/corruption/validation/CAS/LLM defects.
12. `reconcile_exact_version` admits only an empty chain or one exact singleton; a conflicting or multi-version `crew-result.md` chain cannot grow.
13. Concurrent parents have disjoint local child-task sets; no shared executor registry lets one parent's wait/finally consume or cancel another's work.
14. CrewSession recovery never runs the legacy unconditional assignment loop; only an unassigned untouched child is assigned through exact CAS.
15. Orchestrator stop/drain is the first shutdown await, including partial startup, so cancellation cannot bypass the owner barrier.

Builder handback must include changed files, focused/module/blast counts, warnings by source, compile/audit results, `git diff --stat`, and any unresolved question. Do not stage or commit.

## 3. Mandatory Architect PRE-GATE Review

The Architect reviews the unstaged implementation before any full suite. This is the substantive three-pass implementation review:

| Pass | Required decision |
|---|---|
| 1: Contract | live signatures, schema exactness, public ownership, phase transitions, no phantom API |
| 2: Safety | races, cancellation, crash windows, Artifact/result idempotency, retry bounds, real-store tests |
| 3: Scope/Gate | allowlist, default-off, startup/shutdown, AD-1128+ exclusions, test/gate/closeout consistency |

Verdict must be `APPROVED FOR FROZEN FULL GATE`. Any required change returns to the focused gate that owns it, then all affected focused/module/blast gates and all three review passes repeat. No review approval may rely only on source-string tests.

## 4. Freeze Exact Manifest

After Architect approval and before the full suite, freeze SHA-256 and byte size for:

- both root prompt documents;
- every changed production file;
- every changed/new test file;
- the unchanged gate command text copied into the handback.

Use a sorted manifest such as:

```powershell
$paths = @(git status --short | ForEach-Object { $_.Substring(3) }) + @(
  'prompts/ad-1127-crew-session-lifecycle-recovery.md',
  'prompts/ad-1127-crew-session-lifecycle-recovery-execution.md'
)
$paths = $paths | Sort-Object -Unique
$paths | ForEach-Object {
  $item = Get-Item -LiteralPath $_
  $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_).Hash.ToLowerInvariant()
  "$hash $($item.Length) $_"
} | Set-Content -Encoding ascii $env:TEMP\ad1127-frozen-manifest.txt
Get-Content $env:TEMP\ad1127-frozen-manifest.txt
```

The manifest remains outside the repository. Any byte mutation to a frozen prompt, production file, test, or gate command invalidates the freeze. Stop, rerun the affected focused gates, repeat Architect PRE-GATE review, make a new manifest, and only then run a new single authoritative full suite. Never treat a full run against stale hashes as evidence.

## 5. ONE Authoritative Full Suite

Run exactly once against the approved frozen manifest:

```powershell
Set-Location D:\ProbOS
$gateId = [guid]::NewGuid().ToString('N')
$gateDir = Join-Path $env:TEMP ('probos_ad1127_frozen_' + $gateId)
$gateLog = Join-Path $env:TEMP ('probos_ad1127_frozen_' + $gateId + '.log')
if (Test-Path -LiteralPath $gateDir) { throw 'Gate directory collision' }
New-Item -ItemType Directory -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
  & D:\ProbOS\.venv\Scripts\python.exe -m pytest tests/ -p no:cacheprovider -n 4 --dist=loadfile --timeout=90 -q --tb=short *> $gateLog
  $exit = $LASTEXITCODE
  Get-Content -LiteralPath $gateLog -Tail 320
  "AD1127_FULL_LOG=$gateLog"
  "AD1127_FULL_EXIT=$exit"
  if ($exit -ne 0) { exit $exit }
} finally {
  Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Let `N` be net-new collected passing tests relative to the frozen 19,923 baseline:

```text
expected passed = 19,923 + N
expected skipped = 33
expected failed = 0
```

The baseline warning count is 429. Record every warning family and count. Changed production paths and new AD-1127 tests must emit zero warnings. A total other than 429 is acceptable only with exact provenance proving an unrelated environment/collection change; otherwise hard stop. Do not suppress, filter, or normalize warnings to force the number.

If the full suite is red, do not patch first. Classify per the Architect hard-stop rules: reproduce the failing file serially; distinguish implementation regression, order pollution, parallel environment, or baseline rot; return to Architect. Any byte fix invalidates the freeze and requires focused gates plus a new PRE-GATE review/freeze/full run.

## 6. Green Closeout Without Redundant Review

If the single frozen full suite is green, do not perform another broad code review or redundant full suite. Do only:

1. Recompute every frozen hash/size and require exact manifest equality.
2. Verify `git diff --check`, allowlist, no staged files, and exact test/warning equation.
3. Update `PROGRESS.md` with one AD-1127 shipped block including `N`, focused/blast/full counts, cancellation/recovery/idempotency behavior, warning provenance, AD ceiling 1127, BF ceiling 673, and #1046 close-on-push wording.
4. Update `docs/development/roadmap.md` only for AD-1127/#1046 completion and ceilings; do not add AD-1128+ details.
5. Append the AD-1127 decision to `DECISIONS.md` using its existing era-link format.
6. Move both root prompt documents byte-for-byte to:
   - `prompts/archive/ad-1127-crew-session-lifecycle-recovery.md`
   - `prompts/archive/ad-1127-crew-session-lifecycle-recovery-execution.md`
7. Verify pre/post archive SHA-256 equality for each document. Do not reconstruct either file through a patch during the move.
8. Stage only approved production/test files, the three trackers, and the two archive files. Confirm the two root prompt paths are staged as deletions/renames and no other path is staged.
9. Commit exactly:

```text
AD-1127: add CrewSession lifecycle recovery (closes #1046)
```

10. Report commit hash, final staged/committed path list, gates, equation, warning provenance, frozen hash recheck, and `git status --short`.

Builder stops there. No push and no GitHub mutation.

## Hard Stops

- Base, issue state, ceiling, cleanliness, or Architect document hash mismatch.
- Any unrelated dirty path or any commercial-repo change.
- Need for a new DB/table/column, config YAML, EventType, API/UI, dependency, scheduler, queue, daemon, or AD-1128+ feature.
- Inability to prove exact child output, convergence, Artifact, provenance, or final publication identity.
- Any proposal to rerun an ambiguous `in_progress` child or auto-resume a blocked parent.
- Unbounded/per-status scan, unbounded retry, duplicate owner task, unobserved task error, or shutdown admission opened after close.
- Cancellation translated to failed, swallowed, or allowed to close dependencies before checkpoint/drain.
- BF-598/AD-820 guard/marker behavior changed or downgraded.
- MagicMock at persistence/lifecycle substrate boundaries.
- Any mutation after freeze without a complete re-review/re-freeze cycle.
- Any attempt to preserve the pre-adjudication circular `child_id <- plan_hash <- child_id` contract, accept arbitrary placeholder hashes, infer policy from row shape, persist a mode field, add another identity field beyond `plan_seed_hash`, or reconstruct the preserved partial tree.

## Execution Acceptance

- Red-first, focused/module/blast, compile, and audits precede handback.
- Architect PRE-GATE three-pass review precedes the full suite.
- Exact prompt/production/test hashes are frozen.
- Exactly one authoritative full suite runs against that frozen manifest.
- Green closeout uses hash recheck directly, without redundant post-gate review.
- Baseline equation is `19,923 + N`, 33 skipped, zero failed; all 429 baseline warnings and any delta have provenance.
- Trackers, byte-preserving archive, exact staging, and exact commit message are completed only after green.
- Builder performs no push or GitHub mutation.

Verify all changes comply with the Engineering Principles in .github/copilot-instructions.md.

## Architect Three-Pass Document Review

| Pass | Scope | Status |
|---|---|---|
| 1 | partial-tree resume authority, live paths, main-hash binding, and gate ordering | APPROVED |
| 2 | two-stage identity RED-first repair, freeze invalidation, and failure triage | APPROVED |
| 3 | closeout, no-push boundary, and adjudicated binding-prompt parity | APPROVED |

**Document verdict:** READY for Builder handoff, subject only to exact out-of-band SHA-256/byte values in the Architect response.