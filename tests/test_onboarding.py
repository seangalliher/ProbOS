"""AD-442: Adaptive Onboarding & Self-Naming Ceremony tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.acm import AgentCapitalService, LifecycleState
from probos.config import OnboardingConfig, SystemConfig
from probos.crew_profile import CallsignRegistry


# ── Fixtures / Helpers ──────────────────────────────────────────────


def _make_agent(agent_type: str = "diagnostician", callsign: str = "Bones", agent_id: str = "diag-1"):
    agent = MagicMock()
    agent.agent_type = agent_type
    agent.callsign = callsign
    agent.id = agent_id
    agent.pool = agent_type
    agent.state = MagicMock(value="idle")
    agent.confidence = 0.9
    agent.capabilities = []
    agent.is_alive = True
    agent._llm_client = AsyncMock()
    return agent


def _make_runtime(config=None):
    """Build a minimal mock runtime for naming ceremony tests."""
    rt = MagicMock()
    rt.config = config or SystemConfig()
    rt.ontology = None
    rt.identity_registry = None
    rt.registry = MagicMock()
    rt.registry.all.return_value = []
    return rt


# ── Naming Ceremony Tests ──────────────────────────────────────────


class TestNamingCeremony:
    """Tests for _run_naming_ceremony()."""

    def test_naming_ceremony_returns_chosen_callsign(self):
        """Mock LLM returns 'McCoy\\nA classic name.' → returns 'McCoy'."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.ontology = None
        rt.identity_registry = None
        rt.registry = MagicMock()
        rt.registry.all.return_value = []

        agent = _make_agent()
        agent._llm_client.complete = AsyncMock(return_value="McCoy\nA classic name for a doctor.")

        result = asyncio.get_event_loop().run_until_complete(rt._run_naming_ceremony(agent))
        assert result == "McCoy"

    def test_naming_ceremony_fallback_on_empty(self):
        """Empty LLM response → seed callsign returned."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.ontology = None
        rt.identity_registry = None
        rt.registry = MagicMock()
        rt.registry.all.return_value = []

        agent = _make_agent(callsign="Bones")
        agent._llm_client.complete = AsyncMock(return_value="")

        result = asyncio.get_event_loop().run_until_complete(rt._run_naming_ceremony(agent))
        assert result == "Bones"

    def test_naming_ceremony_fallback_on_error(self):
        """LLM raises exception → seed callsign returned."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.ontology = None
        rt.identity_registry = None
        rt.registry = MagicMock()
        rt.registry.all.return_value = []

        agent = _make_agent(callsign="Bones")
        agent._llm_client.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

        result = asyncio.get_event_loop().run_until_complete(rt._run_naming_ceremony(agent))
        assert result == "Bones"

    def test_naming_ceremony_rejects_duplicate(self):
        """Duplicate callsign → seed callsign used instead."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.ontology = None
        rt.identity_registry = None

        # Existing crew member already named "Bones"
        existing = _make_agent(agent_type="other", callsign="Bones", agent_id="other-1")
        rt.registry = MagicMock()
        rt.registry.all.return_value = [existing]

        agent = _make_agent(agent_type="diagnostician", callsign="Doc", agent_id="diag-1")
        agent._llm_client.complete = AsyncMock(return_value="Bones\nI want to be called Bones.")

        result = asyncio.get_event_loop().run_until_complete(rt._run_naming_ceremony(agent))
        assert result == "Doc"  # Falls back to seed

    def test_naming_ceremony_truncates_long_name(self):
        """50-char name → seed callsign used as fallback."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.ontology = None
        rt.identity_registry = None
        rt.registry = MagicMock()
        rt.registry.all.return_value = []

        agent = _make_agent(callsign="Bones")
        long_name = "A" * 50
        agent._llm_client.complete = AsyncMock(return_value=f"{long_name}\nToo long.")

        result = asyncio.get_event_loop().run_until_complete(rt._run_naming_ceremony(agent))
        assert result == "Bones"

    def test_naming_ceremony_strips_quotes(self):
        """LLM returns '"Scotty"' with quotes → stripped to 'Scotty'."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.ontology = None
        rt.identity_registry = None
        rt.registry = MagicMock()
        rt.registry.all.return_value = []

        agent = _make_agent(callsign="Bones")
        agent._llm_client.complete = AsyncMock(return_value='"Scotty"\nThe name feels right.')

        result = asyncio.get_event_loop().run_until_complete(rt._run_naming_ceremony(agent))
        assert result == "Scotty"


# ── Wire Agent Integration Tests ───────────────────────────────────


class TestWireAgentIntegration:
    """Tests for _wire_agent() naming ceremony integration."""

    def _make_wired_runtime(self):
        """Build a ProbOSRuntime with enough wired up for _wire_agent()."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = SystemConfig()
        rt.callsign_registry = CallsignRegistry()
        rt.capability_registry = MagicMock()
        rt.gossip = MagicMock()
        rt.trust_network = MagicMock()
        rt.trust_network.get_or_create.return_value = None
        rt.trust_network.get_score.return_value = 0.5
        rt._emit_event = MagicMock()
        rt.event_log = AsyncMock()
        rt.intent_bus = MagicMock()
        rt.identity_registry = None
        rt.acm = None
        rt.ward_room = None
        rt.ontology = None
        rt.registry = MagicMock()
        rt.registry.all.return_value = []
        rt._is_crew_agent = MagicMock(return_value=True)
        return rt

    def test_wire_agent_runs_ceremony_for_crew(self):
        rt = self._make_wired_runtime()
        rt._run_naming_ceremony = AsyncMock(return_value="McCoy")

        agent = _make_agent(callsign="Bones")
        asyncio.get_event_loop().run_until_complete(rt._wire_agent(agent))

        rt._run_naming_ceremony.assert_called_once_with(agent)

    def test_wire_agent_skips_ceremony_for_infrastructure(self):
        rt = self._make_wired_runtime()
        rt._is_crew_agent = MagicMock(return_value=False)
        rt._run_naming_ceremony = AsyncMock()

        agent = _make_agent(agent_type="introspect", callsign="")
        del agent._llm_client  # Infrastructure agents have no LLM client
        asyncio.get_event_loop().run_until_complete(rt._wire_agent(agent))

        rt._run_naming_ceremony.assert_not_called()

    def test_wire_agent_birth_cert_uses_chosen_name(self):
        rt = self._make_wired_runtime()
        rt._run_naming_ceremony = AsyncMock(return_value="McCoy")
        rt.callsign_registry.set_callsign = MagicMock()

        agent = _make_agent(callsign="Bones")
        asyncio.get_event_loop().run_until_complete(rt._wire_agent(agent))

        # After ceremony, agent.callsign should be updated
        assert agent.callsign == "McCoy"
        rt.callsign_registry.set_callsign.assert_called_once_with("diagnostician", "McCoy")

    def test_wire_agent_posts_welcome_announcement(self):
        rt = self._make_wired_runtime()
        rt._run_naming_ceremony = AsyncMock(return_value="McCoy")

        # Set up Ward Room mock
        all_hands_channel = MagicMock()
        all_hands_channel.name = "All Hands"
        all_hands_channel.id = "ch-all-hands"
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[all_hands_channel])
        rt.ward_room.create_thread = AsyncMock()

        agent = _make_agent(callsign="Bones")
        asyncio.get_event_loop().run_until_complete(rt._wire_agent(agent))

        rt.ward_room.create_thread.assert_called_once()
        call_kwargs = rt.ward_room.create_thread.call_args
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

    def test_check_activation_promotes_at_threshold(self, tmp_path):
        """trust=0.65 → PROBATIONARY → ACTIVE."""
        acm = AgentCapitalService(tmp_path)
        asyncio.get_event_loop().run_until_complete(acm.start())

        # Onboard to get to PROBATIONARY
        asyncio.get_event_loop().run_until_complete(
            acm.onboard("agent-1", "diagnostician", "diagnostician", "medical")
        )
        state = asyncio.get_event_loop().run_until_complete(acm.get_lifecycle_state("agent-1"))
        assert state == LifecycleState.PROBATIONARY

        result = asyncio.get_event_loop().run_until_complete(
            acm.check_activation("agent-1", trust_score=0.65)
        )
        assert result is True

        state = asyncio.get_event_loop().run_until_complete(acm.get_lifecycle_state("agent-1"))
        assert state == LifecycleState.ACTIVE

        asyncio.get_event_loop().run_until_complete(acm.stop())

    def test_check_activation_no_op_below_threshold(self, tmp_path):
        """trust=0.50 → stays PROBATIONARY."""
        acm = AgentCapitalService(tmp_path)
        asyncio.get_event_loop().run_until_complete(acm.start())

        asyncio.get_event_loop().run_until_complete(
            acm.onboard("agent-1", "diagnostician", "diagnostician", "medical")
        )

        result = asyncio.get_event_loop().run_until_complete(
            acm.check_activation("agent-1", trust_score=0.50)
        )
        assert result is False

        state = asyncio.get_event_loop().run_until_complete(acm.get_lifecycle_state("agent-1"))
        assert state == LifecycleState.PROBATIONARY

        asyncio.get_event_loop().run_until_complete(acm.stop())

    def test_check_activation_no_op_if_already_active(self, tmp_path):
        """Already ACTIVE → returns False."""
        acm = AgentCapitalService(tmp_path)
        asyncio.get_event_loop().run_until_complete(acm.start())

        asyncio.get_event_loop().run_until_complete(
            acm.onboard("agent-1", "diagnostician", "diagnostician", "medical")
        )
        # Manually activate
        asyncio.get_event_loop().run_until_complete(
            acm.transition("agent-1", LifecycleState.ACTIVE, reason="manual")
        )

        result = asyncio.get_event_loop().run_until_complete(
            acm.check_activation("agent-1", trust_score=0.90)
        )
        assert result is False

        asyncio.get_event_loop().run_until_complete(acm.stop())


# ── Config Tests ───────────────────────────────────────────────────


class TestOnboardingConfig:

    def test_onboarding_config_defaults(self):
        cfg = OnboardingConfig()
        assert cfg.enabled is True
        assert cfg.naming_ceremony is True
        assert cfg.activation_trust_threshold == 0.65

    def test_ceremony_skipped_when_disabled(self):
        """naming_ceremony=False → no LLM call, seed callsign kept."""
        from probos.runtime import ProbOSRuntime

        config = SystemConfig()
        config.onboarding.naming_ceremony = False

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.config = config
        rt.callsign_registry = CallsignRegistry()
        rt.capability_registry = MagicMock()
        rt.gossip = MagicMock()
        rt.trust_network = MagicMock()
        rt.trust_network.get_or_create.return_value = None
        rt.trust_network.get_score.return_value = 0.5
        rt._emit_event = MagicMock()
        rt.event_log = AsyncMock()
        rt.intent_bus = MagicMock()
        rt.identity_registry = None
        rt.acm = None
        rt.ward_room = None
        rt.ontology = None
        rt.registry = MagicMock()
        rt.registry.all.return_value = []
        rt._is_crew_agent = MagicMock(return_value=True)
        rt._run_naming_ceremony = AsyncMock(return_value="McCoy")

        agent = _make_agent(callsign="Bones")
        asyncio.get_event_loop().run_until_complete(rt._wire_agent(agent))

        # Naming ceremony should NOT have been called because naming_ceremony=False
        rt._run_naming_ceremony.assert_not_called()
        assert agent.callsign == "Bones"


# ── Proactive Activation Check Tests ──────────────────────────────


class TestProactiveActivation:

    def test_proactive_cycle_activates_probationary_agent(self, tmp_path):
        """Agent in PROBATIONARY with trust >= 0.65 → check_activation called."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop(interval=60)

        rt = MagicMock()
        rt.ward_room = MagicMock()
        rt.config = SystemConfig()
        rt._is_crew_agent = MagicMock(return_value=True)

        # Set up trust
        trust_record = MagicMock()
        trust_record.score = 0.70
        rt.trust_network = MagicMock()
        rt.trust_network.get_score.return_value = 0.70
        rt.trust_network.get_trust.return_value = trust_record

        # Set up ACM
        rt.acm = AsyncMock()
        rt.acm.check_activation = AsyncMock(return_value=True)

        # Set up agent
        agent = _make_agent()
        rt.registry = MagicMock()
        rt.registry.all.return_value = [agent]

        # Make the agent pass proactive eligibility
        rt._extract_endorsements = MagicMock(return_value=[])
        loop._runtime = rt
        loop._started_at = 0  # Long ago, no cold start dampening

        # Stub _think_for_agent to avoid full LLM path
        loop._think_for_agent = AsyncMock()

        asyncio.get_event_loop().run_until_complete(loop._run_cycle())

        rt.acm.check_activation.assert_called_once()
