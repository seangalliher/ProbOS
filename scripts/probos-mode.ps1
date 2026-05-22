# probos-mode.ps1 — flip ProbOS between OSS-only and overlay-enabled modes.
#
# ProbOS supports an overlay-package model: any third-party Python
# package that declares an entry point in the ``probos.extensions``
# group is auto-loaded at runtime boot (see AD-697). This script does
# NOT install or uninstall any overlay package — instead it toggles the
# PROBOS_DISABLE_OVERLAY env var in the current shell so you can flip
# between modes without venv churn. Overlay packages stay installed;
# the runtime simply skips discovery when the bypass is set.
#
# Usage (dot-source so env vars persist in your shell):
#     . scripts/probos-mode.ps1 oss       # OSS-only (sets PROBOS_DISABLE_OVERLAY=1)
#     . scripts/probos-mode.ps1 overlay   # Overlay active (clears the var)
#     . scripts/probos-mode.ps1 status    # Show current mode + entry-point summary
#
# To install your overlay package, run the usual pip install in your
# venv — for example:
#     d:\ProbOS\.venv\Scripts\python.exe -m pip install -e <path-to-your-overlay>
#
# After flipping modes, restart ``probos serve`` — overlay discovery
# runs once at boot.

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('oss', 'overlay', 'status', 'help')]
    [string]$Mode = 'status'
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$pyExe = Join-Path $repoRoot '.venv\Scripts\python.exe'

function Get-EntryPointSummary {
    if (-not (Test-Path $pyExe)) { return @() }
    $script = @'
import importlib.metadata as m
try:
    eps = list(m.entry_points(group="probos.extensions"))
except TypeError:
    eps = list(m.entry_points().get("probos.extensions", []))
for ep in eps:
    print(f"{ep.name}\t{ep.value}")
'@
    $out = & $pyExe -c $script 2>$null
    if (-not $out) { return @() }
    return $out -split "`r?`n" | Where-Object { $_ }
}

function Show-Status {
    $bypass = [Environment]::GetEnvironmentVariable('PROBOS_DISABLE_OVERLAY', 'Process')
    $eps = Get-EntryPointSummary
    Write-Host ""
    Write-Host "ProbOS overlay status" -ForegroundColor Cyan
    Write-Host ("  PROBOS_DISABLE_OVERLAY (session): {0}" -f ($bypass | ForEach-Object { if ($_) { $_ } else { '<unset>' } }))
    Write-Host ("  Registered entry points:         {0}" -f $eps.Count)
    foreach ($ep in $eps) { Write-Host "    - $ep" }

    if ($eps.Count -eq 0) {
        Write-Host "  Effective mode:                  OSS-only (no overlay packages installed)" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  To enable overlay support, install a package that declares an entry"
        Write-Host "  point in the 'probos.extensions' group, e.g.:"
        Write-Host "    $pyExe -m pip install -e <path-to-your-overlay>"
        return
    }

    $bypassActive = $bypass -and ($bypass.ToLower() -notin @('0', 'false', 'no', ''))
    if ($bypassActive) {
        Write-Host "  Effective mode:                  OSS-only (overlay installed but bypassed)" -ForegroundColor Yellow
    }
    else {
        Write-Host "  Effective mode:                  OVERLAY ACTIVE" -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "  Flip with:  . scripts/probos-mode.ps1 oss   |   . scripts/probos-mode.ps1 overlay"
    Write-Host "  Restart 'probos serve' after flipping."
}

switch ($Mode) {
    'oss' {
        $env:PROBOS_DISABLE_OVERLAY = '1'
        Write-Host "PROBOS_DISABLE_OVERLAY=1 set in this shell - overlay discovery will be skipped." -ForegroundColor Yellow
        Write-Host "Restart 'probos serve' for the change to take effect."
        Show-Status
    }
    'overlay' {
        if (Test-Path Env:\PROBOS_DISABLE_OVERLAY) { Remove-Item Env:\PROBOS_DISABLE_OVERLAY }
        Write-Host "PROBOS_DISABLE_OVERLAY cleared - any installed overlay packages will load on next boot." -ForegroundColor Green
        Write-Host "Restart 'probos serve' for the change to take effect."
        Show-Status
    }
    'status' { Show-Status }
    'help' {
        Get-Help $PSCommandPath -Detailed
    }
}
