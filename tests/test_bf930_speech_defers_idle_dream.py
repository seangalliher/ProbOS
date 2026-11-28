"""BF-930 (#1668) M2: a spoken reply holds off the idle full dream, within a bound.

Real ``DreamScheduler`` and its monitor loop, the real TTS route and attachment store;
the dreaming engine and the TTS backend are stand-ins. The scheduler's own rule is
driven with an injected ``now``; the monitor-loop tests wait on an event (a liveness
bound only) and assert no duration.
"""

from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.audio.tts import TTSResult
from probos.cognitive.dreaming import SPEECH_DREAM_DEFER_CAP_SECONDS, DreamScheduler
from probos.config import AttachmentsConfig, LipSyncConfig, TTSConfig
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.types import DreamReport

_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
_DREAMING = "probos.cognitive.dreaming"
_CAP = SPEECH_DREAM_DEFER_CAP_SECONDS


class _StubBackend:
    name = "piper"

    async def synthesize(self, text, emotion=None, voice_override=None):
        return TTSResult(audio_bytes=_WAV, mime="audio/wav")


def _scheduler() -> DreamScheduler:
    engine = MagicMock()
    engine.dream_cycle = AsyncMock(return_value=DreamReport())
    engine.proactive_procedure_scan = AsyncMock(return_value={})
    return DreamScheduler(
        engine, idle_threshold_seconds=3600.0, dream_interval_seconds=0.0, micro_dream_interval_seconds=0.0,
    )


@pytest.fixture
async def speech_client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    monkeypatch.setattr("probos.audio.tts.select_backend", lambda name, cfg, service=None: _StubBackend())
    scheduler = _scheduler()
    rt = SimpleNamespace(
        config=SimpleNamespace(
            attachments=AttachmentsConfig(attachments_dir=str(target)),
            lipsync=LipSyncConfig(backend="rhubarb"),
            tts=TTSConfig(backend="piper"),
        ),
        voice_synthesis=None,
        dream_scheduler=scheduler,
    )
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    app = FastAPI()
    app.include_router(avatars_router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, rt, scheduler
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


async def _speak(client: AsyncClient) -> None:
    response = await client.post("/api/avatars/tts", json={"text": "Yes, Captain.", "defer_visemes": True})
    assert response.status_code == 200
    assert isinstance(response.json()["audio_attachment_id"], str)


async def _monitor_two_ticks(scheduler: DreamScheduler) -> None:
    """Run the real monitor loop until its second micro dream: its first full-dream check has run by then."""
    ticks = 0
    second = asyncio.Event()

    async def _micro():
        nonlocal ticks
        ticks += 1
        if ticks >= 2:
            second.set()
        return {"episodes_replayed": 0}

    scheduler.engine.micro_dream = _micro
    scheduler._task = asyncio.create_task(scheduler._monitor_loop())  # not start(): it would reset the idle clock
    try:
        await asyncio.wait_for(second.wait(), timeout=60.0)  # liveness only
    finally:
        await scheduler.stop()


# --- the route to the monitor loop (the seam the defect crossed) ---------------------


@pytest.mark.asyncio
async def test_a_spoken_reply_keeps_a_due_idle_full_dream_from_starting(speech_client, caplog) -> None:
    client, _rt, scheduler = speech_client
    scheduler._last_activity_time = time.monotonic() - 7200.0  # idle for two hours: a full dream is due
    caplog.set_level(logging.INFO, logger=_DREAMING)

    await _speak(client)
    await _monitor_two_ticks(scheduler)

    assert scheduler.engine.dream_cycle.await_count == 0
    assert not any("BF-930: idle full dream starting" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_control_without_speech_the_due_idle_full_dream_starts_and_logs_start_and_finish(speech_client, caplog) -> None:
    _client, _rt, scheduler = speech_client
    scheduler._last_activity_time = time.monotonic() - 7200.0
    caplog.set_level(logging.INFO, logger=_DREAMING)

    await _monitor_two_ticks(scheduler)

    assert scheduler.engine.dream_cycle.await_count >= 1
    messages = [r.getMessage() for r in caplog.records if r.name == _DREAMING]
    assert any(m.startswith("BF-930: idle full dream starting idle_s=") for m in messages)
    assert any(m.startswith("BF-930: idle full dream finished duration_ms=") for m in messages)


@pytest.mark.asyncio
async def test_the_route_leaves_the_idle_clock_alone_once_a_stretch_is_past_the_cap(speech_client) -> None:
    client, _rt, scheduler = speech_client
    now = time.monotonic()
    scheduler._speech_since = now - _CAP - 1.0  # a stretch older than the cap ...
    scheduler._last_dream_time = now - _CAP - 2.0  # ... with no full dream since it began
    scheduler._last_activity_time = now - 7200.0

    await _speak(client)

    assert scheduler._last_activity_time == now - 7200.0


@pytest.mark.asyncio
async def test_a_runtime_without_a_scheduler_still_speaks(speech_client) -> None:
    client, rt, _scheduler = speech_client
    rt.dream_scheduler = None
    await _speak(client)


# --- the scheduler's rule, with an injected clock -------------------------------------


def test_speech_resets_the_idle_timer_until_its_stretch_reaches_the_cap() -> None:
    scheduler = _scheduler()
    assert scheduler.record_speech_activity(now=1000.0) is True
    assert scheduler._last_activity_time == 1000.0
    last = 1000.0 + _CAP - 1.0
    assert scheduler.record_speech_activity(now=last) is True
    assert scheduler.record_speech_activity(now=1000.0 + _CAP) is False
    assert scheduler._last_activity_time == last  # unchanged: the full dream is due idle_threshold_seconds later


def test_a_full_dream_after_the_stretch_began_starts_a_new_stretch() -> None:
    scheduler = _scheduler()
    scheduler.record_speech_activity(now=1000.0)
    late = 1000.0 + _CAP + 5.0
    assert scheduler.record_speech_activity(now=late) is False
    scheduler._last_dream_time = late + 10.0  # as the monitor loop sets it when a full dream completes
    assert scheduler.record_speech_activity(now=late + 20.0) is True
    assert scheduler._last_activity_time == late + 20.0


def test_the_first_reply_after_start_begins_a_stretch() -> None:
    scheduler = _scheduler()
    assert scheduler.record_speech_activity(now=5.0) is True  # _last_dream_time is 0.0 at construction
    assert scheduler.record_speech_activity(now=5.0 + _CAP) is False


def test_typed_activity_is_not_bounded_by_the_speech_cap() -> None:
    scheduler = _scheduler()
    scheduler.record_speech_activity(now=0.0)  # 0.0: below any time.monotonic() value, whatever the uptime
    scheduler.record_speech_activity(now=_CAP)  # refused: past the cap
    before = scheduler._last_activity_time
    scheduler.record_activity()
    assert scheduler._last_activity_time > before
