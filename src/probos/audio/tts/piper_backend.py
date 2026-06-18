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
import subprocess
import sys
import tempfile
from pathlib import Path

from probos.audio.tts.backends import TTSResult
from probos.audio.tts.prosody import resolve_prosody_overrides

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
        voices_dir: str = "tools/piper/voices",
        timeout_seconds: float = 10.0,
        noise_scale: float = 0.85,
        length_scale: float = 1.0,
        noise_w: float = 1.0,
        sentence_silence: float = 0.35,
    ) -> None:
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
        try:
            # BF-282 (2026-05-13): write to a temp WAV file instead of stdout.
            # On Windows, ``--output_file -`` writes to stdout which Piper's
            # C runtime opens in text mode by default, converting every 0x0A
            # byte to 0x0D 0x0A and corrupting the PCM body — produces audio
            # that sounds like static. Writing to a file bypasses the text-
            # mode translation entirely. Identical behavior on Linux/macOS.
            #
            # BF-280 (2026-05-13): use subprocess.Popen in a thread executor
            # instead of asyncio.create_subprocess_exec. The latter requires
            # ProactorEventLoop, but ProbOS runtime uses WindowsSelectorEventLoop
            # which raises NotImplementedError on Windows. Mirrors the
            # shell_command.py:_run_sync pattern.
            def _run_sync() -> tuple[int, bytes, bytes]:
                # NamedTemporaryFile + delete=False so Piper can open it by
                # name; we delete in the finally block after reading.
                with tempfile.NamedTemporaryFile(
                    suffix=".wav", delete=False
                ) as tmp:
                    tmp_path = Path(tmp.name)
                try:
                    proc = subprocess.Popen(
                        [
                            str(binary),
                            "--model", str(model),
                            "--output_file", str(tmp_path),
                            # AD-738e prosody knobs — see TTSConfig docstrings
                            # for tuning rationale. Captain Decision: piper
                            # upstream defaults (0.667 / 1.0 / 0.8 / 0.2) sound
                            # monotone; our defaults bump expressiveness +
                            # rhythm variation at a small clarity cost.
                            "--noise_scale", str(_noise_scale),
                            "--length_scale", str(_length_scale),
                            "--noise_w", str(_noise_w),
                            "--sentence_silence", str(_sentence_silence),
                        ],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    try:
                        _stdout, err = proc.communicate(
                            input=text.encode("utf-8"),
                            timeout=self._timeout_seconds,
                        )
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                        raise
                    rc = proc.returncode or 0
                    if rc != 0 or not tmp_path.is_file():
                        return rc, b"", err
                    return rc, tmp_path.read_bytes(), err
                finally:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except OSError:
                        pass

            loop = asyncio.get_running_loop()
            try:
                returncode, wav_bytes, stderr_bytes = await loop.run_in_executor(
                    None, _run_sync,
                )
            except subprocess.TimeoutExpired:
                logger.warning(
                    "AD-738: piper timed out after %ss synthesizing %d chars",
                    self._timeout_seconds, len(text),
                )
                return None
            if returncode != 0:
                logger.warning(
                    "AD-738: piper exit=%s; stderr=%s",
                    returncode,
                    stderr_bytes.decode("utf-8", errors="replace")[:500],
                )
                return None
            if not wav_bytes:
                logger.warning("AD-738: piper produced 0 bytes; degrading")
                return None
            return TTSResult(audio_bytes=wav_bytes, mime="audio/wav")
        except (OSError, ValueError) as e:
            logger.warning(
                "AD-738: piper subprocess failed: %s: %s", type(e).__name__, e
            )
            return None
