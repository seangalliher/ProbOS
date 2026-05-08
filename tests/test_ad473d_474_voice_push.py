"""AD-473d + AD-474: tests for Web Push registry + voice substrate."""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# AD-473d
# ---------------------------------------------------------------------------


def test_push_registry_register_and_count() -> None:
    from probos.web_push import PushSubscriptionRegistry
    r = PushSubscriptionRegistry()
    r.register(endpoint="https://push.example/abc", keys={"p256dh": "x", "auth": "y"}, subscriber_id="captain")
    assert r.count() == 1
    assert r.for_subscriber("captain")[0].endpoint == "https://push.example/abc"


def test_push_registry_register_rejects_empty_endpoint() -> None:
    from probos.web_push import PushSubscriptionRegistry
    r = PushSubscriptionRegistry()
    with pytest.raises(ValueError):
        r.register(endpoint="", keys={})


def test_push_registry_unregister() -> None:
    from probos.web_push import PushSubscriptionRegistry
    r = PushSubscriptionRegistry()
    r.register(endpoint="e1", keys={"p": "x"})
    assert r.unregister("e1") is True
    assert r.unregister("e1") is False
    assert r.count() == 0


def test_push_registry_replace_same_endpoint() -> None:
    from probos.web_push import PushSubscriptionRegistry
    r = PushSubscriptionRegistry()
    r.register(endpoint="e1", keys={"p": "x"}, subscriber_id="a")
    r.register(endpoint="e1", keys={"p": "y"}, subscriber_id="b")
    assert r.count() == 1
    assert r.all_subscriptions()[0].subscriber_id == "b"


# ---------------------------------------------------------------------------
# AD-474
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browser_speech_recognizer_lifecycle() -> None:
    from probos.voice import BrowserSpeechRecognizer
    r = BrowserSpeechRecognizer()
    await r.start()
    assert r._started is True
    result = await r.transcribe(b"unused")
    assert result.text == ""
    await r.stop()
    assert r._started is False


@pytest.mark.asyncio
async def test_silent_tts_returns_empty_bytes() -> None:
    from probos.voice import SilentTextToSpeech
    tts = SilentTextToSpeech()
    out = await tts.synthesize("hello")
    assert out == b""


def test_static_wake_word_detector_matches_text() -> None:
    from probos.voice import StaticWakeWordDetector
    d = StaticWakeWordDetector(wake_word="Computer")
    assert d.wake_word == "computer"
    assert d.check_text("Computer, status?") is True
    assert d.check_text("hello there") is False


def test_static_wake_word_detector_empty_returns_false() -> None:
    from probos.voice import StaticWakeWordDetector
    d = StaticWakeWordDetector()
    assert d.check_text("") is False


def test_protocols_are_runtime_checkable() -> None:
    from probos.voice import (
        BrowserSpeechRecognizer,
        SilentTextToSpeech,
        SpeechRecognizer,
        TextToSpeech,
    )
    assert isinstance(BrowserSpeechRecognizer(), SpeechRecognizer)
    assert isinstance(SilentTextToSpeech(), TextToSpeech)


@pytest.mark.asyncio
async def test_transcription_result_fields() -> None:
    from probos.voice import TranscriptionResult
    r = TranscriptionResult(text="hello", confidence=0.9, is_final=True)
    assert r.text == "hello"
    assert r.confidence == 0.9
    assert r.is_final is True
    assert r.language == "en-US"
