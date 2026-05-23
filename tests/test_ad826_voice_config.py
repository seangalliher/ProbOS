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


def test_primary_stt_default_transformers() -> None:
    """BF-301: default flipped from 'whisper' to 'transformers'."""
    config = SystemConfig()
    assert config.cognitive.primary_stt == "transformers"


def test_primary_stt_whisper_is_deprecated_alias() -> None:
    """BF-301: 'whisper' Literal value accepted (back-compat) but resolves to transformers in health."""
    cfg = CognitiveConfig(primary_stt="whisper")
    assert cfg.primary_stt == "whisper"  # raw value preserved


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


def test_voice_health_endpoint_default_transformers_offline_disabled(tmp_path: Path) -> None:
    """BF-301: default config: transformers primary, offline_stt_enabled=False → backend unavailable and unhealthy."""
    runtime = _FakeRuntime(tmp_path)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "primary_stt": "transformers",
        "engine": "transformers",
        "backend_available": False,
        "healthy": False,
        "model": "Xenova/whisper-tiny.en",
    }


def test_voice_health_endpoint_transformers_offline_enabled_healthy(tmp_path: Path) -> None:
    """BF-301: offline_stt_enabled=True → backend_available=True, healthy=True. No filesystem probe (browser owns the model)."""
    config = SystemConfig()
    config.cognitive.offline_stt_enabled = True
    runtime = _FakeRuntime(tmp_path, config)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["primary_stt"] == "transformers"
    assert data["engine"] == "transformers"
    assert data["backend_available"] is True
    assert data["healthy"] is True
    assert data["model"] == "Xenova/whisper-tiny.en"


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
    assert data["model"] is None
