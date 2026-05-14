# AD-738 — Server-streamed TTS via Piper (closes the lip-sync loop)

**Status:** Ready for Builder
**GH issue:** none — AD-721b-2.3 was a forward marker filed at Wave 155 close; no GH issue exists.
**Parent ADs:** AD-721b-1 (rhubarb backend, Wave 155), AD-721b-2 (browser real-audio capture, Wave 155). This prompt closes the load-bearing limitation of AD-721b-2: `SpeechSynthesisUtterance` cannot be routed through Web Audio in current browsers, so `MediaStreamDestination` records silence and rhubarb visemes never improve over the heuristic.
**Sibling forward markers (filed in this prompt):** AD-738a (per-agent voice selection), AD-738b (GPU-accelerated TTS backend evaluation — Kokoro / StyleTTS2), AD-738c (server-side voice modulation — apply AD-735 pitch/rate at synthesis time), AD-738d (TTS text caching layer).
**Wave:** 157
**Estimated tests:** ≥ 18 new (≥ 13 Python + ≥ 5 Vitest)

---

## Captain decisions baked in

1. **Operator-provided binary, MIT-licensed.** piper-tts (https://github.com/rhasspy/piper) is **MIT** — verified `gh api repos/rhasspy/piper/license` returns `"key": "mit"`. Top of the permissive preference list per Captain License hygiene rule. ProbOS provides the wrapper; operator drops the platform-specific binary at `tools/piper/piper.exe` (Windows) or `tools/piper/piper` (Linux/macOS). Binary is **never shipped** in the repo — `tools/` is already covered by `.gitignore` line 3 (`/tools/`).
2. **Voice model: `en_US-amy-medium` (MIT).** Verified via the Piper voice catalog (https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/medium — model card declares MIT). Operator drops `en_US-amy-medium.onnx` + `en_US-amy-medium.onnx.json` at `tools/piper/voices/`. Other Piper voices are licensed individually (some are CC-BY-4.0, a few are restricted) — the prompt locks the default to a verified-MIT voice. Operator who picks a different voice is responsible for the license check (forward marker AD-738a will surface a per-agent selector that displays the model license).
3. **Honest-degrade default.** Pydantic default `tts.backend = "browser"`. Today's behaviour preserved exactly: every `speakResponse()` call still uses `SpeechSynthesisUtterance`. Operator opts in by setting `tts.backend: "piper"` AND providing the binary AND the voice model. Any failure (binary missing, model missing, subprocess error, timeout) returns honest-degrade, the browser falls back to `SpeechSynthesisUtterance`. **Speech must NEVER stop because of a TTS failure.**
4. **AD-731 invariant.** Audio bytes go through `AttachmentStore` as content-addressable SHA-256 refs — never inline base64 in any RPC body, never inline in `IntentMessage.params`. The `/api/avatars/tts` response carries the `attachment_id` only; the browser fetches via the existing `GET /api/chat/attachments/{content_hash}` endpoint.
5. **Single round-trip from the browser per utterance.** `/api/avatars/tts` does synthesis + sha256 + AttachmentStore.write + rhubarb internally and returns audio + visemes together. The browser does not orchestrate two endpoints; the lip-sync timing problem (audio start vs. viseme load) collapses to "play `<audio>` element when both are in hand." A separate `GET /api/avatars/tts/status` endpoint exists for one-time feature detection (see Captain decision #9 + Section 4a) so the browser does NOT POST to `/api/avatars/tts` at all when the operator hasn't opted in.
6. **No new TTS abstraction in `src/probos/audio/` exists today.** Verified — `src/probos/audio/` does not exist; no `TTSBackend` Protocol, no `synthesize` callable, no `speak(` callable in `src/probos/`. **This AD creates the seam.** AD-705 (audio I/O abstraction) was speculative — there is no Python module to extend. The new module sits at `src/probos/audio/tts/`.
7. **Subprocess discipline mirrors AD-721b-1.** `asyncio.create_subprocess_exec` with absolute path, full stderr capture, configurable timeout (default 10s — typical synthesis is 0.3-1.5s for a sentence on CPU), Windows `.exe` auto-append. Never `shell=True`.
8. **Browser side stays small.** No new npm dep. The `<audio>` element is created in JS and never mounted to the DOM (HXI principle: visual surface is generative, not skeuomorphic — a hidden `<audio>` is fine). Per-agent `volume` (AD-735) and `rate` map to `<audio>.volume` and `<audio>.playbackRate` directly. **Pitch is deferred to forward marker AD-738c** (server-side modulation at synthesis time); a Web Audio biquad-shelf is non-trivial and produces audible artifacts compared to model-side modulation.

9. **Default-config zero-HTTP guarantee (revision 2026-05-13).** When `tts.backend = "browser"` (default), `speakResponse` MUST NOT POST to `/api/avatars/tts`. Wave 156 had ZERO HTTP per utterance; the load-bearing acceptance criterion ("operators who don't install Piper see ZERO behaviour change") forbids adding RTT on the default path. The browser fetches a one-time status probe (`GET /api/avatars/tts/status` → `{enabled, backend}`) on first `speakResponse` call, caches the result in module-level state in `voice.ts`, and skips the POST entirely when the cached backend is anything other than `"piper"`. The probe is the only HTTP that fires for a default-config operator across the whole HXI session — and only once.

---

## Problem (verified diagnostic baseline — 2026-05-13)

Wave 155 shipped `rhubarb-lip-sync` server-side (AD-721b-1) and the browser-side capture pipeline (AD-721b-2). Captain installed rhubarb 1.14.0, flipped `lipsync.backend: "rhubarb"`, restarted the runtime — and the visemes never improved over the v1 heuristic. Diagnosis:

- AD-721b-2's `captureUtteranceAudio` does the right thing: `AudioContext` + `MediaStreamDestination` + `MediaRecorder` against a `SpeechSynthesisUtterance`. The recorder's `ondataavailable` fires with **0 bytes** because Chromium / Firefox / Edge do **NOT** route `SpeechSynthesis` output through Web Audio (documented at `ui/src/audio/speechAmplitude.ts:1-7`).
- `captureUtteranceAudio` honest-degrades to `null`, the upload short-circuits, the hook returns `frames: []`, `CrewVRM` falls through to `buildHeuristicTrack` — the AD-721b v1 heuristic, exactly the state before Wave 155. The architecture worked; the substrate didn't.
- The honest engineering position recorded in AD-721b-2 was: "the day a browser ships routable SpeechSynthesis (or ProbOS adopts a server-streamed TTS path under a future AD), the capture path lights up automatically." That future AD is this one.

The fix is to make the **server** the source of audio bytes. When the server synthesizes, it has the WAV file before the browser does, so it can run rhubarb on the bytes directly and ship audio + visemes in one response. The browser plays the audio via `<audio>` (which IS controllable: `volume`, `playbackRate`, `muted`, `currentTime`) and feeds the visemes to `CrewVRM` via the existing `useLipSyncCapture` hook, extended with an injection setter.

**Today's path (AD-721b-2 era):**

```
speakResponse(text)
  → SpeechSynthesisUtterance fires onstart
  → useLipSyncCapture listener runs captureUtteranceAudio
  → MediaRecorder records 0 bytes → null
  → hook leaves frames=[], CrewVRM uses buildHeuristicTrack
```

**After AD-738 (when operator opts in):**

```
speakResponse(text, profile, agent_id)
  → POST /api/avatars/tts {text, agent_id}
  → server: PiperBackend.synthesize() → WAV bytes
  → server: sha256(bytes) + AttachmentStore.write(sha256, bytes, "audio/wav")
  → server: generate_visemes(path) → VisemeFrame[]
  → response: {audio_attachment_id, mime, visemes, duration_ms, backend: "piper"}
  → browser: fetch /api/chat/attachments/<sha>, play via <audio> element
  → browser: useLipSyncCapture.injectFrames(visemes) → CrewVRM consumes
```

**Honest-degrade chain (3 tiers, all preserve today's behaviour):**

| Tier | Server config | Browser path | Visemes |
|------|---------------|--------------|---------|
| Best | `tts.backend = "piper"`, binary + model present | `<audio>` plays Piper WAV | rhubarb frames in lockstep |
| Mid  | `tts.backend = "piper"`, binary OR model missing | falls back to `SpeechSynthesisUtterance` | heuristic (server returns `backend: "disabled"`) |
| Default | `tts.backend = "browser"` (default config) | `SpeechSynthesisUtterance` (today's behaviour) | heuristic |

The default config is **identical to Wave 156 behaviour**. Operators who don't install Piper see zero change.

---

## Solution

Five pieces:

1. New module `src/probos/audio/tts/` with a `TTSBackend` Protocol, a `PiperBackend` subprocess wrapper, and a `NullBackend` no-op.
2. New Pydantic model `TTSConfig` in `src/probos/config.py` with `enabled`, `backend`, `binary_path`, `voice_model`, `timeout_seconds`. Default `backend = "browser"` so Wave 156 operators see zero change.
3. New endpoint `POST /api/avatars/tts` in the **existing** `src/probos/routers/avatars.py`. Synthesis + AttachmentStore + rhubarb in a single internal flow.
4. Modify `ui/src/audio/voice.ts` `speakResponse()` to try `/api/avatars/tts` first and fall back to `SpeechSynthesisUtterance`. Keep all four voice-event listener firings (`'start'` / `'end'`) so AD-718 / AD-721 lifecycle subscribers continue to work.
5. Extend `ui/src/audio/useLipSyncCapture.ts` with an `injectFrames(frames)` setter the new TTS path calls. The existing browser-capture path (heuristic / future routable SpeechSynthesis) stays as-is — the hook now has two ingress paths feeding the same `frames` state.

---

## Section 0 — Files touched

| File | Change |
|---|---|
| `src/probos/audio/__init__.py` | NEW (empty docstring) |
| `src/probos/audio/tts/__init__.py` | NEW (re-exports `TTSBackend`, `PiperBackend`, `NullBackend`, `select_backend`) |
| `src/probos/audio/tts/backends.py` | NEW — `TTSBackend` Protocol, `TTSResult` dataclass |
| `src/probos/audio/tts/piper_backend.py` | NEW — subprocess wrapper around `piper` binary |
| `src/probos/audio/tts/null_backend.py` | NEW — returns `None`; selected when `backend = "browser"` |
| `src/probos/config.py` | NEW `TTSConfig` Pydantic model after `LipSyncConfig`; `tts: TTSConfig = Field(default_factory=TTSConfig)` field on `Config` |
| `src/probos/routers/avatars.py` | ADD `GET /api/avatars/tts/status` (one-time browser feature probe) AND `POST /api/avatars/tts` (synthesis endpoint) after the existing `generate_lipsync` handler |
| `tests/test_ad738_piper_tts.py` | NEW — ≥ 10 backend + endpoint tests |
| `ui/src/audio/voice.ts` | MODIFY `speakResponse` to try server path first, fall back to SpeechSynthesis |
| `ui/src/audio/useLipSyncCapture.ts` | EXTEND public surface with `injectFrames(frames)` setter |
| `ui/src/audio/__tests__/voice.serverTts.test.ts` | NEW — ≥ 4 Vitest tests for server-path / fallback |
| `PROGRESS.md` | Wave 157 entry; +tests count delta |
| `DECISIONS.md` | Append AD-738 closure block + four forward markers (AD-738a/b/c/d) |
| `docs/development/roadmap.md` | Mark AD-738 shipped Wave 157; file AD-738a/b/c/d as roadmap entries |
| `.gitignore` | **VERIFY only** — `/tools/` is already on line 3. No edit needed. |

**Do NOT touch:**
- `ui/src/audio/lipSyncCapture.ts` (browser-side capture stays as the dead-code-but-future-compat path; documented in its own header comment as "transitional — becomes dead code if AD-721b-2.3 (this AD) lands; kept for the day routable SpeechSynthesis ships").
- `ui/src/components/profile/CrewVRM.tsx` (consumer wiring is unchanged — the hook signature still returns `{frames, capturing, reset}`; `injectFrames` is the only added method and CrewVRM does not call it directly — `voice.ts` does).
- `src/probos/avatars/rhubarb_backend.py` (reused as a direct internal call; no changes).
- `src/probos/attachments/*` (allow-list already includes `audio/wav` from AD-721b-1; no new MIME needed since Piper outputs WAV).
- `src/probos/api.py` (the `avatars` router is already wired; the new endpoint is added to the existing router).
- AD-735 per-agent volume slider, AD-737 emotion taxonomy, AD-731 ref-shape invariant.

---

## Section 0.5 — License Disposition

| Component | Source | License | Disposition |
|-----------|--------|---------|-------------|
| `piper` binary | https://github.com/rhasspy/piper | **MIT** (verified `gh api repos/rhasspy/piper/license` → `"key": "mit"` on 2026-05-13) | Operator-provided; never enters the repo. ProbOS ships the wrapper module only. |
| `en_US-amy-medium` voice model (default) | https://huggingface.co/rhasspy/piper-voices | **MIT** (model card declares MIT) | Operator-provided at `tools/piper/voices/`; never enters the repo. |
| Other Piper voices | Catalog at https://huggingface.co/rhasspy/piper-voices | Per-voice (mostly MIT or CC-BY-4.0; a few are restricted) | Operator's responsibility. The Pydantic field documents this; AD-738a will surface a license check in the per-agent voice selector UI. |
| Wrapper module | This AD | Inherits repo's Apache 2.0 (LICENSE root) | OSS-clean. |

**Excluded by design (per License hygiene rule):**

- **Coqui XTTS v2** — CPL (non-commercial) — License hygiene rule blocker. Never absorb.
- **Tortoise TTS** — Apache 2.0 (clean), but 5-10s latency makes interactive use impossible. Defer to AD-738b GPU backend evaluation.
- **ElevenLabs** — proprietary cloud API; "OSS should stay free" rule blocks default inclusion. Could be a commercial-overlay-only backend in a future AD.

`/tools/` is already gitignored (verified at `.gitignore:3`). The voice model + binary are large (~80 MB combined for amy-medium); they MUST stay out of the repo.

---

## Section 1 — Pydantic config

### 1a. `TTSConfig` model

In [src/probos/config.py](src/probos/config.py#L1180), add immediately after the `LipSyncConfig` class (around line 1207, after the closing `"""` of `timeout_seconds`):

```python
class TTSConfig(BaseModel):
    """AD-738 — Server-side TTS backend selection.

    Default: ``browser`` — every ``speakResponse()`` call uses
    ``SpeechSynthesisUtterance`` (today's behaviour, zero regression).
    Operator opts in to ``piper`` by setting ``backend: "piper"`` AND
    placing the binary at ``binary_path`` AND placing the voice model
    files at ``tools/piper/voices/<voice_model>.onnx`` (+ ``.onnx.json``).
    Any failure (binary missing, model missing, subprocess error,
    timeout) returns honest-degrade — the browser falls back to
    SpeechSynthesisUtterance. Speech must NEVER stop because of a TTS
    failure.
    """

    enabled: bool = True
    """Master switch for the server-side TTS pipeline. ``False`` makes
    ``POST /api/avatars/tts`` return ``{"backend": "disabled"}``; the
    browser falls back to SpeechSynthesisUtterance."""

    backend: Literal["browser", "piper"] = "browser"
    """``browser``: server returns ``{"backend": "disabled"}``, browser
    uses SpeechSynthesisUtterance (default — zero behaviour change for
    operators who don't install Piper). ``piper``: subprocess wrapper
    around the piper binary."""

    binary_path: str = "tools/piper/piper"
    """Path (relative to repo root or absolute) to the piper binary.
    On Windows the wrapper auto-appends ``.exe`` if the literal path
    does not exist. Operator places the binary; the repo never ships
    it (gitignored under ``/tools/``)."""

    voice_model: str = "en_US-amy-medium"
    """Voice model name. Operator places ``tools/piper/voices/<name>.onnx``
    AND ``tools/piper/voices/<name>.onnx.json`` (Piper requires both).
    Default ``en_US-amy-medium`` is MIT-licensed (verified on the
    rhasspy/piper-voices model card). Operator who picks a different
    voice is responsible for the license check until AD-738a surfaces
    a license display in the per-agent voice selector."""

    timeout_seconds: float = 10.0
    """Subprocess timeout. Piper on a sentence-length input typically
    takes 0.3-1.5s on CPU; default leaves ample headroom for cold
    model load on first call. Tier-2 log-and-degrade on TimeoutExpired —
    endpoint returns honest-degrade, browser falls back."""
```

`Literal` is already imported at the top of `config.py` (verified — used by `LipSyncConfig.backend`).

### 1b. Wire into `Config`

Find the line `lipsync: LipSyncConfig = Field(default_factory=LipSyncConfig)` and add immediately after it:

```python
tts: TTSConfig = Field(default_factory=TTSConfig)
```

### 1c. `config/system.yaml` — no edit

Verified: `config/system.yaml` has no `tts:` block. Pydantic default is authoritative (`backend = "browser"` → endpoint disabled → today's behaviour). Operator opts in by adding:

```yaml
# tools/piper/piper(.exe) and tools/piper/voices/en_US-amy-medium.onnx[.json]
# must exist before flipping backend to "piper".
tts:
  backend: "piper"
```

Document this in the AD-738 entry of `DECISIONS.md` (Section 7) — do NOT add a commented-out block to `system.yaml` (matches AD-721b-1 precedent).

---

## Section 2 — `audio/tts/` module

### 2a. `src/probos/audio/__init__.py`

```python
"""AD-738 — Server-side audio pipeline (TTS, future: STT)."""
```

### 2b. `src/probos/audio/tts/__init__.py`

```python
"""AD-738 — Text-to-speech backends."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from probos.audio.tts.backends import TTSBackend, TTSResult
from probos.audio.tts.null_backend import NullBackend
from probos.audio.tts.piper_backend import PiperBackend

if TYPE_CHECKING:
    from probos.config import TTSConfig


def select_backend(backend_name: str, config: "TTSConfig") -> TTSBackend:
    """Select a backend instance by configured name.

    Tier-2 log-and-degrade: an unknown backend name is treated as
    ``"browser"`` (NullBackend). Logged at WARNING.
    """
    logger = logging.getLogger(__name__)
    if backend_name == "piper":
        return PiperBackend(
            binary_path=config.binary_path,
            voice_model=config.voice_model,
            timeout_seconds=config.timeout_seconds,
        )
    if backend_name == "browser":
        return NullBackend()
    logger.warning(
        "AD-738: unknown TTS backend %r; degrading to NullBackend (browser path)",
        backend_name,
    )
    return NullBackend()


__all__ = ["TTSBackend", "TTSResult", "NullBackend", "PiperBackend", "select_backend"]
```

### 2c. `src/probos/audio/tts/backends.py`

```python
"""AD-738 — TTS backend Protocol and Result dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TTSResult:
    """Output of a TTS synthesis call.

    ``audio_bytes`` is the raw container payload (Piper produces WAV).
    ``mime`` is the container MIME (``audio/wav`` for Piper).
    ``None`` from a backend means "honest-degrade — caller falls back."
    """

    audio_bytes: bytes
    mime: str


class TTSBackend(Protocol):
    """Structural contract for TTS backends.

    Tier-2 log-and-degrade: implementations MUST return ``None`` (not raise)
    on any failure. The endpoint (`POST /api/avatars/tts`) treats ``None``
    as the signal to return ``{"backend": "disabled"}`` to the browser,
    which falls back to ``SpeechSynthesisUtterance``.
    """

    name: str

    async def synthesize(self, text: str) -> TTSResult | None:
        """Synthesize ``text`` to audio bytes. Return ``None`` on any failure."""
        ...
```

### 2d. `src/probos/audio/tts/null_backend.py`

```python
"""AD-738 — NullBackend: returns None; signals "browser falls back to SpeechSynthesis"."""

from __future__ import annotations

from probos.audio.tts.backends import TTSResult


class NullBackend:
    """Selected when ``tts.backend = "browser"``. Always returns ``None``.

    The endpoint translates ``None`` → ``{"backend": "disabled", ...}``
    and the browser-side ``speakResponse`` falls back to
    ``SpeechSynthesisUtterance``. This is the default configuration.
    """

    name: str = "null"

    async def synthesize(self, text: str) -> TTSResult | None:
        """No-op. Returns ``None`` for honest-degrade."""
        return None
```

### 2e. `src/probos/audio/tts/piper_backend.py`

Mirrors `src/probos/avatars/rhubarb_backend.py:_resolve_binary_path` + `probe_version` + `generate_visemes` patterns (verified — same subprocess discipline). Full module:

```python
"""AD-738 — piper-tts subprocess wrapper.

License posture: piper-tts is MIT (verified 2026-05-13 via
``gh api repos/rhasspy/piper/license``). ProbOS provides this wrapper;
the operator provides the binary at ``tts.binary_path`` AND the voice
model files at ``tools/piper/voices/<voice_model>.onnx`` (+ ``.onnx.json``).
The repo never ships either — ``/tools/`` is gitignored.

Tier-2 log-and-degrade: ``synthesize`` returns ``None`` on ANY failure
(binary missing, model missing, subprocess error, timeout, malformed
output). The endpoint treats ``None`` as the signal to return
``{"backend": "disabled"}`` and the browser falls back to
``SpeechSynthesisUtterance``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from probos.audio.tts.backends import TTSResult

logger = logging.getLogger(__name__)


def _resolve_binary_path(configured: str) -> Path | None:
    """Resolve ``configured``, auto-appending ``.exe`` on Windows. Returns
    ``None`` if not found. NEVER raises. Mirrors the AD-721b-1 helper."""
    p = Path(configured).resolve()
    if p.is_file():
        return p
    if sys.platform == "win32" and p.suffix.lower() != ".exe":
        with_exe = p.parent / (p.name + ".exe")
        if with_exe.is_file():
            return with_exe
    return None


def _resolve_voice_model(voice_model: str) -> Path | None:
    """Resolve the ONNX model path under ``tools/piper/voices/``. Piper
    requires BOTH ``<name>.onnx`` and ``<name>.onnx.json`` to exist;
    returns ``None`` if either is missing. NEVER raises."""
    base = Path("tools/piper/voices").resolve()
    onnx = base / f"{voice_model}.onnx"
    json_path = base / f"{voice_model}.onnx.json"
    if not onnx.is_file() or not json_path.is_file():
        return None
    return onnx


class PiperBackend:
    """Subprocess wrapper around the piper binary.

    Piper reads text on stdin and writes a complete WAV file (RIFF header
    + PCM data) to stdout when invoked with ``--model <path> --output_file -``.
    NOTE: ``--output_raw`` writes raw PCM samples WITHOUT a header — that is
    NOT what we want; ``<audio>`` and rhubarb both require a WAV container.
    Verified against rhasspy/piper README (MIT, archived 2025-10-06): the
    ``-`` argument to ``--output_file`` is the documented stdout sink.
    The wrapper passes text via stdin (UTF-8), reads the WAV from stdout,
    and returns it as ``TTSResult(audio_bytes=..., mime="audio/wav")``.
    """

    name: str = "piper"

    def __init__(
        self,
        binary_path: str,
        voice_model: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._binary_path = binary_path
        self._voice_model = voice_model
        self._timeout_seconds = timeout_seconds

    async def synthesize(self, text: str) -> TTSResult | None:
        """Run piper, return WAV bytes or ``None`` on any failure.

        NEVER raises. Empty / whitespace-only ``text`` short-circuits to
        ``None`` (no point invoking the subprocess for nothing)."""
        if not text or not text.strip():
            return None
        binary = _resolve_binary_path(self._binary_path)
        if binary is None:
            logger.warning(
                "AD-738: piper binary not found at %s; degrading to browser",
                self._binary_path,
            )
            return None
        model = _resolve_voice_model(self._voice_model)
        if model is None:
            logger.warning(
                "AD-738: piper voice model %r missing under tools/piper/voices/ "
                "(need both <name>.onnx and <name>.onnx.json); degrading to browser",
                self._voice_model,
            )
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                str(binary),
                "--model", str(model),
                "--output_file", "-",  # WAV (with RIFF header) to stdout. See class docstring.
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=text.encode("utf-8")),
                    timeout=self._timeout_seconds,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.warning(
                    "AD-738: piper timed out after %ss synthesizing %d chars",
                    self._timeout_seconds, len(text),
                )
                return None
            if proc.returncode != 0:
                logger.warning(
                    "AD-738: piper exit=%s; stderr=%s",
                    proc.returncode,
                    stderr_bytes.decode("utf-8", errors="replace")[:500],
                )
                return None
            if not stdout_bytes:
                logger.warning("AD-738: piper produced 0 bytes; degrading")
                return None
            return TTSResult(audio_bytes=stdout_bytes, mime="audio/wav")
        except (OSError, ValueError) as e:
            logger.warning(
                "AD-738: piper subprocess failed: %s: %s", type(e).__name__, e
            )
            return None
```

---

## Section 3 — `POST /api/avatars/tts` endpoint

In [src/probos/routers/avatars.py](src/probos/routers/avatars.py#L88), add immediately after the closing `}` of `generate_lipsync` (around line 88, end of file). Two endpoints — a tiny status probe AND the synthesis endpoint:

```python
@router.get("/tts/status")
async def tts_status(
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-738 — One-time feature probe for the browser.

    The browser caches this response in module-level state in ``voice.ts``
    and skips ``POST /api/avatars/tts`` entirely when ``backend != "piper"``.
    This preserves the Wave 156 zero-HTTP-per-utterance behaviour for
    operators who haven't opted in to server-side TTS (the default).
    """
    cfg = getattr(runtime.config, "tts", None)
    if cfg is None:
        return {"enabled": False, "backend": "browser"}
    return {
        "enabled": bool(cfg.enabled),
        "backend": str(cfg.backend),
    }


@router.post("/tts")
async def synthesize_tts(
    req: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-738 — Server-side TTS + lip-sync in a single round-trip.

    Body: ``{"text": "<utterance>", "agent_id": "<id-or-null>"}``.

    Synthesizes ``text`` via the configured TTS backend, stores the audio
    bytes in AttachmentStore (AD-731 ref-shape invariant), runs rhubarb on
    the resulting file (reuses AD-721b-1 ``generate_visemes``), and returns
    audio + visemes together so the browser plays them in lockstep.

    Returns:
        - Best path: ``{"backend": "piper", "audio_attachment_id": "<sha256>",
          "mime": "audio/wav", "visemes": [...], "duration_ms": <int>}``
        - Honest-degrade: ``{"backend": "disabled", "audio_attachment_id": null,
          "mime": null, "visemes": [], "duration_ms": 0}`` — browser falls
          back to ``SpeechSynthesisUtterance``.
    """
    cfg = getattr(runtime.config, "tts", None)
    if cfg is None or not cfg.enabled or cfg.backend == "browser":
        return {
            "backend": "disabled",
            "audio_attachment_id": None,
            "mime": None,
            "visemes": [],
            "duration_ms": 0,
        }

    payload = await req.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_body")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="invalid_text")
    if len(text) > 4096:
        # Defense-in-depth: cap text length at the boundary. Piper handles
        # long input but a runaway prompt shouldn't tie up the subprocess.
        raise HTTPException(status_code=413, detail="text_too_long")

    from probos.audio.tts import select_backend
    backend = select_backend(cfg.backend, cfg)
    result = await backend.synthesize(text)
    if result is None:
        return {
            "backend": "disabled",
            "audio_attachment_id": None,
            "mime": None,
            "visemes": [],
            "duration_ms": 0,
        }

    # AD-731 invariant: audio bytes flow through AttachmentStore as
    # content-addressable SHA-256 refs. The response carries only the ref.
    # The AttachmentStore Protocol (src/probos/attachments/store.py:14) declares
    # ``write(content_hash, blob, mime) -> Path`` — caller is responsible for
    # computing the sha256. Canonical pattern from
    # src/probos/routers/chat.py:665-692:
    #     actual_hash = hashlib.sha256(blob).hexdigest()
    #     await store.write(actual_hash, blob, declared_mime)
    import hashlib
    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    attachment_id = hashlib.sha256(result.audio_bytes).hexdigest()
    await store.write(attachment_id, result.audio_bytes, result.mime)

    # Reuse AD-721b-1 rhubarb backend by direct internal call. lipsync.backend
    # may be "heuristic" (default) — in that case skip rhubarb and let the
    # browser fall back to its heuristic schedule for THIS audio.
    visemes_payload: list[dict[str, Any]] = []
    lipsync_cfg = getattr(runtime.config, "lipsync", None)
    if lipsync_cfg is not None and lipsync_cfg.enabled and lipsync_cfg.backend == "rhubarb":
        from probos.avatars.rhubarb_backend import generate_visemes
        audio_path = await store.get_path(attachment_id)
        frames = await generate_visemes(
            audio_path,
            binary_path=lipsync_cfg.binary_path,
            timeout_seconds=lipsync_cfg.timeout_seconds,
        )
        visemes_payload = [
            {"time": f.time, "duration": f.duration, "viseme": f.viseme}
            for f in frames
        ]

    # Duration: parse from WAV header. Cheap and self-contained.
    duration_ms = _wav_duration_ms(result.audio_bytes)

    return {
        "backend": backend.name,
        "audio_attachment_id": attachment_id,
        "mime": result.mime,
        "visemes": visemes_payload,
        "duration_ms": duration_ms,
    }


def _wav_duration_ms(wav_bytes: bytes) -> int:
    """Parse WAV header to extract duration in milliseconds.

    Tier-2 log-and-degrade: any parse failure returns ``0``. The browser
    treats ``0`` as "unknown duration"; the ``<audio>`` element knows
    its own duration once metadata loads.
    """
    import struct

    try:
        if len(wav_bytes) < 44 or wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
            return 0
        # Locate the ``fmt `` chunk (canonical WAV) at offset 12.
        # ``data`` chunk size + fmt sample rate gives duration.
        sample_rate = struct.unpack_from("<I", wav_bytes, 24)[0]
        bits_per_sample = struct.unpack_from("<H", wav_bytes, 34)[0]
        num_channels = struct.unpack_from("<H", wav_bytes, 22)[0]
        # Find the data chunk (may not be at offset 36 if fmt has extras).
        idx = 12
        while idx < len(wav_bytes) - 8:
            chunk_id = wav_bytes[idx:idx + 4]
            chunk_size = struct.unpack_from("<I", wav_bytes, idx + 4)[0]
            if chunk_id == b"data":
                bytes_per_sample = (bits_per_sample // 8) * num_channels
                if bytes_per_sample == 0 or sample_rate == 0:
                    return 0
                num_samples = chunk_size // bytes_per_sample
                return int((num_samples / sample_rate) * 1000)
            idx += 8 + chunk_size
        return 0
    except (struct.error, IndexError, ZeroDivisionError):
        return 0
```

**AttachmentStore.write signature verification:** Audited at [src/probos/attachments/store.py:22](src/probos/attachments/store.py#L22) — `async def write(content_hash: str, blob: bytes, mime: str) -> Path`. The Protocol does NOT expose a `put` method; caller computes the sha256 first via `hashlib.sha256(blob).hexdigest()`. Canonical caller pattern at [src/probos/routers/chat.py:665-692](src/probos/routers/chat.py#L665) is the verified template the endpoint above mirrors. The `_get_attachment_store` helper at [src/probos/routers/chat.py:599](src/probos/routers/chat.py#L599) is the same accessor AD-721b-1's lipsync endpoint uses.

---

## Section 4 — Browser side

### 4a. `voice.ts` — try server path first

In [ui/src/audio/voice.ts](ui/src/audio/voice.ts#L99), modify `speakResponse` to gate on a cached one-time status probe BEFORE attempting `/api/avatars/tts`. When the cached probe says `backend != "piper"` (the default), skip the POST entirely and call `_speakBrowserFallback` synchronously — this preserves Wave 156's zero-HTTP-per-utterance behaviour. Only when the probe reports `backend === "piper"` does the POST fire.

The function stays synchronous on its public surface (no API change for the 4 production callers); the server attempt happens inside an async IIFE that fires `'start'` / `'end'` events compatibly. A module-level `_activeAudio` reference cancels any in-flight `<audio>` from a prior `speakResponse` call (Recommended #3 from pass-1 review).

Find the existing `speakResponse` body. Wrap the SpeechSynthesis path in a fallback function and add the gated server path in front:

```typescript
/** AD-738: cached server-feature probe. Populated on first speakResponse call;
 *  invalidated on any non-200 response so a runtime restart with backend=piper
 *  lights up without a browser refresh. */
type TtsStatus = { enabled: boolean; backend: 'browser' | 'piper' | string };
let _ttsStatus: TtsStatus | null = null;
let _ttsStatusInflight: Promise<TtsStatus | null> | null = null;

async function _fetchTtsStatus(): Promise<TtsStatus | null> {
  if (_ttsStatus !== null) return _ttsStatus;
  if (_ttsStatusInflight !== null) return _ttsStatusInflight;
  _ttsStatusInflight = (async () => {
    try {
      const resp = await fetch('/api/avatars/tts/status', { method: 'GET' });
      if (!resp.ok) {
        _ttsStatus = { enabled: false, backend: 'browser' };
        return _ttsStatus;
      }
      const data = await resp.json();
      _ttsStatus = {
        enabled: !!(data && data.enabled),
        backend: (data && typeof data.backend === 'string') ? data.backend : 'browser',
      };
      return _ttsStatus;
    } catch {
      _ttsStatus = { enabled: false, backend: 'browser' };
      return _ttsStatus;
    } finally {
      _ttsStatusInflight = null;
    }
  })();
  return _ttsStatusInflight;
}

/** AD-738: invalidate cache on any failure during the POST path so a runtime
 *  config change (browser → piper or vice versa) is picked up without refresh. */
function _invalidateTtsStatus(): void { _ttsStatus = null; }

/** AD-738: track the active <audio> so a second speakResponse cancels the first. */
let _activeAudio: HTMLAudioElement | null = null;

/** AD-738: try server-streamed TTS first (only when probe says backend=piper);
 *  fall back to SpeechSynthesisUtterance otherwise.
 *  Public surface unchanged — still synchronous, still fires 'start'/'end' events. */
export function speakResponse(
  text: string,
  profile?: VoiceProfile,
  agent_id?: string,
): void {
  if (!('speechSynthesis' in window) && typeof Audio !== 'function') return;

  // Cancel any in-flight audio from a prior call (server path or browser path).
  if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
  }
  if (_activeAudio !== null) {
    try { _activeAudio.pause(); } catch { /* ignore */ }
    _activeAudio = null;
  }

  void (async () => {
    // ZERO-HTTP guarantee for default config (Captain decision #9):
    // probe once, cache, and skip the POST entirely when backend != "piper".
    const status = await _fetchTtsStatus();
    if (status === null || !status.enabled || status.backend !== 'piper') {
      _speakBrowserFallback(text, profile, agent_id);
      return;
    }
    try {
      const resp = await fetch('/api/avatars/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      if (!resp.ok) {
        _invalidateTtsStatus();
        _speakBrowserFallback(text, profile, agent_id);
        return;
      }
      const data = await resp.json();
      if (
        !data ||
        data.backend === 'disabled' ||
        typeof data.audio_attachment_id !== 'string' ||
        data.audio_attachment_id.length !== 64
      ) {
        // Server flipped to disabled — invalidate so the next call re-probes.
        _invalidateTtsStatus();
        _speakBrowserFallback(text, profile, agent_id);
        return;
      }
      // Build a synthetic utterance object so existing 'start'/'end' listeners
      // (AD-718 / AD-721) keep firing the same shape. agent_id propagates.
      const synth = new SpeechSynthesisUtterance(text);
      const audio = new Audio(`/api/chat/attachments/${data.audio_attachment_id}`);
      _activeAudio = audio;
      // Apply per-agent modulation that the <audio> element supports today.
      // pitch is deferred to forward marker AD-738c (server-side modulation).
      const effective = _resolveEffectiveProfile(profile, agent_id);
      audio.volume = Math.max(0, Math.min(1, effective.volume ?? 0.8));
      audio.playbackRate = Math.max(0.25, Math.min(4.0, effective.rate ?? 0.95));
      audio.preservesPitch = false;  // let playbackRate change pitch as a side effect
      const _clearActive = () => { if (_activeAudio === audio) _activeAudio = null; };
      audio.addEventListener('play', () => _fire({ type: 'start', agent_id, utterance: synth }));
      audio.addEventListener('ended', () => { _clearActive(); _fire({ type: 'end', agent_id, utterance: synth }); });
      audio.addEventListener('error', () => { _clearActive(); _fire({ type: 'end', agent_id, utterance: synth }); });
      // AD-738: feed visemes directly to useLipSyncCapture via the new injection setter.
      if (Array.isArray(data.visemes) && data.visemes.length > 0) {
        try {
          // Lazy import to avoid pulling React into modules that don't need it.
          const { injectLipSyncFrames } = await import('./useLipSyncCapture');
          injectLipSyncFrames(data.visemes, agent_id);
        } catch {
          // ignore — visemes are best-effort
        }
      }
      try {
        await audio.play();
      } catch {
        _clearActive();
        _speakBrowserFallback(text, profile, agent_id);
      }
    } catch {
      _invalidateTtsStatus();
      _speakBrowserFallback(text, profile, agent_id);
    }
  })();
}

/** AD-738: factor out per-agent modulation resolution so both server and
 *  fallback paths apply AD-735 volume + AD-737 emotion modulation. */
function _resolveEffectiveProfile(
  profile: VoiceProfile | undefined,
  agent_id: string | undefined,
): VoiceProfile {
  let effective: VoiceProfile = profile ?? {};
  if (agent_id) {
    try {
      const store = useStore.getState();
      const signals = deriveAgentSignals(agent_id, store as unknown as Parameters<typeof deriveAgentSignals>[1]);
      effective = applyEmotionalModulation(
        {
          voice_name: profile?.voice_name,
          pitch: profile?.pitch ?? 0.9,
          rate: profile?.rate ?? 0.95,
          volume: profile?.volume ?? 0.8,
        },
        signals,
      );
    } catch {
      /* fall through with unmodulated profile */
    }
  }
  return effective;
}

/** AD-738: fallback path — the pre-AD-738 SpeechSynthesisUtterance flow. */
function _speakBrowserFallback(
  text: string,
  profile?: VoiceProfile,
  agent_id?: string,
): void {
  if (!('speechSynthesis' in window)) return;
  const utterance = new SpeechSynthesisUtterance(text);
  const effective = _resolveEffectiveProfile(profile, agent_id);
  utterance.rate = effective.rate ?? 0.95;
  utterance.pitch = effective.pitch ?? 0.9;
  utterance.volume = effective.volume ?? 0.8;
  const named = profile?.voice_name ? _resolveVoiceByName(profile.voice_name) : null;
  const voice = named ?? findPreferredVoice();
  if (voice) utterance.voice = voice;
  utterance.onstart = () => _fire({ type: 'start', agent_id, utterance });
  utterance.onend = () => _fire({ type: 'end', agent_id, utterance });
  speechSynthesis.speak(utterance);
}
```

**Surface preservation:** The four production callers (`DecisionSurface.tsx:239`, `IntentSurface.tsx:265,289`, `ProfileChatTab.tsx:124`, `ProfileInfoTab.tsx:425,537`) call `speakResponse(text, profile?, agent_id?)` and expect a void return. Surface unchanged. The `'start'` / `'end'` event shape is unchanged — the synthetic `SpeechSynthesisUtterance` carries the original text so existing listeners that read `utterance.text` continue to work.

### 4b. `useLipSyncCapture.ts` — `injectLipSyncFrames` setter

In [ui/src/audio/useLipSyncCapture.ts](ui/src/audio/useLipSyncCapture.ts), add a module-level mutable subscription so the imperative `injectLipSyncFrames` call from `voice.ts` reaches the React state in any mounted hook. Append at the end of the file:

```typescript
/** AD-738 — Module-level injection registry. ``voice.ts`` calls
 *  ``injectLipSyncFrames`` after the server returns viseme data; every
 *  mounted ``useLipSyncCapture`` hook with matching (or unset) ``agentId``
 *  receives the frames. Mirrors the ``onSpeechEvent`` listener pattern. */

type FrameInjector = (frames: LipSyncFrame[], agentId?: string) => void;
const _injectListeners = new Set<(f: LipSyncFrame[], a?: string) => void>();

/** Imperative entry point called from ``voice.ts`` after a successful
 *  ``/api/avatars/tts`` round-trip. NEVER throws. */
export function injectLipSyncFrames(frames: LipSyncFrame[], agentId?: string): void {
  for (const fn of _injectListeners) {
    try { fn(frames, agentId); } catch { /* ignore */ }
  }
}

function _subscribeInjection(fn: FrameInjector): () => void {
  _injectListeners.add(fn);
  return () => { _injectListeners.delete(fn); };
}
```

Modify the `useLipSyncCapture` body's existing `useEffect` (lines ~62-95) to ALSO subscribe to the injection channel. After the `const off = onSpeechEvent(...)` line, add a parallel subscription:

```typescript
    const offInject = _subscribeInjection((frames, agentId) => {
      if (!enabledRef.current) return;
      // Match the agentId filter the same way the start-listener does.
      if (agentIdRef.current && agentId !== agentIdRef.current) return;
      if (mounted) setFrames(frames);
    });
```

And in the cleanup function add `offInject();` next to `off();`. The hook's public surface (`{frames, capturing, reset}`) stays unchanged; CrewVRM consumes the same shape.

---

## Section 5 — Tests

### 5a. `tests/test_ad738_piper_tts.py` (≥ 10 tests)

| Test | Behaviour |
|------|-----------|
| `test_null_backend_returns_none` | `NullBackend().synthesize("hi")` → `None`. |
| `test_select_backend_browser_returns_null` | `select_backend("browser", cfg)` is a `NullBackend`. |
| `test_select_backend_unknown_degrades_to_null` | Unknown name logs WARNING and returns `NullBackend`. |
| `test_piper_backend_missing_binary_returns_none` | `PiperBackend(binary_path="/nonexistent")...synthesize("hi")` returns `None`; WARNING logged. |
| `test_piper_backend_missing_voice_model_returns_none` | Binary present (use a stub script), model absent → `None`. |
| `test_piper_backend_empty_text_short_circuits` | `synthesize("")` and `synthesize("   ")` both return `None` without spawning a subprocess. |
| `test_piper_backend_subprocess_timeout_returns_none` | Stub binary that sleeps > timeout → `None`; WARNING. |
| `test_piper_backend_nonzero_exit_returns_none` | Stub binary that exits 1 → `None`; WARNING captures stderr. |
| `test_piper_backend_zero_bytes_returns_none` | Stub binary that exits 0 with empty stdout → `None`. |
| `test_piper_backend_happy_path_returns_wav` | Stub binary writes a 44-byte minimal WAV header → `TTSResult(mime="audio/wav", audio_bytes=...)`. |
| `test_endpoint_tts_disabled_returns_disabled` | Config `tts.enabled = False` → `{"backend": "disabled", ...}`. |
| `test_endpoint_tts_browser_backend_returns_disabled` | Config `tts.backend = "browser"` → `{"backend": "disabled", ...}`. **Also assert** `select_backend` is NOT invoked AND no subprocess spawn occurred (mock + side-effect-count guard) — tightens Recommended #6 from pass-1 review. |
| `test_status_endpoint_returns_browser_default` | `GET /api/avatars/tts/status` with default config returns `{"enabled": True, "backend": "browser"}`. |
| `test_status_endpoint_returns_piper_when_configured` | Config `tts.backend = "piper"` → `GET /api/avatars/tts/status` returns `{"enabled": True, "backend": "piper"}`. |
| `test_status_endpoint_when_tts_attr_missing` | Config object without `tts` attr (defensive runtime) → `{"enabled": False, "backend": "browser"}`. |
| `test_endpoint_tts_invalid_text_400` | Empty / whitespace / non-string → 400 `invalid_text`. |
| `test_endpoint_tts_text_too_long_413` | Text > 4096 chars → 413. |
| `test_endpoint_tts_honest_degrade_when_backend_returns_none` | Stub backend returns `None` → endpoint returns `{"backend": "disabled"}`. |
| `test_endpoint_tts_happy_path_returns_attachment_and_visemes` | Stub backend returns valid WAV bytes; lipsync.backend=rhubarb stub returns 2 frames → response contains valid sha256, mime, both visemes, positive duration_ms. **AD-731 invariant:** assert `audio_attachment_id` is a 64-char hex; assert no `audio_bytes` / `audio_base64` key present in response JSON. |
| `test_endpoint_tts_omits_visemes_when_lipsync_heuristic` | Backend returns audio; `lipsync.backend = "heuristic"` → response has audio + empty `visemes`. |
| `test_wav_duration_ms_parses_canonical_header` | Synthetic 1-second WAV (16 kHz, 16-bit mono, 32000 bytes data) → `duration_ms == 1000`. |
| `test_wav_duration_ms_returns_zero_on_malformed` | Garbage bytes → `0`. |

Stub the subprocess via a tiny sh / cmd script written into `tmp_path` — the AD-721b-1 test file uses the same pattern (`tests/test_ad721b1_rhubarb_backend.py`). Cross-platform: Windows uses a `.bat` shim; Linux/macOS uses a `#!/bin/sh` script with `chmod +x`.

### 5b. `ui/src/audio/__tests__/voice.serverTts.test.ts` (≥ 5 Vitest tests)

| Test | Behaviour |
|------|-----------|
| `speakResponse makes ZERO POST to /api/avatars/tts when status reports backend=browser (default config)` | Mock `GET /api/avatars/tts/status` → `{enabled: true, backend: "browser"}`. Call `speakResponse` 3 times. Assert `fetch` was called exactly ONCE total (the GET probe), `speechSynthesis.speak` called 3 times, NO POST to `/api/avatars/tts`. **Load-bearing test for Captain decision #9 (zero-HTTP-per-utterance default-config guarantee).** |
| `speakResponse falls back to SpeechSynthesis when /api/avatars/tts returns disabled (server-side flip)` | Probe returns `backend=piper`; POST returns `{backend: "disabled", ...}` → `speechSynthesis.speak` is called; cache invalidated (next call re-probes). |
| `speakResponse falls back to SpeechSynthesis on POST fetch error` | Probe returns `backend=piper`; mock POST rejects → `speechSynthesis.speak` is called; cache invalidated. |
| `speakResponse plays <audio> when probe=piper and POST returns valid attachment_id` | Probe `backend=piper`; POST returns valid response → `Audio` constructor invoked with `/api/chat/attachments/<sha>`; `speechSynthesis.speak` NOT called. |
| `speakResponse forwards visemes to injectLipSyncFrames` | Probe `backend=piper`; POST returns visemes; mounted `useLipSyncCapture` hook receives them via the injection channel — assert hook's `frames` state updates. |
| `second speakResponse cancels in-flight <audio> from first` | Two back-to-back calls in piper mode → first `Audio.pause()` called before second `Audio.play()`. (Recommended #3 from pass-1 review.) |

Stub `Audio` constructor + `fetch`; reuse the existing `voice.test.ts` mock harness pattern.

### 5c. Regression: `useLipSyncCapture` injection path

Add ONE Vitest in the existing `ui/src/audio/__tests__/useLipSyncCapture.test.tsx`:

| Test | Behaviour |
|------|-----------|
| `useLipSyncCapture receives injected frames from voice.ts` | Render hook with `enabled: true, agentId: "a1"`. Call `injectLipSyncFrames([...], "a1")`. Assert `result.current.frames` contains the injected frames. Assert injection with mismatched `agentId` does NOT update state. |

---

## Section 6 — What this does NOT change

- **SpeechSynthesisUtterance fallback path** — preserved verbatim in `_speakBrowserFallback`. Default config (`tts.backend = "browser"`) takes the fallback every call. Operators who don't install Piper see ZERO behaviour change vs. Wave 156.
- **AD-735 per-agent volume slider** — `effective.volume` is still computed by `applyEmotionalModulation` and applied to BOTH paths (`<audio>.volume` for the server path, `utterance.volume` for the fallback). The slider continues to work end-to-end.
- **AD-737 per-agent emotion taxonomy** — `_resolveEffectiveProfile` calls `deriveAgentSignals` + `applyEmotionalModulation` exactly as today's code does. Custom emotions modulate the same way.
- **AD-731 ref-shape invariant** — audio bytes flow through `AttachmentStore.write(sha256, blob, mime)` (caller-computed hash); the endpoint response carries only the ref. No inline base64 in any RPC body or `IntentMessage.params`.
- **AD-721b-1 rhubarb backend** — reused as a direct internal call. No changes to `rhubarb_backend.py`.
- **AD-721b-2 browser-side capture** — `lipSyncCapture.ts` and `useLipSyncCapture.ts` keep the `onSpeechEvent` capture path. The injection channel is additive. The capture path stays as the future-compat path for the day routable SpeechSynthesis ships.
- **`/api/avatars/lipsync` endpoint** — unchanged. The new `/api/avatars/tts` endpoint composes synthesis + AttachmentStore + rhubarb internally; the standalone lipsync endpoint stays as the entry point for the AD-721b-2 browser-capture path (vestigial when `tts.backend = "piper"`).
- **`config/system.yaml`** — no edit; Pydantic default is authoritative.
- **AD-738a/b/c/d** — filed as forward markers, NOT built in this AD.

---

## Section 7 — Forward markers

File these in `docs/development/roadmap.md` and reference in the AD-738 entry of `DECISIONS.md`. **Do not implement in this wave.**

| AD | Title | Trigger to build |
|----|-------|------------------|
| AD-738a | Per-agent voice selection | `CrewProfile.voice_model` field + selector UI in `ProfileInfoTab.tsx`; surfaces voice license in the picker. Build when operator has > 2 voice models installed. |
| AD-738b | GPU-accelerated TTS backend evaluation (Kokoro Apache 2.0, StyleTTS2 MIT) | New backends slot into the `TTSBackend` Protocol added in this AD. Build when operator with capable GPU (e.g. 5090) requests higher fidelity. License-eligible: Kokoro Apache 2.0, StyleTTS2 MIT. |
| AD-738c | Server-side voice modulation | Apply AD-735 pitch/rate per-agent at the Piper synthesis step rather than `<audio>` post-processing. Closes the "no pitch on `<audio>`" limitation noted in Section 4a. |
| AD-738d | TTS text caching layer | LRU cache keyed `(agent_id, voice, sha256(text))` → `attachment_id`. Build when telemetry shows the same text re-synthesizing > N times in a session window. |

---

## Section 8 — Verification commands

Builder runs these before commit:

1. **Phantom-API pre-check:**
   ```powershell
   ./scripts/phantom-api-precheck.ps1 prompts/ad-721b-2-3-server-streamed-tts.md
   ```
   Expected: zero phantoms.

2. **Confirm AttachmentStore.write signature (NOT `put` — that method does not exist):**
   ```powershell
   Select-String -Path src/probos/attachments/store.py -Pattern "def write\("
   ```
   Expected match: `async def write(self, content_hash: str, blob: bytes, mime: str) -> Path`. If absent or shape changed, hard-stop and surface to Architect — Section 3 endpoint depends on this exact signature.

3. **Focused Python test gate:**
   ```powershell
   d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738_piper_tts.py -v -n 0
   ```
   Expected: all new tests green.

4. **Focused UI test gate:**
   ```powershell
   cd ui; npx vitest run src/audio/__tests__/voice.serverTts.test.ts src/audio/__tests__/useLipSyncCapture.test.tsx
   ```
   Expected: all new + regression tests green.

5. **Full Python test gate:**
   ```powershell
   d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
   ```
   Expected: only documented HEAD-flake set red (see Wave 157 dispatch).

6. **Full UI test gate:**
   ```powershell
   cd ui; npx vitest run
   ```
   Expected: green.

7. **Operator smoke test (manual, post-merge):**
   - Download `piper-windows-amd64.zip` from https://github.com/rhasspy/piper/releases.
   - Extract `piper.exe` to `tools/piper/piper.exe`.
   - Download `en_US-amy-medium.onnx` + `en_US-amy-medium.onnx.json` from https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/amy/medium.
   - Place both files at `tools/piper/voices/`.
   - Edit `config/system.yaml`: add `tts:\n  backend: "piper"` and `lipsync:\n  backend: "rhubarb"`.
   - Restart runtime. Send a DM to any agent. Mouth should sync to real audio.

---

## Section 9 — Tracking updates

| File | Update |
|------|--------|
| `PROGRESS.md` | Add AD-738 to highest-AD line (was AD-737). Update test count delta. |
| `progress-era-5-unification.md` | One-line entry: `AD-738 — Server-streamed TTS via Piper (Wave 157). Closes AD-721b-2.3 forward marker.` |
| `DECISIONS.md` | Append AD-738 entry mirroring AD-721b-1 / AD-735 shape (Decision / Files / Tests / What this does NOT change / Forward markers). License Disposition embedded inline. |
| `docs/development/roadmap.md` | Mark AD-721b-2.3 → shipped as AD-738 in Wave 157. File AD-738a/b/c/d as roadmap entries with the trigger conditions from Section 7. |

---

## Acceptance criteria

- ✅ `tts.backend = "browser"` (default) preserves Wave 156 behaviour exactly — every `speakResponse` call uses `SpeechSynthesisUtterance`. **Zero `POST /api/avatars/tts` traffic on the default-config path** — only the one-time `GET /api/avatars/tts/status` probe fires per HXI session (verified by Vitest `speakResponse makes ZERO POST...`). No regression in the documented HEAD-flake set.
- ✅ `tts.backend = "piper"` with binary + model present produces a `<audio>`-played WAV with rhubarb visemes in lockstep.
- ✅ `tts.backend = "piper"` with binary OR model missing returns honest-degrade; browser falls back to `SpeechSynthesisUtterance`. WARNING logged.
- ✅ AD-731 invariant verified by test: response carries `audio_attachment_id` (64-char hex), no inline audio bytes / base64 anywhere in the JSON.
- ✅ `<audio>.volume` reflects AD-735 per-agent slider; `<audio>.playbackRate` reflects per-agent rate.
- ✅ `'start'` / `'end'` listener events fire from BOTH paths so AD-718 / AD-721 lifecycle subscribers continue to work.
- ✅ ≥ 18 new tests (≥ 13 Python + ≥ 5 Vitest), all green.
- ✅ Phantom-API pre-check returns zero phantoms.
- ✅ Forward markers AD-738a/b/c/d filed in `roadmap.md` and `DECISIONS.md`.
- ✅ License Disposition recorded in `DECISIONS.md` AD-738 entry: Piper MIT, default voice model `en_US-amy-medium` MIT.
- ✅ **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-05-13)

```
# No existing TTS abstraction in src/probos/ — this AD creates the seam.
file_search "src/probos/audio/**" → No files found.
grep "TTS|tts_|class.*Tts|synthesize|speak\(" src/probos/ → 20 unrelated matches
  (decomposer.py prompt text, research synthesis, etc.); zero TTS plumbing.

# AttachmentStore mime allow-list ALREADY includes audio/wav (AD-721b-1).
src/probos/config.py:1140
  "audio/wav",

# /api/avatars/lipsync endpoint exists; rhubarb backend reusable directly.
src/probos/routers/avatars.py:23
  @router.post("/lipsync")
src/probos/avatars/rhubarb_backend.py:147
  async def generate_visemes(audio_path, binary_path, timeout_seconds=30.0)

# avatars router already wired in src/probos/api.py.
src/probos/api.py:199
  avatars,  # AD-721b-1 (Wave 155): /api/avatars/lipsync

# AttachmentStore accessor pattern (verified — same helper AD-721b-1 uses).
src/probos/routers/chat.py:599
  def _get_attachment_store(runtime: Any) -> Any:

# speakResponse in voice.ts; 4 production call sites + tests.
ui/src/audio/voice.ts:99  export function speakResponse(text, profile?, agent_id?)
ui/src/components/DecisionSurface.tsx:239
ui/src/components/IntentSurface.tsx:265, 289
ui/src/components/profile/ProfileChatTab.tsx:124
ui/src/components/profile/ProfileInfoTab.tsx:425, 537

# useLipSyncCapture current shape: {frames, capturing, reset}.
ui/src/audio/useLipSyncCapture.ts:33-44
  export interface UseLipSyncCaptureResult { frames; capturing; reset; }

# CrewVRM consumes useLipSyncCapture — surface stays unchanged.
ui/src/components/profile/CrewVRM.tsx:23
  import { useLipSyncCapture } from '../../audio/useLipSyncCapture';
ui/src/components/profile/CrewVRM.tsx:242
  const lipsync = useLipSyncCapture({ enabled: true, agentId });

# Literal already imported in config.py (used by LipSyncConfig.backend).
src/probos/config.py:1192  backend: Literal["heuristic", "rhubarb"] = "heuristic"

# Highest AD in DECISIONS.md = AD-737. Next available = AD-738.
Select-String -Path DECISIONS.md -Pattern "AD-(7[3-9]\d|[8-9]\d\d)"
  → AD-730, AD-731, AD-732, AD-734, AD-735, AD-736, AD-737

# /tools/ already gitignored.
.gitignore:3  /tools/
```

---

## Revision (2026-05-13)

Pass-1 review (prompts/Reviews/ad-721b-2-3-server-streamed-tts-review.md, verdict Conditional) raised three Required findings. All three confirmed against the live codebase and addressed in this revision.

### R1 — Phantom AttachmentStore.put resolved

- Verified: src/probos/attachments/store.py:14-41 declares the Protocol with write/read/exists/get_path/size only. There is no put method anywhere in src/probos/attachments/.
- Verified caller pattern: src/probos/routers/chat.py:665 computes ctual_hash = hashlib.sha256(blob).hexdigest(); line 692 calls wait store.write(actual_hash, blob, declared_mime).
- Section 3 endpoint code now mirrors the chat-router pattern: hashlib.sha256(...).hexdigest() then wait store.write(hash, blob, mime). The post-Section-3 verification note now points at store.py (the Protocol) instead of filesystem_store.py and documents the correct signature. The Section 8 verification command was updated to grep for def write( in the Protocol file.
- Section 6 ('What this does NOT change') and Captain decisions #5 prose were updated to say AttachmentStore.write(sha256, blob, mime) instead of put.

### R2 — Default-config zero-HTTP-per-utterance regression resolved

- Confirmed against the prior Section 4a code: every speakResponse POSTed to /api/avatars/tts even when 	ts.backend = rowser` (the default). Wave 156 had ZERO HTTP per utterance.
- Chosen approach: option (a) — a tiny GET /api/avatars/tts/status endpoint returning {enabled, backend}. Browser fetches once on first speakResponse call, caches in module-level _ttsStatus in voice.ts, and skips the POST entirely when cached ackend !== piper`. Rationale: option (a) keeps coupling local to the TTS subsystem (no App.tsx wiring, no window.__probos global), preserves the untime config flip → next call re-probes invariant via _invalidateTtsStatus() on POST failure, and matches the AD-705d pre-flight-status-cache pattern.
- New Section 3 endpoint: GET /api/avatars/tts/status (defensive against missing 	ts attr; tier-2 log-and-degrade defaults to {enabled: False, backend: rowser}).
- Section 4a speakResponse rewritten with _fetchTtsStatus() (de-duplicates concurrent first-call probes via _ttsStatusInflight), _invalidateTtsStatus() (called on any non-200 from POST or any malformed response so a config flip lights up without a browser refresh), and _activeAudio cancellation (folds Recommended #3).
- Captain decisions section gained a new #9 documenting the load-bearing zero-HTTP guarantee.
- New tests: 	est_status_endpoint_returns_browser_default, 	est_status_endpoint_returns_piper_when_configured, 	est_status_endpoint_when_tts_attr_missing (Python); speakResponse makes ZERO POST to /api/avatars/tts when status reports backend=browser (default config) (Vitest, load-bearing). The browser-backend Python endpoint test was tightened with a no-side-effect assertion (folds Recommended #6).

### R3 — Section 2e Piper invocation corrected

- Verified against rhasspy/piper README (MIT, archive timestamp 2025-10-06): the --output_raw flag emits raw PCM samples (no header). To stream a complete WAV (RIFF header + PCM data) to stdout, the documented form is --output_file -. The previous prose ('drop --output_raw and let piper write the WAV header') was wrong — without any --output* flag, piper writes to a generated filename in the CWD.
- Section 2e canonical block replaced --output_raw, -` with --output_file, -` plus an inline # WAV (with RIFF header) to stdout. See class docstring. comment. The PiperBackend class docstring was rewritten to document the correct flag, the --output_raw pitfall, and the README verification.
- The duplicated Note on --output_raw paragraph and its standalone corrected-invocation code block (BF-274 / BF-278 footgun shape) were removed entirely. Builder copy-paste of the canonical block now produces the correct invocation.

### Recommended findings disposition

| # | Finding | Disposition |
|---|---------|-------------|
| 1 | gent_id in POST body unused | Folded — request body is now {text} only. AD-738a will reintroduce gent_id when the per-agent voice selector ships. |
| 2 | useLipSyncCapture dual-fire on capture path | Deferred — adds new flag plumbing; out of scope for this revision pass. Documented as a follow-up in the AD-738 closure block. |
| 3 | Cancellation of in-flight <audio> on second call | Folded — module-level _activeAudio reference, paused at top of every speakResponse. New Vitest test added. |
| 4 | select_backend(config: object) loose typing | Folded — typed as TTSConfig via TYPE_CHECKING forward ref. |
| 5 | oice_model_dir configurable field | Deferred — adds new Pydantic field; mild scope expansion. The repo-rooted default is documented in the docstring. |
| 6 | Server-side default-config no-op test | Folded into the tightened 	est_endpoint_tts_browser_backend_returns_disabled (asserts select_backend is NOT called). |

### Acceptance / test count delta

- Header Estimated tests line: ≥ 14 → ≥ 18 (≥ 13 Python + ≥ 5 Vitest).
- Acceptance criteria 1 + 7 updated to reflect zero-HTTP guarantee and new test count.

### Closing self-check (run by Architect 2026-05-13)

- Select-String -Pattern store\\.put\\( prompts/ad-721b-2-3-server-streamed-tts.md → 0 hits in code; only the disposition prose in this revision section mentions put.
- Select-String -Pattern --output_raw prompts/ad-721b-2-3-server-streamed-tts.md → only the explanatory comment in the new Section 2e class docstring (warning prose), zero in code blocks.
- Select-String -Pattern gent_id: agent_id prompts/ad-721b-2-3-server-streamed-tts.md → 0 hits (the unused-field POST body pattern is removed).

