"""AD-738 (Wave 157): Server-streamed TTS via Piper — backend + endpoint tests."""

from __future__ import annotations

import hashlib
import logging
import struct
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.audio.tts import (
    NullBackend,
    PiperBackend,
    TTSResult,
    select_backend,
)
from probos.audio.tts.piper_backend import _resolve_binary_path, _resolve_voice_model
from probos.config import AttachmentsConfig, LipSyncConfig, TTSConfig
from probos.routers.deps import get_runtime
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubProcess:
    """Mimics subprocess.Popen for tests.

    BF-286 (2026-05-13): PiperBackend migrated from
    ``asyncio.create_subprocess_exec`` to ``subprocess.Popen + run_in_executor``
    (BF-280 WindowsSelectorEventLoop) and from stdout to a ``--output_file``
    tempfile (BF-282 Windows text-mode corruption). The stub now mirrors the
    sync subprocess.Popen shape AND writes ``stdout`` to the ``--output_file``
    path if one is present in the args, so the production code reads it back.
    """

    def __init__(
        self,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        hang: bool = False,
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._hang = hang
        self.killed = False
        self._output_file_path: str | None = None  # set by _make_subprocess_factory

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
        if self._hang and timeout is not None:
            import subprocess as _sub
            raise _sub.TimeoutExpired(cmd="stub-piper", timeout=timeout)
        # BF-282 simulation: production code passes --output_file <tmp_path>
        # and reads bytes back from the file. If we have such a path, write
        # the configured stdout payload there.
        if self._output_file_path is not None and self._stdout:
            from pathlib import Path as _Path
            try:
                _Path(self._output_file_path).write_bytes(self._stdout)
            except OSError:
                pass
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode


def _make_subprocess_factory(stub: _StubProcess):
    """Returns a sync callable that replaces subprocess.Popen.

    Captures ``--output_file`` path from args so the stub can simulate
    BF-282's file-write behavior.
    """
    def _factory(args, *_pos, **_kwargs):
        if isinstance(args, (list, tuple)):
            try:
                idx = list(args).index("--output_file")
                stub._output_file_path = (
                    args[idx + 1] if idx + 1 < len(args) else None
                )
            except ValueError:
                pass
        return stub
    return _factory


def _make_minimal_wav(num_samples: int = 16000, sample_rate: int = 16000) -> bytes:
    """Build a minimal canonical-format mono 16-bit PCM WAV blob."""
    bits_per_sample = 16
    num_channels = 1
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)
    data_size = num_samples * block_align
    fmt_chunk = struct.pack(
        "<4sIHHIIHH",
        b"fmt ", 16, 1, num_channels, sample_rate, byte_rate, block_align, bits_per_sample,
    )
    data_chunk = struct.pack("<4sI", b"data", data_size) + b"\x00" * data_size
    riff_size = 4 + len(fmt_chunk) + len(data_chunk)
    return struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE") + fmt_chunk + data_chunk


def _setup_voice_model(voices_dir: Path, voice_model: str = "test-voice") -> None:
    voices_dir.mkdir(parents=True, exist_ok=True)
    (voices_dir / f"{voice_model}.onnx").write_bytes(b"\x00")
    (voices_dir / f"{voice_model}.onnx.json").write_bytes(b"{}")


# ---------------------------------------------------------------------------
# NullBackend + select_backend (3 tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_null_backend_returns_none():
    assert await NullBackend().synthesize("hi") is None
    assert await NullBackend().synthesize("") is None


def test_select_backend_browser_returns_null():
    cfg = TTSConfig()
    backend = select_backend("browser", cfg)
    assert isinstance(backend, NullBackend)


def test_select_backend_piper_returns_piper():
    cfg = TTSConfig(backend="piper")
    backend = select_backend("piper", cfg)
    assert isinstance(backend, PiperBackend)


def test_select_backend_unknown_degrades_to_null(caplog):
    caplog.set_level(logging.WARNING, logger="probos.audio.tts")
    cfg = TTSConfig()
    backend = select_backend("xyz", cfg)
    assert isinstance(backend, NullBackend)
    assert any("unknown TTS backend" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# PiperBackend (7 tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_piper_backend_missing_binary_returns_none(caplog):
    caplog.set_level(logging.WARNING, logger="probos.audio.tts.piper_backend")
    backend = PiperBackend(
        binary_path="/definitely/not/a/real/path/piper",
        voice_model="en_US-amy-medium",
    )
    assert await backend.synthesize("hi") is None
    assert any("piper binary not found" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_piper_backend_missing_voice_model_returns_none(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level(logging.WARNING, logger="probos.audio.tts.piper_backend")
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    # Voice model dir empty.
    monkeypatch.chdir(tmp_path)
    backend = PiperBackend(
        binary_path=str(fake_bin),
        voice_model="missing-voice",
    )
    assert await backend.synthesize("hi") is None
    assert any("piper voice model" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_piper_backend_empty_text_short_circuits(monkeypatch, tmp_path):
    spawned: list[bool] = []

    def _fail_factory(*_a, **_k):
        spawned.append(True)
        raise AssertionError("subprocess should not be spawned for empty text")

    monkeypatch.setattr("subprocess.Popen", _fail_factory)
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    backend = PiperBackend(binary_path=str(fake_bin), voice_model="x")
    assert await backend.synthesize("") is None
    assert await backend.synthesize("   ") is None
    assert spawned == []


@pytest.mark.asyncio
async def test_piper_backend_subprocess_timeout_returns_none(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level(logging.WARNING, logger="probos.audio.tts.piper_backend")
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    _setup_voice_model(tmp_path / "tools" / "piper" / "voices", "v")
    stub = _StubProcess(hang=True)
    monkeypatch.setattr(
        "subprocess.Popen",
        _make_subprocess_factory(stub),
    )
    backend = PiperBackend(
        binary_path=str(fake_bin), voice_model="v", timeout_seconds=0.2,
    )
    assert await backend.synthesize("hello") is None
    assert stub.killed is True
    assert any("piper timed out" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_piper_backend_nonzero_exit_returns_none(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level(logging.WARNING, logger="probos.audio.tts.piper_backend")
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    _setup_voice_model(tmp_path / "tools" / "piper" / "voices", "v")
    stub = _StubProcess(returncode=1, stdout=b"", stderr=b"piper: bad model")
    monkeypatch.setattr(
        "subprocess.Popen",
        _make_subprocess_factory(stub),
    )
    backend = PiperBackend(binary_path=str(fake_bin), voice_model="v")
    assert await backend.synthesize("hi") is None
    assert any(
        "piper exit=1" in r.message and "piper: bad model" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_piper_backend_zero_bytes_returns_none(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level(logging.WARNING, logger="probos.audio.tts.piper_backend")
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    _setup_voice_model(tmp_path / "tools" / "piper" / "voices", "v")
    stub = _StubProcess(returncode=0, stdout=b"", stderr=b"")
    monkeypatch.setattr(
        "subprocess.Popen",
        _make_subprocess_factory(stub),
    )
    backend = PiperBackend(binary_path=str(fake_bin), voice_model="v")
    assert await backend.synthesize("hi") is None
    assert any("0 bytes" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_piper_backend_happy_path_returns_wav(monkeypatch, tmp_path):
    fake_bin = tmp_path / "piper"
    fake_bin.write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    _setup_voice_model(tmp_path / "tools" / "piper" / "voices", "v")
    wav = _make_minimal_wav(num_samples=8000, sample_rate=16000)
    stub = _StubProcess(returncode=0, stdout=wav, stderr=b"")
    monkeypatch.setattr(
        "subprocess.Popen",
        _make_subprocess_factory(stub),
    )
    backend = PiperBackend(binary_path=str(fake_bin), voice_model="v")
    result = await backend.synthesize("hello world")
    assert result is not None
    assert result.mime == "audio/wav"
    assert result.audio_bytes == wav


def test_resolve_binary_path_appends_exe_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    fake_exe = tmp_path / "piper.exe"
    fake_exe.write_bytes(b"")
    resolved = _resolve_binary_path(str(tmp_path / "piper"))
    assert resolved is not None
    assert resolved.name == "piper.exe"


def test_resolve_voice_model_requires_both_files(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    voices = tmp_path / "tools" / "piper" / "voices"
    voices.mkdir(parents=True)
    # Only the .onnx file — no .onnx.json → must return None.
    (voices / "x.onnx").write_bytes(b"")
    assert _resolve_voice_model("x") is None
    (voices / "x.onnx.json").write_bytes(b"{}")
    resolved = _resolve_voice_model("x")
    assert resolved is not None
    assert resolved.name == "x.onnx"


# ---------------------------------------------------------------------------
# WAV duration parser (2 tests)
# ---------------------------------------------------------------------------


def test_wav_duration_ms_parses_canonical_header():
    wav = _make_minimal_wav(num_samples=16000, sample_rate=16000)
    assert avatars_router_mod._wav_duration_ms(wav) == 1000


def test_wav_duration_ms_returns_zero_on_malformed():
    assert avatars_router_mod._wav_duration_ms(b"garbage") == 0
    assert avatars_router_mod._wav_duration_ms(b"") == 0
    assert avatars_router_mod._wav_duration_ms(b"RIFF" + b"\x00" * 40) == 0


# ---------------------------------------------------------------------------
# Endpoint integration (8 tests)
# ---------------------------------------------------------------------------


@pytest.fixture
async def avatar_client(monkeypatch, tmp_path):
    target = tmp_path / "attachments"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "probos.attachments.store._resolve_attachments_dir",
        lambda configured: target,
    )

    cfg_attach = AttachmentsConfig(attachments_dir=str(target))
    cfg_lipsync = LipSyncConfig()  # heuristic default
    cfg_tts = TTSConfig()  # browser default
    rt = SimpleNamespace(
        config=SimpleNamespace(
            attachments=cfg_attach,
            lipsync=cfg_lipsync,
            tts=cfg_tts,
        ),
    )

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()

    a = FastAPI()
    a.include_router(avatars_router_mod.router)
    a.dependency_overrides[get_runtime] = lambda: rt

    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, rt

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


@pytest.mark.asyncio
async def test_status_endpoint_returns_browser_default(avatar_client):
    ac, _rt = avatar_client
    resp = await ac.get("/api/avatars/tts/status")
    assert resp.status_code == 200
    assert resp.json() == {"enabled": True, "backend": "browser"}


@pytest.mark.asyncio
async def test_status_endpoint_returns_piper_when_configured(avatar_client):
    ac, rt = avatar_client
    rt.config.tts = TTSConfig(backend="piper")
    resp = await ac.get("/api/avatars/tts/status")
    assert resp.status_code == 200
    assert resp.json() == {"enabled": True, "backend": "piper"}


@pytest.mark.asyncio
async def test_status_endpoint_when_tts_attr_missing(monkeypatch, tmp_path):
    target = tmp_path / "attachments"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "probos.attachments.store._resolve_attachments_dir",
        lambda configured: target,
    )
    rt = SimpleNamespace(
        config=SimpleNamespace(
            attachments=AttachmentsConfig(attachments_dir=str(target)),
            lipsync=LipSyncConfig(),
            # Note: NO tts attr.
        ),
    )
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    a = FastAPI()
    a.include_router(avatars_router_mod.router)
    a.dependency_overrides[get_runtime] = lambda: rt
    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/avatars/tts/status")
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False, "backend": "browser"}
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


@pytest.mark.asyncio
async def test_endpoint_tts_disabled_returns_disabled(avatar_client):
    ac, rt = avatar_client
    rt.config.tts = TTSConfig(enabled=False, backend="piper")
    resp = await ac.post("/api/avatars/tts", json={"text": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "disabled"
    assert body["audio_attachment_id"] is None
    assert body["visemes"] == []


@pytest.mark.asyncio
async def test_endpoint_tts_browser_backend_returns_disabled(avatar_client, monkeypatch):
    """Default config: backend=browser → endpoint is a no-op.
    Tightens Recommended #6: assert select_backend is NOT called and no
    subprocess is spawned."""
    ac, _rt = avatar_client
    select_calls: list[str] = []
    spawned: list[bool] = []

    def _fake_select(name, cfg):
        select_calls.append(name)
        return select_backend(name, cfg)

    async def _fail_factory(*_a, **_kw):
        spawned.append(True)
        raise AssertionError("subprocess should not be spawned on browser path")

    monkeypatch.setattr("probos.audio.tts.select_backend", _fake_select)
    monkeypatch.setattr("subprocess.Popen", _fail_factory)

    resp = await ac.post("/api/avatars/tts", json={"text": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "disabled"
    assert select_calls == []
    assert spawned == []


@pytest.mark.asyncio
async def test_endpoint_tts_invalid_text_400(avatar_client):
    ac, rt = avatar_client
    rt.config.tts = TTSConfig(backend="piper")
    for bad in ("", "   ", None, 123, []):
        resp = await ac.post("/api/avatars/tts", json={"text": bad})
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid_text"


@pytest.mark.asyncio
async def test_endpoint_tts_text_too_long_413(avatar_client):
    ac, rt = avatar_client
    rt.config.tts = TTSConfig(backend="piper")
    resp = await ac.post("/api/avatars/tts", json={"text": "x" * 4097})
    assert resp.status_code == 413
    assert resp.json()["detail"] == "text_too_long"


@pytest.mark.asyncio
async def test_endpoint_tts_honest_degrade_when_backend_returns_none(
    avatar_client, monkeypatch
):
    ac, rt = avatar_client
    rt.config.tts = TTSConfig(backend="piper")

    class _NoneBackend:
        name = "piper"
        async def synthesize(self, text):
            return None

    monkeypatch.setattr(
        "probos.audio.tts.select_backend",
        lambda name, cfg: _NoneBackend(),
    )
    resp = await ac.post("/api/avatars/tts", json={"text": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "disabled"
    assert body["audio_attachment_id"] is None


@pytest.mark.asyncio
async def test_endpoint_tts_happy_path_returns_attachment_and_visemes(
    avatar_client, monkeypatch
):
    """Stub backend returns valid WAV; rhubarb stub returns 2 frames."""
    ac, rt = avatar_client
    rt.config.tts = TTSConfig(backend="piper")
    rt.config.lipsync = LipSyncConfig(backend="rhubarb")

    wav = _make_minimal_wav(num_samples=16000, sample_rate=16000)
    expected_sha = hashlib.sha256(wav).hexdigest()

    class _StubBackend:
        name = "piper"
        async def synthesize(self, text):
            return TTSResult(audio_bytes=wav, mime="audio/wav")

    from probos.avatars.rhubarb_backend import VisemeFrame

    async def _stub_visemes(*_a, **_kw):
        return [
            VisemeFrame(time=0.0, duration=0.1, viseme="aa"),
            VisemeFrame(time=0.1, duration=0.2, viseme="oh"),
        ]

    monkeypatch.setattr(
        "probos.audio.tts.select_backend",
        lambda name, cfg: _StubBackend(),
    )
    monkeypatch.setattr(
        "probos.avatars.rhubarb_backend.generate_visemes",
        _stub_visemes,
    )

    resp = await ac.post("/api/avatars/tts", json={"text": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "piper"
    # AD-731 invariant: response carries content-addressable ref, NOT bytes.
    assert body["audio_attachment_id"] == expected_sha
    assert len(body["audio_attachment_id"]) == 64
    assert all(c in "0123456789abcdef" for c in body["audio_attachment_id"])
    assert body["mime"] == "audio/wav"
    assert "audio_bytes" not in body
    assert "audio_base64" not in body
    assert len(body["visemes"]) == 2
    assert body["visemes"][0] == {"time": 0.0, "duration": 0.1, "viseme": "aa"}
    assert body["duration_ms"] == 1000


@pytest.mark.asyncio
async def test_endpoint_tts_omits_visemes_when_lipsync_heuristic(
    avatar_client, monkeypatch
):
    ac, rt = avatar_client
    rt.config.tts = TTSConfig(backend="piper")
    # lipsync is heuristic by default
    wav = _make_minimal_wav(num_samples=8000, sample_rate=16000)

    class _StubBackend:
        name = "piper"
        async def synthesize(self, text):
            return TTSResult(audio_bytes=wav, mime="audio/wav")

    called: list[bool] = []

    async def _explode(*_a, **_kw):
        called.append(True)
        raise AssertionError("generate_visemes called on heuristic backend")

    monkeypatch.setattr(
        "probos.audio.tts.select_backend",
        lambda name, cfg: _StubBackend(),
    )
    monkeypatch.setattr(
        "probos.avatars.rhubarb_backend.generate_visemes",
        _explode,
    )
    resp = await ac.post("/api/avatars/tts", json={"text": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "piper"
    assert body["visemes"] == []
    assert body["audio_attachment_id"] is not None
    assert called == []


@pytest.mark.asyncio
async def test_endpoint_tts_invalid_body_400(avatar_client):
    ac, rt = avatar_client
    rt.config.tts = TTSConfig(backend="piper")
    resp = await ac.post(
        "/api/avatars/tts",
        content=b"[]",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_body"
