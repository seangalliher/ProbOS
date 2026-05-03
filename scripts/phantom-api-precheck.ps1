# phantom-api-precheck.ps1
#
# Dispatch-time scripted phantom-API pre-check. Per Wave 8 Retrospective
# Addendum convention #16 (mandatory for Wave 9+).
#
# Greps every `runtime.X` attribute access and every `<Class>.<method>` /
# `<Class>(...)` symbol referenced in a prompt body against the live
# src/probos tree. Flags symbols not found.
#
# Usage:
#   ./scripts/phantom-api-precheck.ps1 prompts/ad-XXX.md [more prompts...]
#   ./scripts/phantom-api-precheck.ps1 prompts/wave-N/*.md
#
# Output: per-prompt findings to stdout; aggregated summary at end.
# Exit code: 0 = clean; 1 = at least one phantom found.
#
# This is a heuristic — false positives happen for:
#   - Symbols introduced BY the prompt (search the prompt body itself before flagging)
#   - Stdlib symbols (asyncio.X, json.X, etc.) — filtered via STDLIB_PREFIXES
#   - Symbols referenced only in commentary / examples
# Architect reviews the output; the script prunes the obvious phantoms only.

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true, Position=0, ValueFromRemainingArguments=$true)]
    [string[]]$PromptPaths
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$srcRoot = Join-Path $repoRoot 'src/probos'

if (-not (Test-Path $srcRoot)) {
    Write-Error "src/probos not found at $srcRoot — run from repo root."
    exit 2
}

# Stdlib / third-party prefixes to ignore on `<X>.<method>` matches.
$STDLIB_PREFIXES = @(
    'asyncio', 'json', 'os', 'sys', 'time', 'logging', 'pathlib', 'typing',
    'datetime', 'collections', 'functools', 'itertools', 're', 'uuid',
    'dataclasses', 'enum', 'abc', 'contextlib', 'concurrent', 'threading',
    'subprocess', 'shutil', 'tempfile', 'io', 'string', 'math', 'hashlib',
    'pytest', 'httpx', 'pydantic', 'rich', 'aiosqlite', 'sqlite3',
    'self', 'cls', 'super', 'rt', 'config', 'kwargs', 'args',
    'np', 'pd', 'asyncio_pool',
    'MagicMock', 'AsyncMock', 'Mock',
    'MethodType', 'FunctionType', 'ModuleType',  # types module
    'Path', 'Optional', 'Union', 'List', 'Dict', 'Set', 'Tuple', 'Callable',
    'Any', 'Iterable', 'Awaitable', 'Coroutine', 'AsyncIterator', 'Iterator'
)

# Markdown / repo filenames to skip (uppercase patterns matching SCREAMING_SNAKE.md)
$DOC_FILE_PATTERN = '^[A-Z][A-Z0-9_-]*\.(md|MD|txt|TXT|yaml|yml|toml|json)$'

# Cache of source contents for fast repeated greps.
$srcContent = @{}
Get-ChildItem -Path $srcRoot -Recurse -Include '*.py' | ForEach-Object {
    $srcContent[$_.FullName] = Get-Content $_.FullName -Raw
}
$allSrc = ($srcContent.Values -join "`n")

function Test-SymbolExists {
    param([string]$symbol)
    # Look for: `def <symbol>(`, `class <symbol>`, `<symbol> =`,
    # `<symbol>:` (attribute annotation), or `self.<symbol> =`
    $patterns = @(
        "def\s+$symbol\b",
        "class\s+$symbol\b",
        "\b$symbol\s*[:=]",
        "self\.$symbol\s*[:=]"
    )
    foreach ($p in $patterns) {
        if ($allSrc -match $p) { return $true }
    }
    return $false
}

$totalPhantoms = 0
$report = [System.Collections.ArrayList]@()

foreach ($promptPath in $PromptPaths) {
    if (-not (Test-Path $promptPath)) {
        Write-Warning "Skip (not found): $promptPath"
        continue
    }
    Write-Host "`n=== $promptPath ===" -ForegroundColor Cyan
    $body = Get-Content $promptPath -Raw

    # Collect candidate symbols from the prompt body.
    $candidates = [System.Collections.Generic.HashSet[string]]::new()

    # Pattern 1: `runtime.X` attribute access
    $matches = [regex]::Matches($body, 'runtime\.([a-z_][a-z0-9_]*)')
    foreach ($m in $matches) {
        $sym = $m.Groups[1].Value
        if ($sym -notin @('emit_event','config','logger')) {
            [void]$candidates.Add("runtime.$sym")
        }
    }

    # Pattern 2: `<Class>.<method>` (CamelCase class)
    $matches = [regex]::Matches($body, '\b([A-Z][a-zA-Z0-9_]+)\.([a-z_][a-z0-9_]+)')
    foreach ($m in $matches) {
        $cls = $m.Groups[1].Value
        $method = $m.Groups[2].Value
        if ($cls -in $STDLIB_PREFIXES) { continue }
        $token = "$cls.$method"
        if ($token -match $DOC_FILE_PATTERN) { continue }
        [void]$candidates.Add("${cls}.${method}")
    }

    # Pattern 3: `<ClassName>(` constructor calls (CamelCase, not stdlib)
    $matches = [regex]::Matches($body, '\b([A-Z][a-zA-Z0-9_]{3,})\(')
    foreach ($m in $matches) {
        $cls = $m.Groups[1].Value
        if ($cls -in $STDLIB_PREFIXES) { continue }
        if ($cls -match '^(True|False|None)$') { continue }
        [void]$candidates.Add("class:${cls}")
    }

    $phantomsHere = [System.Collections.ArrayList]@()
    foreach ($cand in $candidates) {
        # If the prompt body itself defines/introduces the symbol, skip.
        $bareName = $cand -replace '^class:|^runtime\.|^.*\.', ''
        if ($body -match "(def|class)\s+$bareName\b") { continue }

        # Resolve symbol to check.
        $check = $bareName
        if ($cand -like 'runtime.*') {
            # Look for `self.<attr> =` or `<attr>:` Pydantic-style annotation
            # in runtime.py, config.py, or anywhere in src.
            $check = $bareName
        }

        if (-not (Test-SymbolExists $check)) {
            [void]$phantomsHere.Add($cand)
        }
    }

    if ($phantomsHere.Count -eq 0) {
        Write-Host "  Clean — no phantom symbols detected." -ForegroundColor Green
    } else {
        Write-Host "  $($phantomsHere.Count) phantom symbol(s):" -ForegroundColor Yellow
        foreach ($p in $phantomsHere) {
            Write-Host "    - $p" -ForegroundColor Yellow
        }
        $totalPhantoms += $phantomsHere.Count
        [void]$report.Add(@{ Path = $promptPath; Phantoms = @($phantomsHere) })
    }
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
Write-Host "Prompts scanned: $($PromptPaths.Count)"
Write-Host "Total phantom candidates: $totalPhantoms"
if ($totalPhantoms -gt 0) {
    Write-Host "`nReview each candidate before dispatching to architect-review:" -ForegroundColor Yellow
    Write-Host "  - True phantom: fix in prompt before review."
    Write-Host "  - False positive (introduced by prompt, stdlib alias, prose example): note in dispatch."
    Write-Host "`nThis script is heuristic. Architect judgment required."
    exit 1
}
exit 0
