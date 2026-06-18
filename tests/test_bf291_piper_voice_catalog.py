"""BF-291 / AD-738f — Piper voice catalog endpoint + per-call voice override.

Covers:
1. ``GET /api/avatars/tts/voices`` enumerates locally-installed Piper voices
   from ``tools/piper/voices/`` and returns only entries with BOTH
   ``<name>.onnx`` and ``<name>.onnx.json`` files present.
2. ``POST /api/avatars/tts`` accepts an optional ``voice_name`` field that
   is threaded through to ``backend.synthesize(voice_override=...)``.
3. Path-traversal in ``voice_name`` is rejected at the boundary.
4. PiperBackend.synthesize honours ``voice_override`` when the override
   resolves and falls back silently to the configured voice when it
   doesn't.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _make_runtime_with_tts(
    *,
    enabled: bool = True,
    backend: str = "piper",
    voice_model: str = "en_US-amy-medium",
    voices_dir: str | None = None,
) -> Any:
    """Minimal runtime stub for the avatars router."""

    tts_cfg = SimpleNamespace(
        enabled=enabled,
        backend=backend,
        voice_model=voice_model,
        binary_path="tools/piper/piper.exe",
        voices_dir=voices_dir or "tools/piper/voices",
        timeout_seconds=10.0,
        noise_scale=0.85,
        length_scale=0.92,
        noise_w=1.0,
        sentence_silence=0.35,
    )
    config = SimpleNamespace(
        tts=tts_cfg,
        lipsync=SimpleNamespace(enabled=False, backend="heuristic"),
        attachments=SimpleNamespace(enabled=True),
    )
    return SimpleNamespace(
        config=config,
        registry=SimpleNamespace(get=lambda _id: None, all=lambda: []),
    )


def _make_app(runtime: Any):
    from probos.api import create_app
    return create_app(runtime)


# --------------------------------------------------------------------------- #
# 1. /tts/voices enumeration                                                  #
# --------------------------------------------------------------------------- #


def test_bf291_tts_voices_lists_only_complete_pairs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Voices with a missing .onnx.json sidecar must NOT appear in the list."""
    voices_dir = tmp_path / "assets" / "voices"
    voices_dir.mkdir(parents=True)
    # Complete pair — should appear.
    (voices_dir / "en_US-foo-medium.onnx").write_bytes(b"x" * 1024)
    (voices_dir / "en_US-foo-medium.onnx.json").write_text("{}")
    # Orphan onnx, missing sidecar — must be filtered out.
    (voices_dir / "en_US-orphan-medium.onnx").write_bytes(b"x" * 1024)

    # AD-1025a: the listing resolves the configured (absolute) voices_dir,
    # NOT the CWD. chdir somewhere WITHOUT the voices to prove independence.
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    runtime = _make_runtime_with_tts(voices_dir=str(voices_dir))
    client = TestClient(_make_app(runtime))
    resp = client.get("/api/avatars/tts/voices")
    assert resp.status_code == 200
    data = resp.json()
    assert data["backend"] == "piper"
    names = [v["name"] for v in data["voices"]]
    assert "en_US-foo-medium" in names
    assert "en_US-orphan-medium" not in names


def test_bf291_tts_voices_parses_lang_voice_quality(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    voices_dir = tmp_path / "assets" / "voices"
    voices_dir.mkdir(parents=True)
    (voices_dir / "en_GB-cori-high.onnx").write_bytes(b"x" * 2048)
    (voices_dir / "en_GB-cori-high.onnx.json").write_text("{}")

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    runtime = _make_runtime_with_tts(voices_dir=str(voices_dir))
    client = TestClient(_make_app(runtime))
    resp = client.get("/api/avatars/tts/voices")
    assert resp.status_code == 200
    [entry] = resp.json()["voices"]
    assert entry["name"] == "en_GB-cori-high"
    assert entry["lang"] == "en_GB"
    assert entry["voice"] == "cori"
    assert entry["quality"] == "high"
    assert entry["size_mb"] >= 0


def test_bf291_tts_voices_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    # Configured (absolute) voices dir does not exist → empty list.
    missing = tmp_path / "assets" / "voices"
    runtime = _make_runtime_with_tts(voices_dir=str(missing))
    client = TestClient(_make_app(runtime))
    resp = client.get("/api/avatars/tts/voices")
    assert resp.status_code == 200
    assert resp.json()["voices"] == []


def test_bf291_tts_voices_reports_current_voice_model(tmp_path: Path) -> None:
    runtime = _make_runtime_with_tts(
        voice_model="en_US-ryan-medium",
        voices_dir=str(tmp_path / "assets" / "voices"),
    )
    client = TestClient(_make_app(runtime))
    resp = client.get("/api/avatars/tts/voices")
    assert resp.status_code == 200
    assert resp.json()["current"] == "en_US-ryan-medium"


def test_ad1025a_voice_listing_anchors_relative_dir_to_install_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AD-1025a: the default RELATIVE voices_dir ('tools/piper/voices') anchors
    to the ProbOS install root, not the CWD — reproduces the launch-from-a-
    sibling-folder incident where the picker showed no voices."""
    import probos.audio.tts.piper_backend as pb

    fake_root = tmp_path / "install_root"
    voices_dir = fake_root / "tools" / "piper" / "voices"
    voices_dir.mkdir(parents=True)
    (voices_dir / "en_US-amy-medium.onnx").write_bytes(b"x" * 1024)
    (voices_dir / "en_US-amy-medium.onnx.json").write_text("{}")
    monkeypatch.setattr(pb, "_probos_root", lambda: fake_root)

    # CWD is a sibling folder WITHOUT tools/piper/voices (the incident).
    cwd = tmp_path / "sibling"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    runtime = _make_runtime_with_tts()  # default relative voices_dir
    client = TestClient(_make_app(runtime))
    resp = client.get("/api/avatars/tts/voices")
    assert resp.status_code == 200
    names = [v["name"] for v in resp.json()["voices"]]
    assert "en_US-amy-medium" in names


# --------------------------------------------------------------------------- #
# 2. POST /tts forwards voice_name to backend.synthesize                      #
# --------------------------------------------------------------------------- #


def test_bf291_tts_endpoint_forwards_voice_name_to_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _CaptureBackend:
        name = "capture"
        async def synthesize(self, text, emotion=None, voice_override=None):
            captured["text"] = text
            captured["emotion"] = emotion
            captured["voice_override"] = voice_override
            return None  # honest-degrade — endpoint returns disabled shape

    def _fake_select(_backend, _cfg):
        return _CaptureBackend()

    monkeypatch.setattr("probos.audio.tts.select_backend", _fake_select)

    runtime = _make_runtime_with_tts()
    client = TestClient(_make_app(runtime))
    resp = client.post(
        "/api/avatars/tts",
        json={"text": "hello", "voice_name": "en_US-ryan-medium"},
    )
    assert resp.status_code == 200
    assert captured["voice_override"] == "en_US-ryan-medium"


def test_bf291_tts_endpoint_strips_path_traversal_voice_name(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _CaptureBackend:
        name = "capture"
        async def synthesize(self, text, emotion=None, voice_override=None):
            captured["voice_override"] = voice_override
            return None

    monkeypatch.setattr("probos.audio.tts.select_backend", lambda b, c: _CaptureBackend())

    runtime = _make_runtime_with_tts()
    client = TestClient(_make_app(runtime))

    for evil in ("../../etc/passwd", "..\\..\\secrets", "voices/foo"):
        captured.clear()
        resp = client.post(
            "/api/avatars/tts",
            json={"text": "hello", "voice_name": evil},
        )
        assert resp.status_code == 200
        assert captured["voice_override"] is None, (
            f"voice_name {evil!r} must be rejected at the boundary"
        )


def test_bf291_tts_endpoint_omits_voice_override_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _CaptureBackend:
        name = "capture"
        async def synthesize(self, text, emotion=None, voice_override=None):
            captured["voice_override"] = voice_override
            return None

    monkeypatch.setattr("probos.audio.tts.select_backend", lambda b, c: _CaptureBackend())

    runtime = _make_runtime_with_tts()
    client = TestClient(_make_app(runtime))
    resp = client.post("/api/avatars/tts", json={"text": "hello"})
    assert resp.status_code == 200
    assert captured["voice_override"] is None


# --------------------------------------------------------------------------- #
# 3. PiperBackend honours voice_override when resolvable                      #
# --------------------------------------------------------------------------- #


def test_bf291_piper_backend_signature_accepts_voice_override() -> None:
    """PiperBackend.synthesize must accept the new kwarg (Protocol contract)."""
    import inspect

    from probos.audio.tts.piper_backend import PiperBackend

    sig = inspect.signature(PiperBackend.synthesize)
    assert "voice_override" in sig.parameters, (
        "BF-291: PiperBackend.synthesize must accept voice_override kwarg."
    )
    # Default must be None so existing callers (Wave 157 / AD-738e-1 sites)
    # continue to work without modification.
    assert sig.parameters["voice_override"].default is None


def test_bf291_null_backend_accepts_voice_override() -> None:
    """NullBackend mirror — Protocol compat."""
    from probos.audio.tts.null_backend import NullBackend

    # Round-trip — must not raise.
    result = asyncio.run(NullBackend().synthesize("hi", voice_override="en_US-ryan-medium"))
    assert result is None
