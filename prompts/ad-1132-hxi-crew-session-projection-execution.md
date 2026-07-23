# AD-1132 Builder Execution: HXI CrewSession Projection

**Status:** READY after three final prompt-only reviews
**Binding specification:** `prompts/ad-1132-hxi-crew-session-projection.md`
**Binding main SHA-256:** `4993e58478d64af9219f5bc0af242ccd7d0f9ba63b9a519b1d87c3b27e5e4f1b`
**Required build base:** `57e94656b5834ff59bc02e93140137c94f5aa959`
**Expected origin/main:** `e33955a8f7aa6810e8f2d2e2db3a329fadb8e4da`
**Planning ceilings:** local AD-1131 / BF-673
**Scope:** AD-1132 / #1051 only

Main owns behavior/privacy/allowlist/tests/exclusions; this owns freeze,
coding-first gates, three reviews, unpushed commit/deferrals. Apply all six
repairs together; no production/test command until all code/tests exist.

## 1. Handoff and Mechanical Freeze

Before edits require the exact `HEAD`/subject, `origin/main`, ceilings/
reservation, binding, external execution identity, lengths/pair ceiling, and
live anchors below. Preserve unpushed AD-1129..1131 without pull/rebase/reset/
amend/push; permit dirty only the main allowlist/prompts plus the two exact
protected `??` files. Any mismatch hard-stops.

Read-only preflight:

```powershell
$expectedHead = '57e94656b5834ff59bc02e93140137c94f5aa959'
$expectedOrigin = 'e33955a8f7aa6810e8f2d2e2db3a329fadb8e4da'
if ((git rev-parse HEAD) -ne $expectedHead) { throw 'AD-1132 HEAD mismatch' }
if ((git rev-parse origin/main) -ne $expectedOrigin) { throw 'AD-1132 origin mismatch' }
$prompts = @('prompts/ad-1132-hxi-crew-session-projection.md','prompts/ad-1132-hxi-crew-session-projection-execution.md')
$allowedDirtyPaths = @(
  'src/probos/crew_session_projection.py','src/probos/routers/crew_tasks.py',
  'src/probos/routers/threads.py','tests/test_ad1128_crew_session_ingress_dedup.py',
  'tests/test_ad1132_crew_session_api.py','ui/src/components/artifacts/artifactApi.ts',
  'ui/src/components/chats/ChatsPanel.tsx','ui/src/components/chats/__tests__/ChatsPanel.test.tsx',
  'ui/src/components/crew/CrewCollaborationPanel.tsx','ui/src/components/crew/CrewCollaborationPanel.test.tsx',
  'ui/src/components/profile/ProfileChatTab.tsx','ui/src/components/profile/__tests__/ProfileChatTab.crewSession.test.tsx',
  'ui/src/components/sidebar/threadApi.ts','ui/src/components/sidebar/__tests__/threadApi.crewSession.test.ts',
  'ui/src/components/workspace/WorkspaceFilesRail.tsx','ui/src/components/workspace/todosApi.ts',
  'ui/src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx','ui/src/store/types.ts',
  'ui/src/store/useStore.ts','ui/src/store/__tests__/crewSessionProjection.test.ts'
)
$protected = [ordered]@{
  'prompts/ad-1133-live-crew-session-thread-refresh.md' = '0199b70bdad6a578239cc99d6003d1703a1c1b397b83b8826850509cb8768ff4'
  'prompts/ad-1133-live-crew-session-thread-refresh-execution.md' = 'd556b22de5d66759d06ae53a1e392f79a30096b6b3c938f49ef7bee71ad2191d'
}
$dirty = @(git status --porcelain=v1)
$dirtyPaths = @($dirty | ForEach-Object { $_.Substring(3) })
if (@($dirtyPaths | Where-Object { $_ -notin (@($allowedDirtyPaths) + $prompts + @($protected.Keys)) }).Count) {
  throw 'AD-1132 dirty-path mismatch'
}
foreach ($prompt in $prompts) {
  if ($prompt -notin $dirtyPaths) { throw 'AD-1132 prompt missing from dirty set' }
}
foreach ($path in $protected.Keys) {
  if ("?? $path" -notin $dirty -or (Get-FileHash -LiteralPath $path).Hash.ToLowerInvariant() -ne $protected[$path]) {
    throw 'AD-1132 protected identity mismatch'
  }
}
$rows = foreach ($path in $prompts) {
  $item = Get-Item -LiteralPath $path
  [pscustomobject]@{Path=$path;Bytes=$item.Length;SHA256=(Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()}
}
$rows | Format-Table -AutoSize
$combined = ($rows | Measure-Object -Property Bytes -Sum).Sum
if ($rows[0].SHA256 -ne '4993e58478d64af9219f5bc0af242ccd7d0f9ba63b9a519b1d87c3b27e5e4f1b') {
  throw 'AD-1132 main prompt hash mismatch'
}
if ($combined -ge 50000) { throw 'AD-1132 prompt pair exceeds 50000 bytes' }
Write-Output ('COMBINED_BYTES=' + $combined)
```

Record identities/bytes; drift hard-stops. Run no baseline/red/UI/build/
Playwright/full/GitHub command.

## 2. Coding First

Complete every authorized production and test edit before the first pytest,
Vitest, build, or browser command. Editor diagnostics and read-only static
inspection are allowed while coding.

Build order:

1. Pure typed bounded secret-minimized projection and stable error.
2. Service-authoritative session detail; byte-for-behavior generic AD-862 path.
3. Isolated summaries and authoritative projection on existing Start Work.
4. Exact UI types plus keyed clone-on-write one-shot hydration; no WS reducer.
5. Strict detail/artifact GET and existing one-mutation Start Work wrappers.
6. Existing panel: reactive ownership, six states, a11y/motion/layout/focus.
7. Existing chat column/rail/dialog/viewer: thread tokens, stale barriers,
  Start Work and cross-room artifact guards; preserve row flex/min-width.
8. Both session chat rows share context; generic 1:1/group markup stays exact.
9. Finish every named backend/Vitest case, then and only then validate.

If a live signature makes the exact design impossible, stop for Architect
review. Do not add another endpoint, store, event, timer, panel, mutation, or
allowlist path to work around it.

## 3. Pre-Test Static Audit

Before any test command, verify and fix only AD-1132 defects:

- dirty paths are allowlist/prompts plus exact protected `??` AD-1133 files;
  their frozen hashes are unchanged and they are unedited;
- non-session detail still returns exact `parent/children/count`; generic
  summary entries still have exactly four keys;
- CrewSession detail contains only `session`, and detail/summary keys exactly
  match the main prompt;
- every detail source is a service-validated contract, validated synthesis,
  and at most 1,000 direct real WorkItems; no raw metadata crosses the module;
- done refs cross-check; non-done has no synthesis/result/verification; every
  invalid detail is stable 409 and every invalid summary member falls back;
- recursive sentinel scan finds no secret/raw/provenance bytes or AD-1131
  delivery/outbox/notification/metrics fields;
- both store maps/actions clone rather than mutate; no WS/event handler,
  interval, timeout, poll, persistence, or background task was added;
- detail/summary wrappers and both hydration actions reject mismatched embedded
  ownership without re-keying; the mounted panel uses a reactive keyed selector;
- every retained parent binding is thread-tagged; Profile/panel/rail room refs
  update during render, and every AD-1132 post-await mutation checks room plus
  generation, including responses resolved before effect cleanup;
- cancel returns focus to the connected blocked trigger; successful retry
  removing it focuses the current stable session band;
- both session-backed chat-row branches render the same compact context while
  generic non-session 1:1 output remains exact;
- observed 420/320 hosts stack metadata without overlap, including an expanded
  rail; tests drive layout behavior rather than inspect a media-query string;
- backend tests independently hit provenance mismatch, evidence-membership
  failure, and post-admission Start Work projection-conflict 409;
- `ProfileChatTab` keeps the existing row flex and chat-column `minWidth:0`;
  exactly one rail, Start Work dialog, and ArtifactViewer exist;
- passive mount paths contain only GET; retry opening performs no request;
  Start Work still has exactly one POST call site;
- existing Artifact/Todo polling is unchanged and CrewSession has no polling;
- all public Python/TypeScript interfaces are fully typed, all SVG icons are
  inline stroke-based, and reduced-motion/focus/aria behavior is explicit;
- no AD-1131 delivery file, config/YAML, EventType, schema, tracker, archive,
  commercial file, dependency, or AD-1133 implementation changed.

Final-review discriminators, all mandatory before the one validation cycle:

1. Provenance equality test pre-asserts session ref A, synthesis ref B, and
  evidence `[A,B]`; all else matches, so its route 409 isolates equality.
2. `threadApi` validates exact nested AD-862 parent/child/verdict/round keys and
  types using a complete real fixture; partial/additive nested objects fail.
3. Generic 1:1/group rows have no attention attribute/session wrapper/style
  drift; session-only wrapping and `minWidth` stay on session branches.
4. A nonzero-step session row has no U+2713; the generic badge is unchanged.
5. Ordinary Start Work 409 keeps focus in its open dialog; successful retry
  closes and restores its connected opener. Blocked cancel and session-band
  success remain separate tests.
6. Session `verified_at=0` renders through an explicit non-null check and
  session formatter; generic `fmtAgo` is unchanged.

## 4. Changed-Surface Validation

All coding is complete before this section. The backend changed-surface gate
uses all 16 physical cores with work stealing, isolated data, and local/offline
embeddings. Do not use the stale two-worker note from older preflight material.

### 4.1 Backend batch

Run one batch containing the new API/projection tests, unchanged AD-862
regressions, and the AD-1128 route tests with only their allowlisted additive
projection fixture/assertion update:

```powershell
$gateId = [guid]::NewGuid().ToString('N')
$gateDir = Join-Path $env:TEMP ('probos_ad1132_batch_' + $gateId)
New-Item -ItemType Directory -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
try {
  & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest `
    tests/test_ad1132_crew_session_api.py `
    tests/test_ad862_crew_tasks_api.py `
    tests/test_ad1128_crew_session_ingress_dedup.py `
    -p no:cacheprovider -n 16 --dist=worksteal --timeout=90 -q --tb=short
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Record passed/skipped/warning count, duration, exit code, and warning
provenance. Changed paths must emit zero warnings.

A tiny exact test node may run serial with `-n 0` only to discriminate a
concrete xdist/order artifact or pure-node failure after the batch. It does not
replace the final passing `-n 16 --dist=worksteal` batch. Do not run a full
serial file or broad backend suite.

### 4.2 Targeted UI batch

Run only the targeted files from the main prompt, using Vitest's normal thread
pool with no pool/worker override:

```powershell
Set-Location 'D:\ProbOS\ui'
npx vitest run `
  src/store/__tests__/crewSessionProjection.test.ts `
  src/components/sidebar/__tests__/threadApi.crewSession.test.ts `
  src/components/crew/CrewCollaborationPanel.test.tsx `
  src/components/chats/__tests__/ChatsPanel.test.tsx `
  src/components/profile/__tests__/ProfileChatTab.crewSession.test.tsx `
  src/components/workspace/__tests__/WorkspaceFilesRail.test.tsx
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Record per-file test counts, total pass/skip, warnings, duration, and build exit
code. Run no Playwright and add no e2e file; DOM/component evidence is final.

One minimal scoped repair is allowed after a real failure. Rerun the complete
affected backend or UI batch (and production build for any TypeScript repair)
before review. Do not widen scope to fix pre-existing or environmental failures.

## 5. Evidence, Reviews, and Closeout

Return base/origin, dirty-path purposes/identities, gate counts/durations/
warnings/exits, and focused evidence for exact generic keys, six states,
privacy, clone/no-live-update, ownership/race/focus/rows/layout, passive zero-
write, one POST, artifact GET/viewer, and exclusions. DOM evidence suffices.

After all scoped gates are green, return to the Architect for a final three-
pass findings-first implementation re-review. Each pass reports Required,
Recommended, Nits, then Verified; a Required finding permits only a minimal
allowlisted repair and rerun of the complete affected batch/build:

1. **Backend:** authority/bounds/keys, A-vs-B equality isolation, other terminal
  conflicts, 404/503/409, generic compatibility, mixed fallback, one mutation,
  privacy, and no new surface.
2. **HXI:** strict full legacy parser; keyed reactive ownership/stale barriers;
  all three distinct focus contracts; generic 1:1/group parity; session U+2713
  exclusion and epoch zero; 420/320 layout, six states, a11y/motion, one
  dialog/viewer, artifact guard, and passive GET-only.
3. **Scope:** base/origin, frozen identities, allowlist, diagnostics/whitespace,
  zero changed-path warnings, green build, exclusions, and AD-1133 deferrals.

After approval run only diagnostics/scope/whitespace/secrets/hashes, no tests/
build/Playwright. Before/after staging require protected files stay exact `??`
at frozen hashes and absent from `git diff --cached --name-only`; never edit/
commit them. Exclude trackers/archive/AD-1131/others; stage only approved
AD-1132 files, locally unpushed:

```text
AD-1132: add HXI CrewSession projection (closes #1051)
```

Hard-stop on any freeze/scope/gate/build/warning or named functional failure;
passive write/second mutation; new endpoint/config/schema/EventType/live
transport/poller/surface; or tracker/archive/GitHub/AD-1133 work. AD-1133
retains broad gates/Playwright/trackers/archive/reconciliation/push.

Verify all changes comply with the Engineering Principles in
`.github/copilot-instructions.md`.

## Final Prompt-Only Review Record (2026-07-22)

| Pass | Verdict | Verified |
|---|---|---|
| 1 | APPROVED; none | A/B isolation; strict parser; authority/privacy |
| 2 | APPROVED; none | generic parity; no session U+2713; epoch zero; three focus contracts; prior HXI |
| 3 | APPROVED; none | coding-first gates; no Playwright; allowlist/commands/deferrals; binding/audits; pair <50 KB |