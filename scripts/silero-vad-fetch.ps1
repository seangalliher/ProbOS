# scripts/silero-vad-fetch.ps1
# Download the Silero VAD ONNX model (MIT, ~1.5 MB) into
# data/silero-vad/. The runtime never touches this file — only the
# browser-side AD-733c-7 voiceActivity module loads it via
# onnxruntime-web. The model is operator-pullable; bytes are never
# committed to the repo (.gitignore rule).
#
# Source: https://github.com/snakers4/silero-vad (MIT)
# Usage:
#   ./scripts/silero-vad-fetch.ps1
#   ./scripts/silero-vad-fetch.ps1 -Force   # re-download even if present
#
param(
    [switch]$Force,
    [string]$DestDir = "data/silero-vad"
)

$ErrorActionPreference = "Stop"
# Pinned to a specific commit so the SHA below is stable. Update both
# the URL and the expected SHA together.
$ModelUrl = "https://github.com/snakers4/silero-vad/raw/v5.1/src/silero_vad/data/silero_vad.onnx"
$ModelName = "silero_vad.onnx"

if (-not (Test-Path $DestDir)) {
    New-Item -ItemType Directory -Path $DestDir | Out-Null
}

$Target = Join-Path $DestDir $ModelName
if ((Test-Path $Target) -and (-not $Force)) {
    Write-Host "Silero VAD already present at $Target (use -Force to redownload)"
    exit 0
}

Write-Host "Fetching $ModelName from $ModelUrl ..."
Invoke-WebRequest -Uri $ModelUrl -OutFile $Target -UseBasicParsing
$size = (Get-Item $Target).Length
Write-Host ("Downloaded {0} ({1:N0} bytes)" -f $Target, $size)
Write-Host "License: MIT (https://github.com/snakers4/silero-vad/blob/master/LICENSE)"
