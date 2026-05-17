# AD-721e: Fetch CC0 skeletal animation clips for VRM avatars.
#
# Operator runs this once. Clips land in data/avatars/animations/ (gitignored).
# Default source: Quaternius "Ultimate Animated Character Pack" (CC0).
# Backup: KayKit Character Animations (CC0). Mixamo is REJECTED per
# AD-721i-1 license whitelist -- DO NOT modify this script to point at it.
#
# Mirrors scripts/piper-voice-fetch.ps1 (Wave 165 / BF-291) and
# scripts/avatar-assets-fetch.ps1 (AD-721g Wave 167).

[CmdletBinding()]
param(
    [string]$DestDir = "data/avatars/animations",
    [switch]$SkipDownload  # when set, only writes the manifest skeleton
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# License whitelist guard. If this list ever needs to grow, update the
# server-side AD-721i-1 whitelist FIRST (src/probos/avatars/asset_manifest.py
# `_ALLOWED_LICENSES`). Never absorb anything outside this set.
# ---------------------------------------------------------------------------
$AllowedLicenses = @("CC0", "CC0-1.0", "MIT", "Apache-2.0", "BSD-3-Clause", "CC-BY-4.0", "MPL-2.0")

# ---------------------------------------------------------------------------
# Clip catalog. Operator-customizable; the v1 default is the four basic body
# states that AD-721e CrewVRM consumes.
# ---------------------------------------------------------------------------
$Clips = @(
    @{ name = "idle";      file = "idle.glb";      source = "https://quaternius.com/packs/ultimateanimatedcharacter.html"; license = "CC0" },
    @{ name = "talking";   file = "talking.glb";   source = "https://quaternius.com/packs/ultimateanimatedcharacter.html"; license = "CC0" },
    @{ name = "listening"; file = "listening.glb"; source = "https://quaternius.com/packs/ultimateanimatedcharacter.html"; license = "CC0" },
    @{ name = "thinking";  file = "thinking.glb";  source = "https://quaternius.com/packs/ultimateanimatedcharacter.html"; license = "CC0" }
)

# ---------------------------------------------------------------------------
# Prepare destination.
# ---------------------------------------------------------------------------
if (-not (Test-Path $DestDir)) {
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
    Write-Host "[AD-721e] created $DestDir"
}

# ---------------------------------------------------------------------------
# License gate.
# ---------------------------------------------------------------------------
foreach ($clip in $Clips) {
    if (-not ($AllowedLicenses -contains $clip.license)) {
        throw "AD-721i-1 license whitelist violation: clip '$($clip.name)' license '$($clip.license)' is not on the allowed list"
    }
}

# ---------------------------------------------------------------------------
# Manifest writer. Operator extracts the source pack into $DestDir manually
# (Quaternius ships a zip with multiple .glb files); this script writes the
# manifest.json with SHA-256 entries for files present.
# ---------------------------------------------------------------------------
$ManifestPath = Join-Path $DestDir "manifest.json"
$entries = @()
foreach ($clip in $Clips) {
    $filePath = Join-Path $DestDir $clip.file
    if (Test-Path $filePath) {
        $hash = (Get-FileHash $filePath -Algorithm SHA256).Hash.ToLower()
        $entries += @{
            name        = $clip.name
            file        = $clip.file
            sha256      = $hash
            license     = $clip.license
            source_url  = $clip.source
            duration_s  = 0.0
        }
        Write-Host "[AD-721e] registered $($clip.name) (sha=$($hash.Substring(0,8))...)"
    } else {
        Write-Host "[AD-721e] missing $($clip.file) -- operator: extract Quaternius pack into $DestDir then re-run"
    }
}

$manifestJson = @{ clips = $entries } | ConvertTo-Json -Depth 5
Set-Content -Path $ManifestPath -Value $manifestJson -Encoding utf8
Write-Host "[AD-721e] wrote manifest -> $ManifestPath ($($entries.Count) clip(s))"

Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Download Quaternius 'Ultimate Animated Character Pack' from https://quaternius.com"
Write-Host "  2. Extract idle.glb / talking.glb / listening.glb / thinking.glb into $DestDir"
Write-Host "  3. Re-run this script to write the manifest with SHA-256 entries"
Write-Host "  4. Set avatars.animations_enabled=true in config/system.yaml"
Write-Host "  5. Restart probos serve --interactive"
