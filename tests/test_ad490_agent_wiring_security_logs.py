"""Tests for AD-490 agent wiring security logs."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.agent_onboarding import AgentOnboardingService
from probos.config import SystemConfig
from probos.events import EventType


class _FakeAgent:
    def __init__(
        self,
        *,
        agent_id: str = "agent-1",
        agent_type: str = "security_officer",
        pool: str = "security",
        callsign: str = "Worf",
    ) -> None:
        self.id = agent_id
        self.agent_type = agent_type
        self.pool = pool
        self.callsign = callsign
        self.state = SimpleNamespace(value="active")
        self.capabilities: list[object] = []
        self.confidence = 1.0


class _FakeRedTeamAgent:
    def __init__(self, *, pool: str, agent_id: str) -> None:
        self.id = agent_id
        self.pool = pool
        self.agent_type = "red_team"
        self.state = SimpleNamespace(value="active")
        self.capabilities: list[object] = []
        self.confidence = 1.0

    async def start(self) -> None:
        return None


def _make_config() -> SystemConfig:
    config = SystemConfig()
    config.onboarding.enabled = False
    config.onboarding.naming_ceremony = False
    config.orientation.enabled = False
    return config


def _make_identity_registry(order: list[str] | None = None) -> MagicMock:
    async def _resolve_or_issue(**_: object) -> SimpleNamespace:
        if order is not None:
            order.append("identity")
        return SimpleNamespace(
            agent_uuid="sovereign-1",
            did="did:probos:agent-1",
            birth_timestamp=123.0,
        )

    async def _resolve_or_issue_asset_tag(**_: object) -> SimpleNamespace:
        if order is not None:
            order.append("identity")
        return SimpleNamespace(asset_uuid="asset-1")

    identity_registry = MagicMock()
    identity_registry.get_by_slot.return_value = None
    identity_registry.resolve_or_issue = AsyncMock(side_effect=_resolve_or_issue)
    identity_registry.resolve_or_issue_asset_tag = AsyncMock(side_effect=_resolve_or_issue_asset_tag)
    return identity_registry


def _make_onboarding_service(
    *,
    event_log: MagicMock | None = None,
    identity_registry: MagicMock | None = None,
    ontology: MagicMock | None = None,
) -> AgentOnboardingService:
    trust_network = MagicMock()
    trust_network.get_score.return_value = 0.5

    callsign_registry = MagicMock()
    callsign_registry.get_callsign.return_value = ""

    if ontology is None:
        ontology = MagicMock()
        ontology.get_vessel_identity.return_value = SimpleNamespace(
            instance_id="ship-1",
            name="ProbOS",
        )
        ontology.get_agent_department.return_value = "security"
        ontology.get_post_for_agent.return_value = None

    return AgentOnboardingService(
        callsign_registry=callsign_registry,
        capability_registry=MagicMock(),
        gossip=MagicMock(),
        intent_bus=MagicMock(),
        trust_network=trust_network,
        event_log=event_log or MagicMock(log=AsyncMock()),
        identity_registry=identity_registry,
        ontology=ontology,
        event_emitter=MagicMock(),
        config=_make_config(),
        llm_client=None,
        registry=MagicMock(),
        ward_room=None,
        acm=None,
    )


def _agent_wired_log(event_log: MagicMock) -> dict[str, object]:
    for call in event_log.log.await_args_list:
        if call.kwargs.get("event") == "agent_wired":
            return call.kwargs
    raise AssertionError("agent_wired log not emitted")


def test_agent_wired_event_type_exists() -> None:
    assert EventType.AGENT_WIRED.value == "agent_wired"


@pytest.mark.asyncio
async def test_agent_wired_contains_did() -> None:
    event_log = MagicMock(log=AsyncMock())
    service = _make_onboarding_service(
        event_log=event_log,
        identity_registry=_make_identity_registry(),
    )

    with patch("probos.agent_onboarding.is_crew_agent", return_value=True):
        await service.wire_agent(_FakeAgent())

    data = _agent_wired_log(event_log)["data"]
    assert data["did"] == "did:probos:agent-1"


@pytest.mark.asyncio
async def test_agent_wired_contains_callsign() -> None:
    event_log = MagicMock(log=AsyncMock())
    service = _make_onboarding_service(
        event_log=event_log,
        identity_registry=_make_identity_registry(),
    )

    with patch("probos.agent_onboarding.is_crew_agent", return_value=True):
        await service.wire_agent(_FakeAgent(callsign="Worf"))

    data = _agent_wired_log(event_log)["data"]
    assert data["callsign"] == "Worf"


@pytest.mark.asyncio
async def test_agent_wired_contains_department() -> None:
    event_log = MagicMock(log=AsyncMock())
    service = _make_onboarding_service(
        event_log=event_log,
        identity_registry=_make_identity_registry(),
    )

    with patch("probos.agent_onboarding.is_crew_agent", return_value=True):
        await service.wire_agent(_FakeAgent())

    data = _agent_wired_log(event_log)["data"]
    assert data["department"] == "security"


@pytest.mark.asyncio
async def test_agent_wired_without_identity() -> None:
    event_log = MagicMock(log=AsyncMock())
    service = _make_onboarding_service(
        event_log=event_log,
        identity_registry=_make_identity_registry(),
        ontology=None,
    )

    with patch("probos.agent_onboarding.is_crew_agent", return_value=False):
        await service.wire_agent(_FakeAgent(agent_type="system_heartbeat", pool="system"))

    wired_log = _agent_wired_log(event_log)
    data = wired_log["data"]
    assert "did" not in data
    assert wired_log["pool"] == "system"


@pytest.mark.asyncio
async def test_agent_wired_emitted_after_identity_resolution() -> None:
    order: list[str] = []

    async def _log(**kwargs: object) -> int:
        if kwargs.get("event") == "agent_wired":
            order.append("agent_wired")
        return 1

    event_log = MagicMock(log=AsyncMock(side_effect=_log))
    service = _make_onboarding_service(
        event_log=event_log,
        identity_registry=_make_identity_registry(order),
    )

    with patch("probos.agent_onboarding.is_crew_agent", return_value=True):
        await service.wire_agent(_FakeAgent())

    assert order == ["identity", "agent_wired"]


@pytest.mark.asyncio
async def test_red_team_agent_wired_has_department() -> None:
    from probos.runtime import ProbOSRuntime

    runtime = ProbOSRuntime.__new__(ProbOSRuntime)
    runtime.registry = MagicMock()
    runtime.registry.register = AsyncMock()
    runtime.capability_registry = MagicMock()
    runtime.gossip = MagicMock()
    runtime.trust_network = MagicMock()
    runtime.event_log = MagicMock(log=AsyncMock())
    runtime.red_team_agents = []

    with patch("probos.runtime.RedTeamAgent", _FakeRedTeamAgent):
        await runtime._spawn_red_team(1)

    runtime.event_log.log.assert_awaited_once()
    assert runtime.event_log.log.await_args.kwargs["data"] == {"department": "security"}
