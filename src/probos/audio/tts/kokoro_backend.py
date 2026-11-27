"""AD-738g (#1662) S1: Kokoro speech on this machine, from a resident worker process.

The worker (``scripts/kokoro_worker.py``) runs ``kokoro-onnx`` in the operator's venv under
``tools/kokoro/`` (installed by ``scripts/kokoro-fetch.ps1``; ``/tools/`` is gitignored) and
speaks Piper's line protocol, so the runtime's ``VoiceSynthesisService`` (BF-918) owns its
start, restart, timeout and stop. One process serves every voice: the voice and the speed
travel on each request line.

License posture: kokoro-onnx and onnxruntime are MIT and the Kokoro-82M weights Apache-2.0;
the phonemizer (GPL-3.0-or-later) and the espeak-ng library it loads (GPL-3.0-or-later) run
only in that separate process, which receives text, a voice id and a speed and returns a WAV
file path. Nothing in ProbOS imports them (THIRD_PARTY_LICENSES.md, "License policy").

Tier-2 log-and-degrade: ``synthesize`` returns ``None`` on any failure, and the browser speaks.
"""

from __future__ import annotations

import logging
import time
from typing import get_args

from probos.audio.tts.backends import TTSResult
from probos.audio.tts.piper_backend import anchor_install_path, resolve_executable_path
from probos.audio.tts.prosody import resolve_prosody_overrides
from probos.audio.tts.resident import KokoroWorkerKey, VoiceSynthesisService
from probos.config import KokoroTTSConfig

logger = logging.getLogger(__name__)

#: The worker script, relative to the ProbOS root (AD-1025 anchoring).
WORKER_SCRIPT = "scripts/kokoro_worker.py"
#: The voices the backend sends: the English ids of ``KokoroTTSConfig.voice``'s ``Literal`` (one source).
KOKORO_VOICES: frozenset[str] = frozenset(get_args(KokoroTTSConfig.model_fields["voice"].annotation))
#: kokoro-onnx raises ``ValueError`` for a speed outside this range.
SPEED_MIN = 0.5
SPEED_MAX = 2.0


def kokoro_speed(base: float, emotion: str | None) -> float:
    """AD-738e-1's per-emotion ``length_scale`` as a Kokoro speed: ``base / length_scale``, clamped."""
    length_scale = resolve_prosody_overrides(emotion).get("length_scale", 1.0)
    return min(SPEED_MAX, max(SPEED_MIN, base / length_scale))


class KokoroBackend:
    """Kokoro TTS backend (``tts.backend: kokoro``): a 24 kHz 16-bit mono WAV, or ``None`` to degrade."""

    name: str = "kokoro"

    def __init__(self, config: KokoroTTSConfig, service: VoiceSynthesisService | None = None) -> None:
        self._config = config
        # BF-918: the runtime's resident synthesis; without it Kokoro degrades to the browser.
        self._service = service

    def resolve_voice(self, voice_override: str | None) -> str:
        """The voice for one call: a catalogue override (the HXI picker, an AD-718a proposal), else ``tts.kokoro.voice``.

        A name the catalogue lacks (a Piper or browser voice name) is ignored. AD-738f (#1868)
        adds the per-role default between the two.
        """
        if voice_override is not None and voice_override in KOKORO_VOICES:
            return voice_override
        return self._config.voice

    async def synthesize(
        self,
        text: str,
        emotion: str | None = None,
        voice_override: str | None = None,
    ) -> TTSResult | None:
        """WAV bytes from the resident Kokoro worker, or ``None`` on any failure. NEVER raises."""
        if not text or not text.strip():
            return None
        if self._service is None:
            logger.warning("AD-738g: no voice synthesis service on this runtime; degrading to browser")
            return None
        cfg = self._config
        python = resolve_executable_path(cfg.python_path)
        script = anchor_install_path(WORKER_SCRIPT)
        model = anchor_install_path(cfg.model_path)
        voices = anchor_install_path(cfg.voices_path)
        missing = [str(path) for path in (script, model, voices) if not path.is_file()]
        if python is None:
            missing.insert(0, str(anchor_install_path(cfg.python_path)))
        if python is None or missing:
            logger.warning(
                "AD-738g: kokoro is not installed (missing: %s); run scripts/kokoro-fetch.ps1 or set "
                "tts.kokoro.* (relative paths anchor to the ProbOS root); degrading to browser",
                ", ".join(missing),
            )
            return None
        voice = self.resolve_voice(voice_override)
        speed = kokoro_speed(cfg.speed, emotion)
        key = KokoroWorkerKey(
            python=str(python),
            script=str(script),
            model=str(model),
            voices=str(voices),
            threads=cfg.threads,
            default_voice=cfg.voice,
        )
        started = time.perf_counter()
        wav = await self._service.synthesize(key, text, cfg.timeout_seconds, fields={"voice": voice, "speed": speed})
        logger.info(
            "AD-738g: kokoro voice=%s speed=%.2f chars=%d synth_ms=%.0f result=%s",
            voice, speed, len(text), (time.perf_counter() - started) * 1000,
            "ok" if wav is not None else "degraded",
        )
        if wav is None:
            return None
        return TTSResult(audio_bytes=wav, mime="audio/wav")
