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
from collections.abc import Mapping
from types import MappingProxyType
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
#: AD-738f (#1868) S1: each crew role's own voice, keyed by ``agent_type`` so a roster change
#: keeps it: one voice per role, none the ship's ``af_heart``, the gender following each role's
#: archetype in ``voice_profile_defaults.py``. hexgrad/Kokoro-82M VOICES.md (read 2026-11-27)
#: grades the male voices lowest (``am_liam`` D, ``bm_lewis`` D+); ``tts.kokoro.agent_voices``
#: replaces any of them.
KOKORO_ROLE_VOICES: Mapping[str, str] = MappingProxyType({
    "counselor": "af_bella",
    "security_officer": "am_fenrir",
    "diagnostician": "am_michael",
    "pathologist": "bf_emma",
    "surgeon": "af_sarah",
    "pharmacist": "af_kore",
    "architect": "af_nicole",
    "data_analyst": "af_nova",
    "research_specialist": "af_aoede",
    "systems_analyst": "bf_isabella",
    "scout": "am_puck",
    "builder": "bm_george",
    "engineering_officer": "bm_lewis",
    "operations_officer": "bm_fable",
    "training_officer": "am_liam",
})


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

    def resolve_voice(self, voice_override: str | None, agent_type: str | None = None) -> str:
        """The voice for one call; the first match wins (AD-738f, #1868):

        1. ``voice_override`` when it is a catalogue id (the ``voice_name`` the request carries:
           a crew member's voice profile supplies it, saved or being sampled, set by an AD-718a
           proposal or a profile edit; under Kokoro the HXI picker lists browser voices); any other
           name (a Piper or browser voice name) is ignored;
        2. the Captain's ``tts.kokoro.agent_voices[agent_type]``;
        3. the built-in ``KOKORO_ROLE_VOICES[agent_type]``;
        4. ``tts.kokoro.voice``, the ship's voice (no role, or a role in neither map).
        """
        if voice_override is not None and voice_override in KOKORO_VOICES:
            return voice_override
        if agent_type is not None:
            if agent_type in self._config.agent_voices:
                return self._config.agent_voices[agent_type]
            if agent_type in KOKORO_ROLE_VOICES:
                return KOKORO_ROLE_VOICES[agent_type]
        return self._config.voice

    async def synthesize(
        self,
        text: str,
        emotion: str | None = None,
        voice_override: str | None = None,
        agent_type: str | None = None,
    ) -> TTSResult | None:
        """WAV bytes from the resident Kokoro worker, or ``None`` on any failure. NEVER raises.

        AD-738f (#1868): ``agent_type``, the speaking crew role, picks the role's voice
        (``resolve_voice``). The one resident worker serves every voice.
        """
        if not text or not text.strip():
            return None
        # AD-738f (#1868): the route sends only strings; anything else from a direct caller is
        # no role, no per-call voice and no emotion, so this method still never raises.
        role = agent_type if isinstance(agent_type, str) else None
        override = voice_override if isinstance(voice_override, str) else None
        voice = self.resolve_voice(override, role)
        speed = kokoro_speed(self._config.speed, emotion if isinstance(emotion, str) else None)
        started = time.perf_counter()
        wav = await self._speak(text, voice, speed)
        # D10: one line for every attempt, the early degradations in _speak included. The role
        # goes last (AD-738f, #1868), so the Captain can read which role spoke in which voice;
        # no agent id is logged.
        logger.info(
            "AD-738g: kokoro voice=%s speed=%.2f chars=%d synth_ms=%.0f result=%s role=%s",
            voice, speed, len(text), (time.perf_counter() - started) * 1000,
            "ok" if wav is not None else "degraded", role or "-",
        )
        if wav is None:
            return None
        return TTSResult(audio_bytes=wav, mime="audio/wav")

    async def _speak(self, text: str, voice: str, speed: float) -> bytes | None:
        """The worker's WAV bytes, or ``None`` after a WARNING: no service, an install path the
        OS cannot resolve or a missing file, or the service's own degradation. Never raises."""
        if self._service is None:
            logger.warning("AD-738g: no voice synthesis service on this runtime; degrading to browser")
            return None
        cfg = self._config
        try:
            python = resolve_executable_path(cfg.python_path)
            script = anchor_install_path(WORKER_SCRIPT)
            model = anchor_install_path(cfg.model_path)
            voices = anchor_install_path(cfg.voices_path)
            missing = [str(path) for path in (script, model, voices) if not path.is_file()]
            if python is None:
                missing.insert(0, str(anchor_install_path(cfg.python_path)))
        except (OSError, ValueError) as exc:  # Path.resolve on a path the OS cannot represent
            logger.warning(
                "AD-738g: a tts.kokoro path cannot be resolved (%s: %s); degrading to browser",
                type(exc).__name__, exc,
            )
            return None
        if python is None or missing:
            logger.warning(
                "AD-738g: kokoro is not installed (missing: %s); run scripts/kokoro-fetch.ps1 or set "
                "tts.kokoro.* (relative paths anchor to the ProbOS root); degrading to browser",
                ", ".join(missing),
            )
            return None
        key = KokoroWorkerKey(
            python=str(python),
            script=str(script),
            model=str(model),
            voices=str(voices),
            threads=cfg.threads,
            default_voice=cfg.voice,
        )
        return await self._service.synthesize(key, text, cfg.timeout_seconds, fields={"voice": voice, "speed": speed})
