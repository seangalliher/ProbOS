"""BF-301 (#775) — transformers.js STT engine config + health endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from probos.config import CognitiveConfig, SystemConfig
from probos.routers import voice as voice_router


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


def test_transformers_model_default() -> None:
    cfg = CognitiveConfig()
    assert cfg.transformers_model == "Xenova/whisper-tiny.en"


def test_transformers_model_accepts_base_model() -> None:
    cfg = CognitiveConfig(transformers_model="Xenova/whisper-base.en")
    assert cfg.transformers_model == "Xenova/whisper-base.en"


def test_voice_health_returns_engine_transformers_with_model(tmp_path: Path) -> None:
    config = SystemConfig()
    config.cognitive.offline_stt_enabled = True
    runtime = _FakeRuntime(tmp_path, config)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    data = resp.json()
    assert data["engine"] == "transformers"
    assert data["model"] == "Xenova/whisper-tiny.en"
    assert data["backend_available"] is True
    assert data["healthy"] is True


def test_voice_health_whisper_alias_resolves_to_transformers(tmp_path: Path) -> None:
    """BF-301: saved configs with primary_stt='whisper' continue to work."""
    config = SystemConfig()
    config.cognitive.primary_stt = "whisper"
    config.cognitive.offline_stt_enabled = True
    runtime = _FakeRuntime(tmp_path, config)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    data = resp.json()
    assert data["primary_stt"] == "whisper"  # raw config preserved
    assert data["engine"] == "transformers"  # resolved alias
    assert data["backend_available"] is True
    assert data["healthy"] is True


def test_voice_health_browser_primary_model_is_none(tmp_path: Path) -> None:
    config = SystemConfig()
    config.cognitive.primary_stt = "browser"
    runtime = _FakeRuntime(tmp_path, config)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    data = resp.json()
    assert data["engine"] == "browser"
    assert data["model"] is None
    assert data["healthy"] is True


def test_voice_health_offline_disabled_unhealthy(tmp_path: Path) -> None:
    """BF-301: transformers primary + offline_stt_enabled=False → unhealthy."""
    runtime = _FakeRuntime(tmp_path)  # defaults: transformers + offline=False
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    data = resp.json()
    assert data["engine"] == "transformers"
    assert data["backend_available"] is False
    assert data["healthy"] is False


def test_primary_stt_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        CognitiveConfig(primary_stt="azure")  # type: ignore[arg-type]


def test_transformers_model_custom_propagates_to_health(tmp_path: Path) -> None:
    """BF-301: operator can swap to whisper-base.en and health reports it."""
    config = SystemConfig()
    config.cognitive.transformers_model = "Xenova/whisper-base.en"
    config.cognitive.offline_stt_enabled = True
    runtime = _FakeRuntime(tmp_path, config)
    client = _make_client(runtime)
    resp = client.get("/api/voice/health")
    data = resp.json()
    assert data["model"] == "Xenova/whisper-base.en"
