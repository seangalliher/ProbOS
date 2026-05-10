"""AD-718a D8: ``CognitiveAgent.propose_voice_profile`` + endpoint boundary tests."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.crew_profile import CrewProfile, VoiceProfile
from probos.types import LLMResponse
from probos.voice.proposal import VoiceProposalError


def _good_payload() -> dict:
    return {
        "voice_name": "Aria",
        "pitch": 1.05,
        "rate": 0.92,
        "volume": 0.85,
        "rationale": "warm",
    }


# ── Minimal CognitiveAgent subclass (mirrors test_ad721d_propose_appearance) ──


class _MinimalAgent(CognitiveAgent):
    """Bypass heavy CognitiveAgent constructor; exercise voice slice only."""

    def __init__(
        self,
        *,
        llm_client: object,
        runtime: object = None,
        instructions: str = "test agent",
        agent_type: str = "test",
        agent_id: str = "agent-test",
    ) -> None:
        self._llm_client = llm_client
        self._runtime = runtime
        self.instructions = instructions
        self.agent_type = agent_type
        self.id = agent_id

    def _resolve_tier(self) -> str:
        return "standard"


def _agent_with_llm_response(content: str) -> _MinimalAgent:
    client = MagicMock()
    client.complete = AsyncMock(return_value=LLMResponse(content=content))
    return _MinimalAgent(llm_client=client)


# ── Capability-level tests ──


@pytest.mark.asyncio
async def test_propose_voice_profile_happy_path() -> None:
    text = json.dumps(_good_payload())
    agent = _agent_with_llm_response(text)
    profile, rationale = await agent.propose_voice_profile()
    assert isinstance(profile, VoiceProfile)
    assert profile.voice_name == "Aria"
    assert profile.pitch == 1.05
    assert rationale == "warm"


@pytest.mark.asyncio
async def test_propose_voice_profile_raises_on_malformed_llm() -> None:
    agent = _agent_with_llm_response("not valid json: [unterminated")
    with pytest.raises(VoiceProposalError):
        await agent.propose_voice_profile()


@pytest.mark.asyncio
async def test_propose_voice_profile_no_llm_client_raises() -> None:
    agent = _MinimalAgent(llm_client=None)
    with pytest.raises(VoiceProposalError) as exc_info:
        await agent.propose_voice_profile()
    assert exc_info.value.reason == "llm_unavailable"


@pytest.mark.asyncio
async def test_propose_voice_profile_long_captain_note_rejected() -> None:
    agent = _agent_with_llm_response(json.dumps(_good_payload()))
    with pytest.raises(VoiceProposalError) as exc_info:
        await agent.propose_voice_profile(captain_note="x" * 281)
    assert exc_info.value.reason == "invalid_input"


@pytest.mark.asyncio
async def test_propose_voice_profile_propagates_llm_failure() -> None:
    client = MagicMock()
    client.complete = AsyncMock(side_effect=RuntimeError("backend down"))
    agent = _MinimalAgent(llm_client=client)
    with pytest.raises(VoiceProposalError) as exc_info:
        await agent.propose_voice_profile()
    assert exc_info.value.reason == "llm_call_failed"


# ── Endpoint-level tests ──


class _ProfileStoreFake:
    def __init__(self) -> None:
        self.profiles: dict[str, CrewProfile] = {}

    def get(self, agent_id: str):
        return self.profiles.get(agent_id)

    def get_or_create(self, agent_id: str, agent_type: str = "", pool: str = "", **_):
        if agent_id in self.profiles:
            return self.profiles[agent_id]
        crew = CrewProfile(agent_id=agent_id, agent_type=agent_type, pool=pool)
        self.profiles[agent_id] = crew
        return crew

    def update(self, profile: CrewProfile) -> None:
        self.profiles[profile.agent_id] = profile


class _EpisodicMemoryFake:
    def __init__(self) -> None:
        self.stored: list[object] = []

    async def store(self, episode: object) -> None:
        self.stored.append(episode)


def _make_runtime(*, agent_supports_propose: bool = True) -> MagicMock:
    runtime = MagicMock()
    agent = MagicMock()
    agent.id = "agent-007"
    agent.agent_type = "counselor"
    agent.confidence = 0.85
    agent.state = MagicMock()
    agent.state.value = "active"
    agent.tier = "domain"
    agent.pool = "counselor"
    agent.is_alive = True
    if agent_supports_propose:
        agent.propose_voice_profile = AsyncMock(
            return_value=(VoiceProfile(voice_name="Aria", pitch=1.05, rate=0.92, volume=0.85),
                          "warm cadence")
        )
    else:
        del agent.propose_voice_profile

    runtime.registry = MagicMock()
    runtime.registry.get.return_value = agent
    runtime.registry.all.return_value = [agent]
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "Troi"
    runtime.callsign_registry.resolve.return_value = None
    runtime.trust_network = MagicMock()
    runtime.trust_network.get_score.return_value = 0.55
    runtime.trust_network.get_history.return_value = []
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock(return_value=None)
    runtime._start_time = 0.0
    runtime.episodic_memory = _EpisodicMemoryFake()
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()
    runtime.profile_store = _ProfileStoreFake()

    cfg = MagicMock()
    cfg.avatars = MagicMock()
    cfg.avatars.enabled = False
    cfg.avatars.avatars_dir = "data/avatars"
    cfg.avatars.max_vrm_size_bytes = 25 * 1024 * 1024
    runtime.config = cfg

    return runtime


@pytest.fixture
def runtime() -> MagicMock:
    return _make_runtime()


@pytest.fixture
def client(runtime: MagicMock) -> TestClient:
    from probos.api import create_app
    return TestClient(create_app(runtime))


def test_propose_endpoint_returns_proposal(client: TestClient) -> None:
    resp = client.post(
        "/api/agent/agent-007/voice-profile/propose",
        json={"captain_note": ""},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent_id"] == "agent-007"
    assert body["voice_profile"]["voice_name"] == "Aria"
    assert body["voice_profile"]["pitch"] == 1.05
    assert body["rationale"] == "warm cadence"


def test_propose_endpoint_422_on_parser_failure(
    runtime: MagicMock, client: TestClient,
) -> None:
    runtime.registry.get.return_value.propose_voice_profile = AsyncMock(
        side_effect=VoiceProposalError("schema_violation", detail="bad")
    )
    resp = client.post(
        "/api/agent/agent-007/voice-profile/propose",
        json={"captain_note": ""},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"]["reason"] == "schema_violation"


def test_propose_endpoint_404_when_agent_missing(
    runtime: MagicMock, client: TestClient,
) -> None:
    runtime.registry.get.return_value = None
    resp = client.post(
        "/api/agent/missing/voice-profile/propose",
        json={"captain_note": ""},
    )
    assert resp.status_code == 404


def test_propose_endpoint_400_when_agent_lacks_capability() -> None:
    runtime = _make_runtime(agent_supports_propose=False)
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    resp = client.post(
        "/api/agent/agent-007/voice-profile/propose",
        json={"captain_note": ""},
    )
    assert resp.status_code == 400


def test_approve_with_rationale_writes_episode(
    runtime: MagicMock, client: TestClient,
) -> None:
    resp = client.put(
        "/api/agent/agent-007/voice-profile",
        json={
            "voice_name": "Aria",
            "pitch": 1.05,
            "rate": 0.92,
            "volume": 0.85,
            "proposal_rationale": "warm cadence",
        },
    )
    assert resp.status_code == 200, resp.text
    assert len(runtime.episodic_memory.stored) == 1
    ep = runtime.episodic_memory.stored[0]
    outcome = ep.outcomes[0]
    assert outcome["intent"] == "voice_profile_change"
    assert outcome["rationale"] == "warm cadence"
    assert outcome["new_voice"]["voice_name"] == "Aria"


def test_approve_without_rationale_writes_no_episode(
    runtime: MagicMock, client: TestClient,
) -> None:
    resp = client.put(
        "/api/agent/agent-007/voice-profile",
        json={
            "voice_name": "Aria",
            "pitch": 1.05,
            "rate": 0.92,
            "volume": 0.85,
        },
    )
    assert resp.status_code == 200, resp.text
    assert runtime.episodic_memory.stored == []


def test_round_trip_propose_then_approve(
    runtime: MagicMock, client: TestClient,
) -> None:
    propose = client.post(
        "/api/agent/agent-007/voice-profile/propose",
        json={"captain_note": ""},
    )
    assert propose.status_code == 200
    proposal = propose.json()["voice_profile"]
    approve = client.put(
        "/api/agent/agent-007/voice-profile",
        json={**proposal, "proposal_rationale": "approved"},
    )
    assert approve.status_code == 200
    persisted = runtime.profile_store.profiles["agent-007"].voice
    assert persisted.voice_name == "Aria"
    assert persisted.pitch == 1.05
    assert persisted.rate == 0.92
    assert persisted.volume == 0.85
