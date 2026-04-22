"""Tests for BF-101/102 Enhancement: Ship's Computer auto-welcome for new crew.

Validates:
- _newly_commissioned flag set on naming ceremony (cold start path)
- _newly_commissioned flag NOT set on warm boot (identity restoration)
- Auto-welcome posts for new crew in finalize_startup()
- Auto-welcome skipped on cold start
- Auto-welcome skipped when no new crew
- Auto-welcome uses thread_mode='discuss'
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.agent_onboarding import AgentOnboardingService


@pytest.fixture(autouse=True)
def _clear_decision_cache():
    """Clear CognitiveAgent decision cache between tests to prevent pollution."""
    from probos.cognitive.cognitive_agent import _DECISION_CACHES

    _DECISION_CACHES.clear()
    yield
    _DECISION_CACHES.clear()


def _make_config():
    """Create minimal onboarding config."""
    cfg = SimpleNamespace(
        onboarding=SimpleNamespace(
            enabled=True,
            naming_ceremony=True,
        ),
        tiered_trust=SimpleNamespace(
            enabled=True,
            bridge_pools=["counselor"],
            bridge_callsigns=["Meridian"],
            chief_callsigns=["Bones", "LaForge", "Number One", "Worf", "O'Brien"],
            bridge_alpha=4.5,
            bridge_beta=1.0,
            chief_alpha=3.0,
            chief_beta=1.0,
        ),
        consensus=SimpleNamespace(
            trust_prior_alpha=2.0,
            trust_prior_beta=2.0,
        ),
    )
    return cfg


def _make_fake_agent(agent_type="data_analyst", callsign="Rahda"):
    """Create a fake agent for onboarding tests."""
    agent = MagicMock()
    agent.agent_type = agent_type
    agent.callsign = callsign
    agent.id = f"sci_{agent_type}_0_abc12345"
    agent.pool = "science"
    agent._llm_client = AsyncMock()
    agent._newly_commissioned = False
    return agent


# -----------------------------------------------------------------------
# _newly_commissioned flag tests
# -----------------------------------------------------------------------


class TestNewlyCommissionedFlag:
    """Enhancement: _newly_commissioned is set correctly during onboarding."""

    def _make_onboarding_service(self, identity_registry=None, callsign_registry=None):
        """Create AgentOnboardingService with all required args mocked."""
        config = _make_config()
        return AgentOnboardingService(
            config=config,
            identity_registry=identity_registry or MagicMock(),
            callsign_registry=callsign_registry or MagicMock(),
            capability_registry=MagicMock(),
            gossip=MagicMock(),
            intent_bus=MagicMock(),
            trust_network=MagicMock(),
            event_log=AsyncMock(),
            ontology=None,
            event_emitter=MagicMock(),
            llm_client=None,
            registry=MagicMock(),
            ward_room=None,
            acm=None,
        )

    @pytest.mark.asyncio
    async def test_flag_set_on_naming_ceremony(self):
        """After wire_agent() with naming ceremony, agent._newly_commissioned is True."""
        agent = _make_fake_agent()

        identity_registry = MagicMock()
        # No existing cert — cold start path
        identity_registry.get_by_slot.return_value = None
        identity_registry.issue_birth_certificate = MagicMock()

        callsign_registry = MagicMock()
        callsign_registry.get_callsign.return_value = "Rahda"

        svc = self._make_onboarding_service(
            identity_registry=identity_registry,
            callsign_registry=callsign_registry,
        )

        # Mock is_crew_agent to return True
        with patch("probos.agent_onboarding.is_crew_agent", return_value=True):
            # Mock naming ceremony to return a new callsign
            svc.run_naming_ceremony = AsyncMock(return_value="Kira")
            await svc.wire_agent(agent)

        assert getattr(agent, '_newly_commissioned', False) is True

    @pytest.mark.asyncio
    async def test_flag_not_set_on_warm_boot(self):
        """After wire_agent() with existing birth cert, _newly_commissioned is not True."""
        agent = _make_fake_agent()

        cert = SimpleNamespace(
            callsign="Kira",
            birth_timestamp=1000000.0,
        )
        identity_registry = MagicMock()
        identity_registry.get_by_slot.return_value = cert

        callsign_registry = MagicMock()
        callsign_registry.get_callsign.return_value = "Rahda"

        svc = self._make_onboarding_service(
            identity_registry=identity_registry,
            callsign_registry=callsign_registry,
        )
        svc._start_time_wall = 1000000.0

        with patch("probos.agent_onboarding.is_crew_agent", return_value=True):
            await svc.wire_agent(agent)

        assert getattr(agent, '_newly_commissioned', False) is False


# -----------------------------------------------------------------------
# Auto-welcome in finalize_startup() tests
# -----------------------------------------------------------------------


class TestAutoWelcome:
    """Enhancement: finalize_startup() posts batched auto-welcome."""

    @pytest.mark.asyncio
    async def test_auto_welcome_posts_for_new_crew(self):
        """With new crew flagged and ward_room available, posts 'New Crew Aboard'."""
        agent1 = SimpleNamespace(
            callsign="Kira", agent_type="data_analyst", _newly_commissioned=True,
            id="sci_data_analyst_0_abc12345",
        )
        agent2 = SimpleNamespace(
            callsign="Lynx", agent_type="systems_analyst", _newly_commissioned=True,
            id="sci_systems_analyst_0_def67890",
        )

        ward_room = AsyncMock()
        all_hands = SimpleNamespace(id="ch-1", name="All Hands")
        ward_room.get_channel_by_name = AsyncMock(return_value=all_hands)
        ward_room.create_thread = AsyncMock()

        registry = MagicMock()
        registry.all.return_value = [agent1, agent2]
        registry.count = 2

        runtime = MagicMock()
        runtime.ward_room = ward_room
        runtime._cold_start = False
        runtime.registry = registry
        runtime._started = False
        runtime._lifecycle_state = "restart"
        runtime._stasis_duration = 0
        runtime._previous_session = None
        runtime.event_log = AsyncMock()
        runtime.pools = {}
        runtime._red_team_agents = []
        runtime.ontology = None
        runtime.trust_network = MagicMock()
        runtime.trust_network.set_department_lookup = MagicMock()
        runtime.trust_network.set_event_callback = MagicMock()
        runtime.dream_scheduler = None
        runtime.self_mod_pipeline = None
        runtime.callsign_registry = None
        runtime.episodic_memory = None
        runtime.intent_bus = None
        runtime._knowledge_store = None
        runtime.initiative = None
        runtime._emergent_detector = None
        runtime.hebbian_router = None
        runtime.bridge_alerts = None
        runtime.behavioral_monitor = None
        runtime.acm = None
        runtime.onboarding = MagicMock()
        runtime.nats_bus = None

        config = MagicMock()
        config.proactive_cognitive.enabled = False

        from probos.startup.finalize import finalize_startup
        await finalize_startup(runtime=runtime, config=config)

        # Verify auto-welcome was called
        ward_room.create_thread.assert_called()
        calls = ward_room.create_thread.call_args_list
        # Find the "New Crew Aboard" call (may have startup announcement too)
        welcome_calls = [
            c for c in calls
            if c.kwargs.get("title") == "New Crew Aboard"
            or (c.args and len(c.args) > 0 and "New Crew" in str(c))
        ]
        assert len(welcome_calls) == 1
        call_kwargs = welcome_calls[0].kwargs
        assert "Kira" in call_kwargs["body"]
        assert "Lynx" in call_kwargs["body"]
        assert call_kwargs["thread_mode"] == "discuss"
        assert call_kwargs["author_callsign"] == "Ship's Computer"

    @pytest.mark.asyncio
    async def test_auto_welcome_skipped_on_cold_start(self):
        """When runtime._cold_start is True, auto-welcome is skipped."""
        agent = SimpleNamespace(
            callsign="Kira", agent_type="data_analyst", _newly_commissioned=True,
            id="sci_data_analyst_0_abc12345",
        )

        ward_room = AsyncMock()
        all_hands = SimpleNamespace(id="ch-1", name="All Hands")
        ward_room.get_channel_by_name = AsyncMock(return_value=all_hands)
        ward_room.create_thread = AsyncMock()

        registry = MagicMock()
        registry.all.return_value = [agent]
        registry.count = 1

        runtime = MagicMock()
        runtime.ward_room = ward_room
        runtime._cold_start = True  # Cold start!
        runtime.registry = registry
        runtime._started = False
        runtime._lifecycle_state = "first_boot"
        runtime._stasis_duration = 0
        runtime._previous_session = None
        runtime.event_log = AsyncMock()
        runtime.pools = {}
        runtime._red_team_agents = []
        runtime.ontology = None
        runtime.trust_network = MagicMock()
        runtime.trust_network.set_department_lookup = MagicMock()
        runtime.trust_network.set_event_callback = MagicMock()
        runtime.dream_scheduler = None
        runtime.self_mod_pipeline = None
        runtime.callsign_registry = None
        runtime.episodic_memory = None
        runtime.intent_bus = None
        runtime._knowledge_store = None
        runtime.initiative = None
        runtime._emergent_detector = None
        runtime.hebbian_router = None
        runtime.bridge_alerts = None
        runtime.behavioral_monitor = None
        runtime.acm = None
        runtime.onboarding = MagicMock()
        runtime.nats_bus = None

        config = MagicMock()
        config.proactive_cognitive.enabled = False

        from probos.startup.finalize import finalize_startup
        await finalize_startup(runtime=runtime, config=config)

        # The only create_thread call should be the startup announcement, not auto-welcome
        for call in ward_room.create_thread.call_args_list:
            if hasattr(call, 'kwargs'):
                assert call.kwargs.get("title") != "New Crew Aboard"

    @pytest.mark.asyncio
    async def test_auto_welcome_skipped_when_no_new_crew(self):
        """On warm boot with all identities restored, no auto-welcome."""
        agent = SimpleNamespace(
            callsign="Kira", agent_type="data_analyst",
            id="sci_data_analyst_0_abc12345",
            # No _newly_commissioned flag — warm boot
        )

        ward_room = AsyncMock()
        all_hands = SimpleNamespace(id="ch-1", name="All Hands")
        ward_room.get_channel_by_name = AsyncMock(return_value=all_hands)
        ward_room.create_thread = AsyncMock()

        registry = MagicMock()
        registry.all.return_value = [agent]
        registry.count = 1

        runtime = MagicMock()
        runtime.ward_room = ward_room
        runtime._cold_start = False
        runtime.registry = registry
        runtime._started = False
        runtime._lifecycle_state = "restart"
        runtime._stasis_duration = 0
        runtime._previous_session = None
        runtime.event_log = AsyncMock()
        runtime.pools = {}
        runtime._red_team_agents = []
        runtime.ontology = None
        runtime.trust_network = MagicMock()
        runtime.trust_network.set_department_lookup = MagicMock()
        runtime.trust_network.set_event_callback = MagicMock()
        runtime.dream_scheduler = None
        runtime.self_mod_pipeline = None
        runtime.callsign_registry = None
        runtime.episodic_memory = None
        runtime.intent_bus = None
        runtime._knowledge_store = None
        runtime.initiative = None
        runtime._emergent_detector = None
        runtime.hebbian_router = None
        runtime.bridge_alerts = None
        runtime.behavioral_monitor = None
        runtime.acm = None
        runtime.onboarding = MagicMock()
        runtime.nats_bus = None

        config = MagicMock()
        config.proactive_cognitive.enabled = False

        from probos.startup.finalize import finalize_startup
        await finalize_startup(runtime=runtime, config=config)

        # No "New Crew Aboard" thread
        for call in ward_room.create_thread.call_args_list:
            if hasattr(call, 'kwargs'):
                assert call.kwargs.get("title") != "New Crew Aboard"

    @pytest.mark.asyncio
    async def test_auto_welcome_uses_discuss_mode(self):
        """The auto-welcome thread uses thread_mode='discuss'."""
        agent = SimpleNamespace(
            callsign="Atlas", agent_type="research_specialist", _newly_commissioned=True,
            id="sci_research_specialist_0_ghi11111",
        )

        ward_room = AsyncMock()
        all_hands = SimpleNamespace(id="ch-1", name="All Hands")
        ward_room.get_channel_by_name = AsyncMock(return_value=all_hands)
        ward_room.create_thread = AsyncMock()

        registry = MagicMock()
        registry.all.return_value = [agent]
        registry.count = 1

        runtime = MagicMock()
        runtime.ward_room = ward_room
        runtime._cold_start = False
        runtime.registry = registry
        runtime._started = False
        runtime._lifecycle_state = "restart"
        runtime._stasis_duration = 0
        runtime._previous_session = None
        runtime.event_log = AsyncMock()
        runtime.pools = {}
        runtime._red_team_agents = []
        runtime.ontology = None
        runtime.trust_network = MagicMock()
        runtime.trust_network.set_department_lookup = MagicMock()
        runtime.trust_network.set_event_callback = MagicMock()
        runtime.dream_scheduler = None
        runtime.self_mod_pipeline = None
        runtime.callsign_registry = None
        runtime.episodic_memory = None
        runtime.intent_bus = None
        runtime._knowledge_store = None
        runtime.initiative = None
        runtime._emergent_detector = None
        runtime.hebbian_router = None
        runtime.bridge_alerts = None
        runtime.behavioral_monitor = None
        runtime.acm = None
        runtime.onboarding = MagicMock()
        runtime.nats_bus = None

        config = MagicMock()
        config.proactive_cognitive.enabled = False

        from probos.startup.finalize import finalize_startup
        await finalize_startup(runtime=runtime, config=config)

        welcome_calls = [
            c for c in ward_room.create_thread.call_args_list
            if c.kwargs.get("title") == "New Crew Aboard"
        ]
        assert len(welcome_calls) == 1
        assert welcome_calls[0].kwargs["thread_mode"] == "discuss"
