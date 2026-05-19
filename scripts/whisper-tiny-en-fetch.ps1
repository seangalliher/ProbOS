# scripts/whisper-tiny-en-fetch.ps1
# Download the whisper.cpp WASM glue + tiny.en GGML model (~75 MB) into
# data/whisper/. The runtime never touches these files directly — only
# the browser-side AD-705a whisperStt module loads them via fetch.
# The artifacts are operator-pullable; bytes are never committed to the
# repo (.gitignore rule covers data/* — same as data/silero-vad/).
#
# Source: https://github.com/ggerganov/whisper.cpp (MIT)
# Model:  ggml-tiny.en.bin (Hugging Face mirror of OpenAI Whisper weights, MIT).
# Usage:
#   ./scripts/whisper-tiny-en-fetch.ps1
#   ./scripts/whisper-tiny-en-fetch.ps1 -Force        # re-download even if present
#   ./scripts/whisper-tiny-en-fetch.ps1 -ModelOnly    # skip the WASM glue
#
param(
    [switch]$Force,
    [switch]$ModelOnly,
    [string]$DestDir = "data/whisper"
)

$ErrorActionPreference = "Stop"

# Pinned to a specific tag so the SHA below is stable. Update both the
# URL and the expected SHA together. AD-721b-3 v1 = tiny.en only.
$ModelUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/v1.5.4/ggml-tiny.en.bin"
$ModelName = "ggml-tiny.en.bin"
$ModelExpectedSha256 = "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f"

# WASM glue artifacts. whisper.cpp emits UMD-style glue (NOT ESM); see
# upstream examples/whisper.wasm/main.js. Operators who only need the
# model (e.g. Python-side path resolution) can pass -ModelOnly.
$WasmJsUrl = "https://whisper.ggerganov.com/whisper.js"
$WasmBinUrl = "https://whisper.ggerganov.com/whisper.wasm"
$WasmJsName = "whisper.js"
$WasmBinName = "whisper.wasm"

if (-not (Test-Path $DestDir)) {
    New-Item -ItemType Directory -Path $DestDir | Out-Null
}

function Fetch-Artifact($url, $target, $expectedSha = $null) {
    if ((Test-Path $target) -and (-not $Force)) {
        Write-Host "Already present at $target (use -Force to redownload)"
        return
    }
    Write-Host "Fetching $url ..."
    Invoke-WebRequest -Uri $url -OutFile $target -UseBasicParsing
    $size = (Get-Item $target).Length
    Write-Host ("Downloaded {0} ({1:N0} bytes)" -f $target, $size)
    if ($expectedSha) {
        $actual = (Get-FileHash $target -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $expectedSha.ToLower()) {
            Remove-Item $target -Force
            throw "SHA-256 mismatch for $target. Expected $expectedSha, got $actual. File removed."
        }
        Write-Host "SHA-256 verified: $actual"
    }
}

# Model is always pulled.
Fetch-Artifact $ModelUrl (Join-Path $DestDir $ModelName) $ModelExpectedSha256

if (-not $ModelOnly) {
    # WASM glue: not SHA-pinned in v1 (upstream serves rolling builds);
    # forward marker AD-721b-3-1 to mirror a pinned release artifact set.
    Fetch-Artifact $WasmJsUrl (Join-Path $DestDir $WasmJsName)
    Fetch-Artifact $WasmBinUrl (Join-Path $DestDir $WasmBinName)
}

Write-Host ""
Write-Host "whisper.cpp WASM: MIT (https://github.com/ggerganov/whisper.cpp/blob/master/LICENSE)"
Write-Host "Whisper tiny.en weights: MIT (https://github.com/openai/whisper/blob/main/LICENSE)"
