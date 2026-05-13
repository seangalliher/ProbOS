"""AD-721b-1 (Wave 155): rhubarb-lip-sync backend tests.

Covers:
  - Backend availability + version probe (3 tests)
  - Subprocess + JSON parsing (4 tests)
  - Viseme mapping (1 test)
  - Endpoint integration (4 tests)
  - Boundary tests (2 tests)
  - Mime allow-list regression (2 tests)
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.attachments.mime import validate_attachment_bytes
from probos.avatars import rhubarb_backend
from probos.avatars.rhubarb_backend import (
    VisemeFrame,
    _map_preston_blair_to_oculus,
    _resolve_binary_path,
    generate_visemes,
    is_available,
)
from probos.config import AttachmentsConfig, LipSyncConfig, SystemConfig
from probos.routers.deps import get_runtime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubProcess:
    """Mimics asyncio.subprocess.Process for tests.

    Configurable: returncode, stdout, stderr, and an optional "hang" flag that
    causes communicate() to await asyncio.sleep(60) (so asyncio.wait_for can
    cancel it).
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

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            import asyncio
            await asyncio.sleep(60)
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


def _make_subprocess_factory(stub: _StubProcess):
    async def _factory(*_args, **_kwargs):
        return stub

    return _factory


# ---------------------------------------------------------------------------
# Backend availability + version probe (3 tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_available_false_when_binary_missing(caplog):
    """Binary path does not exist → returns False, logs INFO. No exception."""
    caplog.set_level(logging.INFO, logger="probos.avatars.rhubarb_backend")
    result = await is_available("/definitely/not/a/real/binary/rhubarb")
    assert result is False
    assert any(
        "rhubarb binary not found" in rec.message for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_is_available_false_when_version_probe_times_out(
    monkeypatch, tmp_path, caplog
):
    """Cross-platform: monkeypatch subprocess to hang; is_available returns False."""
    caplog.set_level(logging.WARNING, logger="probos.avatars.rhubarb_backend")
    fake_bin = tmp_path / "rhubarb"
    fake_bin.write_bytes(b"")
    # Pretend the binary exists (Path.is_file will return True on the real file).
    stub = _StubProcess(hang=True)
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _make_subprocess_factory(stub),
    )
    result = await is_available(str(fake_bin), timeout_seconds=0.2)
    assert result is False
    assert stub.killed is True
    assert any(
        "--version timed out" in rec.message for rec in caplog.records
    )


def test_resolve_binary_path_appends_exe_on_windows(monkeypatch, tmp_path):
    """On Windows, when the literal path lacks .exe but a sibling .exe exists,
    _resolve_binary_path returns the .exe path."""
    monkeypatch.setattr(sys, "platform", "win32")
    fake_exe = tmp_path / "rhubarb.exe"
    fake_exe.write_bytes(b"")
    resolved = _resolve_binary_path(str(tmp_path / "rhubarb"))
    assert resolved is not None
    assert resolved.name == "rhubarb.exe"
    assert resolved.is_file()


# ---------------------------------------------------------------------------
# Subprocess + JSON parsing (4 tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_visemes_subprocess_timeout_returns_empty(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level(logging.WARNING, logger="probos.avatars.rhubarb_backend")
    fake_bin = tmp_path / "rhubarb"
    fake_bin.write_bytes(b"")
    audio = tmp_path / "capture.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVEdata")
    stub = _StubProcess(hang=True)
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _make_subprocess_factory(stub),
    )
    frames = await generate_visemes(audio, str(fake_bin), timeout_seconds=0.2)
    assert frames == []
    assert stub.killed is True
    assert any("timed out" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_generate_visemes_malformed_json_returns_empty(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level(logging.WARNING, logger="probos.avatars.rhubarb_backend")
    fake_bin = tmp_path / "rhubarb"
    fake_bin.write_bytes(b"")
    audio = tmp_path / "capture.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    stub = _StubProcess(returncode=0, stdout=b"not json {{")
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _make_subprocess_factory(stub),
    )
    frames = await generate_visemes(audio, str(fake_bin))
    assert frames == []
    assert any("malformed JSON" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_generate_visemes_missing_mouthCues_returns_empty(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level(logging.WARNING, logger="probos.avatars.rhubarb_backend")
    fake_bin = tmp_path / "rhubarb"
    fake_bin.write_bytes(b"")
    audio = tmp_path / "capture.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    stub = _StubProcess(returncode=0, stdout=b'{"metadata": {}}')
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _make_subprocess_factory(stub),
    )
    frames = await generate_visemes(audio, str(fake_bin))
    assert frames == []
    assert any("missing mouthCues" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_generate_visemes_happy_path_maps_visemes(monkeypatch, tmp_path):
    fake_bin = tmp_path / "rhubarb"
    fake_bin.write_bytes(b"")
    audio = tmp_path / "capture.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    payload = {
        "mouthCues": [
            {"start": 0.0, "end": 0.12, "value": "X"},
            {"start": 0.12, "end": 0.30, "value": "D"},
            {"start": 0.30, "end": 0.45, "value": "A"},
        ]
    }
    stub = _StubProcess(returncode=0, stdout=json.dumps(payload).encode("utf-8"))
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _make_subprocess_factory(stub),
    )
    frames = await generate_visemes(audio, str(fake_bin))
    assert len(frames) == 3
    assert frames[0].time == 0.0
    assert frames[0].viseme == "sil"
    assert frames[1].time == 0.12
    assert frames[1].viseme == "aa"
    assert frames[2].time == 0.30
    assert frames[2].viseme == "PP"
    # Monotonic time
    times = [f.time for f in frames]
    assert times == sorted(times)


# ---------------------------------------------------------------------------
# Viseme mapping (1 test)
# ---------------------------------------------------------------------------


def test_map_preston_blair_to_oculus_covers_all_9_shapes(caplog):
    caplog.set_level(logging.WARNING, logger="probos.avatars.rhubarb_backend")
    expected = {
        "A": "PP", "B": "kk", "C": "E", "D": "aa", "E": "oh",
        "F": "ou", "G": "FF", "H": "RR", "X": "sil",
    }
    valid_oculus = {
        "sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR",
        "aa", "E", "ih", "oh", "ou",
    }
    for pb, expected_oculus in expected.items():
        mapped = _map_preston_blair_to_oculus(pb)
        assert mapped == expected_oculus
        assert mapped in valid_oculus
    # Forward-compat fallback.
    assert _map_preston_blair_to_oculus("Z") == "sil"
    assert any(
        "unknown Preston Blair viseme" in rec.message for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# Endpoint integration (4 tests)
# ---------------------------------------------------------------------------


@pytest.fixture
async def avatar_client(monkeypatch, tmp_path):
    """Build a FastAPI app wrapping the /api/avatars router with a stub runtime.

    Each test can override `rt.config.lipsync` to exercise the three backend
    branches (disabled/heuristic/rhubarb).
    """
    import probos.routers.avatars as avatars_router_mod
    import probos.routers.chat as chat_router_mod

    target = tmp_path / "attachments"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "probos.attachments.store._resolve_attachments_dir",
        lambda configured: target,
    )

    cfg_attach = AttachmentsConfig(attachments_dir=str(target))
    cfg_lipsync = LipSyncConfig()  # heuristic default
    rt = SimpleNamespace(
        config=SimpleNamespace(attachments=cfg_attach, lipsync=cfg_lipsync),
    )

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()

    a = FastAPI()
    a.include_router(avatars_router_mod.router)
    a.dependency_overrides[get_runtime] = lambda: rt

    store = FilesystemAttachmentStore(target)

    async def _write(blob: bytes, mime: str) -> str:
        sha = hashlib.sha256(blob).hexdigest()
        await store.write(sha, blob, mime)
        return sha

    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, rt, _write

    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


@pytest.mark.asyncio
async def test_endpoint_returns_disabled_when_lipsync_disabled(avatar_client):
    ac, rt, _write = avatar_client
    rt.config.lipsync = LipSyncConfig(enabled=False)
    # Even an unstored id is fine — short-circuit before lookup.
    resp = await ac.post(
        "/api/avatars/lipsync",
        json={"attachment_id": "a" * 64},
    )
    assert resp.status_code == 200
    assert resp.json() == {"backend": "disabled", "frames": []}


@pytest.mark.asyncio
async def test_endpoint_returns_heuristic_when_backend_configured_heuristic(
    avatar_client, monkeypatch
):
    ac, _rt, _write = avatar_client
    sha = await _write(b"RIFF\x00\x00\x00\x00WAVEpayload", "audio/wav")

    # generate_visemes MUST NOT be called on the heuristic branch.
    called: list[bool] = []

    async def _explode(*_a, **_kw):
        called.append(True)
        raise AssertionError("generate_visemes called on heuristic backend")

    monkeypatch.setattr(
        "probos.avatars.rhubarb_backend.generate_visemes",
        _explode,
    )
    resp = await ac.post(
        "/api/avatars/lipsync",
        json={"attachment_id": sha},
    )
    assert resp.status_code == 200
    assert resp.json() == {"backend": "heuristic", "frames": []}
    assert called == []


@pytest.mark.asyncio
async def test_endpoint_invalid_attachment_id_returns_400(avatar_client):
    ac, _rt, _write = avatar_client
    resp = await ac.post(
        "/api/avatars/lipsync",
        json={"attachment_id": "not-hex"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_attachment_id"


@pytest.mark.asyncio
async def test_endpoint_unknown_attachment_id_returns_404(avatar_client):
    ac, _rt, _write = avatar_client
    resp = await ac.post(
        "/api/avatars/lipsync",
        json={"attachment_id": "0" * 64},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "attachment_not_found"


# ---------------------------------------------------------------------------
# Boundary tests (2 tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_visemes_empty_audio_file_returns_empty(
    monkeypatch, tmp_path, caplog
):
    caplog.set_level(logging.WARNING, logger="probos.avatars.rhubarb_backend")
    fake_bin = tmp_path / "rhubarb"
    fake_bin.write_bytes(b"")
    audio = tmp_path / "empty.wav"
    audio.write_bytes(b"")  # 0 bytes; rhubarb refuses
    stub = _StubProcess(
        returncode=1,
        stdout=b"",
        stderr=b"rhubarb: input file is empty",
    )
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _make_subprocess_factory(stub),
    )
    frames = await generate_visemes(audio, str(fake_bin))
    assert frames == []
    assert any(
        "exit=1" in rec.message and "rhubarb: input file is empty" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_generate_visemes_filters_inverted_time_ranges(
    monkeypatch, tmp_path
):
    fake_bin = tmp_path / "rhubarb"
    fake_bin.write_bytes(b"")
    audio = tmp_path / "capture.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    payload = {
        "mouthCues": [
            {"start": 0.0, "end": 0.10, "value": "X"},
            # Inverted range — must be skipped.
            {"start": 0.30, "end": 0.10, "value": "D"},
            {"start": 0.30, "end": 0.40, "value": "A"},
        ]
    }
    stub = _StubProcess(returncode=0, stdout=json.dumps(payload).encode("utf-8"))
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        _make_subprocess_factory(stub),
    )
    frames = await generate_visemes(audio, str(fake_bin))
    # Inverted cue skipped; only the two valid cues remain.
    assert len(frames) == 2
    assert frames[0].viseme == "sil"
    assert frames[1].viseme == "PP"


# ---------------------------------------------------------------------------
# Mime allow-list regression — Section 0.5 (2 tests)
# ---------------------------------------------------------------------------


def test_attachments_default_allows_audio_webm_and_wav():
    """AD-721b-1 Section 0.5a: defaults include the two browser-capture mimes."""
    cfg = AttachmentsConfig()
    assert "audio/webm" in cfg.allowed_mime_types
    assert "audio/wav" in cfg.allowed_mime_types
    # Original 9 still present.
    for legacy in (
        "image/png", "image/jpeg", "image/webp", "image/gif",
        "application/pdf", "text/plain", "text/markdown",
        "application/json", "text/csv",
    ):
        assert legacy in cfg.allowed_mime_types


def test_validate_attachment_bytes_accepts_audio_mime_magic_bytes():
    """AD-721b-1 Section 0.5b: EBML and RIFF/WAVE magic bytes are accepted."""
    # (a) WebM — EBML magic at offset 0.
    ok, mime = validate_attachment_bytes(
        b"\x1a\x45\xdf\xa3rest_of_container_bytes", "audio/webm"
    )
    assert ok is True
    assert mime == "audio/webm"
    # (b) WAV — RIFF at offset 0, WAVE at offset 8.
    ok, mime = validate_attachment_bytes(
        b"RIFF\x00\x00\x00\x00WAVErest_of_chunks", "audio/wav"
    )
    assert ok is True
    assert mime == "audio/wav"
    # Negative: WebM declared but magic bytes don't match.
    ok, reason = validate_attachment_bytes(b"not-a-webm-at-all", "audio/webm")
    assert ok is False
    assert reason == "header_mismatch"
