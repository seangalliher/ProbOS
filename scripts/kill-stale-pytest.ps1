# Kill hung pytest workers WITHOUT touching the live ProbOS runtime.
#
# Background: a previous Builder cleanup pattern was
#     Get-Process python | Where-Object { $_.Path -like "*ProbOS*" } | Stop-Process -Force
# That kills EVERY python.exe under d:\ProbOS\, including the live runtime
# started by `probos serve --interactive`. Use this script instead.
#
# Strategy:
#   1. Read data/probos.pid (and data/node-*/probos.pid) — these are runtime PIDs.
#      Never kill them.
#   2. Match processes by CommandLine containing "pytest" (so we don't kill
#      arbitrary python.exe — only ones that were launched as pytest).
#   3. Use -Force only after the PID-exclusion check.

[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
Push-Location $repoRoot

try {
    # Collect PIDs to protect (live ProbOS runtimes).
    $protectedPids = @()
    $pidFiles = @(
        (Join-Path $repoRoot "data\probos.pid"),
        (Join-Path $repoRoot "data\node-1\probos.pid"),
        (Join-Path $repoRoot "data\node-2\probos.pid")
    )
    foreach ($pf in $pidFiles) {
        if (Test-Path $pf) {
            try {
                $val = [int]((Get-Content $pf -Raw).Trim())
                if ($val -gt 0) { $protectedPids += $val }
            } catch {}
        }
    }
    if ($protectedPids.Count -gt 0) {
        Write-Host "Protecting live ProbOS PIDs: $($protectedPids -join ', ')"
    } else {
        Write-Host "No live ProbOS pidfile found — proceeding with pytest-only sweep."
    }

    # Find pytest processes by CommandLine. Use Win32_Process for CommandLine.
    $candidates = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.Name -eq "python.exe" -or $_.Name -eq "pytest.exe") -and
        ($_.CommandLine -match "pytest")
    }

    if (-not $candidates) {
        Write-Host "No pytest processes found."
        return
    }

    foreach ($p in $candidates) {
        $procId = [int]$p.ProcessId
        if ($protectedPids -contains $procId) {
            Write-Host "SKIP protected pid=$procId (live ProbOS): $($p.CommandLine)"
            continue
        }
        if ($DryRun) {
            Write-Host "DRY-RUN would kill pid=$procId : $($p.CommandLine)"
        } else {
            Write-Host "KILL pid=$procId : $($p.CommandLine)"
            try {
                Stop-Process -Id $procId -Force -ErrorAction Stop
            } catch {
                Write-Warning "Failed to stop pid=${procId}: $_"
            }
        }
    }
} finally {
    Pop-Location
}
