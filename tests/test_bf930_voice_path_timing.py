"""BF-930 (#1668): timing lines of the spoken-reply path (the attachment store, the resident synthesizer, the TTS route).

Synthetic fixtures only: stubs that sleep 30 ms, a fixed fixture, no live figure. The cases marked ``built`` fail on the
base at their own assert and pass once M2 is applied; ``BF930_RUNXFAIL=1`` runs them as plain cases.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import importlib
import importlib.util
import logging
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.attachments import filesystem_store
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.attachments.store import AttachmentStoreFullError
from probos.audio.tts import TTSResult
from probos.audio.tts import resident
from probos.audio.tts.resident import PiperOutcome, PiperWorker, PiperWorkerKey, VoiceSynthesisService
from probos.avatars.rhubarb_backend import VisemeFrame
from probos.config import AttachmentsConfig, LipSyncConfig, TTSConfig
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.security.pii_redaction import PIIRedactor

built = (
    (lambda func: func)
    if os.environ.get("BF930_RUNXFAIL") == "1"
    else pytest.mark.xfail(raises=AssertionError, strict=True)
)

_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 32
_WRITE = "BF-930: attachment write slow"
_FIND = "BF-930: attachment find slow"
_PIPER = "BF-930: piper request slow"
_STORE_LOGGER = "probos.attachments.filesystem_store"
_VOICE_LOGGER = "probos.audio.tts.resident"


def _helper():
    spec = importlib.util.find_spec("probos.utils.step_timing")
    assert spec is not None, "the helper does not exist yet"
    return importlib.import_module("probos.utils.step_timing")


def _lines(caplog, marker: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if marker in r.getMessage()]


def _field(line: str, name: str) -> str:
    found = re.search(rf"\b{name}=(\S+)", line)
    assert found, f"{name} missing from {line!r}"
    return found.group(1)


def _one(lines: list[str]) -> str:
    assert len(lines) == 1, f"expected exactly one line, found {len(lines)}"
    return lines[0]


def _last(lines: list[str]) -> str:
    assert lines, "no such line was written"
    return lines[-1]


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _key() -> PiperWorkerKey:
    return PiperWorkerKey(
        binary="piper", model="m.onnx", noise_scale=0.85, length_scale=1.0, noise_w=1.0, sentence_silence=0.35,
    )


def _slow_index(monkeypatch: pytest.MonkeyPatch, seconds: float = 0.03) -> None:
    real = FilesystemAttachmentStore._save_index_sync

    def slow(self) -> None:
        time.sleep(seconds)
        real(self)

    monkeypatch.setattr(FilesystemAttachmentStore, "_save_index_sync", slow)


def _stub_request(monkeypatch: pytest.MonkeyPatch, delay: float = 0.03, outcome: PiperOutcome | None = None) -> None:
    def request(self, text, timeout):
        time.sleep(delay)
        return outcome or PiperOutcome(b"WAV", "ok")

    monkeypatch.setattr(PiperWorker, "_request", request)


# --- the helper -------------------------------------------------------------------------------


@built
def test_h1_ms_between_is_milliseconds_and_never_negative() -> None:
    step = _helper()
    assert step.ms_between(1.0, 1.5) == 500.0
    assert step.ms_between(2.0, 1.0) == 0.0


@built
def test_h2_emit_line_writes_one_info_line_and_says_so(caplog) -> None:
    step = _helper()
    logger = logging.getLogger("bf930.test.h2")
    caplog.set_level(logging.INFO, logger="bf930.test.h2")
    assert step.emit_line(logger, "BF-930: probe a=%d", 7) is True
    records = [r for r in caplog.records if r.name == "bf930.test.h2"]
    assert [r.getMessage() for r in records] == ["BF-930: probe a=7"] and records[0].levelno == logging.INFO


@built
def test_h3_a_spent_budget_declines_lines_and_the_next_line_written_says_how_many(caplog) -> None:
    step = _helper()
    now = [0.0]
    logger = logging.getLogger("bf930.test.h3")
    caplog.set_level(logging.INFO, logger="bf930.test.h3")
    lines = step.TimingLines(logger, max_lines=2, window_s=60.0, clock=lambda: now[0])
    assert [lines.emit("BF-930: probe") for _ in range(3)] == [True, True, False]
    now[0] = 61.0
    assert lines.emit("BF-930: probe") is True
    texts = [r.getMessage() for r in caplog.records if r.name == "bf930.test.h3"]
    assert texts[-1].endswith("suppressed=1") and not any("suppressed" in t for t in texts[:-1])
    assert lines.emit("BF-930: probe") is True
    assert not [r.getMessage() for r in caplog.records if r.name == "bf930.test.h3"][-1].endswith("suppressed=1")


@built
def test_h4_a_budget_of_zero_is_unbounded(caplog) -> None:
    step = _helper()
    logger = logging.getLogger("bf930.test.h4")
    caplog.set_level(logging.INFO, logger="bf930.test.h4")
    lines = step.TimingLines(logger, max_lines=0)
    assert all(lines.emit("BF-930: probe") for _ in range(50))
    assert len([r for r in caplog.records if r.name == "bf930.test.h4"]) == 50


@built
def test_h5_a_logger_that_raises_never_reaches_the_caller() -> None:
    step = _helper()

    class _Broken:
        def __init__(self) -> None:
            self.debug_calls: list[bool] = []

        def info(self, *_a, **_k) -> None:
            raise RuntimeError("handler failed")

        def debug(self, *_a, **kwargs) -> None:
            self.debug_calls.append(bool(kwargs.get("exc_info")))

    broken = _Broken()
    assert step.emit_line(broken, "BF-930: probe") is False
    assert step.TimingLines(broken).emit("BF-930: probe") is False
    assert broken.debug_calls == [True, True]


# --- the attachment store ---------------------------------------------------------------------


@built
@pytest.mark.asyncio
async def test_t1_a_slow_write_reports_each_step(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_STORE_LOGGER)
    _slow_index(monkeypatch)
    store = FilesystemAttachmentStore(tmp_path)
    sha = _sha("t1")
    await store.write(sha, b"x", "audio/wav")
    line = _one(_lines(caplog, _WRITE))
    for name in ("total_ms", "lock_wait_ms", "locate_ms", "blob_ms", "index_ms", "index_entries", "bytes"):
        float(_field(line, name))
    assert _field(line, "id") == sha[:8] and _field(line, "origin") == "chat_attachment"
    assert _field(line, "behind") == "none" and _field(line, "index_entries") == "1"
    assert float(_field(line, "index_ms")) >= 25


@built
@pytest.mark.asyncio
@pytest.mark.parametrize("holder", ["write", "unlink"])
async def test_t2_a_write_that_waits_for_the_lock_names_what_it_waited_behind(tmp_path, monkeypatch, caplog, holder) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_STORE_LOGGER)
    store = FilesystemAttachmentStore(tmp_path)
    sha_a, sha_b = _sha("t2a"), _sha("t2b")
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    if holder == "write":
        real_locate = FilesystemAttachmentStore._locate_sync

        def slow_locate(self, content_hash, mime):
            loop.call_soon_threadsafe(entered.set)
            time.sleep(0.06)
            return real_locate(self, content_hash, mime)

        monkeypatch.setattr(FilesystemAttachmentStore, "_locate_sync", slow_locate)
        first = asyncio.create_task(store.write(sha_a, b"a", "audio/wav", origin="perception_frame"))
        expected = "write:perception_frame"
    else:
        await store.write(sha_a, b"a", "audio/wav")
        real_save = FilesystemAttachmentStore._save_index_sync

        def slow_save(self) -> None:
            loop.call_soon_threadsafe(entered.set)
            time.sleep(0.06)
            real_save(self)

        monkeypatch.setattr(FilesystemAttachmentStore, "_save_index_sync", slow_save)
        first = asyncio.create_task(store.unlink(sha_a))
        expected = "unlink"
    await asyncio.wait_for(entered.wait(), 5)
    await store.write(sha_b, b"b", "audio/wav")
    await first
    line = _one([text for text in _lines(caplog, _WRITE) if _field(text, "id") == sha_b[:8]])
    assert float(_field(line, "lock_wait_ms")) >= 25 and _field(line, "behind") == expected


@pytest.mark.asyncio
async def test_t3_a_fast_write_logs_nothing_and_changes_nothing(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO, logger=_STORE_LOGGER)
    store = FilesystemAttachmentStore(tmp_path)
    sha = _sha("t3")
    path = await store.write(sha, b"x", "audio/wav", origin="tts_audio")
    assert path == (tmp_path / f"{sha}.wav").resolve() and path.read_bytes() == b"x"
    assert store._index[sha]["origin"] == "tts_audio"  # noqa: SLF001
    assert store._lock.locked() is False  # noqa: SLF001
    assert not _lines(caplog, "BF-930:")


@built
@pytest.mark.asyncio
async def test_t4_a_slow_lookup_reports_its_time_and_the_index_size(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_STORE_LOGGER)
    store = FilesystemAttachmentStore(tmp_path)
    sha = _sha("t4")
    await store.write(sha, b"x", "audio/wav")
    assert await store.exists(sha) is True
    line = _last(_lines(caplog, _FIND))
    float(_field(line, "find_ms"))
    assert _field(line, "index_entries") == "1" and _field(line, "id") == sha[:8]


@built
@pytest.mark.asyncio
async def test_t5_the_stores_lines_are_bounded(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_STORE_LOGGER)
    store = FilesystemAttachmentStore(tmp_path)
    for seed in range(30):
        await store.write(_sha(f"t5-{seed}"), bytes([seed]), "audio/wav")
    assert len(_lines(caplog, _WRITE)) == 12


@pytest.mark.asyncio
async def test_t6_a_failed_write_logs_no_timing_line_and_raises_as_before(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_STORE_LOGGER)
    store = FilesystemAttachmentStore(tmp_path)

    def full(self, data):
        raise OSError(errno.ENOSPC, "no space")

    monkeypatch.setattr(Path, "write_bytes", full)
    with pytest.raises(AttachmentStoreFullError):
        await store.write(_sha("t6"), b"x", "audio/wav")
    assert not _lines(caplog, _WRITE)


# --- the resident synthesizer -----------------------------------------------------------------


@built
@pytest.mark.asyncio
async def test_t7_a_slow_synthesis_reports_its_steps(monkeypatch, caplog) -> None:
    monkeypatch.setattr(resident, "SLOW_SYNTHESIS_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_VOICE_LOGGER)
    _stub_request(monkeypatch)
    service = VoiceSynthesisService()
    try:
        assert await service.synthesize(_key(), "hello", 5.0) == b"WAV"
    finally:
        service.close()
    line = _one(_lines(caplog, _PIPER))
    for name in ("total_ms", "lock_wait_ms", "claim_ms", "pool_wait_ms", "work_ms", "resume_lag_ms", "in_flight", "chars"):
        float(_field(line, name))
    assert _field(line, "result") == "ok" and _field(line, "cold") in ("yes", "no")
    assert float(_field(line, "work_ms")) >= 25


@built
@pytest.mark.asyncio
async def test_t8_a_request_that_queues_for_the_voice_executor_reports_its_pool_wait(monkeypatch, caplog) -> None:
    monkeypatch.setattr(resident, "SLOW_SYNTHESIS_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_VOICE_LOGGER)
    _stub_request(monkeypatch, delay=0.0)
    service = VoiceSynthesisService(workers=1)
    try:
        service.executor.submit(time.sleep, 0.08)
        assert await service.synthesize(_key(), "hello", 5.0) == b"WAV"
    finally:
        service.close()
    assert float(_field(_last(_lines(caplog, _PIPER)), "pool_wait_ms")) >= 40


@built
@pytest.mark.asyncio
async def test_t9_a_request_that_waits_for_its_key_reports_its_lock_wait(monkeypatch, caplog) -> None:
    monkeypatch.setattr(resident, "SLOW_SYNTHESIS_MS", 0.0, raising=False)
    caplog.set_level(logging.INFO, logger=_VOICE_LOGGER)
    _stub_request(monkeypatch, delay=0.05)
    service = VoiceSynthesisService()
    try:
        await asyncio.gather(service.synthesize(_key(), "a", 5.0), service.synthesize(_key(), "b", 5.0))
    finally:
        service.close()
    texts = _lines(caplog, _PIPER)
    assert len(texts) == 2
    assert max(float(_field(text, "lock_wait_ms")) for text in texts) >= 25


@pytest.mark.asyncio
async def test_t10_the_audio_and_the_degrade_are_unchanged(monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING, logger=_VOICE_LOGGER)
    service = VoiceSynthesisService()
    try:
        _stub_request(monkeypatch, delay=0.0)
        assert await service.synthesize(_key(), "hello", 5.0) == b"WAV"
        _stub_request(monkeypatch, delay=0.0, outcome=PiperOutcome(None, "timeout"))
        assert await service.synthesize(_key(), "hello", 5.0) is None
        with service.admit() as admitted:
            assert admitted is True
    finally:
        service.close()
    assert "piper timed out" in caplog.text


# --- the route ----------------------------------------------------------------------------------


@pytest.fixture
async def voice_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    service = VoiceSynthesisService()
    rt = SimpleNamespace(
        config=SimpleNamespace(
            attachments=AttachmentsConfig(attachments_dir=str(target)),
            lipsync=LipSyncConfig(backend="rhubarb"),
            tts=TTSConfig(backend="piper"),
        ),
        voice_synthesis=service,
    )
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()

    class _StubBackend:
        name = "piper"

        async def synthesize(self, text, emotion=None, voice_override=None):
            return TTSResult(audio_bytes=_WAV, mime="audio/wav")

    async def _visemes(audio_path, **_kw):
        return [VisemeFrame(time=0.0, duration=0.1, viseme="aa")]

    monkeypatch.setattr("probos.avatars.rhubarb_backend.generate_visemes", _visemes)
    monkeypatch.setattr("probos.audio.tts.select_backend", lambda name, cfg, service=None: _StubBackend())
    app = FastAPI()
    app.include_router(avatars_router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    service.close()


@built
@pytest.mark.asyncio
async def test_t11_the_route_line_keeps_its_fields_and_gains_the_audio_id(voice_client, caplog) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.avatars")
    body = (await voice_client.post("/api/avatars/tts", json={"text": "hello", "defer_visemes": True})).json()
    [line] = _lines(caplog, "BF-918: tts route")
    order = [line.index(name) for name in ("synth_ms=", "store_ms=", "visemes_ms=", "total_ms=", "visemes=deferred", "audio_ms=")]
    assert order == sorted(order) and line.endswith(f"id={body['audio_attachment_id'][:8]}")
    assert [k for k, _v in re.findall(r"(\w+_ms)=(\d+)", line)] == ["synth_ms", "store_ms", "visemes_ms", "total_ms", "audio_ms"]


@built
@pytest.mark.asyncio
async def test_t12_one_stalled_store_is_visible_from_the_route_line_to_the_store_line(voice_client, monkeypatch, caplog) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    _slow_index(monkeypatch)
    caplog.set_level(logging.INFO)
    answer = await voice_client.post("/api/avatars/tts", json={"text": "hello", "defer_visemes": True})
    body = answer.json()
    assert answer.status_code == 200
    assert set(body) == {"backend", "audio_attachment_id", "mime", "visemes", "visemes_deferred", "duration_ms"}
    route = _one(_lines(caplog, "BF-918: tts route"))
    store = _one(_lines(caplog, _WRITE))
    assert _field(route, "id") == _field(store, "id") == body["audio_attachment_id"][:8]
    assert float(_field(route, "store_ms")) >= 25 and float(_field(store, "index_ms")) >= 25


@built
@pytest.mark.asyncio
async def test_t13_every_new_line_survives_the_log_redactor(voice_client, monkeypatch, caplog) -> None:
    monkeypatch.setattr(filesystem_store, "SLOW_STORE_CALL_MS", 0.0, raising=False)
    monkeypatch.setattr(resident, "SLOW_SYNTHESIS_MS", 0.0, raising=False)
    _slow_index(monkeypatch)
    _stub_request(monkeypatch)
    caplog.set_level(logging.INFO)
    await voice_client.post("/api/avatars/tts", json={"text": "hello", "defer_visemes": True})
    service = VoiceSynthesisService()
    try:
        await service.synthesize(_key(), "hello", 5.0)
    finally:
        service.close()
    texts = _lines(caplog, "BF-930:") + _lines(caplog, "BF-918: tts route")
    assert len(texts) >= 3  # the route line, the store's write line and the synthesizer's line
    assert all(PIIRedactor.redact_all(text) == text for text in texts)
