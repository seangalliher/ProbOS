# AD-721b-1a — ffmpeg-backed audio format conversion for client-captured audio

**Status:** Draft v1.
**Closes:** #663.
**Dependencies:** AD-721b-1 (Wave 155 — rhubarb backend). BF-280 (subprocess pattern). BF-282 (Windows binary-stdout trap). BF-292 (Wave 165 — honest-degrade boundary that this AD completes).
**Estimated tests:** +8 pytest. **0 new pip/npm deps.**

---

## Problem

BF-292 (Wave 165, shipped) added an honest-degrade boundary in `generate_visemes` at `src/probos/avatars/rhubarb_backend.py:209` that rejects non-WAV/OGG audio:

```python
_SUPPORTED_SUFFIXES = {".wav", ".ogg"}
if audio_path.suffix.lower() not in _SUPPORTED_SUFFIXES:
    logger.info("AD-721b-1: rhubarb skipped — unsupported audio format ...")
    return []
```

This stopped the WARNING noise from every browser-captured `audio/webm` clip (Chrome MediaRecorder default), but it means client-captured audio gets the heuristic lip-sync path instead of the rhubarb-quality phonetic alignment path.

## Solution

When `generate_visemes` receives a non-WAV/OGG file, transcode to 16-bit mono 22050 Hz WAV via operator-installed ffmpeg (BF-280: `subprocess.Popen` + thread executor; BF-282: tempfile output, never stdout). Feed converted WAV to rhubarb. If ffmpeg is missing or conversion fails, honest-degrade to `[]` exactly as today (BF-292 contract preserved).

ffmpeg lives at `tools/ffmpeg/ffmpeg.exe` (Windows) or `tools/ffmpeg/ffmpeg` (POSIX). `/tools/` is gitignored — same pattern as piper and rhubarb. License posture: ffmpeg is LGPL-2.1+ / GPL-2+; operator-provided binary avoids any distribution-side license concern.

### Section 1 — Config

`src/probos/config.py` `LipSyncConfig` — add one field:

```python
ffmpeg_binary_path: str = "tools/ffmpeg/ffmpeg"
"""Optional ffmpeg binary for converting non-WAV/OGG audio to rhubarb's
required format. When the binary is missing, generate_visemes honest-
degrades to the heuristic lip-sync path (BF-292 contract preserved).
Operator places the binary; the repo never ships it (gitignored under
``/tools/``). License posture: ffmpeg is LGPL-2.1+ / GPL-2+; the
operator-provided binary keeps ProbOS distribution clean."""
```

NO new `enabled` flag — the path is enabled-when-present, mirroring the rhubarb binary discovery pattern. If `ffmpeg_binary_path` resolves to a missing file, the conversion path is silently skipped.

### Section 2 — `_resolve_ffmpeg_binary` helper

In `src/probos/avatars/rhubarb_backend.py`, add a sibling to `_resolve_binary_path` (which is rhubarb-specific). The new helper has the same Windows `.exe` suffix logic:

```python
def _resolve_ffmpeg_binary(configured: str) -> Path | None:
    """Resolve ``ffmpeg_binary_path`` configured value to an executable Path,
    or return None if missing. Auto-appends ``.exe`` on Windows. NEVER raises.
    Mirrors ``_resolve_binary_path`` (rhubarb) — separate function so the two
    binary discovery paths stay independently overridable in tests."""
```

Pure function — operates only on the configured string. Test-friendly.

### Section 3 — Conversion function

New async function in `rhubarb_backend.py`:

```python
async def _convert_to_wav(
    audio_path: Path,
    ffmpeg_binary: Path,
    *,
    timeout_seconds: float = 30.0,
) -> Path | None:
    """Convert any ffmpeg-supported input to 16-bit mono 22050 Hz WAV.

    Returns the temp file path on success, None on any failure. Caller is
    responsible for ``temp_path.unlink(missing_ok=True)`` in finally.
    Tier-2 throughout — never raises.
    """
```

Implementation contract:

1. Create `tempfile.NamedTemporaryFile(suffix=".wav", delete=False)`. Close immediately (we just need the path). Store path.
2. Build args: `[str(ffmpeg_binary), "-y", "-i", str(audio_path), "-ac", "1", "-ar", "22050", "-acodec", "pcm_s16le", str(temp_path)]`.
3. BF-280: `subprocess.Popen` with `stdout=subprocess.DEVNULL, stderr=subprocess.PIPE`. BF-282: NEVER capture binary on stdout — we wrote to a tempfile via `-y` argument.
4. `loop.run_in_executor(None, _run_sync)` with the Popen + `communicate(timeout=timeout_seconds)` pattern from the existing rhubarb wrapper.
5. On `TimeoutExpired`: kill, wait, return None (after `temp_path.unlink(missing_ok=True)`).
6. On non-zero exit: log warning with stderr first 500 chars, return None (and unlink temp).
7. On success: verify temp file exists and is non-empty (defense in depth). Return temp_path.

### Section 4 — Wire into `generate_visemes`

Modify `generate_visemes` in `rhubarb_backend.py`. Before the `_SUPPORTED_SUFFIXES` check at line 209:

```python
_SUPPORTED_SUFFIXES = {".wav", ".ogg"}
converted_temp: Path | None = None
if audio_path.suffix.lower() not in _SUPPORTED_SUFFIXES:
    # AD-721b-1a: try ffmpeg conversion. If ffmpeg missing or fails,
    # fall through to BF-292's honest-degrade path.
    ffmpeg_cfg_path = getattr(...).ffmpeg_binary_path  # threaded from caller
    ffmpeg_binary = _resolve_ffmpeg_binary(ffmpeg_cfg_path) if ffmpeg_cfg_path else None
    if ffmpeg_binary is not None:
        converted_temp = await _convert_to_wav(audio_path, ffmpeg_binary)
    if converted_temp is None:
        logger.info("AD-721b-1: rhubarb skipped — unsupported format and ffmpeg unavailable")
        return []
    audio_path = converted_temp  # use the converted file for the rest of the function
```

Then at the very end of the function, in a try/finally wrapping the existing rhubarb execution:

```python
try:
    # ... existing rhubarb invocation ...
    return frames
finally:
    if converted_temp is not None:
        converted_temp.unlink(missing_ok=True)
```

Signature change: `generate_visemes(audio_path, binary_path, timeout_seconds=30.0)` adds an optional `ffmpeg_binary_path: str | None = None` keyword-only parameter. The router callsite (`src/probos/routers/avatars.py:70` and `:274`) is updated to pass `cfg.ffmpeg_binary_path`.

### Section 5 — Router callsite updates

`src/probos/routers/avatars.py` — TWO sites call `generate_visemes`:

1. Line ~70 (`generate_lipsync` endpoint).
2. Line ~274 (the TTS path that reuses `generate_visemes`).

Both add `ffmpeg_binary_path=lipsync_cfg.ffmpeg_binary_path` to the call. Use single `replace_string_in_file` per site (BF-274 — do not batch adjacent edits).

### Tests (`tests/test_ad721b_1a_ffmpeg_conversion.py`)

1. `test_resolve_ffmpeg_binary_missing_returns_none`.
2. `test_resolve_ffmpeg_binary_present_returns_path` — tmp_path with executable bit.
3. `test_resolve_ffmpeg_binary_windows_exe_fallback` — sys.platform monkey-patched, file with `.exe` suffix present.
4. `test_convert_to_wav_success_creates_tempfile` — stub the subprocess via `subprocess.Popen` monkey-patch returning a fake process that writes a small WAV to the output path.
5. `test_convert_to_wav_timeout_returns_none_and_cleans_up_tempfile` — `_run_sync` raises `TimeoutExpired`; assert no temp file leak.
6. `test_convert_to_wav_nonzero_exit_returns_none`.
7. `test_generate_visemes_webm_with_ffmpeg_converts_and_processes` — full integration with stubbed ffmpeg + stubbed rhubarb. Assert temp file unlinked in finally.
8. `test_generate_visemes_webm_without_ffmpeg_honest_degrades` — BF-292 contract preserved when ffmpeg path empty/missing.

Test pattern follows BF-286: subprocess shape mirrors production via stubbed `subprocess.Popen` that records args + returns a fake `Popen` object with `communicate()` and `returncode`. Real `LipSyncConfig()` fixture. tmp_path for binary path resolution.

## What This Does NOT Change

- BF-292 honest-degrade contract preserved — `generate_visemes` still returns `[]` on any failure.
- WAV/OGG fast-path unchanged — only non-WAV/OGG audio goes through the new conversion step.
- rhubarb behavior unchanged.
- No client-side WAV encoding (Chrome doesn't support WAV natively; out of scope).
- No real-time streaming viseme generation.
- Stretching the supported suffix set in rhubarb is NOT done — rhubarb still gets only WAV/OGG; ffmpeg bridges everything else.

## Tracking

- `PROGRESS.md` — Wave 166 entry.
- `docs/development/roadmap.md` — close #663.
- `DECISIONS.md` — append AD-721b-1a with the LGPL ffmpeg license posture (operator-provided, gitignored, identical to piper/rhubarb).

Forward markers (TECHNICAL triggers):
- AD-721b-1a-1 — Optional ffmpeg health probe + degraded-but-known status (parallel to rhubarb `is_available`). Trigger: operator-reported ffmpeg version-mismatch issues.
- AD-721b-1a-2 — Pre-convert pool (warm-tempfile reuse) for high-throughput sessions. Trigger: ≥10 conversions/minute observed in production.
- AD-721b-1a-3 — Browser-side AudioContext WAV encoder (eliminates server-side conversion). Trigger: client-side bundle size budget allows the recorder.js absorption.

## Acceptance Criteria

- 8 tests green under serial + parallel gates.
- Full pytest gate: previous +N → ≥+8.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- BF-274 single-replace for adjacent edits in both router callsites and `generate_visemes`.
- BF-280 compliance: subprocess.Popen + thread executor, NO `asyncio.create_subprocess_exec`.
- BF-282 compliance: tempfile output via ffmpeg's `-y output.wav` arg, NEVER capture binary stdout.
- No new pip/npm deps.

## Verified Against Codebase (2026-05-16)

```
grep -n "_SUPPORTED_SUFFIXES = " src/probos/avatars/rhubarb_backend.py
  209:    _SUPPORTED_SUFFIXES = {".wav", ".ogg"}

grep -n "def _resolve_binary_path" src/probos/avatars/rhubarb_backend.py
  107: def _resolve_binary_path(configured: str) -> Path | None:

grep -n "def _run_sync" src/probos/avatars/rhubarb_backend.py
  155:        def _probe_sync() -> tuple[int, bytes, bytes]:
  244:        def _run_sync() -> tuple[int, bytes, bytes]:

grep -n "class LipSyncConfig" src/probos/config.py
  1548: class LipSyncConfig(BaseModel):

grep -n "binary_path: str = " src/probos/config.py
  1567:     binary_path: str = "tools/rhubarb/rhubarb"
  1604:     binary_path: str = "tools/piper/piper"

grep -n "generate_visemes" src/probos/routers/avatars.py
  68:    from probos.avatars.rhubarb_backend import generate_visemes
  70:    frames = await generate_visemes(
  272:        from probos.avatars.rhubarb_backend import generate_visemes
  274:        frames = await generate_visemes(
```

ffmpeg LGPL-2.1+/GPL-2+ posture confirmed in user memory at `/memories/probos-architect-learnings.md` ("License hygiene" + "Windows binary-on-stdout corrupts data" BF-282 lesson).
