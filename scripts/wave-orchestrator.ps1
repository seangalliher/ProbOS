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
#   - Run full pytest gate
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

function Get-Plan {
    if (-not (Test-Path $planPath)) {
        throw "wave-plan.yaml not found at $planPath"
    }
    # Minimal YAML parse — relies on simple structure. For complex YAML use
    # ConvertFrom-Yaml from powershell-yaml module if installed.
    $raw = Get-Content $planPath -Raw
    # Convert YAML to JSON via Python (always available in repo .venv)
    $py = Join-Path $repoRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path $py)) { $py = 'python' }
    $json = $raw | & $py -c "import sys, yaml, json; print(json.dumps(yaml.safe_load(sys.stdin)))"
    return ($json | ConvertFrom-Json -AsHashtable)
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
    'verify_build',    # Run full pytest gate
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
    d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile  # green baseline

  Per-prompt: read prompt + review (apply non-blocking nits at code-review),
  implement section by section, run focused gate at -n 0, update trackers,
  commit with `AD-NNN: <one-line>` format, push.

  Per-commit gate: full pytest passes, test count non-decreasing,
  pre-commit deletion sanity check.

  UI gate (AD-738b / BF-279): if the prompt touches any file under
  ``ui/src/**``, run BOTH ``cd ui; npx vitest run`` AND ``cd ui; npm run build``
  before the commit. Vitest alone does NOT exercise ``tsc -b`` strict checks;
  ``npm run build`` is the only signal that the production bundle compiles.
  Detection: ``git diff --name-only HEAD~1..HEAD -- ui/src/`` after the
  per-prompt edits; if non-empty, run both. The standing rule lives in
  ``prompts/BUILDER-EXECUTION-PLAN.md`` Standing Rules section.

  Begin in dependency order; surface only on hard-stop conditions per
  BUILDER-EXECUTION-PLAN.md.

When Builder reports complete, run:
  ./scripts/wave-orchestrator.ps1 advance
"@
}

function Format-VerifyBuild {
    param([hashtable]$wave)
    @"
============================================================
WAVE $($wave.id) — STAGE: verify_build
============================================================

ACTION: Run full test gate to confirm Builder commits are green.

COMMAND:
  d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile

Expected: 0 failures (environmental flakes acceptable per standing rule —
re-run flaked test at -n 0 to confirm).

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
  git push

When push succeeds, run:
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
        Set-State $state
        Write-Host "Wave $($wave.id) complete." -ForegroundColor Green
        Cmd-Next
        return
    }

    $next = $stages[$currentIdx + 1]
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
    Save-Plan $plan
    if ($state.current_wave -eq $Argument -or -not $state.current_wave) {
        $state.current_wave = $Argument
        $state.current_stage = (Get-StagesForWave $wave)[0]
        Set-State $state
    }
    Write-Host "Wave $Argument reset to pending." -ForegroundColor Yellow
}

function Cmd-Verify {
    $state = Get-State
    $plan = Get-Plan
    if (-not $state.current_wave) {
        Write-Host "No active wave. Run 'next' to begin."
        return
    }
    $wave = $plan.waves | Where-Object { $_.id -eq $state.current_wave } | Select-Object -First 1

    switch ($state.current_stage) {
        'precheck' {
            $patterns = $wave.prompt_paths
            if (-not $patterns) { $patterns = $wave.expected_outputs | Where-Object { $_ -like 'prompts/*.md' } }
            $files = $patterns | ForEach-Object { Get-ChildItem -Path (Join-Path $repoRoot $_) -ErrorAction SilentlyContinue }
            if (-not $files) {
                Write-Error "No drafted prompts found for patterns: $($patterns -join ', ')"
                return
            }
            $script = Join-Path $repoRoot 'scripts/phantom-api-precheck.ps1'
            & $script @($files.FullName)
        }
        'verify_build' {
            $py = Join-Path $repoRoot '.venv/Scripts/pytest.exe'
            & $py 'tests/' '-q' '-n' '8' '--dist=loadfile'
        }
        'verify_outputs' {
            $missing = @()
            foreach ($pattern in $wave.expected_outputs) {
                $hits = Get-ChildItem -Path (Join-Path $repoRoot $pattern) -ErrorAction SilentlyContinue
                if (-not $hits) { $missing += $pattern }
            }
            if ($missing.Count -eq 0) {
                Write-Host "All expected outputs present." -ForegroundColor Green
            } else {
                Write-Host "Missing outputs:" -ForegroundColor Red
                $missing | ForEach-Object { Write-Host "  - $_" }
            }
        }
        default {
            Write-Host "No mechanical verification for stage '$($state.current_stage)'. This is an architect-judgment stage."
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
