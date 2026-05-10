"""ProbOS voice package.

- :mod:`probos.voice._substrate` (re-exported here): AD-474 STT/TTS protocol
  seams (``BrowserSpeechRecognizer``, ``SilentTextToSpeech``,
  ``TranscriptionResult``, ``StaticWakeWordDetector``).
- :mod:`probos.voice.proposal` (AD-718a): hardened parser for agent-authored
  voice proposals (``parse_voice_proposal``, ``VoiceProposalError``).
"""

from probos.voice._substrate import (
    BrowserSpeechRecognizer,
    SilentTextToSpeech,
    SpeechRecognizer,
    StaticWakeWordDetector,
    TextToSpeech,
    TranscriptionResult,
    WakeWordDetector,
)
from probos.voice.proposal import (
    VoiceProposalError,
    parse_voice_proposal,
)

__all__ = [
    "BrowserSpeechRecognizer",
    "SilentTextToSpeech",
    "SpeechRecognizer",
    "StaticWakeWordDetector",
    "TextToSpeech",
    "TranscriptionResult",
    "VoiceProposalError",
    "WakeWordDetector",
    "parse_voice_proposal",
]
