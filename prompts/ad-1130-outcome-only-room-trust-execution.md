# AD-1130 Builder Execution: Outcome-Only CrewSession Trust

**Status:** CONTENT-READY - mechanical hash/size binding pending
**Binding specification:** `prompts/ad-1130-outcome-only-room-trust.md`
**Code-review/repair base:** supplied `5f008fcc` plus the live uncommitted AD-1130 implementation; preserve those production/test bytes until prompt-authorized repair
**Planning ceilings before AD-1130:** AD-1129 / BF-673
**Prompt binding placeholder:** main SHA-256 `<MEASURED_AT_REPAIR_HANDOFF>`, bytes `<MEASURED_AT_REPAIR_HANDOFF>`; execution SHA-256 `<MEASURED_AT_REPAIR_HANDOFF>`, bytes `<MEASURED_AT_REPAIR_HANDOFF>`; combined bytes `<MEASURED_AT_REPAIR_HANDOFF>` and must be `< 50000`
**Scope:** AD-1130 / #1049 only

The main prompt is authoritative for outcome semantics, effect identity,
durability, raw Beta updates, social/work-room policy, allowed files, tests,
and exclusions. This companion is authoritative for sequencing, the one batch,
three reviews, local commit, and AD-1133 deferrals.

## 1. Preflight and Prompt Freeze

Do not edit production/tests until all checks pass:

1. Record supplied base `5f008fcc`. Preserve the live uncommitted AD-1130
  implementation and tests: do not reset, stash, rebase, rebuild, or discard
  them. Ignore every AD-1131 prompt and do not edit/review AD-1129.
2. Highest planned numbers are AD-1129 and BF-673. AD-1130 is reserved for
   #1049; do not allocate another AD/BF.
3. Dirty production/tests must be an exact subset of the main prompt's AD-1130
  allowlist; dirty prompts must be only these two active AD-1130 files. Any
  AD-1131, tracker, archive, commercial, or unrelated path is a hard stop.
4. Re-run the main prompt's live symbol checks and stop on contract drift.
5. Mechanically fill and report both prompt-binding placeholders, require
  combined bytes `< 50000`, and freeze the values. Never transcribe or predict
  them; any later prompt-byte change is a hard stop.

Deferred mechanical freeze step (run only at the repair handoff, not during
this prompt-only compaction):

```powershell
$promptPaths = @(
  'D:\ProbOS\prompts\ad-1130-outcome-only-room-trust.md',
  'D:\ProbOS\prompts\ad-1130-outcome-only-room-trust-execution.md'
)
$promptFreeze = foreach ($path in $promptPaths) {
  [pscustomobject]@{
    Path = $path
    Sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    Bytes = (Get-Item -LiteralPath $path).Length
  }
}
$promptFreeze | Format-Table -AutoSize
$combinedBytes = ($promptFreeze | Measure-Object -Property Bytes -Sum).Sum
if ($combinedBytes -ge 50000) { throw "AD-1130 prompt ceiling exceeded: $combinedBytes" }
"CombinedBytes=$combinedBytes"
```
6. The prior broad count is context only. Do not run baseline, Gate 0-4, a full
   backend suite, a per-file red/green loop, or UI tests.

Do not stash/reset unrelated work. Do not invoke GitHub or push.

## 2. Build Once Before Pytest

Complete all implementation and tests before the first pytest invocation.
Use editor diagnostics/static inspection while coding.

Implement the main prompt's Exact Durable Contract in this order:

1. Receipt post-state columns/migration, one-snapshot duplicate reconciliation,
  and bounded commit-ambiguity recovery through exact retry/restart.
2. Deterministic configured $O(n)$ Shapley attribution above the exact bound.
3. Pre-mutation synchronous busy error and only the exact audited caller guards.
4. Complete all main Required Tests, including repair groups 16-21, before the
  first pytest invocation.

Do not add a generic abstraction unless required by the exact repair. Do not
touch AD-1129 Tool/identity files or any AD-1131 prompt. Do not rebuild already-
correct AD-1130 surfaces merely because they are uncommitted.

## 3. Static Scope Audit

Before pytest, audit the main prompt's exact Implementation Surface, What This
Does Not Change, and Acceptance Criteria. Prove dirty paths remain an exact
allowlist subset; frozen finalizer/session/workforce/startup/social bytes are
unchanged; no queued synchronous outcome path remains; only the exact busy
error is caught by audited callers; and public annotations/contextual logs are
complete. Fix only the three listed repairs before testing.

## 4. One Changed-Surface Batch

After all repair code and tests are complete, run exactly this one backend
batch with 16 workers and work stealing. Do not omit unchanged listed contract
tests and do not add unrelated tests:

```powershell
$gateId = [guid]::NewGuid().ToString('N')
$gateDir = Join-Path $env:TEMP ('probos_ad1130_batch_' + $gateId)
New-Item -ItemType Directory -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
  & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest `
    tests/test_ad1130_outcome_only_room_trust.py `
    tests/test_ad1124_crew_session_contract.py `
    tests/test_ad1126_verified_finalization.py `
    tests/test_ad1127_crew_session_lifecycle_recovery.py `
    tests/test_ad860_crew_verifier.py `
    tests/test_ad861_crew_synth.py `
    tests/test_ad958_conversation_trust.py `
    tests/test_trust.py `
    tests/test_trust_concurrency.py `
    tests/test_trust_dampening.py `
    tests/test_trust_events.py `
    tests/test_ad571_tier_separation.py `
    tests/test_ad722a_divergence_detector.py `
    tests/test_ad489_code_of_conduct.py `
    tests/test_bf206_confab_feedback.py `
    tests/test_dreaming.py `
    tests/test_feedback_engine.py `
    tests/test_proactive.py `
    tests/test_ad480_federation_mcp_a2a.py `
    tests/test_ward_room.py `
    tests/test_consensus_integration.py `
    tests/test_system_qa.py `
    -p no:cacheprovider -n 16 --dist=worksteal --timeout=90 -q --tb=short
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Every changed test must be in this exact list; needing another test path is an
Architect hard stop before pytest. Collect all twenty-one required behavioral
groups from the main prompt. Record exact passed/skipped/warning count,
duration, and exit code. Changed paths must produce zero warnings.

A failure authorizes one minimal AD-1130 repair and rerun of this identical
batch. Do not widen it and do not run serial/focused/blast/full gates. Report
the rerun as the same logical changed-surface gate with both attempts preserved.

## 5. Builder Evidence Package

Return evidence mapped one-to-one to all 21 main Required Tests and every main
Acceptance Criterion, plus supplied base/live-tree preservation, dirty-path
purpose, frozen prompt bindings, exact batch counts/duration/exit/warnings,
static/whitespace audit, and hashes/sizes for every dirty file.

Do not stage, commit, edit trackers, archive prompts, push, or touch GitHub
before all three reviews approve.

## 6. Three Architect Implementation Reviews

### Review 1 - Contract, policy, and attribution

Verify the full outcome matrix, identities, no-effect paths, real raw Beta
evidence, and both exact/analytic Shapley branches. Required findings return to
the same batch.

### Review 2 - Transactions and restart

Verify all main durability/restart criteria with real stores, including receipt
migration, ambiguity reservation, duplicate reconciliation, current-row
presence/removal, newer-row preservation, cancellation, acknowledgement
failure, and fresh restart. Required findings return to the same batch.

### Review 3 - Scope and closeout

Verify base/live-tree preservation, exact allowlist, every busy-only caller,
one-batch evidence, zero changed-path warnings, frozen hashes, exact commit
subject, and AD-1133 deferrals. Closeout begins only after explicit `APPROVED`
on all three passes.

## 7. Local Closeout After Approval

1. Do not rerun pytest. Re-run static scope, whitespace, and hash audits only.
2. Keep `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`, every
  AD-1129/AD-1131 artifact, and all non-allowlisted live bytes unchanged.
3. Stage only approved AD-1130 production/tests and these two prompt files at
   their frozen hashes.
4. Commit locally with the exact subject:

```text
AD-1130: add outcome-only CrewSession trust (closes #1049)
```

5. Verify commit subject/content, clean authorized scope, and prompt hashes.
   Do not push and do not invoke GitHub. AD-1133 owns tracker updates, active-
   prompt archive moves, consolidated broad gate, and push authority.

## Hard Stops

- Supplied base is not `5f008fcc`, the live AD-1130 implementation was reset/
  stashed/rebased/rebuilt/discarded, or any AD-1129/AD-1131 path is edited.
- Prompt combined size is not below 50,000 bytes or a frozen hash changes.
- A trust effect lacks an attempted action/judgment, terminal durable evidence,
  exact resulting session revision, or deterministic identity.
- Correct rejection penalizes a verifier; governance/blocked/cancelled-before-
  commit/no-verifier/no-attempt changes trust; parent failure earns success.
- Terminal transition and outbox enqueue split, or raw Beta mutation and
  receipt split; duplicate/restart can apply twice.
- Receipt post-state is absent on a new row, legacy null post-state is inferred,
  duplicate succeeds from cache alone, current-row removal resurrects cache,
  or a read failure is normalized to absence.
- An ambiguous outcome can reach another mutation, save, stale shutdown
  persistence, or outbox acknowledgement before exact retry/restart authority.
- Sync trust writes queue/return stale state or raise after mutation; a busy-
  only caller aborts completed non-trust work, swallows another RuntimeError,
  or reports the skipped trust adjustment as applied.
- >10 completed votes use Monte Carlo, blanket equal share, unsorted effects,
  exponential enumeration, wrong zero/all-zero policy, or floor renormalization.
- Startup recovery requires an untracked task, timer, loop, wider lifecycle
  refactor, or path outside the allowlist.
- Existing social policy changes beyond task-linked room exclusion.
- Any new trust DB/table/store, receipt field beyond exact post alpha/beta,
  shared Shapley API, mean/rank/Hebbian/HXI/config/YAML/EventType/API, AD-1131+,
  tracker, archive, push, GitHub, or broad-gate work appears.
- The changed-surface batch remains red, changed paths warn, or any review is
  not approved.

## Acceptance

- Main prompt acceptance is met exactly.
- Supplied base `5f008fcc` and the live AD-1130 tree are preserved through the
  exact allowlisted repair; AD-1129/AD-1131 bytes remain untouched.
- Both prompt SHA-256 values and byte lengths are frozen; combined size is
  below 50,000 bytes.
- All code precedes exactly one optimized `-n 16 --dist=worksteal` batch.
- Three Architect implementation reviews approve before closeout.
- Exact local commit is created and remains unpushed; broad gate is deferred to
  AD-1133.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.