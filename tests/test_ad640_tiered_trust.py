"""AD-640: Tiered Trust Initialization — Tests."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from probos.config import TieredTrustConfig, SystemConfig
from probos.events import EventType
from probos.tiered_trust import TrustTier, resolve_tier, initialize_trust


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config():
    return TieredTrustConfig()


@pytest.fixture
def trust_network():
    mock = MagicMock()
    mock.create_with_prior = MagicMock()
    mock.get_or_create = MagicMock()
    return mock


# ---------------------------------------------------------------------------
# Tier Resolution Tests
# ---------------------------------------------------------------------------

class TestResolveTier:
    """Tests 1-5: Tier resolution logic."""

    def test_resolve_tier_bridge_pool(self, config):
        """counselor pool -> BRIDGE."""
        assert resolve_tier("counselor", "Echo", config) == TrustTier.BRIDGE

    def test_resolve_tier_bridge_callsign(self, config):
        """Meridian (First Officer) -> BRIDGE."""
        assert resolve_tier("architect", "Meridian", config) == TrustTier.BRIDGE

    def test_resolve_tier_chief_callsign(self, config):
        """Each chief callsign -> CHIEF."""
        for callsign in ["Bones", "LaForge", "Number One", "Worf", "O'Brien"]:
            assert resolve_tier("some_pool", callsign, config) == TrustTier.CHIEF

    def test_resolve_tier_crew_default(self, config):
        """Unknown pool/callsign -> CREW."""
        assert resolve_tier("some_pool", "Wesley", config) == TrustTier.CREW

    def test_resolve_tier_case_sensitive(self, config):
        """Callsigns are case-sensitive: 'bones' (lowercase) -> CREW."""
        assert resolve_tier("some_pool", "bones", config) == TrustTier.CREW
        assert resolve_tier("some_pool", "laforge", config) == TrustTier.CREW


# ---------------------------------------------------------------------------
# Trust Initialization Tests
# ---------------------------------------------------------------------------

class TestInitializeTrust:
    """Tests 6-10: Trust initialization."""

    def test_initialize_bridge_trust(self, config, trust_network):
        """Bridge agent gets alpha=4.5, beta=1.0."""
        tier = initialize_trust("agent-1", "counselor", "Echo", trust_network, config)
        assert tier == TrustTier.BRIDGE
        trust_network.create_with_prior.assert_called_once_with("agent-1", 4.5, 1.0)

    def test_initialize_chief_trust(self, config, trust_network):
        """Chief agent gets alpha=3.0, beta=1.0."""
        tier = initialize_trust("agent-2", "medical_diagnostician", "Bones", trust_network, config)
        assert tier == TrustTier.CHIEF
        trust_network.create_with_prior.assert_called_once_with("agent-2", 3.0, 1.0)

    def test_initialize_crew_trust(self, config, trust_network):
        """Crew agent gets default alpha=2.0, beta=2.0."""
        tier = initialize_trust("agent-3", "some_pool", "Wesley", trust_network, config)
        assert tier == TrustTier.CREW
        trust_network.create_with_prior.assert_called_once_with("agent-3", 2.0, 2.0)

    def test_initialize_disabled(self, trust_network):
        """When enabled=False, all agents get default (get_or_create path)."""
        cfg = TieredTrustConfig(enabled=False)
        tier = initialize_trust("agent-4", "counselor", "Echo", trust_network, cfg)
        assert tier == TrustTier.CREW
        trust_network.get_or_create.assert_called_once_with("agent-4")
        trust_network.create_with_prior.assert_not_called()

    def test_initialize_returns_tier(self, config, trust_network):
        """Return value matches resolved tier."""
        assert initialize_trust("a", "counselor", "Echo", trust_network, config) == TrustTier.BRIDGE
        trust_network.reset_mock()
        assert initialize_trust("b", "x", "LaForge", trust_network, config) == TrustTier.CHIEF
        trust_network.reset_mock()
        assert initialize_trust("c", "x", "Wesley", trust_network, config) == TrustTier.CREW

    def test_initialize_custom_consensus_priors(self, config, trust_network):
        """Crew uses provided consensus priors, not hardcoded defaults."""
        initialize_trust("agent-5", "some_pool", "Wesley", trust_network, config,
                         consensus_alpha=3.0, consensus_beta=3.0)
        trust_network.create_with_prior.assert_called_once_with("agent-5", 3.0, 3.0)


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestOnboardingIntegration:
    """Tests 11-12: Onboarding integration (mock-based)."""

    def _make_onboarding_service(self, mock_trust, mock_event_emitter, mock_config):
        from probos.agent_onboarding import AgentOnboardingService
        mock_callsign_registry = MagicMock()
        mock_callsign_registry.get_callsign = MagicMock(return_value=None)
        return AgentOnboardingService(
            config=mock_config,
            trust_network=mock_trust,
            event_emitter=mock_event_emitter,
            event_log=AsyncMock(),
            callsign_registry=mock_callsign_registry,
            capability_registry=MagicMock(),
            gossip=MagicMock(),
            intent_bus=MagicMock(),
            identity_registry=None,
            ontology=None,
            llm_client=None,
            registry=MagicMock(),
            ward_room=None,
            acm=None,
        )

    @pytest.mark.asyncio
    async def test_onboarding_uses_tiered_trust(self):
        """AgentOnboardingService calls initialize_trust (not bare get_or_create)."""
        mock_config = MagicMock()
        mock_config.tiered_trust = TieredTrustConfig()
        mock_config.consensus.trust_prior_alpha = 2.0
        mock_config.consensus.trust_prior_beta = 2.0

        mock_trust = MagicMock()
        mock_trust.create_with_prior = MagicMock()
        mock_trust.get_or_create = MagicMock()
        mock_trust.get_score = MagicMock(return_value=0.75)

        mock_event_emitter = MagicMock()
        service = self._make_onboarding_service(mock_trust, mock_event_emitter, mock_config)

        agent = MagicMock()
        agent.id = "test-bridge-agent"
        agent.pool = "counselor"
        agent.callsign = "Echo"
        agent.agent_type = "counselor"
        agent.state = MagicMock(value="idle")
        agent.confidence = 1.0

        await service.wire_agent(agent)

        mock_trust.create_with_prior.assert_called_once_with("test-bridge-agent", 4.5, 1.0)

    @pytest.mark.asyncio
    async def test_tiered_trust_event_emitted(self):
        """TIERED_TRUST_INITIALIZED event fires with correct tier/trust."""
        mock_config = MagicMock()
        mock_config.tiered_trust = TieredTrustConfig()
        mock_config.consensus.trust_prior_alpha = 2.0
        mock_config.consensus.trust_prior_beta = 2.0

        mock_trust = MagicMock()
        mock_trust.create_with_prior = MagicMock()
        mock_trust.get_score = MagicMock(return_value=0.82)

        mock_event_emitter = MagicMock()
        service = self._make_onboarding_service(mock_trust, mock_event_emitter, mock_config)

        agent = MagicMock()
        agent.id = "test-chief"
        agent.pool = "medical_diagnostician"
        agent.callsign = "Bones"
        agent.agent_type = "medical_diagnostician"
        agent.state = MagicMock(value="idle")
        agent.confidence = 1.0

        await service.wire_agent(agent)

        tiered_calls = [
            c for c in mock_event_emitter.call_args_list
            if c[0][0] == EventType.TIERED_TRUST_INITIALIZED
        ]
        assert len(tiered_calls) == 1
        data = tiered_calls[0][0][1]
        assert data["tier"] == "chief"
        assert data["callsign"] == "Bones"


class TestBootCampIntegration:
    """Tests 13-14: Boot camp skips high-trust agents."""

    @pytest.mark.asyncio
    async def test_boot_camp_skips_high_trust(self):
        """Bridge/Chief agents skip boot camp enrollment."""
        from probos.boot_camp import BootCampCoordinator
        from probos.config import BootCampConfig

        mock_trust = MagicMock()
        # Bridge agent: trust 0.82 (above min_trust_score 0.55)
        mock_trust.get_trust_score = MagicMock(return_value=0.82)

        coordinator = BootCampCoordinator(
            config=BootCampConfig(),
            ward_room=MagicMock(),
            trust_service=mock_trust,
            episodic_memory=AsyncMock(),
            emit_event_fn=MagicMock(),
        )

        await coordinator.activate([
            {"agent_id": "bridge-1", "callsign": "Echo", "department": "bridge"},
        ])

        assert coordinator.is_active
        assert not coordinator.is_enrolled("bridge-1")

    @pytest.mark.asyncio
    async def test_boot_camp_enrolls_crew(self):
        """Crew agents (low trust) still enrolled in boot camp."""
        from probos.boot_camp import BootCampCoordinator
        from probos.config import BootCampConfig

        mock_trust = MagicMock()
        # Crew agent: trust 0.50 (below min_trust_score 0.55)
        mock_trust.get_trust_score = MagicMock(return_value=0.50)

        mock_ward_room = AsyncMock()
        mock_ward_room.get_or_create_dm_channel = AsyncMock(return_value=MagicMock(id="dm-1"))
        mock_ward_room.create_thread = AsyncMock(return_value=MagicMock(id="t-1"))
        mock_ward_room.create_post = AsyncMock(return_value=MagicMock(id="p-1"))

        coordinator = BootCampCoordinator(
            config=BootCampConfig(),
            ward_room=mock_ward_room,
            trust_service=mock_trust,
            episodic_memory=AsyncMock(),
            emit_event_fn=MagicMock(),
        )

        await coordinator.activate([
            {"agent_id": "crew-1", "callsign": "Wesley", "department": "science"},
        ])

        assert coordinator.is_active
        assert coordinator.is_enrolled("crew-1")


# ---------------------------------------------------------------------------
# Config Tests
# ---------------------------------------------------------------------------

class TestTieredTrustConfig:
    """Tests 16-18: Config validation."""

    def test_tiered_trust_config_defaults(self):
        """Default values match research recommendation."""
        cfg = TieredTrustConfig()
        assert cfg.enabled is True
        assert cfg.bridge_alpha == 4.5
        assert cfg.bridge_beta == 1.0
        assert cfg.chief_alpha == 3.0
        assert cfg.chief_beta == 1.0
        assert "counselor" in cfg.bridge_pools
        assert "Meridian" in cfg.bridge_callsigns
        assert "Bones" in cfg.chief_callsigns
        assert len(cfg.chief_callsigns) == 5

    def test_tiered_trust_config_customizable(self):
        """Values can be overridden via config."""
        cfg = TieredTrustConfig(
            bridge_alpha=5.0,
            bridge_beta=0.5,
            chief_callsigns=["CustomChief"],
        )
        assert cfg.bridge_alpha == 5.0
        assert cfg.bridge_beta == 0.5
        assert cfg.chief_callsigns == ["CustomChief"]

    def test_system_config_includes_tiered_trust(self):
        """SystemConfig().tiered_trust exists."""
        sys_cfg = SystemConfig()
        assert hasattr(sys_cfg, "tiered_trust")
        assert isinstance(sys_cfg.tiered_trust, TieredTrustConfig)
