# scripts/piper-voice-fetch.ps1
# Download medium- and high-quality English Piper voices into
# tools/piper/voices/. Each voice consists of a paired ``.onnx`` model
# and ``.onnx.json`` config; the runtime needs BOTH to be present.
#
# Source: https://huggingface.co/rhasspy/piper-voices (MIT)
# Usage:
#   ./scripts/piper-voice-fetch.ps1
#   ./scripts/piper-voice-fetch.ps1 -Force   # re-download even if present
#
param(
    [switch]$Force,
    [string]$DestDir = "tools/piper/voices"
)

$ErrorActionPreference = "Stop"
$base = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Voice catalog: (lang_dir, region_dir, voice, quality). Sourced from
# https://github.com/rhasspy/piper/blob/master/VOICES.md and the HF repo
# tree as of 2026-05-15. All Apache 2.0 / MIT-compatible.
$voices = @(
    # en_US medium
    @{ lang = "en"; region = "en_US"; voice = "amy";          quality = "medium" }
    @{ lang = "en"; region = "en_US"; voice = "lessac";       quality = "medium" }
    @{ lang = "en"; region = "en_US"; voice = "ryan";         quality = "medium" }
    @{ lang = "en"; region = "en_US"; voice = "libritts_r";   quality = "medium" }
    @{ lang = "en"; region = "en_US"; voice = "kathleen";     quality = "low"    }  # only low ships
    @{ lang = "en"; region = "en_US"; voice = "kristin";      quality = "medium" }
    @{ lang = "en"; region = "en_US"; voice = "kusal";        quality = "medium" }
    @{ lang = "en"; region = "en_US"; voice = "hfc_female";   quality = "medium" }
    @{ lang = "en"; region = "en_US"; voice = "hfc_male";     quality = "medium" }
    @{ lang = "en"; region = "en_US"; voice = "joe";          quality = "medium" }
    @{ lang = "en"; region = "en_US"; voice = "norman";       quality = "medium" }
    @{ lang = "en"; region = "en_US"; voice = "arctic";       quality = "medium" }
    @{ lang = "en"; region = "en_US"; voice = "bryce";        quality = "medium" }
    @{ lang = "en"; region = "en_US"; voice = "danny";        quality = "low"    }  # only low ships
    @{ lang = "en"; region = "en_US"; voice = "john";         quality = "medium" }
    # en_US high
    @{ lang = "en"; region = "en_US"; voice = "lessac";       quality = "high"   }
    @{ lang = "en"; region = "en_US"; voice = "ryan";         quality = "high"   }
    @{ lang = "en"; region = "en_US"; voice = "libritts";     quality = "high"   }
    # en_GB medium
    @{ lang = "en"; region = "en_GB"; voice = "alan";         quality = "medium" }
    @{ lang = "en"; region = "en_GB"; voice = "alba";         quality = "medium" }
    @{ lang = "en"; region = "en_GB"; voice = "aru";          quality = "medium" }
    @{ lang = "en"; region = "en_GB"; voice = "cori";         quality = "medium" }
    @{ lang = "en"; region = "en_GB"; voice = "jenny_dioco";  quality = "medium" }
    @{ lang = "en"; region = "en_GB"; voice = "northern_english_male"; quality = "medium" }
    @{ lang = "en"; region = "en_GB"; voice = "semaine";      quality = "medium" }
    @{ lang = "en"; region = "en_GB"; voice = "southern_english_female"; quality = "low" }  # only low ships
    @{ lang = "en"; region = "en_GB"; voice = "vctk";         quality = "medium" }
    # en_GB high
    @{ lang = "en"; region = "en_GB"; voice = "alan";         quality = "high"   }
    @{ lang = "en"; region = "en_GB"; voice = "cori";         quality = "high"   }
)

if (-not (Test-Path $DestDir)) {
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
}

$ok = 0
$skipped = 0
$failed = 0

foreach ($v in $voices) {
    $name = "$($v.region)-$($v.voice)-$($v.quality)"
    $onnx = Join-Path $DestDir "$name.onnx"
    $cfg  = Join-Path $DestDir "$name.onnx.json"

    if (-not $Force -and (Test-Path $onnx) -and (Test-Path $cfg)) {
        Write-Host "[skip] $name (already present)" -ForegroundColor DarkGray
        $skipped++
        continue
    }

    $urlOnnx = "$base/$($v.lang)/$($v.region)/$($v.voice)/$($v.quality)/$name.onnx"
    $urlCfg  = "$base/$($v.lang)/$($v.region)/$($v.voice)/$($v.quality)/$name.onnx.json"

    Write-Host "[get ] $name ..." -ForegroundColor Cyan
    try {
        Invoke-WebRequest -Uri $urlOnnx -OutFile $onnx -UseBasicParsing -ErrorAction Stop
        Invoke-WebRequest -Uri $urlCfg  -OutFile $cfg  -UseBasicParsing -ErrorAction Stop
        $sz = [math]::Round((Get-Item $onnx).Length / 1MB, 1)
        Write-Host "[ ok ] $name (${sz} MB)" -ForegroundColor Green
        $ok++
    } catch {
        Write-Host "[fail] $name -- $($_.Exception.Message)" -ForegroundColor Yellow
        if (Test-Path $onnx) { Remove-Item $onnx -Force }
        if (Test-Path $cfg)  { Remove-Item $cfg  -Force }
        $failed++
    }
}

Write-Host ""
Write-Host "Summary: ok=$ok skipped=$skipped failed=$failed" -ForegroundColor White
Write-Host "Voices available at: $((Resolve-Path $DestDir).Path)" -ForegroundColor White
