# AD-721i-1: Avatar assets fetcher.
#
# Reads data/avatar-assets/MANIFEST.md, downloads APPROVED rows to
# data/avatar-assets/_<category>/<name>.<ext>, verifies SHA-256 against the
# manifest, and writes attribution to ATTRIBUTION.txt. Mirrors
# scripts/piper-voice-fetch.ps1 shape.
#
# License policy: CC0 / MIT / Apache-2.0 / BSD / CC-BY only. The manifest
# parser (probos.avatars.asset_manifest.validate_license) is the source of
# truth; this script trusts the disposition column and only downloads
# APPROVED rows.

[CmdletBinding()]
param(
    [string]$ManifestPath = "data/avatar-assets/MANIFEST.md",
    [string]$DestDir     = "data/avatar-assets"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ManifestPath)) {
    Write-Error "Manifest not found at $ManifestPath"
    exit 1
}

if (-not (Test-Path $DestDir)) {
    New-Item -ItemType Directory -Path $DestDir | Out-Null
}

$attributionPath = Join-Path $DestDir "ATTRIBUTION.txt"
"# AD-721i-1: generated attribution log. Do not edit by hand." | Out-File -FilePath $attributionPath -Encoding utf8

$content = Get-Content $ManifestPath -Raw
$currentCategory = $null
$approvedCount = 0
$failureCount = 0

foreach ($rawLine in ($content -split "`r?`n")) {
    $line = $rawLine.Trim()
    if (-not $line) { continue }

    if ($line.StartsWith("## ")) {
        $heading = $line.Substring(3).ToLower() -replace "\s*\(.*\)\s*$",""
        $heading = $heading.Trim()
        switch ($heading) {
            "base meshes"          { $currentCategory = "_base_meshes" }
            "hair styles"          { $currentCategory = "_hair" }
            "outfits"              { $currentCategory = "_outfits" }
            "materials"            { $currentCategory = "_materials" }
            "materials / textures" { $currentCategory = "_materials" }
            default                { $currentCategory = $null }
        }
        continue
    }

    if (-not $line.StartsWith("|") -or -not $currentCategory) { continue }

    $cells = ($line -split "\|") | ForEach-Object { $_.Trim() }
    # Leading/trailing empty cells from |...| split.
    $cells = $cells | Where-Object { $_ -ne "" }
    if ($cells.Count -ne 7) { continue }
    if ($cells[0].ToLower() -eq "name") { continue }
    if ($cells[0].StartsWith("---"))     { continue }

    $disposition = $cells[6]
    if ($disposition -ne "APPROVED") { continue }

    $name      = $cells[0]
    $url       = $cells[1]
    $sha256    = $cells[4]
    $attrib    = $cells[5]

    $targetDir = Join-Path $DestDir $currentCategory
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir | Out-Null
    }
    $ext      = [IO.Path]::GetExtension($url)
    if (-not $ext) { $ext = ".blend" }
    $target   = Join-Path $targetDir "$name$ext"

    Write-Host "Downloading $name from $url..."
    try {
        Invoke-WebRequest -Uri $url -OutFile $target -UseBasicParsing
    } catch {
        Write-Warning "Download failed for $name : $_"
        $failureCount++
        continue
    }

    # SHA-256 verification.
    if ($sha256 -and $sha256 -ne "TBD") {
        $actual = (Get-FileHash -Path $target -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $sha256.ToLower()) {
            Write-Warning "SHA-256 mismatch for $name (expected $sha256, got $actual); deleting"
            Remove-Item $target
            $failureCount++
            continue
        }
    }

    "$name | $attrib" | Out-File -FilePath $attributionPath -Append -Encoding utf8
    $approvedCount++
}

Write-Host ""
Write-Host "AD-721i-1: $approvedCount assets downloaded, $failureCount failures."
if ($approvedCount -eq 0) {
    Write-Host "(Manifest has no APPROVED rows yet - see data/avatar-assets/MANIFEST.md for the audit ledger.)"
}
if ($failureCount -gt 0) { exit 1 }
