# AD-1133 Builder Execution: Live CrewSession and Thread Refresh

**Status:** SECOND FINAL AMENDMENT APPLIED 2026-07-23; CONDITIONAL PENDING MECHANICAL HASH/SIZE
**Binding specification:** `prompts/ad-1133-live-crew-session-thread-refresh.md`
**Binding main SHA-256/bytes:** `bce2d6cfc23de49427d005ffc4cbed7366e9c2ee01e1f44d71d4be9c6d228397` / `41655`
**Required build base:** `d8965f9b3038f9d5c98b7049ab990e43c99c9f80`
**Scope:** AD-1133 / #1052 only

The byte-bound main is the sole implementation contract; this companion only
sequences correction, backend gate, evidence reuse, reviews, and closeout.

## 1. Freeze and Final Repair Allowlist

Preserve the live tree on the required base and mechanically refresh both
hashes/sizes; require combined `<50000`, then freeze. Preserve reviewed
41-path/five-path evidence and record final 49-path/ten-path manifest hashes,
plus unchanged UI/e2e count and prior manifest hash. Later byte drift stops.

The final repair allowlist is exactly:

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

Preserve every other byte. Main Section 6 owns full scope; this list owns the
amendment. Do not edit AD-1132 prompts or allocate an AD/BF.

## 2. Coding Order and Binding Contracts

Before any command: (1) add owner count/bounded projection seams and runtime
pre-projection admission; (2) add source-owned raw-subscription release,
captured bus+subscription delegation, then owner/integration regressions. These
are the only final blockers. Preserve completed lifecycle, dispatcher,
workforce, callbacks, projector, frontend, and e2e bytes. A blocking signature
returns to Architect; never widen scope.

## 3. Backend-Only Gate

Audit ten paths/owners; run only their editor diagnostics, this pycompile, and
backend batch. One repair reruns affected checks. No UI, build, Playwright,
full suite, Git, tracker, archive, or GitHub command runs during correction.

```powershell
& 'D:\ProbOS\.venv\Scripts\python.exe' -m py_compile `
  src/probos/runtime.py src/probos/substrate/pool_group.py `
  src/probos/notifications.py src/probos/directive_store.py `
  src/probos/mesh/nats_bus.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Use isolated local/offline data and the established 16-core backend profile:

```powershell
$gateId = [guid]::NewGuid().ToString('N')
$gateDir = Join-Path $env:TEMP ('probos_ad1133_changed_' + $gateId)
New-Item -ItemType Directory -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
  & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest `
    tests/test_ad1133_live_crew_session_refresh.py `
    tests/test_ad1132_crew_session_api.py `
    tests/test_ad1127_crew_session_lifecycle_recovery.py `
    tests/test_ad1125_room_bound_execution.py `
    tests/test_ad1128_crew_session_ingress_dedup.py `
    tests/test_hxi_events.py `
    tests/test_architect_api.py `
    tests/test_ad722b_1_crew_scope_auth.py `
    tests/test_ad637d_system_events_nats.py `
    tests/test_ad637a_nats_foundation.py `
    tests/test_workforce.py `
    tests/test_pool_groups.py `
    tests/test_notifications.py `
    tests/test_directive_store.py `
    -p no:cacheprovider -n 16 --dist=worksteal --timeout=90 -q --tb=short
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

## 4. Evidence, Reuse, and Audits

Record gate exits/counts/skips/warnings/duration. Audit ten paths against the
49-path manifest, whitespace/tokens, binding, pair bytes, and unchanged
workforce/UI/e2e hashes.

UI/e2e must match the stored exact aggregate (prefix `fff7ae95`); then reuse
only `155 targeted Vitest passed; production build passed; 1 focused
Playwright passed`. Never rerun/repair UI; drift stops. Hand back base,
hashes/sizes/counts, gates, blockers, reused evidence, and verdicts. Do not
stage/commit before approval.

## 5. Optimized Three-Pass Final Review

Each findings-first pass uses Required/Recommended/Nits/Verified. A Required
finding permits one minimal repair, affected Section 3 checks, and pass restart.

1. **Snapshot admission:** owner APIs, checks before full projection, no runtime
  private access, stable overflow, exact-cap/parity tests.
2. **NATS release:** captured bus+subscription, shielded idempotent cleanup,
  tracking baseline, no duplicate delivery, unchanged ordinary subscriptions.
3. **Scope/evidence:** base, delta, diagnostics/gate, whitespace/tokens,
   manifests, prompt hashes/sizes, combined `<50000`, and UI evidence.

After green backend, run only these passes and mechanical reconciliation. No
full Python, Vitest, build, or Playwright rerun. Approval authorizes this exact
local unpushed implementation commit subject:

```text
AD-1133: add live CrewSession refresh (closes #1052)
```

Do not include tracker/archive changes and do not push this commit yet.

## 6. Consolidated End Gate and Closeout

Implementation gate: exact base/binding; frozen ten-path amendment and
49-path manifest; green diagnostics/pycompile/backend; unchanged workforce/UI/
e2e with reused evidence; clean whitespace/tokens; recorded prompt hashes/
sizes below 50 KB combined; and three Approved reviews. Then create only the
Section 5 implementation commit.

After that commit and all three reviews:

1. Update `PROGRESS.md` and `docs/development/roadmap.md` once for the complete
  AD-1128 through AD-1133 local stack, exact backend/reused-UI evidence,
  provenance, issue close-on-push state, and final AD/BF ceilings.
2. Update `DECISIONS.md` only for an actual unrecorded architectural decision.
3. Byte-preserving move the completed AD-1128 through AD-1133 prompt pairs to
  `prompts/archive/`, verifying every pre/post SHA-256.
4. Create one local closeout commit containing only trackers and archive moves.
5. Architect-review stack order/subjects, frozen hashes, evidence, and clean
  trees in both roots.
6. Only then push the OSS stack; never push the commercial repo.
7. Re-read remote issue/CI state and reconcile #1047 through #1052, parent
  epic #1041, commit links, close keywords, and required checks. Claim closure
  only after the remote reflects it.

Any production/test repair during closeout requires new authorization.

## Hard Stops

- Any main hard stop/acceptance or referenced blocker failure.
- Base/binding/handoff/manifest/allowlist mismatch, combined bytes `>=50000`,
  or unresolved template token.
- Any correction edit outside the ten paths, including AD-1132 prompts,
  API/hub/projector/workforce/UI/e2e/config/trackers/commercial.
- Full projection before owner admission, runtime owner-private access, or a
  successfully released raw subscription remaining tracked.
- Any main Sections 1-4 or 7-8 security, privacy, bounds, cancellation,
  ordering, ownership, cleanup, snapshot, or resync violation.
- Red gate, whitespace/path warning, UI/e2e drift, Required finding, or
  unapproved evidence substitution.
- UI/full-suite rerun; premature stage/commit/tracker/archive/push/GitHub; or
  closeout requiring production/test repair.

## Acceptance

- Main Sections 0-8 remain the behavioral contract. This companion additionally
  requires its exact base/repair/freeze/gate/evidence/review/commit/closeout.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Authority (2026-07-23)

The bound main's `Verified Against Codebase`, Decision, Sections 1-2, 5-6, and
8 own every referenced anchor and contract; none is duplicated here.
