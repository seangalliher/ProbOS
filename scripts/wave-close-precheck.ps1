[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-python.ps1')

$script:FailCount = 0
$script:WarnCount = 0

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "== $Title ==" -ForegroundColor Cyan
}

function Add-Fail {
    param([string]$Message)
    $script:FailCount += 1
    Write-Host "FAIL: $Message" -ForegroundColor Red
}

function Add-Warn {
    param([string]$Message)
    $script:WarnCount += 1
    Write-Warning $Message
}

function Add-Info {
    param([string]$Message)
    Write-Host "INFO: $Message" -ForegroundColor DarkCyan
}

function Read-FileRaw {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return ''
    }
    return Get-Content -Path $Path -Raw
}

function Get-LineNumberFromIndex {
    param(
        [string]$Text,
        [int]$Index
    )
    if ($Index -le 0) {
        return 1
    }
    $prefix = $Text.Substring(0, [Math]::Min($Index, $Text.Length))
    return ([regex]::Matches($prefix, "`n").Count + 1)
}

function Get-ExportedSymbols {
    param([string]$ModulePath)

    $symbols = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $text = Read-FileRaw -Path $ModulePath
    if ([string]::IsNullOrWhiteSpace($text)) {
        return @()
    }

    $direct = [regex]::Matches(
        $text,
        '(?m)^\s*export\s+(?:const|function|async\s+function|class|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)'
    )
    foreach ($m in $direct) {
        [void]$symbols.Add($m.Groups[1].Value)
    }

    $named = [regex]::Matches($text, '(?m)^\s*export\s*\{([^}]*)\}')
    foreach ($m in $named) {
        $parts = $m.Groups[1].Value -split ','
        foreach ($part in $parts) {
            $trimmed = $part.Trim()
            if ([string]::IsNullOrWhiteSpace($trimmed)) {
                continue
            }
            $baseName = ($trimmed -split '\s+as\s+')[0].Trim()
            if ($baseName -match '^[A-Za-z_][A-Za-z0-9_]*$') {
                [void]$symbols.Add($baseName)
            }
        }
    }

    return @($symbols)
}

function Get-MockBlocks {
    param([string]$TestPath)

    $text = Read-FileRaw -Path $TestPath
    if ([string]::IsNullOrWhiteSpace($text)) {
        return @()
    }

    $pattern = 'vi\.mock\(\s*[''\"]([^''\"]+)[''\"]\s*,\s*\(\s*\)\s*=>\s*\(\s*\{([\s\S]*?)\}\s*\)\s*\)'
    $matches = [regex]::Matches($text, $pattern)
    $blocks = @()
    foreach ($m in $matches) {
        $blocks += [pscustomobject]@{
            MockPath = $m.Groups[1].Value
            Body = $m.Groups[2].Value
            Line = Get-LineNumberFromIndex -Text $text -Index $m.Index
        }
    }
    return $blocks
}

function Get-MockKeys {
    param([string]$MockBody)

    $keys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $matches = [regex]::Matches($MockBody, '(?m)([A-Za-z_][A-Za-z0-9_]*)\s*:')
    foreach ($m in $matches) {
        [void]$keys.Add($m.Groups[1].Value)
    }
    return @($keys)
}

function Check-LockFileSync {
    param([string]$Root)

    Write-Section -Title 'Check 1: lock-file sync'

    $uiDir = Join-Path $Root 'ui'
    if (-not (Test-Path $uiDir)) {
        Add-Fail "ui directory not found: $uiDir"
        return
    }

    $output = ''
    Push-Location $uiDir
    try {
        $output = (& npm install --package-lock-only --dry-run 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0) {
            Add-Fail "npm --package-lock-only --dry-run exited $LASTEXITCODE in ui"
            if (-not [string]::IsNullOrWhiteSpace($output)) {
                Add-Info ($output.Trim())
            }
            return
        }

        if ($output -match '(?i)(package-lock\.json\s+would\s+update|would\s+update.*package-lock\.json|lockfile.*(out\s+of\s+date|needs?\s+update))') {
            Add-Fail 'package-lock.json appears out of sync with package.json (dry-run indicates changes).'
            Add-Info ($output.Trim())
            return
        }

        Write-Host 'PASS: lock-file sync check' -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}

function Check-MockParity {
    param([string]$Root)

    Write-Section -Title 'Check 2: mock parity'

    $uiSrc = Join-Path $Root 'ui/src'
    if (-not (Test-Path $uiSrc)) {
        Add-Fail "ui/src not found: $uiSrc"
        return
    }

    # AD-748 v1: static heavily-mocked list. Keep in sync with prompt/ad-748-wave-close-ci-hygiene.md.
    $moduleMap = @{
        'audio/voice' = 'ui/src/audio/voice.ts'
        'audio/wakeWord' = 'ui/src/audio/wakeWord.ts'
        'audio/speechInput' = 'ui/src/audio/speechInput.ts'
        'store/useStore' = 'ui/src/store/useStore.ts'
        'api' = 'ui/src/api.ts'
    }

    $tests = Get-ChildItem -Path $uiSrc -Recurse -Filter '*.test.tsx' -File -ErrorAction SilentlyContinue
    $hadFailure = $false

    foreach ($entry in $moduleMap.GetEnumerator()) {
        $moduleKey = $entry.Key
        $modulePath = Join-Path $Root $entry.Value
        $exports = Get-ExportedSymbols -ModulePath $modulePath

        if ($exports.Count -eq 0) {
            Add-Info "No exports discovered in $modulePath; skipping parity diff for this module."
            continue
        }

        foreach ($testFile in $tests) {
            $blocks = Get-MockBlocks -TestPath $testFile.FullName
            foreach ($block in $blocks) {
                if ($block.MockPath -notmatch [regex]::Escape($moduleKey)) {
                    continue
                }

                $keys = Get-MockKeys -MockBody $block.Body
                foreach ($symbol in $exports) {
                    if ($keys -notcontains $symbol) {
                        Add-Fail ("$($testFile.FullName):$($block.Line) mock '$($block.MockPath)' missing export '$symbol' from $modulePath")
                        $hadFailure = $true
                    }
                }
            }
        }
    }

    if (-not $hadFailure) {
        Write-Host 'PASS: mock parity check' -ForegroundColor Green
    }
}

function Check-PythonGatePreflight {
    param([string]$Root)

    Write-Section -Title 'Check 3: Python gate preflight'

    $gateScript = Join-Path $Root 'scripts/run_test_gate.py'
    if (-not (Test-Path $gateScript)) {
        Add-Fail "canonical gate wrapper not found: $gateScript"
        return
    }

    try {
        $python = Resolve-ProbOSPython -RepoRoot $Root
    } catch {
        Add-Fail "Python resolution failed: $($_.Exception.Message)"
        return
    }

    Push-Location $Root
    try {
        & $python $gateScript --preflight-only --label wave-close
        $exitCode = $LASTEXITCODE

        if ($exitCode -ne 0) {
            Add-Fail "Python gate preflight failed with exit code $exitCode"
            return
        }

        Write-Host 'PASS: Python gate preflight' -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}

function Get-GlobalPytestTimeout {
    param([string]$Root)

    $pyprojectPath = Join-Path $Root 'pyproject.toml'
    if (-not (Test-Path $pyprojectPath)) {
        return 180
    }

    $text = Read-FileRaw -Path $pyprojectPath
    if ($text -match '(?m)^\s*timeout\s*=\s*(\d+)\s*$') {
        return [int]$Matches[1]
    }
    return 180
}

function Check-LocalTightTimeoutAudit {
    param([string]$Root)

    Write-Section -Title 'Check 4: local-tight pytest-timeout audit'

    $testsDir = Join-Path $Root 'tests'
    if (-not (Test-Path $testsDir)) {
        Add-Info "tests directory not found: $testsDir"
        return
    }

    $globalTimeout = Get-GlobalPytestTimeout -Root $Root
    Add-Info "Global pytest timeout baseline: $globalTimeout second(s)"

    $testFiles = Get-ChildItem -Path $testsDir -Recurse -Filter '*.py' -File -ErrorAction SilentlyContinue
    $matches = Select-String -Path $testFiles.FullName -Pattern '@pytest\.mark\.timeout\((\d+)\)' -AllMatches
    $count = 0
    foreach ($match in $matches) {
        foreach ($capture in $match.Matches) {
            $value = [int]$capture.Groups[1].Value
            if ($value -lt $globalTimeout) {
                Add-Info ("$($match.Path):$($match.LineNumber) local timeout $value is tighter than global $globalTimeout")
                $count += 1
            }
        }
    }

    Add-Info "Tight-timeout findings: $count"
    Write-Host 'PASS: timeout audit check (informational)' -ForegroundColor Green
}

function Check-VitestUnhandledErrorGate {
    param([string]$Root)

    Write-Section -Title 'Check 5: vitest unhandled-error gate'

    $uiDir = Join-Path $Root 'ui'
    if (-not (Test-Path $uiDir)) {
        Add-Fail "ui directory not found: $uiDir"
        return
    }

    Push-Location $uiDir
    try {
        & npx vitest run
        if ($LASTEXITCODE -ne 0) {
            Add-Fail "vitest run exited $LASTEXITCODE"
            return
        }

        Write-Host 'PASS: vitest unhandled-error gate' -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}

Check-LockFileSync -Root $RepoRoot
Check-MockParity -Root $RepoRoot
Check-PythonGatePreflight -Root $RepoRoot
Check-LocalTightTimeoutAudit -Root $RepoRoot
Check-VitestUnhandledErrorGate -Root $RepoRoot

Write-Host ""
Write-Host "Summary: FAIL=$script:FailCount WARN=$script:WarnCount" -ForegroundColor Cyan

if ($script:FailCount -gt 0) {
    exit 1
}

exit 0