# AD-1128 Builder Execution: Optimized Protocol

**Authority:** `prompts/ad-1128-crew-session-ingress-dedup.md` is binding for behavior, APIs, allowlist, tests, exclusions, and closeout. This document is binding for execution order and gates. A conflict is an Architect hard stop.

**Latest precedence (2026-07-21 final code review):** Section 12 of this document supersedes Sections 0 through 11 wherever they conflict. The complete AD-1128 tree is frozen by the final authorized hashes; only local unpushed closeout is permitted, with broad validation deferred to AD-1133.

**Adjudication input bindings:** main SHA-256 `e1815f293fee4636dff84c717c91facd24afc3df71f2fbe3f3b9d14cf11e4c17`, 33,922 bytes; execution SHA-256 `f06d010a96206b366556e17a0b1eb1e7e995a7489587c190b8547437ba980553`, 14,963 bytes.
**Amended main prompt binding:** SHA-256 `81253e95d4c9211711c588d7752b6d11e6ec19da08362d95d3f66fc9ad550111`, 42,667 bytes. Builder must verify this value and the amended execution hash from the Architect handoff before any edit; any prompt-byte change requires a fresh Architect handoff.
**Historical final UI-adjudication input bindings (superseded by Section 12):** main SHA-256 `30230a1a65eb20e8e0b627baacc0ffd65f6905c23c77d4132efae8d5be76fa17`; execution SHA-256 `f3a82812b24f504a24a21db2339add4d2e8a8914860f6d3318d120b6ba1514e0`.
**Required revision:** clean `HEAD == origin/main == e33955a8f7aa6810e8f2d2e2db3a329fadb8e4da` before these two prompt files; #1046 `CLOSED`, #1047 `OPEN`, AD ceiling 1127, BF ceiling 673.
**Baseline full backend gate:** 20,032 passed / 33 skipped / 198 warnings / 0 failed.
**Builder policy:** no push, issue/PR mutation, remote write, dev server, or Playwright.

**Final closeout rule:** Sections 0 through 11 are historical and must not be rerun. Section 12 alone controls: preserve the reviewed tree, perform no further implementation or validation work, mechanically bind the amended prompt bytes, and create only the approved local unpushed commit. Trackers, prompt archive, push, GitHub mutation, and broad gates remain deferred.

## 0. Hard-Stop Preflight

Read `.github/copilot-instructions.md` and both AD-1128 documents first. Verify:

```powershell
Set-Location D:\ProbOS
git rev-parse HEAD
git rev-parse origin/main
git status --short
gh issue view 1046 --json state
gh issue view 1047 --json state
Get-FileHash -Algorithm SHA256 prompts/ad-1128-crew-session-ingress-dedup.md
```

For the initial build only, hard stop unless both revisions equal the required base, #1046 is closed, #1047 is open, and the only dirty paths are the two Architect prompt files with their handed-off hashes. The post-gate resume rule above supersedes this historical cleanliness/GitHub check. Do not stash, reset, clean, checkout, stage, commit, or absorb any mismatch.

Read the main prompt's live anchors and only the allowed files needed for the current group. Do not remap the repository.

## 1. Build Groups And Focused Gates

Write failing behavior tests before each production group. A red test must fail for the intended contract reason, not import/syntax/fixture setup.

### Group A: Contracts, Canonicalization, Scan, Resume

Implement principal/open result, strict canonical text, bounded config, candidate query, exact-first/semantic selection, owner union, duplicate CAS, and blocked retry evidence/transition edges. Use real stores and real rank fixtures; scorer/decomposer/schedule may be narrow deterministic fakes.

Red/focused:

```powershell
& D:\ProbOS\.venv\Scripts\python.exe -m pytest tests/test_ad1128_crew_session_ingress_dedup.py -q -n 0 --timeout=90 -k "principal or canonical or exact or semantic or scorer or scan or duplicate or owner or blocked or retry"
```

### Group B: Provisioning, Compensation, Repair, Schedule Handoff

Implement strict marker, exact WorkItem/ChatThread primitives, double scan, held decomposition, phase repair, install/adopt reuse, cancellation reconciliation, compensation, startup repair-before-scan, and one-time scheduler binding. Do not start a runner from the service.

Red/focused:

```powershell
& D:\ProbOS\.venv\Scripts\python.exe -m pytest tests/test_ad1128_crew_session_ingress_dedup.py -q -n 0 --timeout=90 -k "double_scan or decompose or provision or room or marker or compensate or repair or cancel or schedule or startup"
```

### Group C: Captain NL, API, Agent Wrapper, Default-Off

Implement the conditional coordinator instance/planner descriptor, real handler, strict room POST, nonblocking `[CREW]` delegate, and removal/delegation of the old direct creator. Preserve `[GROUP_CHAT]` exactly.

Red/focused:

```powershell
& D:\ProbOS\.venv\Scripts\python.exe -m pytest tests/test_ad1128_crew_session_ingress_dedup.py tests/test_ad868_self_originated_crew.py -q -n 0 --timeout=90 -k "intent or api or proactive or provenance or rank or default_off or group_chat"
```

### Group D: HXI Passive Read And Explicit Command

Remove passive task creation and add the dialog/one-POST action with complete states. Update obsolete AD-1084 assertions; do not preserve a test that encodes passive mutation.

Focused Vitest:

```powershell
Set-Location D:\ProbOS\ui
npx vitest run src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx src/components/workspace/__tests__/TodosList.test.tsx
```

Do not run Vite dev/preview and do not run Playwright.

## 2. Module And Blast Gates

After all groups are focused-green, run the complete backend feature module serially:

```powershell
Set-Location D:\ProbOS
& D:\ProbOS\.venv\Scripts\python.exe -m pytest tests/test_ad1128_crew_session_ingress_dedup.py tests/test_ad868_self_originated_crew.py -q -n 0 --timeout=90
```

Run the landed CrewSession/lifecycle blast serially:

```powershell
& D:\ProbOS\.venv\Scripts\python.exe -m pytest tests/test_ad1124_crew_session_contract.py tests/test_ad1125_room_bound_execution.py tests/test_ad1126_verified_finalization.py tests/test_ad1127_crew_session_lifecycle_recovery.py tests/test_ad867_crew_orchestrator.py tests/test_ad868_self_originated_crew.py tests/test_ad859_crew_executor.py tests/test_ad925_auto_task_room.py tests/test_bf598_shutdown_idempotency.py tests/test_ad820_shutdown_integrity.py tests/test_bf296_shutdown_phase_ordering.py -q -n 0 --timeout=90
```

Run the full changed workspace UI neighborhood, then compile/build:

```powershell
Set-Location D:\ProbOS\ui
npx vitest run src/components/workspace
npm run build
```

Return to the repo and compile only changed Python plus the new test:

```powershell
Set-Location D:\ProbOS
& D:\ProbOS\.venv\Scripts\python.exe -m compileall -q src/probos/agents/operations/coordinator.py src/probos/cognitive/crew_orchestrator.py src/probos/cognitive/crew_session.py src/probos/config.py src/probos/proactive.py src/probos/routers/threads.py src/probos/runtime.py src/probos/startup/finalize.py src/probos/threads src/probos/workforce.py tests/test_ad1128_crew_session_ingress_dedup.py tests/test_ad868_self_originated_crew.py
git diff --check
```

No full backend or full UI suite is permitted yet.

## 3. Required Audits Before Handback

1. Dirty paths are an exact subset of the main prompt allowlist; no YAML, schema/DDL, dependency, EventType, commercial, AD-1129+ projection/WS/metrics/trust/delivery path changed.
2. `open_or_resume` is the only create/resume ingress. `originate_crew_task` is removed or delegates; no direct parent/child creation and no `await run_crew_task` remains on ingress paths.
3. `CrewOrchestrator.schedule` remains the sole task owner. No new task registry, runner, queue, daemon, poller, `ensure_future`, or unheld `create_task`.
4. Disabled mode has no live/planner descriptor, repair/candidate scan, scorer, decomposition, parent/thread/task creation, schedule, or passive UI mutation. POST returns fail-closed before service work.
5. Agent identity, crew status, and live Lieutenant+ rank are checked before scan/scorer/decompose/write, including post-decomposition rank drift.
6. Goal uses exact str, NFKC/casefold/whitespace, punctuation retention, NUL/surrogate/UTF-8/char bounds, and SHA-256. Criteria/deliverable compatibility is exact as specified.
7. Scan and scorer work have independent hard caps. Overflow and malformed candidates/scorer output fail closed. Exact precedes semantic; tie ordering is deterministic.
8. Admission lock spans both scans/decomposition/provisioning. No write precedes scan 2. Duplicate CAS increments once per invocation and preserves facilitator/provenance/plan.
9. Marker phases/fields are exact and bounded. Every cross-store mutation has authoritative reread/cancel reconciliation. Compensation deletes only untouched marker-owned state and never after session authority.
10. Repair runs before the normal AD-1127 scan and starts no daemon. Plan work calls only landed install/adopt APIs.
11. Blocked work schedules only after explicit Captain/evidence-gated retry; terminal rows never reopen; verifying restoration exists in both fine/coarse machines.
12. API rejects extra/principal fields and has happy/error/validation cases. UI mount/open/collapse/poll are GET-only; confirm is one POST with loading/error/disabled/double-submit coverage and stroke icons/no emoji.
13. Real stores and real registry/rank fixtures cover substrate behavior. No MagicMock at those boundaries. Schedule/scorer/decomposer protocol fakes and explicit barrier subclasses are narrow.
14. New public methods are fully annotated. Logs include what failed, why it matters, and the next durable disposition; no goal/content/secrets are logged.
15. Search changed prompt/example/response text against `_CAPABILITY_GAP_RE`; no user-visible false capability-gap phrase is added.

## 4. Builder Handback And Architect PRE-GATE

Builder stops before expensive gates and reports:

- exact changed paths and `git diff --stat`;
- red-first evidence and focused/module/blast/UI counts;
- compile/build/diff/audit results;
- warning families/counts;
- every intentional update to a pre-AD-1128 test;
- any unresolved contract or environment issue.

Architect then performs all three implementation passes:

| Pass | Required decision |
|---|---|
| 1 Contract | live signatures, principal boundary, exact canonical/dedup/result/marker/API contracts, no phantom API |
| 2 Safety | races, double scan, rank drift, cancellation, commit ambiguity, compensation, repair, blocked evidence, one runner |
| 3 Scope/Gate | allowlist/default-off/UI read-only/deferred ADs, tests, warning equation, freeze and closeout consistency |

The historical required verdict was `APPROVED FOR FROZEN FULL GATES`, and that review is complete. Do not rerun it during post-gate correction. No source-string-only proof may approve a persistence, rank, scheduling, cancellation, or API behavior.

## 5. Post-Gate Adjudication Binding

The completed optimized changed-surface batch is authoritative evidence, not permission to modify production. Backend log `probos_ad1128_backend_5d2642e4c688480aa6ba9c053134f277.log` has SHA-256 `bf0ebe0f8ca44a4768e667d6a07c1077f88ff1718db22cb84090244d90b63ff6`: 177 collected, 158 passed, 19 failed under `-n 16 --dist=worksteal` in 75.89 seconds. Targeted UI is accepted at 23/23 in 3.34 seconds. No UI byte may change and no UI rerun is authorized.

Architect verdict: all 19 observed reds are test-contract defects. Fifteen new AD-1128 tests share a service clock fixed at `1_000.0`, behind the real parent `created_at`; the live `crew_session_clock_regression` is correct. Four exact legacy tests encode pre-AD-1128 startup/public-surface assumptions. One adjacent exact-public-set test in AD-1124 is guaranteed stale and is authorized proactively. No production fix is authorized.

Only these test functions may change:

```text
tests/test_ad1128_crew_session_ingress_dedup.py
  shared _Clock default used by the write-capable harness
  test_open_or_resume_provisions_parent_room_plan_and_clears_marker
  test_open_or_resume_punctuation_difference_is_not_exact

tests/test_ad867_crew_orchestrator.py
  test_maybe_dispatch_holds_task_reference

tests/test_ad1124_crew_session_contract.py
  test_enabled_wirer_real_stores_attaches_once_preserving_identity
  test_public_service_api_and_annotations_are_exact
  test_source_has_to_thread_and_no_raw_sqlite_schema_or_lifecycle_path

tests/test_ad1126_verified_finalization.py
  test_public_session_apis_and_finalizer_signature_are_fully_typed
```

Support code may be local to those functions only. Do not edit module-wide helpers except the AD-1128 `_Clock` default. In the punctuation test, only its scorer-call assertion may change. Do not change production/tests outside this list, UI, trackers, archive, config/YAML, Git, or GitHub.

Apply these exact corrections:

1. Change the AD-1128 `_Clock` default from `1_000.0` to `32_503_680_000.0` (year 3000 UTC, below `_MAX_TIMESTAMP`). Keep its deterministic `+1.0` progression. Do not use wall time or monkeypatch `time.time`. In the named provisioning test, after authoritative parent reload, assert `parent.metadata["crew_session"]["transitioned_at"] > parent.created_at`.
2. In the AD-867 named test, construct the orchestrator with a local narrow service fake implementing `async def repair_provisioning(self, *, limit: int) -> tuple[str, ...]`, recording limits and returning `()`. Assert exactly `[config.agentic_dispatch.crew_provisioning_repair_limit]` after `start()`. Preserve every held-owner-task assertion.
3. In the AD-1124 wiring test, provide all six live mandatory dependencies: the existing real work/thread stores plus non-null `registry`, `ontology`, `trust_network`, and `llm_client`. Preserve attach-once and object-identity assertions; do not weaken `_wire_crew_session_service()`.
4. In AD-1124's exact service API test, add only these parameter sets:

```text
captain_principal: self
agent_principal: self, agent_id
bind_scheduler: self, schedule
open_or_resume: self, principal, goal, success_criteria, expected_deliverable,
                facilitator_id, owner_ids, requested_thread_id, retry_blocked
repair_provisioning: self, limit
```

5. In AD-1124's source guard, remove only `open_or_resume` from the forbidden tuple. Attribute each `asyncio.create_task` call to its containing async function and require the exact owner set `_run_held_to_thread`, `_reconcile_cancelled_parent_create`, `_checkpoint_cancelled_provisioning`, `_reconcile_cancelled_plan_commit`. Require one call per owner, one assigned task, and a shield/drain in each owner; preserve the existing detailed `_reconcile_plan_commit` target/name/shield assertions and `"create_task" not in merge_source`.
6. In the AD-1126 exact public set, add only `captain_principal`, `agent_principal`, `bind_scheduler`, `open_or_resume`, and `repair_provisioning`. Leave all finalizer/store signature assertions unchanged.

No test rename, deletion, skip, xfail, new parametrization, parameter removal, or test addition is allowed. Collection cardinality and net-new `N` therefore remain unchanged. The existing AD-1124 tests `test_initialize_clock_regression_rejects_without_mutation` and `test_transition_clock_regression_rejects_without_mutation` are immutable negative controls.

## 6. Freeze And One Optimized Correction Gate

Before test edits, require every production/UI hash in `%TEMP%\ad1128_post_manifest_5d2642e4c688480aa6ba9c053134f277.txt` to match. After edits, freeze both amended prompts and the four authorized test paths to a new external correction manifest. Production/UI mismatch is a hard stop; do not repair it.

Run exactly one backend correction batch. Do not run a serial pre-gate, full `tests/`, full UI, build, Playwright, or a second confidence run. AD-1133 owns the next full-suite gate.

```powershell
Set-Location D:\ProbOS
$gateId = [guid]::NewGuid().ToString('N')
$gateDir = Join-Path $env:TEMP ('probos_ad1128_correction_' + $gateId)
$gateLog = Join-Path $env:TEMP ('probos_ad1128_correction_' + $gateId + '.log')
if (Test-Path -LiteralPath $gateDir) { throw 'Gate directory collision' }
New-Item -ItemType Directory -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
  & D:\ProbOS\.venv\Scripts\python.exe -m pytest `
    tests/test_ad1128_crew_session_ingress_dedup.py `
    tests/test_ad867_crew_orchestrator.py::test_maybe_dispatch_holds_task_reference `
    tests/test_ad1124_crew_session_contract.py::test_enabled_wirer_real_stores_attaches_once_preserving_identity `
    tests/test_ad1124_crew_session_contract.py::test_public_service_api_and_annotations_are_exact `
    tests/test_ad1124_crew_session_contract.py::test_source_has_to_thread_and_no_raw_sqlite_schema_or_lifecycle_path `
    tests/test_ad1124_crew_session_contract.py::test_initialize_clock_regression_rejects_without_mutation `
    tests/test_ad1124_crew_session_contract.py::test_transition_clock_regression_rejects_without_mutation `
    tests/test_ad1126_verified_finalization.py::test_public_session_apis_and_finalizer_signature_are_fully_typed `
    -p no:cacheprovider -n 16 --dist=worksteal --timeout=90 -q --tb=short *> $gateLog
  $exit = $LASTEXITCODE
  Get-Content -LiteralPath $gateLog -Tail 320
  "AD1128_CORRECTION_LOG=$gateLog"
  "AD1128_CORRECTION_EXIT=$exit"
  if ($exit -ne 0) { exit $exit }
} finally {
  Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Green requires zero failures and zero warnings from these paths. On any red, stop and return the exact failure to Architect; do not patch again. Recompute the correction manifest and require exact equality. Report the original 177-test batch and accepted 23-test UI result separately from this correction batch; never combine their pass counts.

### Final One-Node Correction

The correction batch above completed 176/177 backend; do not rerun it. The accepted UI result remains 23/23 and no UI rerun is authorized. The sole failure is `tests/test_ad1128_crew_session_ingress_dedup.py::test_open_or_resume_punctuation_difference_is_not_exact`.

Production is correct. Section 3 requires fresh rows and fresh scoring both before decomposition and after decomposition before the first provisioning write. The live method performs both scans under the admission lock. Change only the scorer-call assertion to this exact ordered value:

```python
[
    ("report alpha", "report: alpha"),
    ("report alpha", "report: alpha"),
]
```

The first call is the bounded pre-decomposition semantic scan. The second is the fresh post-decomposition race barrier against an external/non-cooperating writer. Do not remove, cache, coalesce, or otherwise change either production call. Test cardinality and net-new backend test accounting `N` remain unchanged.

Run only this exact node:

```powershell
Set-Location D:\ProbOS
$gateId = [guid]::NewGuid().ToString('N')
$gateDir = Join-Path $env:TEMP ('probos_ad1128_exact_' + $gateId)
if (Test-Path -LiteralPath $gateDir) { throw 'Gate directory collision' }
New-Item -ItemType Directory -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
  & D:\ProbOS\.venv\Scripts\python.exe -m pytest `
    tests/test_ad1128_crew_session_ingress_dedup.py::test_open_or_resume_punctuation_difference_is_not_exact `
    -p no:cacheprovider -n 0 --timeout=90 -q --tb=short
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Then perform static audits only: verify both handed-off prompt hashes/sizes; require frozen production/UI hashes unchanged; require the final correction to replace only that one assertion; require no test definition, parametrization, skip/xfail, or collection-cardinality change; and require no path outside the existing AD-1128 correction allowlist to gain a new mutation. Do not run any broader backend selection, UI test, build, Playwright, full suite, or second confidence run. Green is one passed, zero failed, zero warnings. Report the completed 176/177 correction batch, this exact-node result, and accepted UI 23/23 separately.

## 7. Green Hash Recheck And Direct Closeout

When the one correction gate is green, do not perform a redundant broad review or another gate:

1. Recompute every frozen hash/size and require exact manifest equality.
2. Recheck `git diff --check`, the exact amended allowlist, no staged paths, unchanged collection cardinality/net `N`, and warning provenance.
3. Update `PROGRESS.md` with AD-1128 behavior, unchanged `N`, focused/blast results, the 177-test changed-surface batch, the 176/177 correction-batch result, the final exact-node result, accepted targeted UI 23/23, warning provenance, explicit full-suite deferral to AD-1133, AD ceiling 1128, BF ceiling 673, and #1047 close-on-push wording.
4. Update `docs/development/roadmap.md` only for AD-1128/#1047 completion and ceilings. Do not add AD-1129+ details.
5. Append AD-1128 to `DECISIONS.md` using the existing era-link format.
6. Move both prompt files byte-for-byte to `prompts/archive/`; verify each pre/post SHA-256. Do not reconstruct through a patch.
7. Stage only allowlisted implementation/tests/UI, three trackers, and two archive files. Confirm root prompt deletions/renames and no other staged path.
8. Commit exactly `AD-1128: add unified CrewSession ingress (closes #1047)`.
9. Report commit hash, committed paths, original/correction/UI counts separately, unchanged `N`, full-suite deferral to AD-1133, warning provenance, and final hash recheck. Stop with no push and no GitHub mutation.

## Hard Stops

- Base, issue state, ceilings, cleanliness, prompt hash, or allowlist mismatch.
- Need for schema/DDL/index/YAML/dependency/EventType/commercial/AD-1129+ changes.
- A second runner, inline runner await, unbounded scan/scorer/retry/marker, or passive HXI mutation.
- Caller-forgeable accepted principal, agent rank checked only in proactive code, terminal reopen, or broad blocked retry.
- Write before scan 2, duplicate count not exactly once per duplicate invocation, or facilitator/provenance/plan rewrite.
- Compensation after session authority or deletion without exact untouched proof.
- Cancellation swallowed/translated, sync mutation abandoned in a thread, or uncertain commit hidden.
- Any mutation after freeze without complete affected revalidation and new PRE-GATE/freeze.
- Any production/UI mutation during post-gate correction, any test change outside the four authorized paths and five exact legacy functions plus the three named AD-1128 locations, any cardinality change, or any broader backend/full-UI run before AD-1133.
- Builder push or GitHub mutation.

Verify all changes comply with the Engineering Principles in .github/copilot-instructions.md.

## 8. Code-Review Repair Execution Amendment

**Status:** READY for one five-finding implementation batch and one targeted validation batch.

This section is the only active workflow for the code-review repair. Preserve the complete live implementation, including the already-correct two-scan scorer behavior and all AD-1124 through AD-1127 service-owned lifecycle CAS paths. Do not rerun or resume the historical correction-only workflow. Ignore untracked AD-1129 prompts and do not inspect, hash, edit, stage, archive, or report them.

### 8.1 Frozen Inputs And Allowed Paths

Before any implementation edit, require exact prompt inputs:

```text
prompts/ad-1128-crew-session-ingress-dedup.md
  SHA-256 b71859afb69b5abeb8735379f4cf3a0feb216a07a4c54c4524831ee47791ba76
  size    70,702 bytes

prompts/ad-1128-crew-session-ingress-dedup-execution.md
  use the exact Architect handoff SHA-256 and size reported after this amendment
```

The implementation changed-path set must be an exact subset of:

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

No other production, test, UI, config/YAML, schema/DDL, dependency, tracker, archive, prompt, commercial, Git, or GitHub path is authorized. `todosApi.ts` is unchanged: the existing request shape remains valid. Do not create a new source, test, or UI file.

### 8.2 One Implementation Batch, No Red-First Runs

Complete all production, test, and UI edits for all five findings before running any test, build, compile, lint, dev-server, Playwright, or confidence command. Reading and static reasoning are allowed. Do not stop after an individual finding for a focused run.

Implement in this dependency order:

1. **Store admission capability and generic barriers.** Add the exact typed create request/protocols and private one-shot real port in `workforce.py`; extract one private insert helper so generic and privileged creation share SQL/requirement/cache/event behavior. Reject generic CrewSession create/from-template/update/transition/assign/claim/unassign and parent-mutating booking paths before side effects. Preserve child work types and every exact service CAS API. Add only the specified 409 mappings in the generic workforce router.
2. **Service reservation and provenance.** Inject the claimed port from finalize wiring; keep it optional for legacy non-ingress service use and mandatory before `open_or_resume()` work. Validate the exact marker-only production request in the cognitive layer. Hold the store reservation over requested-room reread, scan 2, fresh scoring, and parent insert. Add the single exact provenance helper and use it through `_validate_loaded()`, initialization, provisioning validation, authoritative rereads, repair, and publication paths before scorer/write/schedule. Re-raise provenance failure from repair without fail-transition or marker mutation.
3. **Startup repaired-id handoff.** Capture repaired ids, append unseen recovery ids, apply one combined `crew_resume_scan_limit`, validate the entire selected batch through service session/recovery APIs before any schedule, then schedule active states once in deterministic order.
4. **Existing route authentication.** Add only `Depends(require_crew_scope)` to Start Work and configured-token missing/wrong/valid tests using the current auth config/pattern. Preserve empty-token local pass-through and all current status mapping.
5. **Keyboard-complete modal.** Add initial Goal focus, explicit Tab/Shift+Tab containment, programmatically focusable pending fallback, guarded Escape, and connected-opener restoration to the existing rail. Preserve request count, error/form state, HXI styling, dimensions, and passive GET-only behavior.

After production/UI behavior is complete, make all tests in the same edit batch. Do not run them yet.

### 8.3 Exact Compatibility-Test Authority

`tests/test_ad1128_crew_session_ingress_dedup.py` owns every new behavior test: reservation race, generic router/store rejections and child control, repaired-id union/cap/validation, configured Bearer cases, and provenance fail-closed controls.

The four landed lifecycle files may change only where their fixtures or assertions are made obsolete by this repair:

- Replace bare generic `create_work_item(work_type="crew_session")` fixture setup with the real claimed port and `CrewSessionParentCreate`. Retain deterministic ids/timestamps and all room/session/recovery state.
- Replace only Captain-session `originator_id="captain-1"` fixtures with exact lowercase `"captain"`. Do not alter unrelated metadata/provenance test values.
- A test needing non-draft or malformed persisted authority must begin with a port-created draft and use an existing exact CAS helper under test to reach that state; no public bypass flag, test-only production hook, private reach-through, source-string authorization, raw SQL, or direct private lock access may be added.
- `test_initialize_session_generic_writer_interleaving_conflicts_without_mutation`: keep all three parameter cases, but each generic assigned-to/work-type/status attempt must now reject `crew_session_write_reserved`; release the existing service CAS barrier and prove initialization remains authoritative and mutation-free.
- `test_transition_session_generic_status_interleaving_conflicts_without_mutation`: generic transition rejects and the service transition commits; preserve exact status/session checks.
- `test_transition_session_generic_metadata_alias_interleaving_conflicts_without_mutation`: generic metadata update rejects before alias injection and the service transition remains authoritative; retain a separate exact-JSON CAS alias-conflict assertion if that is the behavior the test originally protects.
- `test_generic_status_writer_cannot_interleave_after_merge_admission`: preserve the lock-order proof, then require the queued generic writer to raise `crew_session_write_reserved` with no second SQL update/event.
- Update exact public/type guards for `CrewSessionParentCreate`, `CrewSessionParentReservation.create_parent`, `CrewSessionAdmissionPort.reserve`, `WorkItemStore.claim_crew_session_admission_port`, and the `CrewSessionService.__init__` `admission_port` parameter. Do not add a new public CrewSessionService method.

Preserve every test name and test cardinality unless a genuinely new AD-1128 behavior test is required. New tests increase net `N`; existing tests may not be renamed, deleted, skipped, xfailed, merged, or weakened. Negative clock, plan, recovery, room, cancellation, finalization, publication, and exact JSON-type tests remain intact.

### 8.4 Required New Test Cases

Add narrowly named cases covering at least:

```text
test_store_crew_session_admission_port_claim_is_one_shot_and_typed
test_store_crew_session_reservation_is_task_scoped_one_use_and_detached
test_generic_crew_session_writers_and_router_reject_before_side_effects
test_generic_child_work_type_remains_writable
test_crew_session_claim_unassign_and_booking_paths_reject_before_side_effects
test_scan2_reservation_blocks_generic_parent_and_commits_one_authority
test_start_schedules_repaired_id_absent_from_recovery_candidates
test_start_unions_repaired_first_once_under_one_global_cap
test_start_malformed_provenance_schedules_nothing
test_start_work_configured_token_missing_and_wrong_reject_before_service
test_start_work_configured_token_valid_reaches_service
test_loaded_captain_and_agent_provenance_is_exact_before_scorer_or_write
test_provisioning_and_initialize_reject_forged_provenance_without_mutation
```

Names may follow the file's existing naming grammar, but each behavior must remain independently assertable. For store tests, inspect real requirement rows/events as well as parent rows. For startup, use a schedule spy and require complete-batch validation before its first call. For auth, use the real dependency and config, not a dependency override. For provenance, include valid Captain/agent controls and assert zero scorer/decomposer/room/write/schedule calls on malformed rows.

Extend only `WorkspaceFilesRail.test.tsx` with:

```text
opens with Goal focused
Tab wraps last enabled control to first; Shift+Tab wraps first to last
non-pending Escape closes, stops propagation, and restores opener focus
pending Escape is inert and focus remains inside the dialog container
Cancel and successful submit restore the connected opener
```

Retain every existing passive-read, one-POST, retry/error, stale-room-response, no-emoji, and stable-layout assertion.

### 8.5 One Targeted Validation Batch

After all five implementations and all authorized test migrations are complete, run this batch exactly once. Do not run a red-first node, a serial preflight, an intermediate finding gate, a second confidence run, or any broader selection.

Python changed-set gate, one invocation. It collects at least eight tests and therefore must use the stable 16-core ceiling:

```powershell
Set-Location D:\ProbOS
$gateId = [guid]::NewGuid().ToString('N')
$gateDir = Join-Path $env:TEMP ('probos_ad1128_review_repair_' + $gateId)
$gateLog = Join-Path $env:TEMP ('probos_ad1128_review_repair_' + $gateId + '.log')
if (Test-Path -LiteralPath $gateDir) { throw 'Gate directory collision' }
New-Item -ItemType Directory -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
  & D:\ProbOS\.venv\Scripts\python.exe -m pytest `
    tests/test_ad1124_crew_session_contract.py `
    tests/test_ad1125_room_bound_execution.py `
    tests/test_ad1126_verified_finalization.py `
    tests/test_ad1127_crew_session_lifecycle_recovery.py `
    tests/test_ad1128_crew_session_ingress_dedup.py `
    -p no:cacheprovider -n 16 --dist=worksteal --timeout=90 -q --tb=short *> $gateLog
  $exit = $LASTEXITCODE
  Get-Content -LiteralPath $gateLog -Tail 320
  "AD1128_REVIEW_REPAIR_LOG=$gateLog"
  "AD1128_REVIEW_REPAIR_EXIT=$exit"
  if ($exit -ne 0) { exit $exit }
} finally {
  Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Directly affected UI gate, one invocation with Vitest's default pool and no extra worker/pool flag:

```powershell
Set-Location D:\ProbOS\ui
npx vitest run src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
```

These two invocations are one validation batch. Green requires zero failures. Report warning families and prove no new warning originates from changed paths; do not conflate accepted historical counts with this repair batch.

If either invocation fails, stop and return the exact failure to Architect. Do not patch, rerun, widen selection, serialize a parallel failure, quarantine, skip, xfail, or invoke the old hard-stop triage tree in this same Builder pass. A repair requires a new Architect adjudication and a newly bound prompt hash.

Do not run full `tests/`, any other Python node, full UI, `npm run build`, TypeScript build, compileall, lint, Playwright, Vite, dev server, or coverage. AD-1133 owns the consolidated full gate.

### 8.6 Static Review And Handback

After the one green validation batch, perform read-only scope and source audits only; no further executable validation:

1. Prompt bytes still match the two handed-off hashes/sizes.
2. Changed paths are an exact subset of Section 8.1 and no AD-1129 path was touched.
3. The service never accesses a private store authority/lock; `workforce.py` never imports the cognitive module; no public method accepts an authority token/bypass/source-string credential; each reservation is one-use, context/task/store/generation-bound, and input-detached before the row lock.
4. Generic CrewSession create/template/update/transition/assign/claim/unassign and parent-mutating booking paths reject before SQL/events/bookings; exact service CAS methods remain the lifecycle mutation path.
5. The reservation spans second-room reread, fresh scan/scoring, and parent insertion; scan 1 remains outside it.
6. Startup validates the complete repaired-first capped union before the first `schedule()` and starts no daemon/runner.
7. Start Work imports and uses the existing `require_crew_scope` and introduces no browser token handling or auth configuration.
8. `_validate_loaded()` enforces the exact lowercase Captain/agent parent provenance relation, and every persisted-session scorer/write/repair/schedule path goes through it.
9. Focus never escapes the open modal, pending Escape is inert, and success/Cancel/Escape restore only a connected opener.
10. No test deletion/skip/xfail/rename weakened landed coverage; report net-new test count `N` separately.

Hand back:

- exact changed paths and sizes;
- prompt SHA-256/size bindings;
- Python collected/passed/failed/skipped/warnings, duration, worker mode, and log hash;
- directly affected Vitest passed/failed count and duration;
- exact compatibility tests/helpers changed and why;
- net-new backend/UI test counts;
- the ten static audit outcomes;
- explicit statement that full Python/UI/build/Playwright are deferred to AD-1133.

Stop after handback. Do not update `PROGRESS.md`, roadmap, or `DECISIONS.md`; do not archive prompts; do not stage, commit, push, call GitHub, or close #1047.

### 8.7 Repair Hard Stops

- A real store can be written by presenting a public token, source string, boolean bypass, copied sentinel, retained/exited reservation, child-task reservation call, duplicate create, or privately reached authority.
- The service reaches into `_work_item_row_write_lock` or another store private member; `workforce.py` imports cognitive CrewSession code.
- Scan 2 is outside the reservation, the row lock is held during scorer/decomposer work, or two real service instances can insert concurrently.
- Generic CrewSession parent mutation remains possible through the supported workforce router/store methods, or child work types are accidentally reserved.
- Startup applies independent schedule caps, schedules before validating the full selected batch, loses a repaired-only id, or changes the sole task owner.
- Start Work uses a new auth mechanism or HXI-held secret instead of `require_crew_scope`.
- Any malformed persisted provenance is normalized to a repairable provisioning error or reaches scorer, write, fail-transition, marker/participant mutation, or schedule.
- Pending focus can leave the dialog, Escape closes a pending request, or opener restoration targets a detached element.
- Any path outside Section 8.1 changes, any AD-1129 path is considered, or any forbidden validation/closeout action runs.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 9. Failed-Gate Repair Execution Amendment

**Status:** CONTENT READY; execution is NOT READY until the Architect supplies
the exact post-amendment SHA-256 and byte size for both active prompts.

This section supersedes Section 8's failed-gate stop and every earlier workflow
where they conflict. The binding behavior and exact compatibility semantics are
in `Post-Coding Backend Gate Adjudication (2026-07-21)` in the main prompt.
Preserve the full live tree and ignore AD-1129 prompt files.

### 9.1 Frozen Handoff And New Mutation Set

Architect input hashes before this amendment were:

```text
prompts/ad-1128-crew-session-ingress-dedup.md
  SHA-256 b71859afb69b5abeb8735379f4cf3a0feb216a07a4c54c4524831ee47791ba76

prompts/ad-1128-crew-session-ingress-dedup-execution.md
  SHA-256 391ad49bfacb0ff426e0b149b7d9b55131f00692c34a5570d6c9ebd1554f6fe5
```

Before editing implementation/tests, require the exact post-amendment prompt
SHA-256 values and byte sizes from the Architect handoff. A mismatch is a hard
stop. Do not normalize or rewrite either prompt.

Preserve all currently changed paths. New mutations after this handoff are an
exact subset of:

```text
src/probos/workforce.py
tests/test_ad1126_verified_finalization.py
tests/test_ad1127_crew_session_lifecycle_recovery.py
tests/test_ad1128_crew_session_ingress_dedup.py
```

No other production, test, UI, config/YAML, schema, dependency, tracker,
archive, prompt, commercial, Git, or GitHub mutation is authorized. No new file
is authorized. Both active AD-1128 prompts are frozen inputs after handoff; the
Builder must not edit them.

### 9.2 One Implementation Batch

Make every repair before running any executable validation:

1. In `WorkItemStore.delete_untouched_crew_session_provisioning()`, change only
   the contradictory empty-description predicate to require the exact validated
   marker goal stored by the privileged create path. Preserve every other
   untouched predicate, lock, transaction, requirement/child/booking check, and
   return behavior. Do not change `crew_session.py`.
2. Apply the seven exact AD-1126 helper/test migrations from the main prompt.
   Generic parent writes remain rejected; real conflict injection uses only
  `CrewSessionService` or the exact store CAS APIs. The status parameter uses
  the main prompt's exact legal `verifying -> blocked_needs_captain` competing
  transition. Add the missing real claimed port to the one local `_Stores`
  fixture.
3. Apply the two exact AD-1127 authoritative-reread probe repairs. Keep every
   cancellation and recovery assertion.
4. Preserve the three AD-1128 compensation outcomes as deletion of exact
   untouched pre-session authority. Only add/adjust assertions needed to prove
   the fixture's description equals the marker goal; do not change their
   expected policy.

No test definition, parameter, or collection count may change. Do not edit
passing production/UI behavior, weaken reservation, add an admission mutation
API, or introduce a test-only bypass.

### 9.3 One Validation Batch

After all fixes are complete, run the same backend target exactly once:

```powershell
Set-Location D:\ProbOS
$gateId = [guid]::NewGuid().ToString('N')
$gateDir = Join-Path $env:TEMP ('probos_ad1128_gate_adjudication_' + $gateId)
$gateLog = Join-Path $env:TEMP ('probos_ad1128_gate_adjudication_' + $gateId + '.log')
if (Test-Path -LiteralPath $gateDir) { throw 'Gate directory collision' }
New-Item -ItemType Directory -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
  & D:\ProbOS\.venv\Scripts\python.exe -m pytest `
    tests/test_ad1124_crew_session_contract.py `
    tests/test_ad1125_room_bound_execution.py `
    tests/test_ad1126_verified_finalization.py `
    tests/test_ad1127_crew_session_lifecycle_recovery.py `
    tests/test_ad1128_crew_session_ingress_dedup.py `
    -p no:cacheprovider -n 16 --dist=worksteal --timeout=90 -q --tb=short *> $gateLog
  $exit = $LASTEXITCODE
  Get-Content -LiteralPath $gateLog -Tail 320
  "AD1128_GATE_ADJUDICATION_LOG=$gateLog"
  "AD1128_GATE_ADJUDICATION_EXIT=$exit"
  if ($exit -ne 0) { exit $exit }
} finally {
  Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Green requires exactly 535 collected, 535 passed, zero failed. Then run the
directly affected UI file once with Vitest's default pool:

```powershell
Set-Location D:\ProbOS\ui
npx vitest run src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
```

These two invocations are one validation batch. If either fails, stop and hand
the exact failure back to Architect. Do not patch, rerun, serialize, widen,
quarantine, skip, or xfail in the same Builder pass.

Do not run full `tests/`, another Python node, another Vitest file, full UI,
build, TypeScript build, compileall, lint, Playwright, Vite, dev server,
coverage, or a second confidence gate.

### 9.4 Static Audits And Handback

After green validation, perform read-only audits only:

1. Both active AD-1128 prompt hashes/sizes still match the handoff.
2. New mutations are an exact subset of Section 9.1; AD-1129 was untouched.
3. Generic CrewSession parent writers still reject before side effects; no new
   token, bypass, source-string authority, private lock, or private port access
   exists.
4. Every internal parent fixture uses the real port claimed through the owning
   public store API; reservations remain task-scoped and create-only.
5. Reachable race tests use the exact service/store CAS surface; generic methods
   occur only in explicit reservation-rejection assertions.
6. Sibling metadata is shallow-preserved before and after publication.
7. Both AD-1127 probes use authoritative post-reconciliation status/assignment.
8. Exact untouched compensation matches the live parent create contract; every
   ambiguity still leaves a discoverable marker, and post-session deletion is
   impossible.
9. No test name/parameter/cardinality changed; backend collection remains 535.
10. No UI byte changed; report the directly affected Vitest result separately.

Hand back prompt hashes/sizes, exact changed paths, backend and Vitest counts,
durations/log hash, warning provenance, and all ten audit outcomes. Stop without
tracker/archive/Git/GitHub actions.

### 9.5 Hard Stops

- Any production change beyond the one description predicate.
- Any successful generic CrewSession parent mutation or mutation authority
  derived from the create-only admission port.
- Any test-only bypass, raw SQL, private lock/port/token access, MagicMock
  authority, or fabricated accepted reassignment/deletion.
- Any compensation policy change from exact deletion to unconditional retention,
  or any delete after drift, uncertainty, or session initialization.
- Any changed path outside Section 9.1, test-cardinality change, AD-1129 access,
  forbidden command, rerun, or closeout action.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

### 9.6 Final Review Record And Local Closeout Terms

**Status:** APPROVED FOR LOCAL UNPUSHED COMMIT. This review record is
incorporated by final Section 12 and documents why the earlier
production-freeze/test-defect conclusion is superseded. The complete AD-1128
implementation is frozen at the reviewed bytes. Do not edit production,
backend tests, UI, config, trackers, archive files, commercial files, or any
AD-1129+ file.

#### 9.6.1 Corrected UI Adjudication

The prior conclusion that production was correct and the test simulation was
stale is falsified and withdrawn. Three realistic/synthetic harness attempts
reproduced focus escape. The discriminating jsdom diagnostic showed that the
old comma-group `querySelectorAll()` returned enabled controls in selector-group
order (`button`, then `input`, then `textarea`) rather than the required dialog
document order.

The final production implementation fixes that root cause without changing the
dialog layout or request behavior:

- it enumerates `dialog.querySelectorAll('*')` in document order;
- it filters each element with `.matches(focusableSelector)`;
- it owns every enabled `Tab` and `Shift+Tab` move with `preventDefault()` and
  modular index arithmetic; and
- it retains the no-enabled-control pending fallback on the programmatically
  focusable dialog container.

The final test dispatches component-owned keydowns and proves the exact forward
sequence Goal -> Criteria -> Deliverable -> Retry -> Cancel -> Confirm -> Goal,
plus Goal -> Confirm on reverse wrap. The exact focused node passed, the current
`WorkspaceFilesRail` file passed 21/21, and editor diagnostics are clean.

These exact UI bytes are authorized:

```text
ui/src/components/workspace/WorkspaceFilesRail.tsx
  SHA-256 9f5be91ae2feda65d68682f0d46df6a9ce3f022cc6bb7767a13b01da9ad2a998

ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
  SHA-256 74595698d786746fee41aded080176144976b3db6ee3e9a1bbbf25b8741b56c4
```

Any mismatch is an Architect hard stop. Do not restore the selector-list
implementation and do not replace the component-owned keydown assertions with
native jsdom Tab navigation.

#### 9.6.2 Accepted Final Evidence

The following evidence is complete and must not be rerun during closeout:

- backend changed surface: 535 collected, 534 passed, one failed; the exact
  corrected node then passed, reconciling all 535 nodes on the final contract;
- the earlier 177-node changed surface and its exact corrections are reconciled;
- current targeted UI: 21/21 `WorkspaceFilesRail` on the exact hashes above;
- prior UI neighborhood: 23/23 `WorkspaceFilesRail` plus `TodosList`;
- editor diagnostics, diff checks, and static scope audits are clean; and
- net-new backend test accounting is `N=65`.

No broad backend suite was run by Captain directive. Do not run full Python,
full UI, build, typecheck, lint, Playwright, Vite, dev server, coverage, or a
confidence rerun. The consolidated AD-1133 gate owns broad validation.

#### 9.6.3 Mechanical Prompt Binding

Architect input bindings before this amendment were:

```text
prompts/ad-1128-crew-session-ingress-dedup.md
  SHA-256 af59778ad27788a874e747c83da9b67d0bfd8bf0b179bf85c5be6533c0d79deb

prompts/ad-1128-crew-session-ingress-dedup-execution.md
  SHA-256 902337edca865d881f4419c7aa80724e734179b0b3c1ee267d50fa451b0b6ac8
```

Before the local commit, mechanically compute the raw SHA-256 and byte length
of both amended active prompts and include all four values in the closeout
report. Hashing is a measurement step only: do not normalize, re-save, patch,
or otherwise revise either prompt while binding it. A prompt mismatch requires
a fresh Architect handoff.

#### 9.6.4 Local Commit Only

After the mechanical binding:

1. Preserve the already reviewed AD-1128 actual diff exactly; add or remove no
   implementation path. Include these two amended active prompts in that same
   local commit.
2. Do not update `PROGRESS.md`, `docs/development/roadmap.md`, or
   `DECISIONS.md`. Do not move either prompt into `prompts/archive/`. Those
   tracker/archive actions remain deferred until the AD-1133 consolidated gate.
3. Create one local commit with the exact message
   `AD-1128: add unified CrewSession ingress (closes #1047)`.
4. Do not push, close or mutate #1047, create a PR, or perform any other GitHub
   action. The `closes` trailer takes effect only when a later authorized push
   reaches the default branch.
5. Report the local commit id, both amended prompt hash/size bindings, the two
   authorized UI hashes, backend evidence as 534/535 plus the corrected exact
   node, targeted UI 21/21 and prior neighborhood 23/23 separately, `N=65`, and
   the explicit AD-1133 broad-validation deferral.

#### 9.6.5 Three-Pass Prompt Review

**Pass 1 - Contract: APPROVED.** The final amendment corrects the falsified UI
adjudication, freezes the exact root-cause repair, and preserves the unified
ingress, reservation, provenance, auth, repair scheduling, and sole-runner
contracts reviewed in the main prompt.

**Pass 2 - Safety: APPROVED.** No validation evidence is overstated: the 535
backend nodes are reported as a 534/535 batch plus one corrected exact-node
pass, and broad backend/UI/build/Playwright validation remains explicitly
deferred. No new implementation mutation is authorized.

**Pass 3 - Scope/Closeout: APPROVED.** Closeout is one local unpushed commit of
the frozen reviewed diff plus these two prompt amendments. Trackers, archive,
AD-1129+, validation reruns, push, and GitHub mutation remain out of scope.

Verify all changes comply with the Engineering Principles in
`.github/copilot-instructions.md`.

## 10. Final One-Node Adjudication Amendment

**Status:** CONTENT READY; Builder handoff requires only mechanical SHA-256 and
byte-size binding for both active prompts.

This section supersedes Section 9's 535-test rerun and failed-gate stop. The
latest unchanged batch collected 535 tests under `-n 16 --dist=worksteal`: 534
passed, one failed in 26.42 seconds. Preserve the full live tree and ignore
AD-1129 prompts.

### 10.1 Input And Frozen Binding

Architect input hashes before this amendment were:

```text
prompts/ad-1128-crew-session-ingress-dedup.md
  SHA-256 f6aa3d2401e41a1ad24d12858d285668450188087b9b845680ec422a4b84a04a

prompts/ad-1128-crew-session-ingress-dedup-execution.md
  SHA-256 e09f72dbb572d51e4170787817acd780606f32cf9baff8aa4639a9a40697e9c9
```

Before any test edit, mechanically compute and bind each amended prompt's raw
SHA-256 and byte length. The Architect session did not run commands and had no
file hash/stat tool; absence of those two post-edit bindings is the only
remaining handoff condition. Do not normalize, rewrite, or otherwise change a
prompt while hashing it.

Every production, UI, config/YAML, schema, dependency, tracker, archive,
commercial, and other test byte is frozen. After prompt handoff, the sole
authorized implementation-tree mutation is:

```text
tests/test_ad1126_verified_finalization.py
  test_failure_classification_noop_reassignment_and_startup_matrix only
```

No helper outside that function, test definition/name/parameter, or other line
is authorized to change.

### 10.2 Exact Test Edit

Apply the main prompt's `Final AD-1128 Adjudication` exactly:

1. Retain the `other-facilitator` generic update and exact
   `crew_session_write_reserved` rejection. Generic CrewSession writes remain
   reserved even when a caller proposes the current value; do not add a bypass
   or reassignment API.
2. In the same subcase, prove the public service no-op with an
   `executing -> executing` call carrying the authoritative revision and no
   progress fields. Assert exact contract equality, unchanged revision,
   assignment, status, metadata, `updated_at`, and event count.
3. Run the existing finalizer/results and assert `claimed=True`,
   `completed=False`, `state="failed"`, `reason="verification_defect"`.
4. Keep the real `_StatusTransitionOnClaim` race. Replace only the obsolete
   outer revision-exception expectation with the finalizer result
   `claimed=False`, `completed=False`, `state="blocked_needs_captain"`,
   `reason="claim_lost"`. Retain exact winning row, revision-bearing contract,
   blocked status, and facilitator assertions.

Do not change production. Direct stale CAS remains covered by the immutable
AD-1124 stale-revision test; the finalizer intentionally converts its own lost
claim into an observation after authoritative reread.

### 10.3 One Exact Backend Node

Run only:

```powershell
Set-Location D:\ProbOS
$gateId = [guid]::NewGuid().ToString('N')
$gateDir = Join-Path $env:TEMP ('probos_ad1128_final_exact_' + $gateId)
if (Test-Path -LiteralPath $gateDir) { throw 'Gate directory collision' }
New-Item -ItemType Directory -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
  & D:\ProbOS\.venv\Scripts\python.exe -m pytest `
    tests/test_ad1126_verified_finalization.py::test_failure_classification_noop_reassignment_and_startup_matrix `
    -p no:cacheprovider -n 0 --timeout=90 -q --tb=short
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Green requires one passed, zero failed, and no new warning from the changed
test. Do not run the 535-test batch, another Python node, a serial/parallel
confidence rerun, full tests, build, compileall, lint, coverage, Playwright,
Vite, or dev server.

### 10.4 Conditional UI And Static Audits

No UI byte changed. If
`ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx` has not yet
run in the current repair pass solely because the backend failure stopped the
batch, run that file once with Vitest's default pool. If a result already exists
for the unchanged current UI bytes, reuse it and do not rerun any UI test.

After the exact backend node and any still-pending UI file, perform read-only
static audits only:

1. Both active prompt hashes/sizes equal the mechanical handoff binding.
2. Only the named existing test-function body changed after prompt handoff;
   production and UI hashes remain frozen.
3. Test name, parameters, skip/xfail state, and collection cardinality are
   unchanged.
4. Generic different-facilitator reassignment still raises
   `crew_session_write_reserved`; no token, bypass, source-string authority,
   private lock/port access, or new assignment API exists.
5. The no-op assertion proves exact contract/revision/row/time/event
   preservation before finalization.
6. The finalizer reaches the original `verification_defect` classification
   after the no-op.
7. The true status-transition race advances the winning contract and returns
   `claim_lost`; its complete authoritative row is preserved.
8. The immutable AD-1124 direct stale-revision oracle remains present.
9. No AD-1129 file was inspected into scope or changed.
10. No tracker/archive/Git/GitHub/closeout action occurred.

Hand back the two prompt SHA-256/size bindings, exact-node result, conditional
UI result or reused evidence, and all ten static audit outcomes. Report the
534/535 batch separately; never combine it with the exact-node count.

### 10.5 Hard Stops

- Any production/UI/other-test mutation or any helper edit outside the named
  test function.
- Any accepted generic CrewSession update, including a same-value exception to
  `crew_session_write_reserved`.
- Any revision increment, timestamp/metadata/status/assignment change, or event
  from the service-owned no-op.
- Any expectation that `CrewSessionFinalizer.finalize()` propagates the stale
  claim's inner revision exception after authoritative reread.
- Any test/cardinality/parameter/skip/xfail change, broader gate, rerun,
  AD-1129 access, closeout, Git, or GitHub action.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 11. Final UI Gate Adjudication Amendment

**Status:** CONTENT READY; Builder handoff requires only mechanical SHA-256 and
byte-size binding for both active prompts.

This section supersedes Section 10 and every earlier workflow where they
conflict. Preserve the complete live tree and ignore AD-1129 prompts. Retain
the green 534/535 backend scoped batch plus its corrected exact node; no
backend test or command is authorized.

### 11.1 Decision And Frozen Component

The remaining targeted UI result is 21 collected, 20 passed, one failed, with
two React `act(...)` warnings. The failed existing test leaves Confirm focused
after a synthetic forward Tab. The main prompt's `Final AD-1128 UI Gate
Adjudication` is binding: the live `WorkspaceFilesRail.tsx` focus trap is
correct and frozen. Do not edit it and do not replace it with native
`<dialog>` semantics.

The failure is adjudicated as a test-simulation/timing defect. The test does
not settle the component's two asynchronous mount fetch updates or observe
Confirm becoming enabled before direct focus plus synthetic `keyDown`. Correct
the test with awaited `userEvent`; do not duplicate or alter the production
handler. Persistent failure or an act warning after the exact correction is a
hard stop requiring a new Architect pass.

Architect input hashes before this amendment are:

```text
prompts/ad-1128-crew-session-ingress-dedup.md
  SHA-256 30230a1a65eb20e8e0b627baacc0ffd65f6905c23c77d4132efae8d5be76fa17

prompts/ad-1128-crew-session-ingress-dedup-execution.md
  SHA-256 f3a82812b24f504a24a21db2339add4d2e8a8914860f6d3318d120b6ba1514e0
```

Before any test edit, mechanically compute and bind the amended raw SHA-256
and byte length of both active prompts. The absence of those post-edit values
is the only handoff condition. Do not normalize or modify a prompt while
hashing it.

### 11.2 Exact Mutation

The sole mutable implementation-tree path is:

```text
ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
```

Only these changes are authorized:

1. Import the already installed default `userEvent` from
   `@testing-library/user-event`.
2. Replace only the body of
   `wraps Tab forward and Shift+Tab backward across enabled dialog controls`.
3. Replace only the body of
   `pending Escape is inert and keeps focus on the dialog container`.

No helper or other test body may change. Keep every test name, parameter,
mock, setup/teardown, skip/xfail state, and the exact 21-test collection.

Implement the enabled-wrap test exactly as follows:

- Create `userEvent.setup()`, render expanded, and await both
  `input-row-in1` and `artifact-row-art1` before opening the dialog.
- Open with `user.click` and await Goal focus.
- Fill Goal and Deliverable with `user.type`; fill the existing two criteria
  lines with `user.type` and `{Enter}`. Do not call the synchronous fill helper.
- Await Confirm enabled.
- Click Goal, then use awaited `user.tab()` calls and assert Criteria,
  Deliverable, Retry, Cancel, and Confirm in that exact order.
- From Confirm, awaited forward Tab must focus Goal. From Goal, awaited
  `user.tab({ shift: true })` must focus Confirm.

Implement the pending test exactly as follows:

- Use `userEvent.setup()`, await the same two stable rows, open and fill using
  awaited user interactions, await Confirm enabled, then click it once.
- Preserve the deferred request. Await one fetch call and dialog-container
  focus after all controls become disabled.
- Send awaited Escape and assert the same dialog remains mounted and focused.
- Send awaited forward Tab and awaited Shift+Tab; after each, assert focus is
  still on the same dialog container.
- Resolve inside async `act` and await dialog removal before returning.

The existing initial-focus, non-pending Escape/opener, and Cancel/success
opener tests remain unchanged.

### 11.3 One Targeted Gate

Run exactly once with Vitest's default pool:

```powershell
Set-Location D:\ProbOS\ui
npx vitest run src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
```

Green is exactly 21 passed, zero failed, and zero React `act(...)` warnings.
If it is not green, stop and return the exact output. Do not patch, rerun,
widen, run any backend command, run another UI file, build, typecheck, lint,
use Playwright/Vite/dev server, or perform a confidence run.

### 11.4 Read-Only Audits And Handback

After green, audit only:

1. Both prompt hashes/sizes equal the mechanical handoff binding.
2. Only the authorized import and two existing test bodies changed after
   handoff.
3. `WorkspaceFilesRail.tsx` and every production/backend-test byte remain
   frozen.
4. Test collection remains 21 with unchanged names, parameters, and
   skip/xfail state.
5. Enabled navigation proves all real stops plus both boundary directions.
6. Pending Escape, Tab, and Shift+Tab all retain the same dialog focus.
7. Initial mount and deferred submit updates finish within awaited test scope;
   no React act warning remains.
8. Retained backend evidence is reported separately and was not rerun.
9. AD-1129 was not inspected into scope or changed.
10. No tracker/archive/Git/GitHub/closeout action occurred.

Hand back both mechanical prompt SHA-256/size bindings and the targeted Vitest
count/duration. Stop without any other action.

### 11.5 Three-Pass Review

**Pass 1 - Contract: APPROVED TEST-HARNESS CORRECTION.** The frozen component
already implements initial focus, enabled boundary wrapping, pending fallback,
guarded Escape, and connected-opener restoration. Awaited user interaction
tests the DOM contract rather than a jsdom non-navigation artifact.

**Pass 2 - Safety: APPROVED.** Both enabled boundary directions and both
pending Tab directions are asserted. Awaiting mount rows, enabled state, and
submit completion removes uncontrolled React scheduling without weakening
focus or request assertions.

**Pass 3 - Scope/Gate: CONTENT READY; MECHANICAL HASH/SIZE BINDING REQUIRED.**
One existing UI test file and one targeted Vitest run are the full remaining
scope. Production, backend, test cardinality, and closeout state are frozen.

### 11.6 Hard Stops

- Any component, production, backend-test, helper, other UI test, config,
  tracker, archive, commercial, or AD-1129 mutation.
- Any test rename/parameter/cardinality/skip/xfail change.
- Removing Shift+Tab coverage, omitting the pending no-control fallback, or
  weakening opener/Escape assertions elsewhere.
- Any remaining failure or React act warning followed by a patch or rerun.
- Any backend command, broader UI selection, second run, build, typecheck,
  lint, Playwright, Vite/dev-server, Git, or GitHub action.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 12. Final Review And Local Closeout Authority

**Status: APPROVED FOR LOCAL UNPUSHED COMMIT.** This physically final section
supersedes Sections 0 through 11 wherever they conflict. The complete corrected
UI root cause, exact component/test hashes, accepted backend/UI evidence,
mechanical prompt-binding requirement, local-only commit instructions, and
three-pass prompt review are recorded in Section 9.6 and the main prompt's
`Final AD-1128 Prompt Amendment And Code Review`.

The complete implementation/test/UI tree is frozen. Do not run another test,
validation, build, or implementation command; edit another implementation
path; update trackers; archive prompts; inspect or mutate AD-1129+; push; or
mutate GitHub. The only permitted commands are read-only hash/stat measurement
for the two amended prompts and the one local commit itself. Mechanically bind
the two amended prompt SHA-256 values and byte sizes, then create only the local
unpushed commit with exact message
`AD-1128: add unified CrewSession ingress (closes #1047)`. Broad backend/UI/
build/Playwright validation and tracker/archive completion remain deferred to
AD-1133.

Verify all changes comply with the Engineering Principles in
`.github/copilot-instructions.md`.
