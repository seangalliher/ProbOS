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

    async def synthesize(
        self,
        text: str,
        emotion: str | None = None,
        voice_override: str | None = None,
    ) -> TTSResult | None:
        """Synthesize ``text`` to audio bytes. Return ``None`` on any failure.

        AD-738e-1: ``emotion`` is an optional v1 ``EmotionalIntent`` name
        (lowercase) used to apply per-emotion prosody overrides. ``None``
        or unknown names keep backend defaults (additive guarantee).

        BF-291 / AD-738f: ``voice_override`` is an optional voice-model
        name (e.g. ``en_US-ryan-medium``). When set and resolvable under
        ``tools/piper/voices/``, the backend uses that voice for THIS
        call only (no instance mutation). Unknown / unresolvable falls
        back to the configured ``tts.voice_model`` silently.
        """
        ...
