"""AD-718: VoiceProfile dataclass + agent voice-profile API tests."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

from probos.crew_profile import (
    CrewProfile,
    PersonalityTraits,
    Rank,
    VoiceProfile,
)
from probos.voice_profile_defaults import (
    DEFAULT_VOICE_PROFILES,
    default_voice_for,
)


# ── VoiceProfile dataclass ───────────────────────────────────────


def test_voice_profile_defaults_match_voice_ts_v0():
    """Empty VoiceProfile() must mirror the v0 hardcoded utterance defaults."""
    vp = VoiceProfile()
    assert vp.voice_name == ""
    assert vp.pitch == 0.9
    assert vp.rate == 0.95
    assert vp.volume == 0.8


def test_voice_profile_validates_ranges():
    """__post_init__ rejects out-of-range pitch/rate/volume."""
    with pytest.raises(ValueError, match="pitch"):
        VoiceProfile(pitch=2.5)
    with pytest.raises(ValueError, match="rate"):
        VoiceProfile(rate=0.05)
    with pytest.raises(ValueError, match="volume"):
        VoiceProfile(volume=1.1)


def test_voice_profile_to_from_dict_roundtrip():
    """to_dict / from_dict round-trip preserves all four fields."""
    vp = VoiceProfile(voice_name="Microsoft Aria Online (Natural)",
                      pitch=1.05, rate=0.92, volume=0.85)
    restored = VoiceProfile.from_dict(vp.to_dict())
    assert restored == vp


def test_crew_profile_voice_persistence():
    """CrewProfile.to_dict()/from_dict() preserves the voice field."""
    profile = CrewProfile(
        agent_id="abc",
        agent_type="counselor",
        personality=PersonalityTraits(),
        voice=VoiceProfile(voice_name="Troi", pitch=1.05, rate=0.92, volume=0.85),
    )
    restored = CrewProfile.from_dict(profile.to_dict())
    assert restored.voice.voice_name == "Troi"
    assert restored.voice.pitch == 1.05
    assert restored.voice.rate == 0.92
    assert restored.voice.volume == 0.85


def test_crew_profile_default_voice_when_missing_in_dict():
    """from_dict() fills voice with the bare default when key is absent."""
    legacy = {
        "agent_id": "x",
        "agent_type": "scout",
        "rank": Rank.ENSIGN.value,
        # No "voice" key — pre-AD-718 persistence.
    }
    restored = CrewProfile.from_dict(legacy)
    assert isinstance(restored.voice, VoiceProfile)
    assert restored.voice.pitch == 0.9


# ── default_voice_for ────────────────────────────────────────────


def test_default_voice_for_known_agent_type():
    """Counselor seed matches the spec (Troi — warm/slower)."""
    counselor = default_voice_for("counselor")
    assert counselor.pitch == 1.05
    assert counselor.rate == 0.92
    assert counselor.volume == 0.85


def test_default_voice_for_unknown_agent_type():
    """Unknown agent_type returns the bare-default VoiceProfile()."""
    assert default_voice_for("nonsense") == VoiceProfile()


def test_default_voice_profiles_cover_15_standing_crew():
    """Sanity: the 15 standing crew agent_types are all keyed."""
    expected = {
        "counselor", "security_officer", "diagnostician", "pathologist",
        "surgeon", "pharmacist", "architect", "data_analyst",
        "research_specialist", "systems_analyst", "scout", "builder",
        "engineering_officer", "operations_officer", "training_officer",
    }
    assert expected.issubset(set(DEFAULT_VOICE_PROFILES.keys()))


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


class _ProfileStoreFake:
    def __init__(self):
        self.profiles: dict[str, CrewProfile] = {}

    def get(self, agent_id):
        return self.profiles.get(agent_id)

    def get_or_create(self, agent_id, agent_type="", pool="", **defaults):
        if agent_id in self.profiles:
            return self.profiles[agent_id]
        crew = CrewProfile(agent_id=agent_id, agent_type=agent_type, pool=pool)
        self.profiles[agent_id] = crew
        return crew

    def update(self, profile):
        self.profiles[profile.agent_id] = profile


@pytest.fixture
def mock_runtime(mock_agent):
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
    runtime.profile_store = _ProfileStoreFake()
    return runtime


@pytest.fixture
def client(mock_runtime):
    from probos.api import create_app
    from fastapi.testclient import TestClient
    return TestClient(create_app(mock_runtime))


def test_get_profile_includes_voice_profile(client):
    resp = client.get("/api/agent/agent-007/profile")
    assert resp.status_code == 200
    data = resp.json()
    assert "voiceProfile" in data
    vp = data["voiceProfile"]
    # Defense-in-depth: never None; all four fields present.
    assert isinstance(vp, dict)
    for key in ("voice_name", "pitch", "rate", "volume"):
        assert key in vp
    # Counselor seed kicks in via default_voice_for.
    assert vp["pitch"] == 1.05


def test_set_voice_profile_endpoint_happy(client, mock_runtime):
    resp = client.put("/api/agent/agent-007/voice-profile", json={
        "voice_name": "Microsoft Aria Online (Natural)",
        "pitch": 1.10, "rate": 0.90, "volume": 0.85,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["agentId"] == "agent-007"
    assert body["voiceProfile"]["pitch"] == 1.10
    # Persisted in profile_store.
    crew = mock_runtime.profile_store.get("agent-007")
    assert crew is not None
    assert crew.voice.pitch == 1.10
    assert crew.voice.voice_name == "Microsoft Aria Online (Natural)"


def test_set_voice_profile_endpoint_validation(client):
    resp = client.put("/api/agent/agent-007/voice-profile", json={
        "voice_name": "", "pitch": 3.0, "rate": 1.0, "volume": 0.8,
    })
    assert resp.status_code == 400
    assert "pitch" in resp.json()["detail"]


def test_set_voice_profile_endpoint_missing_agent(client, mock_runtime):
    mock_runtime.registry.get.return_value = None
    resp = client.put("/api/agent/missing/voice-profile", json={
        "voice_name": "", "pitch": 0.9, "rate": 0.95, "volume": 0.8,
    })
    assert resp.status_code == 404
