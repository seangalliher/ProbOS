"""AD-721b-1a (Wave 166) - ffmpeg-backed audio format conversion tests.

BF-280: subprocess.Popen + loop.run_in_executor (not asyncio.create_subprocess).
BF-282: ffmpeg writes to a tempfile via -y <path>, NOT captured on stdout.
BF-286: subprocess shape mirrors production via stubbed subprocess.Popen
that records args and returns a fake process object.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from probos.avatars.rhubarb_backend import (
    _convert_to_wav,
    _resolve_ffmpeg_binary,
    generate_visemes,
)
from probos.config import LipSyncConfig


# ---------------------------------------------------------------------------
# Section 2: _resolve_ffmpeg_binary
# ---------------------------------------------------------------------------


def test_resolve_ffmpeg_binary_missing_returns_none(tmp_path: Path) -> None:
    assert _resolve_ffmpeg_binary(str(tmp_path / "nope")) is None
    assert _resolve_ffmpeg_binary("") is None


def test_resolve_ffmpeg_binary_present_returns_path(tmp_path: Path) -> None:
    f = tmp_path / "ffmpeg"
    f.write_bytes(b"#!/bin/sh\n")
    resolved = _resolve_ffmpeg_binary(str(f))
    assert resolved is not None
    assert resolved.resolve() == f.resolve()


def test_resolve_ffmpeg_binary_windows_exe_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("probos.avatars.rhubarb_backend.sys.platform", "win32")
    exe = tmp_path / "ffmpeg.exe"
    exe.write_bytes(b"\x4d\x5a")  # MZ header
    resolved = _resolve_ffmpeg_binary(str(tmp_path / "ffmpeg"))
    assert resolved is not None
    assert resolved.resolve() == exe.resolve()


# ---------------------------------------------------------------------------
# Section 3: _convert_to_wav
# ---------------------------------------------------------------------------


class _FakePopen:
    """BF-286 mirror: records args + emulates Popen.communicate / returncode."""

    instances: list["_FakePopen"] = []

    def __init__(
        self,
        args: list[str],
        *,
        stdout: Any = None,
        stderr: Any = None,
        output_bytes: bytes = b"RIFFfake_wav_data",
        returncode: int = 0,
        raise_timeout: bool = False,
    ) -> None:
        self.args = args
        self.returncode = returncode
        self._output_bytes = output_bytes
        self._raise_timeout = raise_timeout
        self._killed = False
        _FakePopen.instances.append(self)

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        if self._raise_timeout:
            raise subprocess.TimeoutExpired(self.args, timeout or 0)
        # ffmpeg's last positional arg is the output file path.
        out_path = Path(self.args[-1])
        if self.returncode == 0:
            out_path.write_bytes(self._output_bytes)
        return b"", b"" if self.returncode == 0 else b"ffmpeg fake error"

    def kill(self) -> None:
        self._killed = True

    def wait(self) -> int:
        return self.returncode


def _make_popen_factory(**defaults: Any):
    def _factory(args: list[str], **kwargs: Any) -> _FakePopen:
        merged = {**defaults, **kwargs}
        merged.pop("stdout", None)
        merged.pop("stderr", None)
        return _FakePopen(args, **merged)
    return _factory


@pytest.fixture(autouse=True)
def _reset_popen_log() -> None:
    _FakePopen.instances.clear()


@pytest.mark.asyncio
async def test_convert_to_wav_success_creates_tempfile(tmp_path: Path) -> None:
    src = tmp_path / "input.webm"
    src.write_bytes(b"webm bytes")
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"#!/bin/sh\n")
    factory = _make_popen_factory(returncode=0, output_bytes=b"RIFFwavedata")
    with patch("probos.avatars.rhubarb_backend.subprocess.Popen", side_effect=factory):
        out = await _convert_to_wav(src, ffmpeg)
    assert out is not None
    assert out.exists()
    assert out.stat().st_size > 0
    # BF-282 contract: ffmpeg invocation wrote to a tempfile (last positional).
    invocation = _FakePopen.instances[0]
    assert invocation.args[0] == str(ffmpeg)
    assert "-i" in invocation.args
    assert invocation.args[-1] == str(out)
    out.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_convert_to_wav_timeout_returns_none_and_cleans_up_tempfile(
    tmp_path: Path,
) -> None:
    src = tmp_path / "input.webm"
    src.write_bytes(b"webm bytes")
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"#!/bin/sh\n")
    factory = _make_popen_factory(raise_timeout=True)
    # Track tempfile names created so we can assert cleanup after.
    created: list[Path] = []
    real_named = Path
    with patch("probos.avatars.rhubarb_backend.subprocess.Popen", side_effect=factory):
        out = await _convert_to_wav(src, ffmpeg, timeout_seconds=0.5)
    assert out is None
    # The Popen.args[-1] was the output tempfile path; it must not leak.
    assert _FakePopen.instances[0]._killed is True  # noqa: SLF001
    leaked = Path(_FakePopen.instances[0].args[-1])
    assert not leaked.exists()


@pytest.mark.asyncio
async def test_convert_to_wav_nonzero_exit_returns_none(tmp_path: Path) -> None:
    src = tmp_path / "input.webm"
    src.write_bytes(b"webm bytes")
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"#!/bin/sh\n")
    factory = _make_popen_factory(returncode=1)
    with patch("probos.avatars.rhubarb_backend.subprocess.Popen", side_effect=factory):
        out = await _convert_to_wav(src, ffmpeg)
    assert out is None
    leaked = Path(_FakePopen.instances[0].args[-1])
    assert not leaked.exists()


# ---------------------------------------------------------------------------
# Section 4: generate_visemes integration with ffmpeg path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_visemes_webm_with_ffmpeg_converts_and_processes(
    tmp_path: Path,
) -> None:
    src = tmp_path / "client.webm"
    src.write_bytes(b"fake webm bytes")
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"#!/bin/sh\n")
    rhubarb = tmp_path / "rhubarb"
    rhubarb.write_bytes(b"#!/bin/sh\n")

    converted_paths: list[Path] = []

    # ffmpeg writes a "wav" payload; rhubarb returns a small JSON schedule.
    def factory(args: list[str], **kwargs: Any) -> _FakePopen:
        is_ffmpeg = args[0] == str(ffmpeg)
        if is_ffmpeg:
            popen = _FakePopen(args, output_bytes=b"RIFFfakewav", returncode=0)
            converted_paths.append(Path(args[-1]))
            return popen
        # rhubarb: stdout JSON
        rh = _FakePopen(args, returncode=0)
        rh._output_bytes = b""

        def _communicate(timeout: float | None = None) -> tuple[bytes, bytes]:
            return (
                b'{"mouthCues":[{"start":0.0,"end":0.1,"value":"X"}]}',
                b"",
            )
        rh.communicate = _communicate  # type: ignore[method-assign]
        return rh

    with patch("probos.avatars.rhubarb_backend.subprocess.Popen", side_effect=factory):
        frames = await generate_visemes(
            src,
            binary_path=str(rhubarb),
            ffmpeg_binary_path=str(ffmpeg),
        )

    # Two subprocess invocations: ffmpeg then rhubarb.
    assert len(_FakePopen.instances) == 2
    assert _FakePopen.instances[0].args[0] == str(ffmpeg)
    assert _FakePopen.instances[1].args[0] == str(rhubarb)
    # Converted tempfile must be unlinked in finally.
    assert converted_paths
    assert not converted_paths[0].exists()


@pytest.mark.asyncio
async def test_generate_visemes_webm_without_ffmpeg_honest_degrades(
    tmp_path: Path,
) -> None:
    """BF-292 contract preserved when ffmpeg path is empty / missing."""
    src = tmp_path / "client.webm"
    src.write_bytes(b"fake webm bytes")
    rhubarb = tmp_path / "rhubarb"
    rhubarb.write_bytes(b"#!/bin/sh\n")
    frames = await generate_visemes(
        src,
        binary_path=str(rhubarb),
        ffmpeg_binary_path=None,
    )
    assert frames == []
    # ffmpeg path is missing too - same honest-degrade.
    frames = await generate_visemes(
        src,
        binary_path=str(rhubarb),
        ffmpeg_binary_path=str(tmp_path / "does-not-exist"),
    )
    assert frames == []


# ---------------------------------------------------------------------------
# Config exposure
# ---------------------------------------------------------------------------


def test_lipsync_config_exposes_ffmpeg_binary_path_default() -> None:
    cfg = LipSyncConfig()
    assert cfg.ffmpeg_binary_path == "tools/ffmpeg/ffmpeg"
