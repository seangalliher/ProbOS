"""AD-721d D10: Appearance HXI endpoints — boundary tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.avatars.dsl import AppearanceProposalError, AvatarDSL
from probos.crew_profile import CrewProfile, PersonalityTraits, Rank, VoiceProfile


# ── Fakes ───────────────────────────────────────────────────────


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


def _good_dsl_dict() -> dict:
    return AvatarDSL().model_dump()


def _make_runtime(*, avatars_enabled: bool = True, agent_supports_design: bool = True) -> MagicMock:
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
    if agent_supports_design:
        # Mimic CognitiveAgent.propose_appearance happy-path.
        agent.propose_appearance = AsyncMock(return_value=AvatarDSL())
    else:
        # No propose_appearance attribute — endpoint must 400.
        del agent.propose_appearance

    runtime.registry = MagicMock()
    runtime.registry.get.return_value = agent
    runtime.registry.all.return_value = [agent]
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

    # Config for feature gate.
    cfg = MagicMock()
    cfg.avatars = MagicMock()
    cfg.avatars.enabled = avatars_enabled
    cfg.avatars.avatars_dir = "data/avatars"
    cfg.avatars.max_vrm_size_bytes = 25 * 1024 * 1024
    # AD-721d-1: propose endpoint reads this to enforce the iteration cap;
    # set it explicitly so int(...) doesn't trip on a MagicMock child attr.
    cfg.avatars.max_proposal_iterations = 3
    runtime.config = cfg

    return runtime


@pytest.fixture
def runtime() -> MagicMock:
    return _make_runtime()


@pytest.fixture
def client(runtime: MagicMock) -> TestClient:
    from probos.api import create_app
    return TestClient(create_app(runtime))


@pytest.fixture(autouse=True)
def _reset_proposal_history():
    """AD-721d-1: reset module-level proposal history between tests so the
    iteration cap doesn't fire when this file runs in the same process as
    test_ad721d1_dsl_preview.py.
    """
    from probos.avatars import proposal_history
    proposal_history.reset_all()
    yield
    proposal_history.reset_all()


# ── Tests ───────────────────────────────────────────────────────


def test_propose_endpoint_returns_dsl(client: TestClient) -> None:
    resp = client.post("/api/agent/agent-007/appearance/propose",
                       json={"captain_note": ""})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent_id"] == "agent-007"
    assert body["dsl"]["body"]["type"] == "average"


def test_propose_endpoint_propagates_typed_error_as_422(runtime: MagicMock,
                                                       client: TestClient) -> None:
    runtime.registry.get.return_value.propose_appearance = AsyncMock(
        side_effect=AppearanceProposalError(
            "schema_violation", detail="bad enum"
        ),
    )
    resp = client.post("/api/agent/agent-007/appearance/propose", json={})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["reason"] == "schema_violation"


def test_propose_endpoint_400_when_agent_does_not_support_design() -> None:
    runtime = _make_runtime(agent_supports_design=False)
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    resp = client.post("/api/agent/agent-007/appearance/propose", json={})
    assert resp.status_code == 400


def test_propose_endpoint_404_when_agent_missing(runtime: MagicMock,
                                                 client: TestClient) -> None:
    runtime.registry.get.return_value = None
    resp = client.post("/api/agent/missing/appearance/propose", json={})
    assert resp.status_code == 404


def test_put_appearance_validates_dsl(client: TestClient) -> None:
    bad = _good_dsl_dict()
    bad["body"]["type"] = "alien"
    resp = client.put("/api/agent/agent-007/appearance", json={"dsl": bad})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["reason"] == "schema_violation"


def test_put_appearance_persists_and_round_trips(runtime: MagicMock,
                                                 client: TestClient) -> None:
    """propose → approve → re-fetch profile → DSL persists."""
    # Step 1: propose
    propose = client.post("/api/agent/agent-007/appearance/propose", json={})
    assert propose.status_code == 200
    proposed = propose.json()["dsl"]

    # Step 2: PUT the approved DSL
    put = client.put("/api/agent/agent-007/appearance", json={"dsl": proposed})
    assert put.status_code == 200, put.text
    # Persisted on the live ProfileStore. Compare via AvatarDSL re-validation
    # because JSON-roundtrip turns tuple into list (color_hsl).
    crew = runtime.profile_store.get("agent-007")
    assert crew is not None
    assert AvatarDSL.model_validate(crew.appearance.dsl) == AvatarDSL.model_validate(proposed)

    # Step 3: GET /profile surfaces the DSL inside appearance.
    profile_resp = client.get("/api/agent/agent-007/profile")
    assert profile_resp.status_code == 200
    appearance = profile_resp.json()["appearance"]
    assert appearance["dsl"]["body"]["type"] == "average"


def test_endpoints_503_when_avatars_disabled() -> None:
    runtime = _make_runtime(avatars_enabled=False)
    from probos.api import create_app
    client = TestClient(create_app(runtime))
    p = client.post("/api/agent/agent-007/appearance/propose", json={})
    assert p.status_code == 503
    g = client.put("/api/agent/agent-007/appearance", json={"dsl": _good_dsl_dict()})
    assert g.status_code == 503


def test_appearance_profile_dsl_roundtrip_through_dataclass() -> None:
    """``AppearanceProfile.to_dict`` / ``from_dict`` round-trips ``dsl``."""
    from probos.crew_profile import AppearanceProfile

    dsl_dict = _good_dsl_dict()
    profile = AppearanceProfile(dsl=dsl_dict)
    restored = AppearanceProfile.from_dict(profile.to_dict())
    assert restored.dsl == dsl_dict
    # ``None`` round-trips too.
    plain = AppearanceProfile()
    restored_plain = AppearanceProfile.from_dict(plain.to_dict())
    assert restored_plain.dsl is None
