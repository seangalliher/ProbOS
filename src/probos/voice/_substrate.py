"""AD-474: Voice Interaction substrate — STT/TTS protocol seams.

Foundation cut. Provides ABCs for speech recognition and text-to-speech
plus a browser-friendly default that proxies through the HXI's WebSocket
(real backends ship in AD-474a Whisper, AD-474b Deepgram, etc.).

Voice pipeline target: wake word -> STT -> intent -> TTS. v1 ships the
seam shapes only; runtime wiring is the forcing function for AD-474c.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptionResult:
    """One STT recognition event."""
    text: str
    confidence: float
    is_final: bool
    language: str = "en-US"


@runtime_checkable
class SpeechRecognizer(Protocol):
    """Speech-to-text backend protocol."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def transcribe(self, audio_bytes: bytes) -> TranscriptionResult: ...


@runtime_checkable
class WakeWordDetector(Protocol):
    """Wake-word listener (e.g. Porcupine, OpenWakeWord)."""

    @property
    def wake_word(self) -> str: ...
    async def listen_once(self, audio_bytes: bytes) -> bool: ...


@runtime_checkable
class TextToSpeech(Protocol):
    """TTS synthesizer protocol."""

    async def synthesize(self, text: str, *, voice: str = "default") -> bytes: ...


class BrowserSpeechRecognizer:
    """AD-474 default — relies on browser-side Web Speech API.

    The runtime side does no transcription; transcripts arrive over the
    HXI WebSocket as ``{"type": "voice_transcript", "text": ...}``
    messages and are fed back into the chat path.
    """

    def __init__(self, *, language: str = "en-US") -> None:
        self.language = language
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        # Browser does the work; runtime-side stub returns empty.
        return TranscriptionResult(text="", confidence=0.0, is_final=False, language=self.language)


class SilentTextToSpeech:
    """No-op TTS — returns empty bytes so callers can no-op gracefully."""

    async def synthesize(self, text: str, *, voice: str = "default") -> bytes:
        return b""


class StaticWakeWordDetector:
    """Fixed-string wake-word matcher — case-insensitive substring on
    pre-transcribed text. Real wake-word ML models (Porcupine,
    OpenWakeWord) ship in AD-474a.
    """

    def __init__(self, *, wake_word: str = "computer") -> None:
        self._wake_word = wake_word.lower()

    @property
    def wake_word(self) -> str:
        return self._wake_word

    async def listen_once(self, audio_bytes: bytes) -> bool:
        # Default detector cannot work from raw bytes; callers feed
        # the transcribed text instead via ``check_text``.
        return False

    def check_text(self, text: str) -> bool:
        if not text:
            return False
        return self._wake_word in text.lower()
