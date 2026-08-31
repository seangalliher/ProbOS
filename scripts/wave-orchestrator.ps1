# wave-orchestrator.ps1
#
# Semi-autonomous wave dispatch coordinator. Reads prompts/wave-plan.yaml,
# tracks state in prompts/wave-orchestrator-state.json, and steps through
# the architect/builder pipeline with three mandatory architect gates:
#
#   GATE 1 (after review-2): architect approves dispatch to Builder
#   GATE 2 (after builder build): architect approves diff before push
#   GATE 3 (after push): architect approves GH issue closure
#
# Between gates, the orchestrator does the mechanical work:
#   - Dispatch architect subagent (drafting)
#   - Run scripts/phantom-api-precheck.ps1
#   - Dispatch architect subagent (review pass-1)
#   - Dispatch architect subagent (revision pass)
#   - Dispatch architect subagent (review pass-2)
#   - Dispatch builder subagent (continuous build)
#   - Dispatch architect subagent (completed-build review)
#   - Run one consolidated verification gate
#   - Close GH issues + archive prompts + commit
#
# This script does NOT itself invoke subagents — it produces dispatch
# instructions on stdout. The user (or a parent agent) reads the dispatch
# and triggers the subagent. State is updated when the user runs
# `wave-orchestrator.ps1 advance` to move to the next stage.
#
# Why this shape: Subagent invocation is currently a chat-side operation
# (runSubagent tool). PowerShell can't trigger that. So this script is the
# orchestrator's bookkeeping layer; the chat loop is the executor.
#
# Usage:
#   ./scripts/wave-orchestrator.ps1 status         # show current state
#   ./scripts/wave-orchestrator.ps1 next           # show next dispatch instruction
#   ./scripts/wave-orchestrator.ps1 advance        # mark current stage complete
#   ./scripts/wave-orchestrator.ps1 reset <wave>   # rewind a wave to pending
#   ./scripts/wave-orchestrator.ps1 verify         # run mechanical checks for current stage

[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet('status', 'next', 'advance', 'reset', 'verify', 'help')]
    [string]$Command = 'status',

    [Parameter(Position=1)]
    [string]$Argument
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$planPath = Join-Path $repoRoot 'prompts/wave-plan.yaml'
$statePath = Join-Path $repoRoot 'prompts/wave-orchestrator-state.json'
. (Join-Path $PSScriptRoot 'resolve-python.ps1')

# ---------- State management ----------

function Get-State {
    if (-not (Test-Path $statePath)) {
        $default = @{
            current_wave = $null
            current_stage = 'idle'
            history = @()
        }
        $default | ConvertTo-Json -Depth 10 | Set-Content $statePath -Encoding UTF8
    }
    return (Get-Content $statePath -Raw | ConvertFrom-Json -AsHashtable)
}

function Set-State {
    param([hashtable]$state)
    $state | ConvertTo-Json -Depth 10 | Set-Content $statePath -Encoding UTF8
}

  function Get-Sha256Text {
    param([string]$Value)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
      return [BitConverter]::ToString(
        $hasher.ComputeHash($bytes)
      ).Replace('-', '').ToLowerInvariant()
    } finally {
      $hasher.Dispose()
    }
  }

  function Get-FileSha256 {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
      throw "Gate artifact is missing: $Path"
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
  }

function Get-GitTreeIdentity {
  $head = ((& git -C $repoRoot rev-parse HEAD) | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $head) {
    throw "Unable to resolve Git HEAD for verification receipt"
  }
  $headTree = ((& git -C $repoRoot rev-parse 'HEAD^{tree}') | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $headTree) {
    throw "Unable to resolve the committed Git tree for verification receipt"
  }
  $indexTree = ((& git -C $repoRoot write-tree) | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $indexTree) {
    throw "Unable to resolve Git index tree for verification receipt"
  }
  $statusLines = @(& git -C $repoRoot status --porcelain=v1 --untracked-files=all)
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve Git status for verification receipt"
  }
  $statusBytes = [Text.Encoding]::UTF8.GetBytes(
    [string]::Join("`n", [string[]]$statusLines)
  )
  $hasher = [Security.Cryptography.SHA256]::Create()
  try {
    $statusHash = [BitConverter]::ToString(
      $hasher.ComputeHash($statusBytes)
    ).Replace('-', '').ToLowerInvariant()
  } finally {
    $hasher.Dispose()
  }
  return @{
    head = $head
    head_tree = $headTree
    index_tree = $indexTree
    status_sha256 = $statusHash
  }
}

function Test-GitTreeIdentity {
  param([hashtable]$Expected, [hashtable]$Actual)
  return (
    $Expected.head -eq $Actual.head -and
    $Expected.head_tree -eq $Actual.head_tree -and
    $Expected.index_tree -eq $Actual.index_tree -and
    $Expected.status_sha256 -eq $Actual.status_sha256
  )
}

  function Test-CommittedTreeIdentity {
    param([hashtable]$Identity)
    if ($Identity.head_tree -ne $Identity.index_tree) {
      [Console]::Error.WriteLine(
        "Canonical full gate and push require the Git index to equal the committed HEAD tree."
      )
      return $false
    }
    return $true
  }

  function ConvertTo-GateLabel {
    param([string]$Value)
    $label = (($Value.Trim().ToLowerInvariant() -replace '[^a-z0-9]+', '-').Trim('-'))
    if (-not $label) { return 'gate' }
    if ($label.Length -gt 48) { return $label.Substring(0, 48) }
    return $label
  }

  function Resolve-GateArtifactPath {
    param([string]$RelativePath)
    if (-not $RelativePath -or [IO.Path]::IsPathRooted($RelativePath)) {
      throw "Gate receipt contains an invalid artifact path: $RelativePath"
    }
    $artifactRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'logs/gates'))
    $fullPath = [IO.Path]::GetFullPath((Join-Path $repoRoot $RelativePath))
    $fromRoot = [IO.Path]::GetRelativePath($artifactRoot, $fullPath)
    if ($fromRoot -eq '..' -or $fromRoot.StartsWith("..$([IO.Path]::DirectorySeparatorChar)")) {
      throw "Gate receipt artifact escapes logs/gates: $RelativePath"
    }
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
      throw "Gate receipt artifact is missing: $RelativePath"
    }
    return $fullPath
  }

  function Read-GateSuccessReceipt {
    param(
      [string]$Path,
      [string]$ExpectedLabel,
      [hashtable]$ExpectedTree
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
      throw "Canonical gate did not create its requested success receipt"
    }
    try {
      $receipt = Get-Content -LiteralPath $Path -Raw |
        ConvertFrom-Json -AsHashtable -ErrorAction Stop
    } catch {
      throw "Canonical gate success receipt is invalid JSON: $($_.Exception.Message)"
    }
    if ($receipt.schema_version -ne 1 -or $receipt.label -ne $ExpectedLabel) {
      throw "Canonical gate success receipt schema or label is invalid"
    }
    $status = $receipt.status
    if (
      $status.wrapper_exit_code -ne 0 -or
      $status.preflight_exit_code -ne 0 -or
      $status.pytest_exit_code -ne 0 -or
      $status.preflight_only -ne $false -or
      $status.tree_changed -ne $false
    ) {
      throw "Canonical gate success receipt does not describe a clean full-gate success"
    }
    foreach ($field in @('head', 'head_tree', 'index_tree', 'status_sha256')) {
      if ($receipt.tree[$field] -ne $ExpectedTree[$field]) {
        throw "Canonical gate receipt tree field '$field' does not match the admitted tree"
      }
    }
    $manifestPath = Resolve-GateArtifactPath -RelativePath $receipt.manifest.path
    $junitPath = Resolve-GateArtifactPath -RelativePath $receipt.junit.path
    $collectionPath = Resolve-GateArtifactPath -RelativePath $receipt.collection.path
    if ((Get-FileSha256 -Path $manifestPath) -ne $receipt.manifest.sha256) {
      throw "Canonical gate manifest hash does not match its success receipt"
    }
    if ((Get-FileSha256 -Path $junitPath) -ne $receipt.junit.sha256) {
      throw "Canonical gate JUnit hash does not match its success receipt"
    }
    if ((Get-FileSha256 -Path $collectionPath) -ne $receipt.collection.sha256) {
      throw "Canonical gate collection hash does not match its success receipt"
    }
    try {
      $manifest = Get-Content -LiteralPath $manifestPath -Raw |
        ConvertFrom-Json -AsHashtable -ErrorAction Stop
    } catch {
      throw "Canonical gate manifest is invalid JSON: $($_.Exception.Message)"
    }
    if (
      $manifest.wrapper_exit_code -ne 0 -or
      $manifest.preflight_exit_code -ne 0 -or
      $manifest.pytest_exit_code -ne 0 -or
      $manifest.preflight_only -ne $false -or
      $manifest.tree_changed -ne $false
    ) {
      throw "Canonical gate manifest does not describe a clean full-gate success"
    }
    $totals = $receipt.junit.totals
    if (
      $totals.tests -le 0 -or
      $totals.failures -ne 0 -or
      $totals.errors -ne 0 -or
      $manifest.junit_totals.tests -ne $totals.tests -or
      $manifest.junit_totals.failures -ne $totals.failures -or
      $manifest.junit_totals.errors -ne $totals.errors -or
      $manifest.junit_totals.skipped -ne $totals.skipped -or
      $manifest.junit_totals.extra_reports -ne $totals.extra_reports
    ) {
      throw "Canonical gate JUnit totals are absent, red, or inconsistent"
    }
    $collectionTotals = $receipt.collection.totals
    if (
      $collectionTotals.nodes -le 0 -or
      $collectionTotals.workers -le 0 -or
      -not $collectionTotals.sha256 -or
      $manifest.collection_totals.nodes -ne $collectionTotals.nodes -or
      $manifest.collection_totals.workers -ne $collectionTotals.workers -or
      $manifest.collection_totals.sha256 -ne $collectionTotals.sha256 -or
      $manifest.collection_path.Replace('\', '/') -ne $receipt.collection.path
    ) {
      throw "Canonical gate collection totals are absent or inconsistent"
    }
    return $receipt
  }

  function Test-GateReceipt {
    param([hashtable]$State, [hashtable]$Wave)
    if (-not $State.ContainsKey('verify_build_receipt')) {
      [Console]::Error.WriteLine(
        "No successful canonical gate receipt exists for wave '$($Wave.id)'. Run 'verify'."
      )
      return $false
    }
    $receipt = $State.verify_build_receipt
    if ($receipt.wave_id -ne $Wave.id) {
      [Console]::Error.WriteLine(
        "Canonical gate receipt belongs to wave '$($receipt.wave_id)', not '$($Wave.id)'."
      )
      return $false
    }
    try {
      $currentIdentity = Get-GitTreeIdentity
      if (
        -not (Test-CommittedTreeIdentity -Identity $currentIdentity) -or
        -not (Test-GitTreeIdentity -Expected $receipt.tree -Actual $currentIdentity)
      ) {
        [Console]::Error.WriteLine(
          "Canonical gate receipt is stale because the Git tree changed. Return to review_build and rerun 'verify'."
        )
        return $false
      }
      $artifactPath = Resolve-GateArtifactPath -RelativePath $receipt.artifact.path
      if ((Get-FileSha256 -Path $artifactPath) -ne $receipt.artifact.sha256) {
        throw "Canonical gate receipt artifact hash changed after verification"
      }
      $null = Read-GateSuccessReceipt `
        -Path $artifactPath `
        -ExpectedLabel $receipt.label `
        -ExpectedTree $currentIdentity
    } catch {
      [Console]::Error.WriteLine("Canonical gate receipt validation failed: $($_.Exception.Message)")
      return $false
    }
    return $true
  }

  function Get-PushTarget {
    $branch = ((& git -C $repoRoot symbolic-ref --quiet --short HEAD) | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $branch) {
      throw "Push stage requires an attached Git branch"
    }
    $remote = ((& git -C $repoRoot config --get "branch.$branch.remote") | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $remote) {
      throw "Branch '$branch' has no configured push remote"
    }
    $remoteRef = ((& git -C $repoRoot config --get "branch.$branch.merge") | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $remoteRef -or -not $remoteRef.StartsWith('refs/heads/')) {
      throw "Branch '$branch' has no valid configured merge ref"
    }
    $remoteUrl = if ($remote -eq '.') {
      '.'
    } else {
      ((& git -C $repoRoot remote get-url --push $remote) | Out-String).Trim()
    }
    if ($LASTEXITCODE -ne 0 -or -not $remoteUrl) {
      throw "Unable to resolve push URL for remote '$remote'"
    }
    $commit = ((& git -C $repoRoot rev-parse HEAD) | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $commit) {
      throw "Unable to resolve the local commit after push"
    }
    return @{
      branch = $branch
      remote = $remote
      remote_ref = $remoteRef
      remote_url = $remoteUrl
      remote_url_sha256 = Get-Sha256Text -Value $remoteUrl
      commit = $commit
    }
  }

  function Get-RemoteRefCommit {
    param([hashtable]$Target)
    $lines = @(
      & git -C $repoRoot ls-remote --exit-code --refs $Target.remote_url $Target.remote_ref
    )
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) {
      throw "Unable to resolve exactly one remote ref '$($Target.remote_ref)' on '$($Target.remote)'"
    }
    $parts = ([string]$lines[0]).Trim() -split '\s+', 2
    if ($parts.Count -ne 2 -or $parts[1] -ne $Target.remote_ref) {
      throw "Remote '$($Target.remote)' returned an unexpected ref for '$($Target.remote_ref)'"
    }
    return $parts[0]
  }

function Get-Plan {
    if (-not (Test-Path $planPath)) {
        throw "wave-plan.yaml not found at $planPath"
    }
    # Minimal YAML parse — relies on simple structure. For complex YAML use
    # ConvertFrom-Yaml from powershell-yaml module if installed.
    $raw = Get-Content $planPath -Raw
    # Convert YAML to JSON via Python (always available in repo .venv)
    $py = Resolve-ProbOSPython -RepoRoot $repoRoot
    $json = $raw | & $py -c "import sys, yaml, json; print(json.dumps(yaml.safe_load(sys.stdin)))"
    $parseExitCode = $LASTEXITCODE
    if ($parseExitCode -ne 0 -or -not $json) {
      throw "wave-plan.yaml parser failed with exit code $parseExitCode"
    }
    try {
      $plan = $json | ConvertFrom-Json -AsHashtable -ErrorAction Stop
    } catch {
      throw "wave-plan.yaml parser returned invalid JSON: $($_.Exception.Message)"
    }
    if (-not $plan -or -not ($plan.ContainsKey('waves'))) {
      throw "wave-plan.yaml must define a waves collection"
    }
    return $plan
}

# ---------- Stage definitions ----------

# The pipeline stages for a main/combo wave. Meta waves skip Builder stages.
$MAIN_STAGES = @(
    'draft',           # Architect drafts prompts
    'precheck',        # phantom-api-precheck.ps1
    'review_1',        # Architect pass-1 review
    'revision',        # Architect applies findings
    'review_2',        # Architect pass-2 review
    'gate_1',          # ARCHITECT GATE: approve Builder dispatch
    'build',           # Builder executes
    'review_build',    # Architect reviews the completed code before broad tests
    'verify_build',    # Run consolidated Python/UI/E2E gates
    'gate_2',          # ARCHITECT GATE: approve push
    'push',            # git push
    'gate_3',          # ARCHITECT GATE: approve issue closure
    'close',           # gh issue close + archive prompts
    'retrospective'    # Optional retrospective stub. Advancing from this stage marks wave done.
)

$META_STAGES = @(
    'draft',
    'precheck',
    'verify_outputs',  # Confirm expected_outputs files exist
    'gate_1',          # ARCHITECT GATE: approve commit
    'commit_push'      # Verify commit/push landed. Advancing from this stage marks wave done.
)

function Get-StagesForWave {
    param([hashtable]$wave)
    if ($wave.kind -eq 'meta') { return $META_STAGES }
    return $MAIN_STAGES
}

# ---------- Dispatch instruction generators ----------

function Format-DraftDispatch {
    param([hashtable]$wave)
    if ($wave.prompts_already_drafted) {
        return @"
============================================================
WAVE $($wave.id) — STAGE: draft (SKIPPED)
============================================================

Prompts for this wave were already drafted in a prior wave. Wave-level
dispatch reference: $($wave.dispatch_prompt)

Run:  ./scripts/wave-orchestrator.ps1 advance
to proceed to the precheck stage.
"@
    }
    $promptPath = $wave.dispatch_prompt
    if (-not $promptPath) {
        $promptPath = "prompts/WAVE-$($wave.id)-DISPATCH.md (does not exist yet — architect must draft this dispatch first)"
    }
    @"
============================================================
WAVE $($wave.id) — STAGE: draft
============================================================

ACTION: Invoke Architect subagent (runSubagent agentName='Architect').

DISPATCH PROMPT TO USE:
  $promptPath

Read that file and execute the 'Subagent Prompt' block verbatim. Standard
expectations:
  - Verify-first against live codebase
  - Apply all 19 standing conventions
  - Run scripts/phantom-api-precheck.ps1 before declaring done
  - Single commit, push to origin/main

When the subagent reports complete, run:
  ./scripts/wave-orchestrator.ps1 advance
"@
}

function Format-PrecheckDispatch {
    param([hashtable]$wave)
    $patterns = $wave.prompt_paths
    if (-not $patterns) { $patterns = $wave.expected_outputs | Where-Object { $_ -like 'prompts/*' } }
    $patternList = ($patterns | Where-Object { $_ -like '*.md' }) -join ' '
    @"
============================================================
WAVE $($wave.id) — STAGE: precheck
============================================================

ACTION: Run phantom-API pre-check on drafted prompts.

COMMAND:
  ./scripts/phantom-api-precheck.ps1 $patternList

Expected: 0 phantoms (or all flagged candidates documented as false positives
in the dispatch summary).

If phantoms found:
  - True phantom (prompt asserts a non-existent symbol): fix in prompt
  - False positive (prose example, stdlib alias, prompt-introduced symbol):
    note in summary, proceed

When clean (or false-positives documented), run:
  ./scripts/wave-orchestrator.ps1 advance
"@
}

function Format-ReviewDispatch {
    param([hashtable]$wave, [string]$pass)
    $passLabel = if ($pass -eq '1') { 'first-pass' } else { 'second-pass (post-revision)' }
    @"
============================================================
WAVE $($wave.id) — STAGE: review_$pass
============================================================

ACTION: Invoke Architect subagent for $passLabel review.

The subagent reads each drafted prompt + applies prompts/review-criteria.md
3-tier format (Required / Recommended / Nits / Verified). Output is one
review file per prompt at prompts/Reviews/<stem>-review.md, plus a
README-wave-$($wave.id)-pass-$pass.md sweep summary.

Tolerance per convention #15 (relaxed): 1 ⚠️ allowed on highest-risk prompt.

When subagent reports complete, run:
  ./scripts/wave-orchestrator.ps1 advance

If verdict is unacceptable (multiple ⚠️ or any ❌ on non-highest-risk),
run:  ./scripts/wave-orchestrator.ps1 reset $($wave.id)
to rewind and re-dispatch the revision.
"@
}

function Format-RevisionDispatch {
    param([hashtable]$wave)
    @"
============================================================
WAVE $($wave.id) — STAGE: revision
============================================================

ACTION: Invoke Architect subagent for revision pass.

The subagent reads prompts/Reviews/*-review.md from this wave + applies
all Required findings to the corresponding prompts. Recommended findings
are folded in unless they expand scope. Each revised prompt gets a
`## Revision (YYYY-MM-DD)` section appended.

Closing self-check (per Wave 8 retrospective): after applying revisions,
grep each prompt for the OLD names/values that were changed; expect zero
hits (catches Solution Overview drift).

When subagent reports complete, run:
  ./scripts/wave-orchestrator.ps1 advance
"@
}

function Format-Gate1 {
    param([hashtable]$wave)
    @"
============================================================
WAVE $($wave.id) — GATE 1: ARCHITECT APPROVAL TO DISPATCH BUILDER
============================================================

The wave has completed two review passes. Inspect:
  - prompts/Reviews/README-wave-$($wave.id)-pass-2.md (sweep summary)
  - Any ⚠️ verdicts in individual review files

Verdict criteria (relaxed tolerance):
  ✓ APPROVE if: 5✅ + at most 1⚠️ on highest-risk prompt, no ❌
  ✗ REJECT if: any ❌, multiple ⚠️, or ⚠️ on a non-highest-risk prompt

If APPROVE:
  ./scripts/wave-orchestrator.ps1 advance

If REJECT (third revision needed):
  ./scripts/wave-orchestrator.ps1 reset $($wave.id)
  (rewinds to revision stage; expect to do another revision+review cycle)
"@
}

function Format-BuildDispatch {
    param([hashtable]$wave)
    $patterns = ($wave.prompt_paths -join "`n  - ")
    @"
============================================================
WAVE $($wave.id) — STAGE: build
============================================================

ACTION: Invoke Builder subagent (runSubagent agentName='Builder').

DISPATCH (paste to Builder):

  Build Wave $($wave.id) — continuous-build mode.

  Read first:
    - prompts/BUILDER-EXECUTION-PLAN.md
    - .github/copilot-instructions.md
    - DECISIONS.md (Wave 5/5-7/8 retrospective entries — 19 standing conventions)
    - prompts/Reviews/README-wave-$($wave.id)-pass-2.md
    - The wave prompts:
      - $patterns

  Pre-flight:
    git pull
    git status --short                                                # must be clean
    Get-FileHash -Algorithm SHA256 <wave prompt paths>                 # freeze approved prompts

  Per-prompt: read prompt + review (apply non-blocking nits at code-review),
  implement section by section, run focused gate at -n 0, update trackers,
  commit with `AD-NNN: <one-line>` format. Do not push until gate_2.

  Per-commit gate: prompt-specific + adjacent changed-slice tests pass,
  expected new test count matches, pre-commit deletion sanity check.

  UI coding gate: run the exact changed Vitest files while implementing.
  Full Vitest + ``npm run build`` run once in verify_build after Architect
  reviews the complete code stack. Playwright scenarios run there when the
  wave changes a user-facing workflow.

  Begin in dependency order; surface only on hard-stop conditions per
  BUILDER-EXECUTION-PLAN.md.

When Builder reports complete, run:
  ./scripts/wave-orchestrator.ps1 advance
"@
}

function Format-ReviewBuild {
    param([hashtable]$wave)
    @"
============================================================
WAVE $($wave.id) — STAGE: review_build
============================================================

ACTION: Invoke Architect subagent (runSubagent agentName='Architect') for a
completed-build code review BEFORE broad tests.

Review ``origin/main..HEAD`` against the frozen prompts and live code. Lead
with findings and inspect:
  - scope and prompt-hash drift
  - single durable-state, lifecycle, and event-emission ownership
  - dependency direction and public contract placement
  - hostile wire-boundary exact type/value validation
  - retry/restart idempotency for delivery, trust, metrics, and publication
  - snapshot/live/reconnect projection parity
  - clean-checkout portability and unrelated-work preservation

Do not run the full repository gate in this stage. Use a narrow executable
check only when needed to falsify a specific review finding.

If APPROVED (or after Builder repairs all Required findings), run:
  ./scripts/wave-orchestrator.ps1 advance

If REJECTED:
  Re-dispatch Builder with the exact findings, rerun focused affected tests,
  and repeat this review before advancing.
"@
}

function Format-VerifyBuild {
    param([hashtable]$wave)
    @"
============================================================
WAVE $($wave.id) — STAGE: verify_build
============================================================

ACTION: Run one consolidated gate on the reviewed, frozen wave stack.

PYTHON:
  ./scripts/wave-orchestrator.ps1 verify

The wrapper runs generated-reference and phantom-API preflight checks first,
preserves pytest's real exit code, and writes unique log/JUnit/manifest timing
artifacts. Do not replace it with a direct ``pytest tests/`` command.

IF UI CHANGED:
  cd ui
  npx vitest run
  npm run build

IF A USER-FACING WORKFLOW CHANGED:
  cd ui
  npx playwright test <affected scenarios>

Expected: wrapper exit 0, a valid JUnit report, and a receipt bound to the
unchanged Git tree. A serial rerun of a failing node is diagnostic only; it
cannot replace or override a nonzero canonical wrapper result.

Any shared source/test repair invalidates this gate. Return to review_build,
review the repair, then rerun the affected consolidated gate.

When green, run:
  ./scripts/wave-orchestrator.ps1 advance

If genuine failure, re-dispatch Builder with the failing test list, OR
hard-stop and surface to architect.
"@
}

function Format-Gate2 {
    param([hashtable]$wave)
    @"
============================================================
WAVE $($wave.id) — GATE 2: ARCHITECT APPROVAL TO PUSH
============================================================

ACTION: Inspect commits before pushing.

COMMANDS:
  git log --oneline origin/main..HEAD
  git diff origin/main..HEAD --stat
  git log -p origin/main..HEAD | Select-String -Pattern 'TODO|XXX|FIXME|breakpoint'

COMMIT-COUNT AUDIT (AD-738a — audit trail only, NEVER blocks a push):
  `$expected = ($wave.prompt_paths | Measure-Object).Count
  `$actual   = (git log --oneline origin/main..HEAD | Measure-Object).Count
  if (`$expected -ne `$actual) {
    Write-Host "AUDIT: wave $($wave.id) expected `$expected commit(s); HEAD has `$actual unpushed commit(s). Review the extra commits before pushing." -ForegroundColor Yellow
  } else {
    Write-Host "AUDIT: wave $($wave.id) commit count matches (`$expected)." -ForegroundColor Green
  }

Look for:
  - Unintended file changes (drift outside wave scope)
  - Commit messages match `AD-NNN: <one-line>` pattern
  - No accidental large deletions
  - No commercial-boundary leaks (vendor names in shipping content for
    Commercial-tagged ADs)

If APPROVE:
  ./scripts/wave-orchestrator.ps1 advance

If REJECT:
  Investigate. Possible actions:
    - git revert <bad-commit>; re-dispatch builder
    - Manual fix; re-run verify_build
"@
}

function Format-PushAction {
    param([hashtable]$wave)
    @"
============================================================
WAVE $($wave.id) — STAGE: push
============================================================

ACTION: Push commits to origin/main.

COMMAND:
  ./scripts/wave-orchestrator.ps1 verify

The orchestrator revalidates the canonical gate receipt, runs ``git push``,
and records the exact local/upstream commit pair. When it succeeds, run:
  ./scripts/wave-orchestrator.ps1 advance
"@
}

function Format-Gate3 {
    param([hashtable]$wave)
    $issueList = if ($wave.issues_to_close -and $wave.issues_to_close.Count -gt 0) {
        ($wave.issues_to_close | ForEach-Object { "  - #$_" }) -join "`n"
    } else {
        "  (none configured — review wave commits and identify issues to close)"
    }
    @"
============================================================
WAVE $($wave.id) — GATE 3: APPROVE GH ISSUE CLOSURE
============================================================

ACTION: Confirm which GitHub issues should be closed by this wave's commits.

CONFIGURED issues_to_close:
$issueList

To inspect what was actually built, review the latest commits:
  git log --oneline origin/main..HEAD~$($MAIN_STAGES.Count)..origin/main

Update prompts/wave-plan.yaml `issues_to_close` for this wave if needed,
then advance to trigger automated closure:
  ./scripts/wave-orchestrator.ps1 advance
"@
}

function Format-CloseAction {
    param([hashtable]$wave)
    $issues = $wave.issues_to_close
    if (-not $issues -or $issues.Count -eq 0) {
        return @"
============================================================
WAVE $($wave.id) — STAGE: close (NO ISSUES TO CLOSE)
============================================================

No issues configured for closure. Proceeding to retrospective.

  ./scripts/wave-orchestrator.ps1 advance
"@
    }
    $closures = ($issues | ForEach-Object { "  gh issue close $_ --comment 'Closed in Wave $($wave.id) — see DECISIONS.md' --reason completed" }) -join "`n"
    @"
============================================================
WAVE $($wave.id) — STAGE: close
============================================================

ACTION: Close $($issues.Count) GitHub issue(s).

COMMANDS:
$closures

Then archive the wave's prompts:
  Move-Item prompts/ad-*.md prompts/archive/ -Force  # adjust pattern per wave
  Move-Item prompts/Reviews/*.md prompts/Reviews/archive/ -Force

When done, run:
  ./scripts/wave-orchestrator.ps1 advance
"@
}

function Format-RetrospectiveAction {
    param([hashtable]$wave)
    @"
============================================================
WAVE $($wave.id) — STAGE: retrospective (OPTIONAL)
============================================================

If this wave revealed new conventions or surprising failure modes worth
banking, draft a retrospective addendum entry in DECISIONS.md. Otherwise,
skip.

Heuristic: write a retrospective when:
  - Pass-1 Required count increased vs prior wave (new failure mode)
  - A novel pattern emerged (e.g., Combo A in Wave 8)
  - A standing convention was added/revised

When done (or skipped), run:
  ./scripts/wave-orchestrator.ps1 advance

This advances to 'done'; the next invocation moves to the next wave.
"@
}

# ---------- Stage dispatcher ----------

function Format-StageDispatch {
    param([hashtable]$wave, [string]$stage)
    switch ($stage) {
        'draft'         { return Format-DraftDispatch $wave }
        'precheck'      { return Format-PrecheckDispatch $wave }
        'review_1'      { return Format-ReviewDispatch $wave '1' }
        'revision'      { return Format-RevisionDispatch $wave }
        'review_2'      { return Format-ReviewDispatch $wave '2' }
        'gate_1'        { return Format-Gate1 $wave }
        'build'         { return Format-BuildDispatch $wave }
        'review_build'  { return Format-ReviewBuild $wave }
        'verify_build'  { return Format-VerifyBuild $wave }
        'gate_2'        { return Format-Gate2 $wave }
        'push'          { return Format-PushAction $wave }
        'gate_3'        { return Format-Gate3 $wave }
        'close'         { return Format-CloseAction $wave }
        'retrospective' { return Format-RetrospectiveAction $wave }
        'verify_outputs' {
            $files = $wave.expected_outputs -join ', '
            return @"
============================================================
WAVE $($wave.id) — STAGE: verify_outputs
============================================================

ACTION: Confirm meta-prompt outputs exist.

EXPECTED FILES:
  $files

When confirmed, run:
  ./scripts/wave-orchestrator.ps1 advance
"@
        }
        'commit_push' {
            return @"
============================================================
WAVE $($wave.id) — STAGE: commit_push
============================================================

ACTION: Verify the meta-prompt's commit landed and was pushed.

COMMANDS:
  git log --oneline -1
  git status

When confirmed, run:
  ./scripts/wave-orchestrator.ps1 advance
"@
        }
        default { return "Unknown stage: $stage" }
    }
}

# ---------- Commands ----------

function Find-NextWave {
    param([hashtable]$plan, [hashtable]$state)
    foreach ($wave in $plan.waves) {
        if ($wave.status -ne 'done' -and $wave.status -ne 'closed') {
            # Check dependencies
            if ($wave.depends_on) {
                $blocked = $false
                foreach ($depId in $wave.depends_on) {
                    $dep = $plan.waves | Where-Object { $_.id -eq $depId } | Select-Object -First 1
                    if ($dep -and $dep.status -ne 'done' -and $dep.status -ne 'closed') {
                        $blocked = $true
                        break
                    }
                }
                if ($blocked) { continue }
            }
            return $wave
        }
    }
    return $null
}

function Cmd-Status {
    $state = Get-State
    $plan = Get-Plan
    Write-Host "Wave Orchestrator Status" -ForegroundColor Cyan
    Write-Host "========================"
    Write-Host "Current wave:  $($state.current_wave)"
    Write-Host "Current stage: $($state.current_stage)"
    Write-Host ""
    Write-Host "Wave queue:"
    foreach ($w in $plan.waves) {
        $marker = if ($w.id -eq $state.current_wave) { ">>>" } else { "   " }
        $color = switch ($w.status) {
            'done'    { 'Green' }
            'closed'  { 'Green' }
            'pending' { 'Gray' }
            default   { 'Yellow' }
        }
        Write-Host "$marker $($w.id) [$($w.status)] — $($w.title)" -ForegroundColor $color
    }
    Write-Host ""
    if ($state.history -and $state.history.Count -gt 0) {
        Write-Host "Recent history (last 5):"
        $state.history | Select-Object -Last 5 | ForEach-Object {
            Write-Host "  - $_"
        }
    }
}

function Cmd-Next {
    $state = Get-State
    $plan = Get-Plan

    if (-not $state.current_wave) {
        $next = Find-NextWave $plan $state
        if (-not $next) {
            Write-Host "All waves complete." -ForegroundColor Green
            return
        }
        $state.current_wave = $next.id
        $state.current_stage = (Get-StagesForWave $next)[0]
        Set-State $state
    }

    $wave = $plan.waves | Where-Object { $_.id -eq $state.current_wave } | Select-Object -First 1
    if (-not $wave) {
        Write-Error "current_wave $($state.current_wave) not found in plan"
        return
    }

    $dispatch = Format-StageDispatch $wave $state.current_stage
    Write-Host $dispatch
}

function Cmd-Advance {
    $state = Get-State
    $plan = Get-Plan

    if (-not $state.current_wave) {
        Cmd-Next
        return
    }

    $wave = $plan.waves | Where-Object { $_.id -eq $state.current_wave } | Select-Object -First 1
    $stages = Get-StagesForWave $wave
    $currentIdx = [Array]::IndexOf($stages, $state.current_stage)

    if ($currentIdx -lt 0) {
        Write-Error "Unknown stage $($state.current_stage) for wave $($wave.id)"
        return
    }

    if ($state.current_stage -in @('verify_build', 'gate_2', 'push')) {
        if (-not (Test-GateReceipt -State $state -Wave $wave)) {
            exit 2
        }
    }
    if ($state.current_stage -eq 'push') {
        if (-not $state.ContainsKey('push_receipt')) {
            [Console]::Error.WriteLine(
                "No successful orchestrated push receipt exists for wave '$($wave.id)'. Run 'verify'."
            )
            exit 2
        }
        $pushIdentity = Get-PushTarget
        $remoteCommit = Get-RemoteRefCommit -Target $pushIdentity
        $pushReceipt = $state.push_receipt
        if (
            $pushReceipt.wave_id -ne $wave.id -or
            $pushReceipt.commit -ne $pushIdentity.commit -or
          $pushReceipt.remote -ne $pushIdentity.remote -or
          $pushReceipt.remote_ref -ne $pushIdentity.remote_ref -or
          $pushReceipt.remote_url_sha256 -ne $pushIdentity.remote_url_sha256 -or
          $remoteCommit -ne $pushIdentity.commit
        ) {
            [Console]::Error.WriteLine(
                "Orchestrated push receipt does not match the current local/upstream commit. Run 'verify'."
            )
            exit 2
        }
    }

    # Record history
    $timestamp = Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'
    if (-not $state.history) { $state.history = @() }
    $state.history += "$timestamp wave=$($wave.id) stage=$($state.current_stage) -> advance"

    # Advance
    if ($currentIdx -ge ($stages.Count - 1)) {
        # Last stage — mark wave done; clear current
        $wave.status = 'done'
        # Persist plan back
        Save-Plan $plan
        $state.current_wave = $null
        $state.current_stage = 'idle'
        $state.Remove('verify_build_receipt')
        $state.Remove('push_receipt')
        Set-State $state
        Write-Host "Wave $($wave.id) complete." -ForegroundColor Green
        Cmd-Next
        return
    }

    $next = $stages[$currentIdx + 1]
    if ($next -eq 'verify_build') {
      $state.Remove('verify_build_receipt')
      $state.Remove('push_receipt')
    }
    $state.current_stage = $next
    Set-State $state
    Write-Host "Advanced to stage: $next" -ForegroundColor Cyan
    Write-Host ""
    Cmd-Next
}

function Cmd-Reset {
    if (-not $Argument) {
        Write-Error "Usage: wave-orchestrator.ps1 reset <wave-id>"
        return
    }
    $state = Get-State
    $plan = Get-Plan
    $wave = $plan.waves | Where-Object { $_.id -eq $Argument } | Select-Object -First 1
    if (-not $wave) {
        Write-Error "Wave $Argument not found"
        return
    }
    $wave.status = 'pending'
    $state.Remove('verify_build_receipt')
    $state.Remove('push_receipt')
    Save-Plan $plan
    if ($state.current_wave -eq $Argument -or -not $state.current_wave) {
        $state.current_wave = $Argument
        $state.current_stage = (Get-StagesForWave $wave)[0]
    }
    Set-State $state
    Write-Host "Wave $Argument reset to pending." -ForegroundColor Yellow
}

function Cmd-Verify {
    $state = Get-State
    if (-not $state.current_wave) {
    [Console]::Error.WriteLine("No active wave. Run 'next' to begin.")
    exit 2
    }
  $plan = Get-Plan
    $wave = $plan.waves | Where-Object { $_.id -eq $state.current_wave } | Select-Object -First 1
  if (-not $wave) {
    [Console]::Error.WriteLine(
      "Active wave '$($state.current_wave)' is absent from wave-plan.yaml."
    )
    exit 2
  }

    switch ($state.current_stage) {
        'precheck' {
            $patterns = $wave.prompt_paths
            if (-not $patterns) { $patterns = $wave.expected_outputs | Where-Object { $_ -like 'prompts/*.md' } }
      if (-not $patterns) {
        [Console]::Error.WriteLine(
          "Active wave '$($wave.id)' has no prompt paths to precheck."
        )
        exit 2
      }
            $files = @()
            foreach ($pattern in @($patterns)) {
              $promptMatches = @(
                Get-ChildItem -Path (Join-Path $repoRoot $pattern) -ErrorAction SilentlyContinue
              )
              if (-not $promptMatches) {
                [Console]::Error.WriteLine(
                  "No drafted prompt found for declared pattern: $pattern"
                )
                exit 2
              }
              $files += $promptMatches
            }
            $script = Join-Path $repoRoot 'scripts/phantom-api-precheck.ps1'
            & $script @($files.FullName | Sort-Object -Unique)
            exit $LASTEXITCODE
        }
        'verify_build' {
            $state.Remove('verify_build_receipt')
            $state.Remove('push_receipt')
            Set-State $state
            $identityBefore = Get-GitTreeIdentity
            if (-not (Test-CommittedTreeIdentity -Identity $identityBefore)) {
                exit 2
            }
            $receiptDirectory = Join-Path $repoRoot 'logs/gates'
            $null = New-Item -ItemType Directory -Path $receiptDirectory -Force
            $receiptPath = Join-Path $receiptDirectory (
                "wave-$($wave.id)-$([guid]::NewGuid().ToString('N')).receipt.json"
            )
            $expectedLabel = ConvertTo-GateLabel -Value "wave-$($wave.id)"
            $py = Resolve-ProbOSPython -RepoRoot $repoRoot
            $gate = Join-Path $repoRoot 'scripts/run_test_gate.py'
            & $py $gate '--label' "wave-$($wave.id)" '--receipt' $receiptPath
            $exitCode = $LASTEXITCODE
            if ($exitCode -ne 0) {
                Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
                [Console]::Error.WriteLine(
                    "Canonical Python gate failed with exit code $exitCode"
                )
                exit $exitCode
            }
            $identityAfter = Get-GitTreeIdentity
            if (
                -not (Test-CommittedTreeIdentity -Identity $identityAfter) -or
                -not (Test-GitTreeIdentity -Expected $identityBefore -Actual $identityAfter)
            ) {
                Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
                [Console]::Error.WriteLine(
                    "Git tree changed between canonical gate invocation and receipt creation"
                )
                exit 3
            }
            try {
                $null = Read-GateSuccessReceipt `
                    -Path $receiptPath `
                    -ExpectedLabel $expectedLabel `
                    -ExpectedTree $identityAfter
            } catch {
                Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
                [Console]::Error.WriteLine(
                    "Canonical gate receipt validation failed: $($_.Exception.Message)"
                )
                exit 5
            }
            $state = Get-State
            if (
                $state.current_wave -ne $wave.id -or
                $state.current_stage -ne 'verify_build'
            ) {
                Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
                [Console]::Error.WriteLine(
                    "Wave state changed while the canonical gate ran; receipt not recorded"
                )
                exit 3
            }
            $state.verify_build_receipt = @{
                wave_id = $wave.id
                verified_at = (Get-Date).ToUniversalTime().ToString('o')
                label = $expectedLabel
                tree = $identityAfter
                artifact = @{
                    path = [IO.Path]::GetRelativePath($repoRoot, $receiptPath).Replace('\', '/')
                    sha256 = Get-FileSha256 -Path $receiptPath
                }
            }
            Set-State $state
            exit 0
        }
        'push' {
          $state.Remove('push_receipt')
          Set-State $state
          if (-not (Test-GateReceipt -State $state -Wave $wave)) {
            exit 2
          }
          $identityBefore = Get-GitTreeIdentity
          if (-not (Test-CommittedTreeIdentity -Identity $identityBefore)) {
            exit 2
          }
          $pushTarget = Get-PushTarget
          & git -C $repoRoot push --porcelain $pushTarget.remote_url "$($pushTarget.commit):$($pushTarget.remote_ref)"
          $pushExitCode = $LASTEXITCODE
          if ($pushExitCode -ne 0) {
            [Console]::Error.WriteLine(
              "Git push failed with exit code $pushExitCode"
            )
            exit $pushExitCode
          }
          $identityAfter = Get-GitTreeIdentity
          if (-not (Test-GitTreeIdentity -Expected $identityBefore -Actual $identityAfter)) {
            [Console]::Error.WriteLine(
              "Git tree changed while the orchestrated push ran; receipt not recorded"
            )
            exit 3
          }
          $pushed = Get-PushTarget
          if (
            $pushed.remote -ne $pushTarget.remote -or
            $pushed.remote_ref -ne $pushTarget.remote_ref -or
            $pushed.remote_url_sha256 -ne $pushTarget.remote_url_sha256
          ) {
            [Console]::Error.WriteLine(
              "Configured push target changed while git push ran; receipt not recorded"
            )
            exit 3
          }
          $remoteCommit = Get-RemoteRefCommit -Target $pushed
          if ($remoteCommit -ne $pushed.commit) {
            [Console]::Error.WriteLine(
              "Git push returned success but remote ref '$($pushed.remote_ref)' is not at '$($pushed.commit)'"
            )
            exit 3
          }
          $state = Get-State
          if ($state.current_wave -ne $wave.id -or $state.current_stage -ne 'push') {
            [Console]::Error.WriteLine(
              "Wave state changed while git push ran; receipt not recorded"
            )
            exit 3
          }
          if (-not (Test-GateReceipt -State $state -Wave $wave)) {
            exit 3
          }
          $state.push_receipt = @{
            wave_id = $wave.id
            pushed_at = (Get-Date).ToUniversalTime().ToString('o')
            branch = $pushed.branch
            remote = $pushed.remote
            remote_ref = $pushed.remote_ref
            remote_url_sha256 = $pushed.remote_url_sha256
            commit = $pushed.commit
          }
          Set-State $state
          exit 0
        }
        'verify_outputs' {
          if (-not $wave.expected_outputs) {
            [Console]::Error.WriteLine(
              "Active wave '$($wave.id)' has no expected outputs to verify."
            )
            exit 2
          }
            $missing = @()
            foreach ($pattern in $wave.expected_outputs) {
                $hits = Get-ChildItem -Path (Join-Path $repoRoot $pattern) -ErrorAction SilentlyContinue
                if (-not $hits) { $missing += $pattern }
            }
            if ($missing.Count -eq 0) {
                Write-Host "All expected outputs present." -ForegroundColor Green
              exit 0
            } else {
                Write-Host "Missing outputs:" -ForegroundColor Red
                $missing | ForEach-Object { Write-Host "  - $_" }
              exit 1
            }
        }
        default {
            [Console]::Error.WriteLine(
              "No mechanical verification for stage '$($state.current_stage)'."
            )
            exit 2
        }
    }
}

function Save-Plan {
    param([hashtable]$plan)
    # Round-trip via Python YAML to preserve field order is non-trivial; for
    # now we update statuses by reading + rewriting the YAML literally.
    # Since the orchestrator only flips `status: pending` <-> `status: done`,
    # do a regex replace.
    $raw = Get-Content $planPath -Raw
    foreach ($wave in $plan.waves) {
        $waveBlock = "  - id: `"$($wave.id)`""
        $idx = $raw.IndexOf($waveBlock)
        if ($idx -lt 0) { continue }
        # Find next 'status:' after this idx, before the next '  - id:'
        $nextWaveIdx = $raw.IndexOf("`n  - id:", $idx + 1)
        if ($nextWaveIdx -lt 0) { $nextWaveIdx = $raw.Length }
        $blockText = $raw.Substring($idx, $nextWaveIdx - $idx)
        $updated = [regex]::Replace($blockText, '(\n\s+status:\s+)\w+', { param($m) $m.Groups[1].Value + $wave.status })
        $raw = $raw.Substring(0, $idx) + $updated + $raw.Substring($nextWaveIdx)
    }
    Set-Content -Path $planPath -Value $raw -Encoding UTF8 -NoNewline
}

function Cmd-Help {
    @"
Wave Orchestrator — semi-autonomous wave dispatch

Commands:
  status            Show current wave + stage + queue
  next              Print dispatch instruction for the current stage
  advance           Mark current stage complete; move to next stage
  reset <wave>      Rewind a wave to pending
  verify            Run mechanical verification for the current stage (if any)
  help              This text

Pipeline (main wave):
  draft -> precheck -> review_1 -> revision -> review_2 -> [GATE 1]
       -> build -> verify_build -> [GATE 2] -> push
       -> [GATE 3] -> close -> retrospective -> done

Three architect gates require explicit `advance` after human inspection.
Other stages require `advance` after the dispatched subagent reports complete.

State files:
  prompts/wave-plan.yaml                   (edit to add waves)
  prompts/wave-orchestrator-state.json     (auto-managed)
"@
}

# ---------- Entry point ----------

switch ($Command) {
    'status'  { Cmd-Status }
    'next'    { Cmd-Next }
    'advance' { Cmd-Advance }
    'reset'   { Cmd-Reset }
    'verify'  { Cmd-Verify }
    'help'    { Cmd-Help }
}
