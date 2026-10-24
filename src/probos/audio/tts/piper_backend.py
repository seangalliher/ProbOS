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

import logging
import sys
from pathlib import Path

from probos.audio.tts.backends import TTSResult
from probos.audio.tts.prosody import resolve_prosody_overrides
from probos.audio.tts.resident import PiperWorkerKey, VoiceSynthesisService

logger = logging.getLogger(__name__)


def _probos_root() -> Path:
    """AD-1025: the ProbOS install/repo root.

    ``src/probos/audio/tts/piper_backend.py`` -> ``parents[4]`` walks
    tts->audio->probos->src->root. Mirrors ``__main__.py``'s ``project_root``
    (``Path(__file__).resolve().parent.parent.parent`` from
    ``src/probos/__main__.py``) -- both land on the repo root that holds the
    bundled, gitignored ``tools/`` directory. Verified by counting segments.
    """
    return Path(__file__).resolve().parents[4]


def _anchor_path(configured: str) -> Path:
    """AD-1025 (DD-1): anchor a configured asset path to the ProbOS install
    root, never the process CWD. An absolute path is returned resolved
    as-is; a relative path resolves against ``_probos_root()``. NEVER raises.
    Mirrors the bundled-tools anchor in ``__main__.py``."""
    candidate = Path(configured)
    if not candidate.is_absolute():
        candidate = _probos_root() / candidate
    return candidate.resolve()


def resolve_voices_dir(voices_dir: str) -> Path:
    """AD-1025a: anchor the configured Piper voices directory to the ProbOS
    install root. Public helper shared by ``PiperBackend.synthesize`` and the
    ``GET /api/avatars/tts/voices`` listing endpoint so both resolve the same
    location regardless of the process CWD. Absolute as-is; relative under
    ``_probos_root()``; NEVER the CWD. NEVER raises."""
    return _anchor_path(voices_dir)


def _resolve_binary_path(configured: str) -> Path | None:
    """Resolve ``configured`` against the ProbOS install root (AD-1025/DD-1):
    absolute used as-is, relative anchored to ``_probos_root()`` (NOT the
    CWD). Auto-appends ``.exe`` on Windows. Returns ``None`` if not found.
    NEVER raises. Mirrors the AD-721b-1 helper."""
    p = _anchor_path(configured)
    if p.is_file():
        return p
    if sys.platform == "win32" and p.suffix.lower() != ".exe":
        with_exe = p.parent / (p.name + ".exe")
        if with_exe.is_file():
            return with_exe
    return None


def _resolve_voice_model(voice_model: str, voices_base: Path) -> Path | None:
    """Resolve the ONNX model path under ``voices_base`` (AD-1025/DD-2: the
    caller anchors the configured ``voices_dir`` via ``_anchor_path``). Piper
    requires BOTH ``<name>.onnx`` and ``<name>.onnx.json`` to exist; returns
    ``None`` if either is missing. NEVER raises."""
    onnx = voices_base / f"{voice_model}.onnx"
    json_path = voices_base / f"{voice_model}.onnx.json"
    if not onnx.is_file() or not json_path.is_file():
        return None
    return onnx


class PiperBackend:
    """Piper TTS backend.

    Resolves the binary, the voice model (including the BF-291 per-call
    override) and the per-emotion prosody (AD-738e-1) for one call, then asks
    the runtime's ``VoiceSynthesisService`` (BF-918) for the audio: a resident
    ``piper --json-input`` process for that voice and prosody set, which writes
    each WAV to a file (BF-282) and runs on the voice executor. Returns
    ``TTSResult(audio_bytes=..., mime="audio/wav")`` or ``None`` (degrade).
    ``<audio>`` and rhubarb both need a WAV container, never raw PCM.
    """

    name: str = "piper"

    def __init__(
        self,
        binary_path: str,
        voice_model: str,
        voices_dir: str = "tools/piper/voices",
        timeout_seconds: float = 10.0,
        noise_scale: float = 0.85,
        length_scale: float = 1.0,
        noise_w: float = 1.0,
        sentence_silence: float = 0.35,
        service: VoiceSynthesisService | None = None,
    ) -> None:
        # BF-918: the runtime's resident synthesis; without it Piper degrades to the browser.
        self._service = service
        self._binary_path = binary_path
        self._voice_model = voice_model
        self._voices_dir = voices_dir
        self._timeout_seconds = timeout_seconds
        self._noise_scale = noise_scale
        self._length_scale = length_scale
        self._noise_w = noise_w
        self._sentence_silence = sentence_silence

    async def synthesize(
        self,
        text: str,
        emotion: str | None = None,
        voice_override: str | None = None,
    ) -> TTSResult | None:
        """Run piper, return WAV bytes or ``None`` on any failure.

        AD-738e-1: ``emotion`` is an optional v1 ``EmotionalIntent`` name.
        When provided and known, applies per-emotion prosody overrides
        for THIS call only (no instance mutation). Unknown / ``None`` /
        ``"neutral"`` falls through to constructor defaults — additive
        guarantee, no regression for existing call paths.

        BF-291 / AD-738f: ``voice_override`` is an optional Piper voice
        model name (e.g. ``en_US-ryan-medium``). When set and resolvable
        under ``tools/piper/voices/``, the backend uses that voice for
        THIS call only. Unknown / unresolvable falls back to the
        configured ``tts.voice_model`` silently with a debug log so the
        per-call override path is observable.

        NEVER raises. Empty / whitespace-only ``text`` short-circuits to
        ``None`` (no point invoking the subprocess for nothing)."""
        if not text or not text.strip():
            return None
        binary = _resolve_binary_path(self._binary_path)
        if binary is None:
            logger.warning(
                "AD-738/AD-1025: piper binary not found (configured=%r, "
                "resolved=%s); install the binary there or set tts.binary_path "
                "(relative paths anchor to the ProbOS root, not the CWD); "
                "degrading to browser",
                self._binary_path,
                _anchor_path(self._binary_path),
            )
            return None
        # AD-1025/DD-2: anchor the configured voices dir to the ProbOS install
        # root (absolute as-is, relative under _probos_root()), never the CWD.
        # Both the configured voice and the BF-291 override resolve under it.
        voices_base = _anchor_path(self._voices_dir)
        # BF-291 / AD-738f: per-call voice override. Resolve first; on
        # failure log at DEBUG and fall back to the configured voice.
        effective_voice = self._voice_model
        if voice_override and isinstance(voice_override, str):
            override_path = _resolve_voice_model(voice_override, voices_base)
            if override_path is not None:
                effective_voice = voice_override
                logger.debug(
                    "BF-291: piper using per-call voice override %r "
                    "(configured default: %r)",
                    voice_override, self._voice_model,
                )
            else:
                logger.debug(
                    "BF-291: piper voice override %r missing under %s; "
                    "falling back to configured %r",
                    voice_override, voices_base, self._voice_model,
                )
        model = _resolve_voice_model(effective_voice, voices_base)
        if model is None:
            logger.warning(
                "AD-738/AD-1025: piper voice model %r missing under %s "
                "(need both <name>.onnx and <name>.onnx.json); install the "
                "model files there or set tts.voices_dir; degrading to browser",
                effective_voice,
                voices_base,
            )
            return None
        # AD-738e-1: resolve per-emotion prosody overrides for THIS call.
        # Tier-2 log-and-degrade: bad / unknown emotion falls back to
        # constructor defaults silently.
        _ov = resolve_prosody_overrides(emotion)
        _noise_scale      = _ov.get("noise_scale",      self._noise_scale)
        _length_scale     = _ov.get("length_scale",     self._length_scale)
        _noise_w          = _ov.get("noise_w",          self._noise_w)
        _sentence_silence = _ov.get("sentence_silence", self._sentence_silence)
        if self._service is None:
            logger.warning(
                "BF-918: no voice synthesis service on this runtime; degrading to browser"
            )
            return None
        # BF-918 (#1626): one resident process per (voice, prosody) key on the voice
        # executor. The service keeps BF-280, BF-282, BF-892 and the timeout, and logs
        # any failure in the AD-738 wording.
        key = PiperWorkerKey(
            binary=str(binary),
            model=str(model),
            noise_scale=_noise_scale,
            length_scale=_length_scale,
            noise_w=_noise_w,
            sentence_silence=_sentence_silence,
        )
        wav_bytes = await self._service.synthesize(key, text, self._timeout_seconds)
        if wav_bytes is None:
            return None
        return TTSResult(audio_bytes=wav_bytes, mime="audio/wav")
