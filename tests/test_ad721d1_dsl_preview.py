"""AD-721d-1 D10: DSL preview + revision-cycle endpoint tests.

Pattern lifted from ``tests/test_ad721d_endpoints.py``. Each test resets
``proposal_history`` in an ``autouse`` fixture (BEFORE and AFTER) so no
order-dependence creeps in across the parallel gate.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.avatars import proposal_history
from probos.avatars.dsl import AppearanceProposalError, AvatarDSL
from probos.crew_profile import CrewProfile


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


def _make_runtime(
    *,
    avatars_enabled: bool = True,
    agent_supports_design: bool = True,
    max_proposal_iterations: int = 3,
) -> MagicMock:
    runtime = MagicMock()
    agent = MagicMock()
    agent.id = "agent-007"
    agent.agent_type = "counselor"
    agent.pool = "counselor"
    if agent_supports_design:
        agent.propose_appearance = AsyncMock(return_value=AvatarDSL())
    else:
        del agent.propose_appearance

    runtime.registry = MagicMock()
    runtime.registry.get.return_value = agent
    runtime.registry.all.return_value = [agent]
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "Troi"
    runtime.trust_network = MagicMock()
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
    # AD-721d-1: explicit emit_event mock so we can assert string-keyed calls.
    runtime.emit_event = MagicMock()

    cfg = MagicMock()
    cfg.avatars = MagicMock()
    cfg.avatars.enabled = avatars_enabled
    cfg.avatars.avatars_dir = "data/avatars"
    cfg.avatars.max_vrm_size_bytes = 25 * 1024 * 1024
    cfg.avatars.max_proposal_iterations = max_proposal_iterations
    runtime.config = cfg

    return runtime


@pytest.fixture(autouse=True)
def _reset_proposal_history():
    """AD-721d-1: order-independence — clear history before AND after each test."""
    proposal_history.reset_all()
    yield
    proposal_history.reset_all()


@pytest.fixture
def runtime() -> MagicMock:
    return _make_runtime()


@pytest.fixture
def client(runtime: MagicMock) -> TestClient:
    from probos.api import create_app
    return TestClient(create_app(runtime))


# ── Tests ───────────────────────────────────────────────────────


def test_propose_request_accepts_previous_dsl(client: TestClient) -> None:
    """Second POST with previous_dsl returns proposal_iteration=2."""
    r1 = client.post("/api/agent/agent-007/appearance/propose", json={})
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["proposal_iteration"] == 1
    assert body1["max_iterations"] == 3

    r2 = client.post(
        "/api/agent/agent-007/appearance/propose",
        json={"captain_note": "shorter hair", "previous_dsl": body1["dsl"]},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["proposal_iteration"] == 2


def test_propose_iteration_cap_returns_429(client: TestClient) -> None:
    """4th propose call (default cap=3) returns 429."""
    for i in range(3):
        r = client.post("/api/agent/agent-007/appearance/propose", json={})
        assert r.status_code == 200, f"call {i+1} failed: {r.text}"

    r4 = client.post("/api/agent/agent-007/appearance/propose", json={})
    assert r4.status_code == 429
    detail = r4.json()["detail"]
    assert detail["reason"] == "iteration_cap_reached"
    assert detail["iteration"] == 3
    assert detail["max_iterations"] == 3


def test_propose_history_cleared_on_approve(client: TestClient) -> None:
    """After PUT /appearance succeeds, next propose returns proposal_iteration=1."""
    r1 = client.post("/api/agent/agent-007/appearance/propose", json={})
    assert r1.status_code == 200
    dsl = r1.json()["dsl"]

    put = client.put("/api/agent/agent-007/appearance", json={"dsl": dsl})
    assert put.status_code == 200

    r2 = client.post("/api/agent/agent-007/appearance/propose", json={})
    assert r2.status_code == 200
    assert r2.json()["proposal_iteration"] == 1


def test_propose_history_cleared_on_delete(client: TestClient) -> None:
    """DELETE proposal-history clears the counter."""
    r1 = client.post("/api/agent/agent-007/appearance/propose", json={})
    assert r1.status_code == 200
    r2 = client.post("/api/agent/agent-007/appearance/propose", json={})
    assert r2.json()["proposal_iteration"] == 2

    d = client.delete("/api/agent/agent-007/appearance/proposal-history")
    assert d.status_code == 200
    assert d.json()["cleared_iterations"] == 2

    r3 = client.post("/api/agent/agent-007/appearance/propose", json={})
    assert r3.json()["proposal_iteration"] == 1


def test_propose_invalid_previous_dsl_returns_422_no_increment(client: TestClient) -> None:
    """Malformed previous_dsl returns 422 AND doesn't consume an iteration slot."""
    bad = _good_dsl_dict()
    bad["body"]["type"] = "INVALID"
    r = client.post(
        "/api/agent/agent-007/appearance/propose",
        json={"captain_note": "x", "previous_dsl": bad},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["reason"] == "invalid_previous_dsl"
    # No iteration consumed.
    assert proposal_history.iteration_count("agent-007") == 0


def test_propose_captain_note_over_280_returns_422(runtime: MagicMock,
                                                   client: TestClient) -> None:
    """Existing AD-721d 280-char validator still fires through the new code path."""
    runtime.registry.get.return_value.propose_appearance = AsyncMock(
        side_effect=AppearanceProposalError(
            "invalid_input", detail="captain_note must be ≤ 280 chars, got 281",
        ),
    )
    r = client.post(
        "/api/agent/agent-007/appearance/propose",
        json={"captain_note": "x" * 281},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["reason"] == "invalid_input"


def test_parse_appearance_dsl_security_guards_still_hold() -> None:
    """Regression: oversized / YAML-anchor / depth-bomb payloads still rejected."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    # Oversized — > 16 KiB.
    oversized = "a" * (16 * 1024 + 1)
    with pytest.raises(AppearanceProposalError) as exc:
        CognitiveAgent._parse_appearance_dsl(oversized)
    assert exc.value.reason == "response_oversized"

    # YAML anchor.
    anchor_doc = "body: &a\n  type: average\nfoo: *a\n"
    with pytest.raises(AppearanceProposalError) as exc:
        CognitiveAgent._parse_appearance_dsl(anchor_doc)
    assert exc.value.reason == "yaml_anchor_or_alias"

    # Depth bomb — 9 nested dicts (cap=8).
    depth_doc = "a:\n " + "a:\n ".join(" " * i for i in range(10))
    # Build a deterministic deeply nested JSON-ish doc.
    nested = "{" + "\"a\":{" * 9 + "\"x\":1" + "}" * 9 + "}"
    with pytest.raises(AppearanceProposalError) as exc:
        CognitiveAgent._parse_appearance_dsl(nested)
    assert exc.value.reason == "depth_exceeded"


def test_avatars_config_max_proposal_iterations_validator() -> None:
    """AvatarsConfig validates the iteration bound at parse time."""
    from probos.config import AvatarsConfig

    # Defaults pass.
    AvatarsConfig()
    # Mid-range value is accepted.
    AvatarsConfig(max_proposal_iterations=5)
    # Below-range raises.
    with pytest.raises(Exception):
        AvatarsConfig(max_proposal_iterations=0)
    # Above-range raises.
    with pytest.raises(Exception):
        AvatarsConfig(max_proposal_iterations=11)


def test_propose_avatars_feature_disabled_returns_503() -> None:
    """All 3 endpoints return 503 when cfg.avatars.enabled is False."""
    runtime = _make_runtime(avatars_enabled=False)
    from probos.api import create_app
    client = TestClient(create_app(runtime))

    p = client.post("/api/agent/agent-007/appearance/propose", json={})
    assert p.status_code == 503
    g = client.put("/api/agent/agent-007/appearance", json={"dsl": _good_dsl_dict()})
    assert g.status_code == 503
    d = client.delete("/api/agent/agent-007/appearance/proposal-history")
    assert d.status_code == 503


def test_proposal_history_isolated_per_agent(client: TestClient,
                                              runtime: MagicMock) -> None:
    """Agent A iterations do not leak into agent B's counter."""
    # Set up a second agent on the same runtime registry.
    other_agent = MagicMock()
    other_agent.id = "agent-002"
    other_agent.agent_type = "ops"
    other_agent.pool = "ops"
    other_agent.propose_appearance = AsyncMock(return_value=AvatarDSL())

    real_agent = runtime.registry.get.return_value
    runtime.registry.get.side_effect = lambda aid: (
        real_agent if aid == "agent-007" else other_agent if aid == "agent-002" else None
    )

    # Two iterations on agent-007.
    client.post("/api/agent/agent-007/appearance/propose", json={})
    client.post("/api/agent/agent-007/appearance/propose", json={})
    # One iteration on agent-002 — should be iteration=1.
    r = client.post("/api/agent/agent-002/appearance/propose", json={})
    assert r.status_code == 200
    assert r.json()["proposal_iteration"] == 1

    assert proposal_history.iteration_count("agent-007") == 2
    assert proposal_history.iteration_count("agent-002") == 1


def test_emit_event_appearance_proposal_on_each_iteration(
    client: TestClient, runtime: MagicMock,
) -> None:
    """Each propose call emits ('appearance_proposal', {...})."""
    client.post("/api/agent/agent-007/appearance/propose",
                json={"captain_note": "hello"})
    client.post("/api/agent/agent-007/appearance/propose", json={})

    proposal_emits = [
        call for call in runtime.emit_event.call_args_list
        if call.args and call.args[0] == "appearance_proposal"
    ]
    assert len(proposal_emits) == 2

    # First payload: has_captain_note=True, len=5.
    first_payload = proposal_emits[0].args[1]
    assert first_payload["agent_id"] == "agent-007"
    assert first_payload["iteration"] == 1
    assert first_payload["has_captain_note"] is True
    assert first_payload["captain_note_len"] == 5

    # Second payload: has_captain_note=False, len=0, iteration=2.
    second_payload = proposal_emits[1].args[1]
    assert second_payload["iteration"] == 2
    assert second_payload["has_captain_note"] is False
    assert second_payload["captain_note_len"] == 0


def test_emit_event_appearance_approved_clears_history(
    client: TestClient, runtime: MagicMock,
) -> None:
    """PUT /appearance fires 'appearance_approved' AND clears history."""
    r1 = client.post("/api/agent/agent-007/appearance/propose", json={})
    client.post("/api/agent/agent-007/appearance/propose", json={})
    assert proposal_history.iteration_count("agent-007") == 2

    put = client.put("/api/agent/agent-007/appearance",
                     json={"dsl": r1.json()["dsl"]})
    assert put.status_code == 200

    approved_emits = [
        call for call in runtime.emit_event.call_args_list
        if call.args and call.args[0] == "appearance_approved"
    ]
    assert len(approved_emits) == 1
    payload = approved_emits[0].args[1]
    assert payload["agent_id"] == "agent-007"
    assert payload["iterations_used"] == 2

    assert proposal_history.iteration_count("agent-007") == 0


def test_delete_proposal_history_endpoint_emits_history_cleared(
    client: TestClient, runtime: MagicMock,
) -> None:
    """DELETE fires 'appearance_history_cleared' with reason='delete'."""
    client.post("/api/agent/agent-007/appearance/propose", json={})
    d = client.delete("/api/agent/agent-007/appearance/proposal-history")
    assert d.status_code == 200
    cleared_emits = [
        call for call in runtime.emit_event.call_args_list
        if call.args and call.args[0] == "appearance_history_cleared"
    ]
    assert len(cleared_emits) == 1
    payload = cleared_emits[0].args[1]
    assert payload["agent_id"] == "agent-007"
    assert payload["reason"] == "delete"
