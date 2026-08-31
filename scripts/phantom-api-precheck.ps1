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
# Exit code: 0 = clean; 1 = at least one phantom found; 2 = operational failure.
#
# This is a heuristic - false positives happen for:
#   - Symbols introduced BY the prompt (search the prompt body itself before flagging)
#   - Stdlib symbols (asyncio.X, json.X, etc.) - filtered via STDLIB_PREFIXES
#   - Symbols referenced only in commentary / examples
# Architect reviews the output; the script prunes the obvious phantoms only.

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true, Position=0, ValueFromRemainingArguments=$true)]
    [string[]]$PromptPaths
)

$ErrorActionPreference = 'Stop'
$requiredPowerShellMajor = 7
if ($PSVersionTable.PSVersion.Major -lt $requiredPowerShellMajor) {
    [Console]::Error.WriteLine(
        "phantom-api-precheck.ps1 requires PowerShell 7 (pwsh); found $($PSVersionTable.PSVersion)."
    )
    exit 2
}
$repoRoot = Split-Path -Parent $PSScriptRoot
$srcRoot = Join-Path $repoRoot 'src/probos'
. (Join-Path $PSScriptRoot 'resolve-python.ps1')

if (-not (Test-Path $srcRoot)) {
    Write-Error "src/probos not found at $srcRoot - run from repo root."
    exit 2
}

$missingPromptPaths = @(
    $PromptPaths | Where-Object {
        -not (Test-Path -LiteralPath $_ -PathType Leaf)
    }
)
if ($missingPromptPaths.Count -gt 0) {
    [Console]::Error.WriteLine(
        "Prompt path(s) not found: $($missingPromptPaths -join ', ')"
    )
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

function Get-FilteredPromptBody {
    # AD-685: Shared pre-filter applied uniformly to BOTH the existing
    # symbol-existence check AND the new kwarg check. Strips:
    #   1. Fenced code blocks NOT tagged python/py (pwsh, bash, sh, text,
    #      json, bare). Only ```python and ```py blocks are scanned.
    #   2. `## Revision` sections (audit-trail; expected to mention deprecated
    #      names) through the next `## ` heading or EOF.
    #   3. Markdown table rows where a cell is a single backticked symbol
    #      followed by free prose (suppresses motivation-table cites of
    #      past phantoms).
    # Stripped regions are replaced with whitespace of equal length to
    # preserve line numbers for downstream regex error reporting.
    param([string]$body)

    # 1. Fenced code blocks. Match opening fence + optional language tag.
    # Replace any fence whose tag is NOT 'python' or 'py' with whitespace.
    $body = [regex]::Replace(
        $body,
        '(?ms)^(```)([a-zA-Z0-9_+-]*)\r?\n(.*?)^```',
        {
            param($m)
            $tag = $m.Groups[2].Value.ToLower()
            if ($tag -eq 'python' -or $tag -eq 'py') {
                # Keep python blocks intact.
                return $m.Value
            }
            # Replace entire match with newlines/spaces of equal length.
            return ($m.Value -replace '[^\r\n]', ' ')
        }
    )

    # 2. `## Revision` sections through the next `## ` heading or EOF.
    $body = [regex]::Replace(
        $body,
        '(?ms)^## Revision\b.*?(?=^## |\z)',
        {
            param($m)
            return ($m.Value -replace '[^\r\n]', ' ')
        }
    )

    # 3. Markdown prose-table cells: pipe-delimited cell whose content is a
    # backticked symbol or call expression followed by prose (heuristic to
    # suppress motivation-table cites of past phantoms - e.g., a Wave 10
    # row mentioning `WorkItemStore.get_pending` or `event_log.query(...)`).
    $body = [regex]::Replace(
        $body,
        '(?m)^\|.*$',
        {
            param($m)
            $line = $m.Value
            # Skip table separator rows.
            if ($line -match '^\|[\s|:-]+\|?\s*$') { return $line }
            # Mask any backticked call expression or dotted symbol within
            # the row. Patterns covered:
            #   `Class.method`, `Class(args)`, `obj.method(args)`, `Class.method(args)`.
            $masked = [regex]::Replace(
                $line,
                '`([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*\s*\([^`]*\)|[A-Z][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*)`',
                {
                    param($mm)
                    return ($mm.Value -replace '[^\r\n]', ' ')
                }
            )
            return $masked
        }
    )

    # 4. Inline-prose backticked phantom-shape citations (broadens #3 beyond
    # tables). After step 1 stripped non-Python fences, anything still in
    # backticks outside ```python``` blocks is prose. Recursive-validity
    # tuning per AD-685 Hard-Stop: bullet-list and paragraph cites of past
    # phantoms (e.g., `WorkItemStore.get_pending`, `event_log.query(...)`)
    # would otherwise survive into the symbol check / kwarg check. Real
    # production code lives in ```python``` blocks (preserved) - backticked
    # call-shapes elsewhere are documentation references. Patterns masked:
    #   - `Class.method`     (CamelCase dotted)
    #   - `obj.method(args)` (any dotted call site)
    #   - `Class(args)`      (CamelCase constructor call)
    $body = [regex]::Replace(
        $body,
        '`([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*\s*\([^`]*\)|[A-Z][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*|[A-Z][a-zA-Z0-9_]*\([^`]*\))`',
        {
            param($m)
            return ($m.Value -replace '[^\r\n]', ' ')
        }
    )

    return $body
}

$totalPhantoms = 0
$report = [System.Collections.ArrayList]@()

foreach ($promptPath in $PromptPaths) {
    Write-Host "`n=== $promptPath ===" -ForegroundColor Cyan
    $body = Get-Content $promptPath -Raw

    # AD-685: Shared pre-filter applied uniformly to BOTH the existing
    # symbol-existence check AND the new kwarg check. Strips/masks regions
    # that are expected to mention deprecated names (audit trails) or
    # non-Python prose. Replaces stripped regions with whitespace of equal
    # length to preserve line numbers.
    $filteredBody = Get-FilteredPromptBody $body

    # Collect candidate symbols from the prompt body.
    $candidates = [System.Collections.Generic.HashSet[string]]::new()

    # Pattern 1: `runtime.X` attribute access
    $matches = [regex]::Matches($filteredBody, 'runtime\.([a-z_][a-z0-9_]*)')
    foreach ($m in $matches) {
        $sym = $m.Groups[1].Value
        if ($sym -notin @('emit_event','config','logger')) {
            [void]$candidates.Add("runtime.$sym")
        }
    }

    # Pattern 2: `<Class>.<method>` (CamelCase class)
    $matches = [regex]::Matches($filteredBody, '\b([A-Z][a-zA-Z0-9_]+)\.([a-z_][a-z0-9_]+)')
    foreach ($m in $matches) {
        $cls = $m.Groups[1].Value
        $method = $m.Groups[2].Value
        if ($cls -in $STDLIB_PREFIXES) { continue }
        $token = "$cls.$method"
        if ($token -match $DOC_FILE_PATTERN) { continue }
        [void]$candidates.Add("${cls}.${method}")
    }

    # Pattern 3: `<ClassName>(` constructor calls (CamelCase, not stdlib)
    $matches = [regex]::Matches($filteredBody, '\b([A-Z][a-zA-Z0-9_]{3,})\(')
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
        if ($filteredBody -match "(def|class)\s+$bareName\b") { continue }

        # Tuning #1 (Wave 8.5): suppress runtime.X when the prompt itself
        # introduces it via a `runtime.X =` self-introduction or
        # `runtime.X: <Type> =` Pydantic-style annotation.
        if ($cand -like 'runtime.*') {
            if ($filteredBody -match "runtime\.$bareName\s*[:=]") { continue }
            if ($filteredBody -match "self\.$bareName\s*[:=]") { continue }
        }

        # Tuning #2 (Wave 8.5): suppress symbols within negative framing
        # (NOT/was/should be/will be/no longer). The body is talking ABOUT
        # the symbol's absence, not asserting its existence.
        $idx = 0
        $negativeFraming = $false
        while (($idx = $filteredBody.IndexOf($bareName, $idx)) -ge 0) {
            $start = [Math]::Max(0, $idx - 30)
            $window = $filteredBody.Substring($start, [Math]::Min(60, $filteredBody.Length - $start))
            if ($window -match '\b(NOT|not|was|should be|will be|no longer|removed|deprecated)\b') {
                $negativeFraming = $true
                break
            }
            $idx += $bareName.Length
        }
        if ($negativeFraming) { continue }

        if (-not (Test-SymbolExists $bareName)) {
            [void]$phantomsHere.Add(@{ Symbol = $cand; Category = $(if ($cand -like 'runtime.*') { 'runtime.X' } elseif ($cand -like 'class:*') { '<Class>(...)' } else { '<Class>.<method>' }) })
        }
    }

    # AD-685: Kwarg-mismatch check via Python AST helper.
    # AD-685b: Method-name validation also via the same helper. Helper
    # output is a JSON object with `phantoms` (kwarg + method-name) and
    # `unresolved` (informational; no exit-code impact).
    $helperPath = Join-Path $PSScriptRoot 'phantom_api_ast_helper.py'
    if (-not (Test-Path -LiteralPath $helperPath -PathType Leaf)) {
        [Console]::Error.WriteLine("phantom API helper not found: $helperPath")
        exit 2
    }
    try {
        $pythonExe = Resolve-ProbOSPython -RepoRoot $repoRoot
    } catch {
        [Console]::Error.WriteLine("Python resolution failed: $($_.Exception.Message)")
        exit 2
    }
    $unresolvedHere = @()
    try {
        $helperJson = $filteredBody | & $pythonExe $helperPath --src-root $srcRoot
        $helperExitCode = $LASTEXITCODE
        if ($helperExitCode -ne 0) {
            throw "phantom_api_ast_helper.py exited $helperExitCode"
        }
        if (-not $helperJson) {
            throw 'phantom_api_ast_helper.py returned no JSON'
        }
        $parsed = $helperJson | ConvertFrom-Json -ErrorAction Stop
        if (-not ($parsed.PSObject.Properties.Name -contains 'phantoms')) {
            throw "phantom_api_ast_helper.py JSON omitted 'phantoms'"
        }
                foreach ($p in $parsed.phantoms) {
                    if ($p.category -eq 'method_phantom') {
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.resolved_class).$($p.method)(...)"
                            Category = 'method_phantom'
                            CallSite = $p.call_site
                        })
                    } elseif ($p.category -eq 'type_shape_mismatch') {
                        $expected = ($p.expected_types -join '|')
                        if (-not $expected) { $expected = '<unknown>' }
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.method)($($p.kwarg)=<$($p.value_type)> -> expected <$expected>)"
                            Category = 'type_shape_mismatch'
                            CallSite = $p.call_site
                        })
                    } elseif ($p.category -eq 'field_phantom') {
                        $valid = ($p.valid_fields -join ',')
                        if ($valid.Length -gt 80) { $valid = $valid.Substring(0, 80) + '...' }
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.class).$($p.field) <$($p.access_kind)> -> not in fields {$valid}"
                            Category = 'field_phantom'
                            CallSite = $p.call_site
                        })
                    } elseif ($p.category -eq 'property_field_collision') {
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.child).$($p.name) shadows $($p.parent).$($p.name) ($($p.kind))"
                            Category = 'property_field_collision'
                            CallSite = "$($p.child).$($p.name)"
                        })
                    } else {
                        [void]$phantomsHere.Add(@{
                            Symbol = "$($p.method)($($p.kwarg)=...)"
                            Category = 'kwarg_mismatch'
                            CallSite = $p.call_site
                        })
                    }
                }
                if ($parsed.PSObject.Properties.Name -contains 'unresolved' -and $parsed.unresolved) {
                    $unresolvedHere = @($parsed.unresolved)
                }
    } catch {
        [Console]::Error.WriteLine(
            "AST helper failed on ${promptPath}: $($_.Exception.Message)"
        )
        exit 2
    }

    if ($phantomsHere.Count -eq 0) {
        Write-Host "  Clean - no phantom symbols detected." -ForegroundColor Green
    } else {
        Write-Host "  $($phantomsHere.Count) phantom symbol(s):" -ForegroundColor Yellow
        foreach ($p in $phantomsHere) {
            Write-Host "    - [$($p.Category)] $($p.Symbol)" -ForegroundColor Yellow
        }
        $totalPhantoms += $phantomsHere.Count
        [void]$report.Add(@{ Path = $promptPath; Phantoms = @($phantomsHere) })
    }

    # AD-685b: Display unresolved (skipped) entries informationally; these
    # do NOT contribute to phantom count and do NOT affect exit code.
    if ($unresolvedHere.Count -gt 0) {
        Write-Host "  Skipped (unresolved class):" -ForegroundColor DarkGray
        foreach ($u in $unresolvedHere) {
            Write-Host "    ~ [$($u.reason)] $($u.call_site) (obj=$($u.obj))" -ForegroundColor DarkGray
        }
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
