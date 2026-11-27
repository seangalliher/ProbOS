# scripts/kokoro-fetch.ps1
# AD-738g (#1662) S1: install the local Kokoro voice into tools/kokoro/ (gitignored).
#
#   1. A Python 3.12 venv at tools/kokoro/venv made by uv, holding kokoro-onnx==0.6.1
#      (MIT) and what it pulls: onnxruntime (MIT), numpy, phonemizer (GPL-3.0-or-later)
#      and espeakng-loader (bundles espeak-ng, GPL-3.0-or-later). This venv is separate
#      from ProbOS's and cannot import probos; ProbOS never imports these packages.
#   2. The Kokoro-82M model files (Apache-2.0 weights) from the kokoro-onnx release
#      model-files-v1.0, each checked for its size and SHA-256 (the release publishes no
#      digests; the pins are the LFS ids of the byte-identical files on
#      huggingface.co/fastrtc/kokoro-onnx, and matched a download on 2026-11-27).
#   3. One test sentence spoken through scripts/kokoro_worker.py, the worker ProbOS runs.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\kokoro-fetch.ps1 -Force   # rebuild the venv, re-download
#
param(
    [switch]$Force,
    [string]$DestDir = "tools/kokoro"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest is many times slower with its progress bar

$Root = Split-Path -Parent $PSScriptRoot
if (-not [System.IO.Path]::IsPathRooted($DestDir)) { $DestDir = Join-Path $Root $DestDir }
$Pin = "kokoro-onnx==0.6.1"
$Base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
$Files = @(
    @{ name = "kokoro-v1.0.onnx"; size = 325532387; sha256 = "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5" }
    @{ name = "voices-v1.0.bin";  size = 28214398;  sha256 = "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d" }
)

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required (https://docs.astral.sh/uv/). Install it, then run this script again."
}
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

# 1. The venv and the pinned runtime.
$Venv = Join-Path $DestDir "venv"
$Python = Join-Path $Venv "Scripts\python.exe"
if ($Force -and (Test-Path $Venv)) { Remove-Item -Recurse -Force $Venv }
if (-not (Test-Path $Python)) {
    & uv venv --python 3.12 $Venv
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed (exit $LASTEXITCODE)" }
}
& uv pip install --python $Python $Pin
if ($LASTEXITCODE -ne 0) { throw "uv pip install $Pin failed (exit $LASTEXITCODE)" }

# 2. The model files, size- and hash-checked; a mismatch deletes the download and stops.
foreach ($f in $Files) {
    $target = Join-Path $DestDir $f.name
    if (-not $Force -and (Test-Path $target) -and ((Get-FileHash $target -Algorithm SHA256).Hash.ToLower() -eq $f.sha256)) {
        Write-Host "[skip] $($f.name) (present, SHA-256 verified)" -ForegroundColor DarkGray
        continue
    }
    $part = "$target.part"
    Write-Host "[get ] $($f.name) ..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri "$Base/$($f.name)" -OutFile $part -UseBasicParsing
    $size = (Get-Item $part).Length
    $actual = (Get-FileHash $part -Algorithm SHA256).Hash.ToLower()
    if ($size -ne $f.size -or $actual -ne $f.sha256) {
        Remove-Item $part -Force
        throw "Mismatch for $($f.name): expected $($f.size) bytes, SHA-256 $($f.sha256); got $size bytes, $actual. File removed."
    }
    Move-Item -Force $part $target
    Write-Host "[ ok ] $($f.name) (SHA-256 verified: $actual)" -ForegroundColor Green
}

# 3. The boundary and one spoken line through the real worker.
# Windows PowerShell 5.1 turns a redirected native stderr line into an error record, which
# "Stop" would make terminating; the expected ImportError traceback must not end the script.
$Previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Python -I -c "import probos" 2>$null
$Importable = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $Previous
if ($Importable) { throw "The Kokoro venv can import probos; it must not (licence boundary)." }
Write-Host "[ ok ] the Kokoro venv cannot import probos" -ForegroundColor Green

$Model = Join-Path $DestDir "kokoro-v1.0.onnx"
$Voices = Join-Path $DestDir "voices-v1.0.bin"
$Worker = Join-Path $Root "scripts\kokoro_worker.py"
$Probe = Join-Path $DestDir "fetch-check.wav"
if (Test-Path $Probe) { Remove-Item $Probe -Force }
# Windows PowerShell 5.1 pipes text to a native program as ASCII ($OutputEncoding), so a
# non-ASCII destination would reach the worker as '?': escape each non-ASCII UTF-16 unit as
# \uXXXX, which the worker's json.loads decodes. The worker answers in UTF-8; the console
# decodes it as UTF-8 for the comparison and gets its own encoding back afterwards.
$ProbeJson = [regex]::Replace((ConvertTo-Json $Probe), '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
$Line = '{"text": "Kokoro is ready, Captain.", "output_file": ' + $ProbeJson + ', "voice": "af_heart", "speed": 1.0}'
$ConsoleEncoding = [Console]::OutputEncoding
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { Write-Host "[warn] cannot set the console encoding; a non-ASCII path may fail the comparison" -ForegroundColor Yellow }
try {
    $Answer = $Line | & $Python -I $Worker --model $Model --voices $Voices --threads 4 --default-voice af_heart
    $Exit = $LASTEXITCODE
} finally {
    try { [Console]::OutputEncoding = $ConsoleEncoding } catch { }
}
if ($Exit -ne 0 -or -not (Test-Path $Probe) -or "$Answer".Trim() -ne $Probe) {
    throw "The Kokoro worker did not speak the test line (exit $Exit, answer '$Answer'); its messages are above."
}
$Bytes = (Get-Item $Probe).Length
Remove-Item $Probe -Force
Write-Host "[ ok ] the Kokoro worker spoke the test line ($Bytes bytes of 24 kHz WAV)" -ForegroundColor Green
Write-Host ""
Write-Host "Kokoro is installed at: $DestDir" -ForegroundColor White
Write-Host "Set tts.backend: kokoro and tts.sentence_pipelining_enabled: true in config/system.yaml, then restart." -ForegroundColor White
