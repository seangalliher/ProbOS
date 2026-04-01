"""AD-442: Adaptive Onboarding & Self-Naming Ceremony tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.acm import AgentCapitalService, LifecycleState
from probos.agent_onboarding import AgentOnboardingService
from probos.config import OnboardingConfig, SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.runtime import ProbOSRuntime
from probos.cognitive.llm_client import BaseLLMClient
from probos.consensus.trust import TrustNetwork
from probos.mesh.capability import CapabilityRegistry
from probos.mesh.gossip import GossipProtocol
from probos.mesh.intent import IntentBus
from probos.substrate.agent import BaseAgent
from probos.substrate.event_log import EventLog
from probos.substrate.registry import AgentRegistry
from probos.types import LLMResponse
from probos.ward_room import WardRoomService
from probos.ward_room_router import WardRoomRouter


# ── Fixtures / Helpers ──────────────────────────────────────────────


def _make_agent(agent_type: str = "diagnostician", callsign: str = "Bones", agent_id: str = "diag-1"):
    agent = MagicMock(spec=BaseAgent)
    agent.agent_type = agent_type
    agent.callsign = callsign
    agent.id = agent_id
    agent.pool = agent_type
    agent.state = MagicMock(value="idle")
    agent.confidence = 0.9
    agent.capabilities = []
    agent.is_alive = True
    agent._llm_client = AsyncMock(spec=BaseLLMClient)
    return agent


def _make_runtime(config=None):
    """Build a minimal mock runtime for naming ceremony tests."""
    rt = MagicMock(spec=ProbOSRuntime)
    rt.config = config or SystemConfig()
    rt.ontology = None
    rt.identity_registry = None
    rt.registry = MagicMock(spec=AgentRegistry)
    rt.registry.all.return_value = []
    return rt


def _attach_onboarding(rt):
    """AD-515: Attach AgentOnboardingService so onboarding delegates properly."""
    rt.onboarding = AgentOnboardingService(
        callsign_registry=getattr(rt, 'callsign_registry', CallsignRegistry()),
        capability_registry=MagicMock(spec=CapabilityRegistry),
        gossip=MagicMock(spec=GossipProtocol),
        intent_bus=MagicMock(spec=IntentBus),
        trust_network=MagicMock(spec=TrustNetwork),
        event_log=AsyncMock(spec=EventLog),
        identity_registry=getattr(rt, 'identity_registry', None),
        ontology=getattr(rt, 'ontology', None),
        event_emitter=MagicMock(),
        config=rt.config,
        llm_client=None,
        registry=rt.registry,
        ward_room=None,
        acm=None,
    )


# ── Naming Ceremony Tests ──────────────────────────────────────────


class TestNamingCeremony:
    """Tests for onboarding.run_naming_ceremony()."""

    @pytest.mark.asyncio
    async def test_naming_ceremony_returns_chosen_callsign(self):
        """Mock LLM returns 'McCoy\\nA classic name.' → returns 'McCoy'."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.ontology = None
        rt.identity_registry = None
        rt.registry = MagicMock(spec=AgentRegistry)
        rt.registry.all.return_value = []
        _attach_onboarding(rt)

        agent = _make_agent()
        agent._llm_client.complete = AsyncMock(return_value=LLMResponse(content="McCoy\nA classic name for a doctor."))

        result = await rt.onboarding.run_naming_ceremony(agent)
        assert result == "McCoy"

    @pytest.mark.asyncio
    async def test_naming_ceremony_fallback_on_empty(self):
        """Empty LLM response → seed callsign returned."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.ontology = None
        rt.identity_registry = None
        rt.registry = MagicMock(spec=AgentRegistry)
        rt.registry.all.return_value = []
        _attach_onboarding(rt)

        agent = _make_agent(callsign="Bones")
        agent._llm_client.complete = AsyncMock(return_value=LLMResponse(content=""))

        result = await rt.onboarding.run_naming_ceremony(agent)
        assert result == "Bones"

    @pytest.mark.asyncio
    async def test_naming_ceremony_fallback_on_error(self):
        """LLM raises exception → seed callsign returned."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.ontology = None
        rt.identity_registry = None
        rt.registry = MagicMock(spec=AgentRegistry)
        rt.registry.all.return_value = []
        _attach_onboarding(rt)

        agent = _make_agent(callsign="Bones")
        agent._llm_client.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

        result = await rt.onboarding.run_naming_ceremony(agent)
        assert result == "Bones"

    @pytest.mark.asyncio
    async def test_naming_ceremony_rejects_duplicate(self):
        """Duplicate callsign → seed callsign used instead."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.ontology = None
        rt.identity_registry = None

        # Existing crew member already named "Bones"
        existing = _make_agent(agent_type="other", callsign="Bones", agent_id="other-1")
        rt.registry = MagicMock(spec=AgentRegistry)
        rt.registry.all.return_value = [existing]
        _attach_onboarding(rt)

        agent = _make_agent(agent_type="diagnostician", callsign="Doc", agent_id="diag-1")
        agent._llm_client.complete = AsyncMock(return_value=LLMResponse(content="Bones\nI want to be called Bones."))

        result = await rt.onboarding.run_naming_ceremony(agent)
        assert result == "Doc"  # Falls back to seed

    @pytest.mark.asyncio
    async def test_naming_ceremony_truncates_long_name(self):
        """50-char name → seed callsign used as fallback."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.ontology = None
        rt.identity_registry = None
        rt.registry = MagicMock(spec=AgentRegistry)
        rt.registry.all.return_value = []
        _attach_onboarding(rt)

        agent = _make_agent(callsign="Bones")
        long_name = "A" * 50
        agent._llm_client.complete = AsyncMock(return_value=LLMResponse(content=f"{long_name}\nToo long."))

        result = await rt.onboarding.run_naming_ceremony(agent)
        assert result == "Bones"

    @pytest.mark.asyncio
    async def test_naming_ceremony_strips_quotes(self):
        """LLM returns '"Scotty"' with quotes → stripped to 'Scotty'."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.ontology = None
        rt.identity_registry = None
        rt.registry = MagicMock(spec=AgentRegistry)
        rt.registry.all.return_value = []
        _attach_onboarding(rt)

        agent = _make_agent(callsign="Bones")
        agent._llm_client.complete = AsyncMock(return_value=LLMResponse(content='"Scotty"\nThe name feels right.'))

        result = await rt.onboarding.run_naming_ceremony(agent)
        assert result == "Scotty"


# ── Wire Agent Integration Tests ───────────────────────────────────


class TestWireAgentIntegration:
    """Tests for onboarding.wire_agent() naming ceremony integration."""

    def _make_wired_runtime(self):
        """Build a ProbOSRuntime with enough wired up for onboarding.wire_agent()."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.callsign_registry = CallsignRegistry()
        rt.capability_registry = MagicMock(spec=CapabilityRegistry)
        rt.gossip = MagicMock(spec=GossipProtocol)
        rt.trust_network = MagicMock(spec=TrustNetwork)
        rt.trust_network.get_or_create.return_value = None
        rt.trust_network.get_score.return_value = 0.5
        rt._emit_event = MagicMock()
        rt.event_log = AsyncMock(spec=EventLog)
        rt.intent_bus = MagicMock(spec=IntentBus)
        rt.identity_registry = None
        rt.acm = None
        rt.ward_room = None
        rt.ontology = None
        rt.registry = MagicMock(spec=AgentRegistry)
        rt.registry.all.return_value = []
        _attach_onboarding(rt)
        return rt

    @pytest.mark.asyncio
    @patch("probos.agent_onboarding.is_crew_agent", return_value=True)
    async def test_wire_agent_runs_ceremony_for_crew(self, mock_is_crew):
        rt = self._make_wired_runtime()
        rt.onboarding.run_naming_ceremony = AsyncMock(return_value="McCoy")

        agent = _make_agent(callsign="Bones")
        await rt.onboarding.wire_agent(agent)

        rt.onboarding.run_naming_ceremony.assert_called_once_with(agent)

    @pytest.mark.asyncio
    @patch("probos.agent_onboarding.is_crew_agent", return_value=False)
    async def test_wire_agent_skips_ceremony_for_infrastructure(self, mock_is_crew):
        rt = self._make_wired_runtime()
        rt.onboarding.run_naming_ceremony = AsyncMock()

        agent = _make_agent(agent_type="introspect", callsign="")
        del agent._llm_client  # Infrastructure agents have no LLM client
        await rt.onboarding.wire_agent(agent)

        rt.onboarding.run_naming_ceremony.assert_not_called()

    @pytest.mark.asyncio
    @patch("probos.agent_onboarding.is_crew_agent", return_value=True)
    async def test_wire_agent_birth_cert_uses_chosen_name(self, mock_is_crew):
        rt = self._make_wired_runtime()
        rt.onboarding.run_naming_ceremony = AsyncMock(return_value="McCoy")

        agent = _make_agent(callsign="Bones")
        await rt.onboarding.wire_agent(agent)

        # After ceremony, agent.callsign should be updated
        assert agent.callsign == "McCoy"
        assert rt.callsign_registry.get_callsign("diagnostician") == "McCoy"

    @pytest.mark.asyncio
    @patch("probos.agent_onboarding.is_crew_agent", return_value=True)
    async def test_wire_agent_posts_welcome_announcement(self, mock_is_crew):
        rt = self._make_wired_runtime()
        rt.onboarding.run_naming_ceremony = AsyncMock(return_value="McCoy")

        # Set up Ward Room mock on the onboarding service (where wire_agent runs)
        all_hands_channel = MagicMock()
        all_hands_channel.name = "All Hands"
        all_hands_channel.id = "ch-all-hands"
        ward_room = AsyncMock(spec=WardRoomService)
        ward_room.list_channels = AsyncMock(return_value=[all_hands_channel])
        ward_room.create_thread = AsyncMock()
        rt.onboarding._ward_room = ward_room

        agent = _make_agent(callsign="Bones")
        await rt.onboarding.wire_agent(agent)

        ward_room.create_thread.assert_called_once()
        call_kwargs = ward_room.create_thread.call_args
        assert "Welcome Aboard" in call_kwargs.kwargs.get("title", "") or "Welcome Aboard" in str(call_kwargs)


# ── CallsignRegistry Tests ─────────────────────────────────────────


class TestCallsignRegistrySetCallsign:
    """Tests for CallsignRegistry.set_callsign()."""

    def test_set_callsign_updates_both_maps(self):
        reg = CallsignRegistry()
        reg._type_to_callsign["diagnostician"] = "Bones"
        reg._callsign_to_type["bones"] = "diagnostician"

        reg.set_callsign("diagnostician", "McCoy")

        assert reg.get_callsign("diagnostician") == "McCoy"
        result = reg.resolve("McCoy")
        assert result is not None
        assert result["agent_type"] == "diagnostician"

    def test_set_callsign_removes_old_mapping(self):
        reg = CallsignRegistry()
        reg._type_to_callsign["diagnostician"] = "Bones"
        reg._callsign_to_type["bones"] = "diagnostician"

        reg.set_callsign("diagnostician", "McCoy")
        reg.set_callsign("diagnostician", "Leonard")

        assert reg.get_callsign("diagnostician") == "Leonard"
        # Old name "McCoy" should no longer resolve
        assert reg.resolve("McCoy") is None
        # New name should resolve
        assert reg.resolve("Leonard") is not None


# ── ACM Activation Tests ───────────────────────────────────────────


class TestACMActivation:
    """Tests for AgentCapitalService.check_activation()."""

    @pytest.mark.asyncio
    async def test_check_activation_promotes_at_threshold(self, tmp_path):
        """trust=0.65 → PROBATIONARY → ACTIVE."""
        acm = AgentCapitalService(tmp_path)
        await acm.start()

        # Onboard to get to PROBATIONARY
        await acm.onboard("agent-1", "diagnostician", "diagnostician", "medical")
        state = await acm.get_lifecycle_state("agent-1")
        assert state == LifecycleState.PROBATIONARY

        result = await acm.check_activation("agent-1", trust_score=0.65)
        assert result is True

        state = await acm.get_lifecycle_state("agent-1")
        assert state == LifecycleState.ACTIVE

        await acm.stop()

    @pytest.mark.asyncio
    async def test_check_activation_no_op_below_threshold(self, tmp_path):
        """trust=0.50 → stays PROBATIONARY."""
        acm = AgentCapitalService(tmp_path)
        await acm.start()

        await acm.onboard("agent-1", "diagnostician", "diagnostician", "medical")

        result = await acm.check_activation("agent-1", trust_score=0.50)
        assert result is False

        state = await acm.get_lifecycle_state("agent-1")
        assert state == LifecycleState.PROBATIONARY

        await acm.stop()

    @pytest.mark.asyncio
    async def test_check_activation_no_op_if_already_active(self, tmp_path):
        """Already ACTIVE → returns False."""
        acm = AgentCapitalService(tmp_path)
        await acm.start()

        await acm.onboard("agent-1", "diagnostician", "diagnostician", "medical")
        # Manually activate
        await acm.transition("agent-1", LifecycleState.ACTIVE, reason="manual")

        result = await acm.check_activation("agent-1", trust_score=0.90)
        assert result is False

        await acm.stop()


# ── Config Tests ───────────────────────────────────────────────────


class TestOnboardingConfig:

    def test_onboarding_config_defaults(self):
        cfg = OnboardingConfig()
        assert cfg.enabled is True
        assert cfg.naming_ceremony is True
        assert cfg.activation_trust_threshold == 0.65

    @pytest.mark.asyncio
    @patch("probos.agent_onboarding.is_crew_agent", return_value=True)
    async def test_ceremony_skipped_when_disabled(self, mock_is_crew):
        """naming_ceremony=False → no LLM call, seed callsign kept."""
        from probos.runtime import ProbOSRuntime

        config = SystemConfig()
        config.onboarding.naming_ceremony = False

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = config
        rt.callsign_registry = CallsignRegistry()
        rt.capability_registry = MagicMock(spec=CapabilityRegistry)
        rt.gossip = MagicMock(spec=GossipProtocol)
        rt.trust_network = MagicMock(spec=TrustNetwork)
        rt.trust_network.get_or_create.return_value = None
        rt.trust_network.get_score.return_value = 0.5
        rt._emit_event = MagicMock()
        rt.event_log = AsyncMock(spec=EventLog)
        rt.intent_bus = MagicMock(spec=IntentBus)
        rt.identity_registry = None
        rt.acm = None
        rt.ward_room = None
        rt.ontology = None
        rt.registry = MagicMock(spec=AgentRegistry)
        rt.registry.all.return_value = []
        _attach_onboarding(rt)
        rt.onboarding.run_naming_ceremony = AsyncMock(return_value="McCoy")

        agent = _make_agent(callsign="Bones")
        await rt.onboarding.wire_agent(agent)

        # Naming ceremony should NOT have been called because naming_ceremony=False
        rt.onboarding.run_naming_ceremony.assert_not_called()
        assert agent.callsign == "Bones"


# ── Proactive Activation Check Tests ──────────────────────────────


class TestProactiveActivation:

    @pytest.mark.asyncio
    async def test_proactive_cycle_activates_probationary_agent(self, tmp_path):
        """Agent in PROBATIONARY with trust >= 0.65 → check_activation called."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop(interval=60, cooldown=0)

        rt = MagicMock(spec=ProbOSRuntime)
        rt.ward_room = AsyncMock(spec=WardRoomService)
        rt.config = SystemConfig()
        rt.ontology = None  # is_crew_agent uses legacy set; "diagnostician" is crew

        # Set up trust
        trust_record = MagicMock()
        trust_record.score = 0.70
        rt.trust_network = MagicMock(spec=TrustNetwork)
        rt.trust_network.get_score.return_value = 0.70
        rt.trust_network.get_record.return_value = trust_record

        # Set up ACM
        rt.acm = AsyncMock()
        rt.acm.check_activation = AsyncMock(return_value=True)

        # Set up agent
        agent = _make_agent()
        rt.registry = MagicMock(spec=AgentRegistry)
        rt.registry.all.return_value = [agent]

        # Make the agent pass proactive eligibility
        rt.ward_room_router = MagicMock(spec=WardRoomRouter)
        rt.ward_room_router.extract_endorsements = MagicMock(return_value=[])
        loop._runtime = rt
        loop._started_at = 0  # Long ago, no cold start dampening

        # Stub _think_for_agent to avoid full LLM path
        loop._think_for_agent = AsyncMock()

        await loop._run_cycle()

        rt.acm.check_activation.assert_called_once()
