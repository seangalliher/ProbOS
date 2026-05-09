"""AD-721: AppearanceProfile dataclass + avatar serving endpoint tests."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

from probos.config import AvatarsConfig, SystemConfig
from probos.crew_profile import (
    AppearanceProfile,
    CrewProfile,
    PersonalityTraits,
    Rank,
    VoiceProfile,
)


# ── Dataclass ────────────────────────────────────────────────────


def test_appearance_profile_defaults():
    a = AppearanceProfile()
    assert a.vrm_url == ""
    assert a.expression_overrides == {}
    assert a.color_palette_hint == ""


def test_appearance_profile_to_from_dict_roundtrip():
    a = AppearanceProfile(
        vrm_url="/avatars/echo.vrm",
        expression_overrides={"relaxed": 0.2, "happy": 0.1},
        color_palette_hint="#d0a030",
    )
    restored = AppearanceProfile.from_dict(a.to_dict())
    assert restored == a


def test_appearance_profile_from_dict_handles_missing_keys():
    restored = AppearanceProfile.from_dict({})
    assert restored == AppearanceProfile()


def test_crew_profile_appearance_persistence():
    profile = CrewProfile(
        agent_id="echo",
        agent_type="counselor",
        personality=PersonalityTraits(),
        voice=VoiceProfile(),
        appearance=AppearanceProfile(
            vrm_url="/avatars/echo.vrm",
            expression_overrides={"relaxed": 0.2},
            color_palette_hint="#d0a030",
        ),
    )
    restored = CrewProfile.from_dict(profile.to_dict())
    assert restored.appearance.vrm_url == "/avatars/echo.vrm"
    assert restored.appearance.expression_overrides == {"relaxed": 0.2}
    assert restored.appearance.color_palette_hint == "#d0a030"


def test_crew_profile_appearance_default_when_missing_in_dict():
    legacy = {
        "agent_id": "x",
        "agent_type": "scout",
        "rank": Rank.ENSIGN.value,
    }
    restored = CrewProfile.from_dict(legacy)
    assert isinstance(restored.appearance, AppearanceProfile)
    assert restored.appearance.vrm_url == ""


# ── AvatarsConfig ────────────────────────────────────────────────


def test_avatars_config_defaults():
    cfg = AvatarsConfig()
    assert cfg.enabled is False
    assert cfg.avatars_dir == "data/avatars"
    assert cfg.max_vrm_size_bytes == 25 * 1024 * 1024
    assert cfg.fallback_to_parametric_on_error is True


def test_system_config_includes_avatars():
    cfg = SystemConfig()
    assert hasattr(cfg, "avatars")
    assert cfg.avatars.enabled is False


# ── HTTP endpoints ──────────────────────────────────────────────


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.id = "agent-007"
    agent.agent_type = "counselor"
    agent.confidence = 0.85
    agent.state = MagicMock()
    agent.state.value = "active"
    agent.tier = "domain"
    agent.pool = "counselor"
    agent.is_alive = True
    return agent


@pytest.fixture
def mock_runtime(mock_agent, tmp_path):
    runtime = MagicMock()
    runtime.registry = MagicMock()
    runtime.registry.get.return_value = mock_agent
    runtime.registry.all.return_value = [mock_agent]
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "Troi"
    runtime.callsign_registry.resolve.return_value = {
        "callsign": "Troi", "agent_type": "counselor",
        "agent_id": "agent-007",
        "display_name": "Counselor", "department": "bridge",
    }
    runtime.trust_network = MagicMock()
    runtime.trust_network.get_score.return_value = 0.55
    runtime.trust_network.get_history.return_value = []
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock(return_value=None)
    runtime._start_time = 0.0
    runtime.episodic_memory = None
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()
    runtime.profile_store = None

    avatars_dir = tmp_path / "avatars"
    avatars_dir.mkdir()
    cfg = SystemConfig()
    cfg.avatars = AvatarsConfig(enabled=True, avatars_dir=str(avatars_dir))
    runtime.config = cfg
    runtime._avatars_dir = avatars_dir
    return runtime


@pytest.fixture
def client(mock_runtime):
    from probos.api import create_app
    from fastapi.testclient import TestClient
    return TestClient(create_app(mock_runtime))


def test_avatars_enabled_endpoint_returns_flag(client, mock_runtime):
    resp = client.get("/api/config/avatars-enabled")
    assert resp.status_code == 200
    assert resp.json() == {"enabled": True}
    mock_runtime.config.avatars.enabled = False
    resp = client.get("/api/config/avatars-enabled")
    assert resp.json() == {"enabled": False}


def test_avatar_get_path_traversal_rejected(client):
    # FastAPI/Starlette intercepts ".." in path params with a 404 before our handler,
    # but a single-component name with a leading dot is still routed; assert non-200.
    resp = client.get("/api/system/avatars/..%2Fetc%2Fpasswd")
    assert resp.status_code in (400, 404)


def test_avatar_get_unknown_file_404(client):
    resp = client.get("/api/system/avatars/missing.vrm")
    assert resp.status_code == 404


def test_avatar_get_oversize_rejected(client, mock_runtime):
    big_path = mock_runtime._avatars_dir / "big.vrm"
    # Write 26 MB to exceed default 25 MB cap.
    big_path.write_bytes(b"\0" * (26 * 1024 * 1024))
    resp = client.get("/api/system/avatars/big.vrm")
    assert resp.status_code == 413


def test_avatar_get_happy_path(client, mock_runtime):
    f = mock_runtime._avatars_dir / "echo.vrm"
    f.write_bytes(b"FAKE-VRM-BYTES")
    resp = client.get("/api/system/avatars/echo.vrm")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/octet-stream")
    assert resp.content == b"FAKE-VRM-BYTES"


def test_avatar_get_when_disabled_returns_404(client, mock_runtime):
    mock_runtime.config.avatars.enabled = False
    f = mock_runtime._avatars_dir / "echo.vrm"
    f.write_bytes(b"FAKE-VRM-BYTES")
    resp = client.get("/api/system/avatars/echo.vrm")
    assert resp.status_code == 404


def test_get_profile_includes_appearance(client):
    resp = client.get("/api/agent/agent-007/profile")
    assert resp.status_code == 200
    data = resp.json()
    assert "appearance" in data
    appearance = data["appearance"]
    assert isinstance(appearance, dict)
    for key in ("vrm_url", "expression_overrides", "color_palette_hint"):
        assert key in appearance
