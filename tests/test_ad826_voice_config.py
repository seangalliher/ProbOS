"""AD-826 — whisper-first STT priority config + health endpoint."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from probos.config import CognitiveConfig, SystemConfig
from probos.routers import voice as voice_router
from probos.settings.section_registry import get_section


class _FakeRuntime:
    """Minimal real-shape runtime stand-in (BF-287 — not MagicMock)."""

    def __init__(self, data_dir: Path, config: SystemConfig | None = None) -> None:
        self.config = config if config is not None else SystemConfig()
        self.data_dir = data_dir


def _make_client(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(voice_router.router)
    app.dependency_overrides[voice_router.get_runtime] = lambda: runtime
    app.dependency_overrides[voice_router.require_crew_scope] = lambda: None
    return TestClient(app)


def test_primary_stt_default_whisper() -> None:
    config = SystemConfig()
    assert config.cognitive.primary_stt == "whisper"


def test_primary_stt_accepts_browser() -> None:
    cfg = CognitiveConfig(primary_stt="browser")
    assert cfg.primary_stt == "browser"


def test_primary_stt_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        CognitiveConfig(primary_stt="azure")  # type: ignore[arg-type]


def test_fallback_stt_enabled_default_true() -> None:
    assert SystemConfig().cognitive.fallback_stt_enabled is True


def test_primary_stt_registered_in_section_registry() -> None:
    section = get_section("llm_tiers")
    assert section is not None
    ids = {f.field_id for f in section.fields}
    assert "cognitive.primary_stt" in ids
    assert "cognitive.fallback_stt_enabled" in ids


def test_voice_health_endpoint_whisper_primary_unhealthy(tmp_path: Path) -> None:
    """Default config: whisper primary, no model on disk → unhealthy."""
    runtime = _FakeRuntime(tmp_path)
    # offline_stt_enabled defaults to False AND no model file → unhealthy.
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "primary_stt": "whisper",
        "engine": "whisper",
        "backend_available": False,
        "healthy": False,
    }


def test_voice_health_endpoint_whisper_primary_healthy(tmp_path: Path) -> None:
    """offline_stt_enabled + model file present → healthy."""
    config = SystemConfig()
    config.cognitive.offline_stt_enabled = True
    # whisper_model_path default is "whisper/ggml-tiny.en.bin" relative to data_dir.
    model_path = tmp_path / "whisper" / "ggml-tiny.en.bin"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"fake ggml weights")
    runtime = _FakeRuntime(tmp_path, config)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["primary_stt"] == "whisper"
    assert data["engine"] == "whisper"
    assert data["backend_available"] is True
    assert data["healthy"] is True


def test_voice_health_endpoint_browser_primary_always_healthy(tmp_path: Path) -> None:
    """primary_stt=browser → healthy regardless of artifact state."""
    config = SystemConfig()
    config.cognitive.primary_stt = "browser"
    # offline_stt_enabled stays False, no model file on disk.
    runtime = _FakeRuntime(tmp_path, config)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["primary_stt"] == "browser"
    assert data["engine"] == "browser"
    assert data["backend_available"] is False
    assert data["healthy"] is True
