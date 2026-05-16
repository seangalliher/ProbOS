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

    async def synthesize(
        self,
        text: str,
        emotion: str | None = None,
        voice_override: str | None = None,
    ) -> TTSResult | None:
        """No-op. Returns ``None`` for honest-degrade.

        AD-738e-1: ``emotion`` accepted for Protocol compat; ignored.
        BF-291 / AD-738f: ``voice_override`` accepted for Protocol compat;
        ignored because the null backend produces no audio.
        """
        del emotion, voice_override
        return None
