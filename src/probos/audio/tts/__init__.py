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
            noise_scale=config.noise_scale,
            length_scale=config.length_scale,
            noise_w=config.noise_w,
            sentence_silence=config.sentence_silence,
        )
    if backend_name == "browser":
        return NullBackend()
    logger.warning(
        "AD-738: unknown TTS backend %r; degrading to NullBackend (browser path)",
        backend_name,
    )
    return NullBackend()


__all__ = ["TTSBackend", "TTSResult", "NullBackend", "PiperBackend", "select_backend"]
