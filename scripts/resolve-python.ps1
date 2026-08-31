function Resolve-ProbOSPython {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $root = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
    $candidates = [System.Collections.Generic.List[string]]::new()

    if ($env:PROBOS_PYTHON) {
        if (-not (Test-Path -LiteralPath $env:PROBOS_PYTHON -PathType Leaf)) {
            throw "PROBOS_PYTHON does not name an existing file: $env:PROBOS_PYTHON"
        }
        return (Resolve-Path -LiteralPath $env:PROBOS_PYTHON).Path
    }
    $candidates.Add((Join-Path $root '.venv/Scripts/python.exe'))
    $candidates.Add((Join-Path $root '.venv/bin/python'))

    $commonRaw = (& git -C $root rev-parse --git-common-dir 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $commonRaw) {
        throw "Unable to resolve Git common directory for Python selection: $root"
    }
    $commonDir = if ([IO.Path]::IsPathRooted($commonRaw)) {
        $commonRaw
    } else {
        Join-Path $root $commonRaw
    }
    $commonRoot = Split-Path -Parent (
        Resolve-Path -LiteralPath $commonDir -ErrorAction Stop
    ).Path
    $candidates.Add((Join-Path $commonRoot '.venv/Scripts/python.exe'))
    $candidates.Add((Join-Path $commonRoot '.venv/bin/python'))

    $seen = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($candidate in $candidates) {
        if (-not $candidate -or -not $seen.Add($candidate)) {
            continue
        }
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw (
        "No ProbOS Python interpreter found. Set PROBOS_PYTHON to an existing " +
        "interpreter or create .venv in the worktree/common repository root. " +
        "Checked: " + ($candidates -join ', ')
    )
}