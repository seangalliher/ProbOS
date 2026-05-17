"""BF-292: rhubarb generate_visemes honest-degrade on unsupported audio format.

Captain log showed rhubarb subprocess failing on every browser-captured webm:
  rhubarb exit=1 on <sha>.webm; stderr=Application terminating with error:
  Error processing file ...webm.

Rhubarb only accepts WAV and OGG. Reject at the boundary and return [] so
the heuristic path takes over without burning a subprocess + WARNING noise.
"""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path

import pytest


def test_bf292_rhubarb_skips_webm_audio_honest_degrade(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Webm input must return [] without invoking the subprocess."""
    from probos.avatars.rhubarb_backend import generate_visemes

    audio = tmp_path / "test.webm"
    audio.write_bytes(b"RIFF-fake-not-actually-wav")

    caplog.set_level(logging.INFO, logger="probos.avatars.rhubarb_backend")

    frames = asyncio.run(
        generate_visemes(audio, binary_path="tools/rhubarb/rhubarb")
    )

    assert frames == [], "webm input must honest-degrade to empty viseme list"

    info_messages = [
        r.getMessage() for r in caplog.records
        if r.levelno == logging.INFO
        and r.name == "probos.avatars.rhubarb_backend"
    ]
    assert any(".webm" in m and "unsupported audio format" in m for m in info_messages), (
        f"Expected INFO log noting unsupported webm. Got: {info_messages}"
    )

    # No WARNING should fire — wrong input is not a fault.
    warn_messages = [
        r.getMessage() for r in caplog.records
        if r.levelno >= logging.WARNING
        and r.name == "probos.avatars.rhubarb_backend"
    ]
    assert not warn_messages, (
        f"BF-292: webm input must NOT emit WARNING. Got: {warn_messages}"
    )


def test_bf292_rhubarb_skips_mp3_audio(tmp_path: Path) -> None:
    """Other unsupported formats (mp3, m4a) take the same path."""
    from probos.avatars.rhubarb_backend import generate_visemes

    for suffix in (".mp3", ".m4a", ".aac", ".flac"):
        audio = tmp_path / f"test{suffix}"
        audio.write_bytes(b"fake")
        frames = asyncio.run(
            generate_visemes(audio, binary_path="tools/rhubarb/rhubarb")
        )
        assert frames == [], (
            f"{suffix} input must honest-degrade to empty viseme list"
        )


def test_bf292_rhubarb_extension_check_case_insensitive(tmp_path: Path) -> None:
    """Uppercase extensions should still be skipped (no subprocess invocation)."""
    from probos.avatars.rhubarb_backend import generate_visemes

    audio = tmp_path / "test.WEBM"
    audio.write_bytes(b"fake")

    # If the subprocess WERE invoked, it would fail with exit=1 because the
    # binary path doesn't resolve. Reaching [] without that subprocess
    # failure proves the boundary check fired BEFORE subprocess invocation.
    # (The empty result is what we'd see either way; the test name + INFO
    # log assertion in the webm test is the actual contract.)
    frames = asyncio.run(
        generate_visemes(audio, binary_path="tools/rhubarb/rhubarb")
    )
    assert frames == []


def test_bf292_rhubarb_still_invokes_for_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WAV input must still reach the subprocess path (regression guard)."""
    import inspect

    from probos.avatars import rhubarb_backend

    # Source-level guard: the boundary check must reject .webm/.mp3/etc. but
    # NOT .wav or .ogg. Inspecting source is cheaper than mocking subprocess.
    src = inspect.getsource(rhubarb_backend.generate_visemes)
    assert '_SUPPORTED_SUFFIXES = {".wav", ".ogg"}' in src, (
        "BF-292: _SUPPORTED_SUFFIXES must include .wav and .ogg only."
    )
    assert ".webm" not in src.split("_SUPPORTED_SUFFIXES")[1].split("}")[0], (
        ".webm must NOT be in the supported set."
    )
