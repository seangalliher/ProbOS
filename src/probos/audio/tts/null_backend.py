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
