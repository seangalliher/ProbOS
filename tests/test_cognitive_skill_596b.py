"""Tests for AD-596b: Intent Discovery + compose_instructions() Integration."""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.skill_catalog import (
    CognitiveSkillCatalog,
    CognitiveSkillEntry,
)
from probos.cognitive.standing_orders import (
    _skill_catalog,
    compose_instructions,
    set_skill_catalog,
)
from probos.types import IntentDescriptor, IntentMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_catalog_mock(
    descriptions: list[tuple[str, str, str]] | None = None,
    entries: list[CognitiveSkillEntry] | None = None,
    instructions: dict[str, str] | None = None,
    intent_map: dict[str, list[CognitiveSkillEntry]] | None = None,
) -> MagicMock:
    """Build a mock CognitiveSkillCatalog with controllable return values."""
    catalog = MagicMock()
    catalog.get_descriptions.return_value = descriptions or []
    catalog.list_entries.return_value = entries or []
    catalog.get_instructions.side_effect = lambda name: (instructions or {}).get(name)
    catalog.find_by_intent.side_effect = lambda i: (intent_map or {}).get(i, [])
    return catalog


def _make_skill_entry(
    name: str = "test-skill",
    description: str = "A test skill",
    department: str = "*",
    min_rank: str = "ensign",
    intents: list[str] | None = None,
    skill_dir: Path | None = None,
) -> CognitiveSkillEntry:
    return CognitiveSkillEntry(
        name=name,
        description=description,
        skill_dir=skill_dir or Path("/tmp/skills/test"),
        department=department,
        min_rank=min_rank,
        intents=intents or [],
    )


# ===========================================================================
# compose_instructions() Integration
# ===========================================================================


class TestComposeSkillIntegration:
    """Tier 7 cognitive skills in compose_instructions()."""

    def setup_method(self):
        set_skill_catalog(None)

    def teardown_method(self):
        set_skill_catalog(None)

    def test_compose_includes_skill_descriptions(self):
        """With catalog set, output includes Available Cognitive Skills section."""
        catalog = _make_catalog_mock(descriptions=[
            ("code-review", "Review code for quality", "code_review"),
            ("design-check", "Check architecture compliance", "design_check"),
        ])
        set_skill_catalog(catalog)

        result = compose_instructions("builder", "")
        assert "<available_skills>" in result
        assert 'name="code-review"' in result
        assert 'name="design-check"' in result
        assert "Review code for quality" in result

    def test_compose_no_catalog_no_skills_section(self):
        """Without catalog, output has no skills section."""
        result = compose_instructions("builder", "")
        assert "Available Cognitive Skills" not in result

    def test_compose_filters_by_department(self):
        """Department is passed to get_descriptions for filtering."""
        catalog = _make_catalog_mock(descriptions=[("s", "d", "")])
        set_skill_catalog(catalog)

        compose_instructions("builder", "", department="engineering")
        catalog.get_descriptions.assert_called_once_with(
            department="engineering",
            agent_rank=None,
        )

    def test_compose_filters_by_rank(self):
        """agent_rank parameter is passed through for rank filtering."""
        catalog = _make_catalog_mock(descriptions=[("s", "d", "")])
        set_skill_catalog(catalog)

        # "builder" auto-resolves to department="engineering" via get_department()
        compose_instructions("builder", "", agent_rank="lieutenant")
        catalog.get_descriptions.assert_called_once_with(
            department="engineering",
            agent_rank="lieutenant",
        )

    def test_compose_agent_rank_none_shows_all(self):
        """agent_rank=None shows all skills (backward compat)."""
        catalog = _make_catalog_mock(descriptions=[("s", "d", "")])
        set_skill_catalog(catalog)

        # "builder" auto-resolves to department="engineering" via get_department()
        compose_instructions("builder", "")
        catalog.get_descriptions.assert_called_once_with(
            department="engineering",
            agent_rank=None,
        )


# ===========================================================================
# _gather_context() Integration
# ===========================================================================


class TestGatherContextSkills:
    """Cognitive skill descriptions in proactive _gather_context()."""

    def _make_loop_and_rt(self, catalog=None):
        """Build a minimal ProactiveCognitiveLoop with mocked internals.

        Disables deep code paths (episodic memory, ward room, etc.) by
        setting their runtime attributes to None so hasattr() guards
        pass but the truthiness check fails.
        """
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)

        # Attributes accessed directly on self (no hasattr guard)
        loop._llm_status = "operational"
        loop._llm_failure_count = 0
        loop._agent_cooldowns = {}
        loop._cooldown = 120.0
        loop._config = MagicMock()
        loop._config.system = MagicMock()

        # Runtime mock — disable deep code paths by setting to None
        rt = MagicMock()
        rt.cognitive_skill_catalog = catalog
        rt.episodic_memory = None      # skip section 1
        rt.bridge_alerts = None        # skip section 2
        rt.event_log = None            # skip section 3
        rt.ward_room = None            # skip section 4
        rt.skill_service = None        # skip section 6
        rt._social_memory_service = None
        rt.recreation_service = None
        rt._introspective_telemetry = None
        rt.conn_manager = None

        loop._runtime = rt
        return loop, rt

    def test_gather_context_includes_cognitive_skills(self):
        """Context dict has cognitive_skills key when catalog exists."""
        catalog = _make_catalog_mock(
            descriptions=[("my-skill", "Does things")]
        )
        loop, rt = self._make_loop_and_rt(catalog=catalog)
        rt.ontology.get_agent_department.return_value = "engineering"
        rt.trust_network.get_score.return_value = 0.5

        agent = MagicMock()
        agent.id = "test-agent"
        agent.agent_type = "builder"

        context = asyncio.run(loop._gather_context(agent, 0.5))

        assert "cognitive_skills" in context
        assert context["cognitive_skills"] == [
            {"name": "my-skill", "description": "Does things"}
        ]

    def test_gather_context_no_catalog_no_skills(self):
        """Without catalog, context has no cognitive_skills key."""
        loop, rt = self._make_loop_and_rt(catalog=None)

        agent = MagicMock()
        agent.id = "test-agent"
        agent.agent_type = "builder"

        context = asyncio.run(loop._gather_context(agent, 0.5))

        assert "cognitive_skills" not in context

    def test_gather_context_filters_by_department_and_rank(self):
        """Department and rank are passed to get_descriptions."""
        catalog = _make_catalog_mock(descriptions=[])
        loop, rt = self._make_loop_and_rt(catalog=catalog)
        rt.ontology.get_agent_department.return_value = "engineering"
        rt.trust_network.get_score.return_value = 0.7

        agent = MagicMock()
        agent.id = "test-agent"
        agent.agent_type = "builder"

        asyncio.run(loop._gather_context(agent, 0.7))

        # Verify department and rank were passed
        call_args = catalog.get_descriptions.call_args
        assert call_args is not None
        assert call_args.kwargs.get("department") == "engineering"
        # Rank is resolved from trust score via Rank.from_trust()
        assert call_args.kwargs.get("agent_rank") is not None


# ===========================================================================
# _collect_intent_descriptors() Integration
# ===========================================================================


class TestCollectIntentDescriptors:
    """Cognitive skill intents in _collect_intent_descriptors()."""

    def _make_runtime(self, catalog=None):
        """Build a minimal runtime mock with spawner and catalog."""
        rt = MagicMock()

        # Agent template with one intent
        template_cls = MagicMock()
        template_cls.intent_descriptors = [
            IntentDescriptor(name="read_file", description="Read a file")
        ]
        rt.spawner._templates = {"builder": template_cls}
        rt.cognitive_skill_catalog = catalog

        # Import the actual method and bind to mock
        from probos.runtime import ProbOSRuntime
        rt._collect_intent_descriptors = ProbOSRuntime._collect_intent_descriptors.__get__(rt)

        return rt

    def test_collect_descriptors_includes_catalog_intents(self):
        """Descriptor list includes cognitive skill intents."""
        entry = _make_skill_entry(
            name="comm-skill",
            description="Communication skill",
            intents=["proactive_think"],
        )
        catalog = _make_catalog_mock(entries=[entry])
        rt = self._make_runtime(catalog=catalog)

        descriptors = rt._collect_intent_descriptors()
        names = [d.name for d in descriptors]

        assert "read_file" in names  # from template
        assert "proactive_think" in names  # from skill

    def test_collect_descriptors_deduplicates(self):
        """Same intent name in template and skill = no duplicate."""
        entry = _make_skill_entry(intents=["read_file"])
        catalog = _make_catalog_mock(entries=[entry])
        rt = self._make_runtime(catalog=catalog)

        descriptors = rt._collect_intent_descriptors()
        read_file_count = sum(1 for d in descriptors if d.name == "read_file")
        assert read_file_count == 1

    def test_collect_descriptors_no_catalog_unchanged(self):
        """Without catalog, only template descriptors returned."""
        rt = self._make_runtime(catalog=None)

        descriptors = rt._collect_intent_descriptors()
        assert len(descriptors) == 1
        assert descriptors[0].name == "read_file"


# ===========================================================================
# handle_intent() — On-Demand Loading
# ===========================================================================


class TestHandleIntentSkills:
    """Cognitive skill on-demand loading in handle_intent()."""

    def _make_agent(self, catalog=None, handled_intents=None):
        """Build a minimal CognitiveAgent mock for handle_intent testing."""
        from probos.cognitive.cognitive_agent import CognitiveAgent
        from probos.types import AgentMeta
        from probos.substrate.agent import AgentState

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent.id = "test-agent-001"
        agent.agent_type = "builder"
        agent.callsign = "TestAgent"
        agent._handled_intents = handled_intents or {"direct_message", "ward_room_notification"}
        agent._skills = {}
        agent._cognitive_skill_catalog = catalog
        agent._llm_client = AsyncMock()
        agent._runtime = MagicMock()
        agent._runtime.registry.get_by_pool.return_value = []  # no counselors
        agent._runtime.procedure_store = None  # no procedure store (accessed via @property)
        agent.instructions = ""
        agent.rank = None
        agent.confidence = 0.8
        agent.meta = AgentMeta()
        agent.state = AgentState.ACTIVE
        agent._last_fallback_info = None
        agent._working_memory = None

        # Mock perceive and decide
        agent.perceive = AsyncMock(return_value={
            "intent": "custom_skill_intent",
            "text": "test input",
        })
        agent._recall_relevant_memories = AsyncMock(side_effect=lambda i, o: o)
        agent.decide = AsyncMock(return_value={
            "action": "execute",
            "llm_output": "Test response",
        })
        agent.act = AsyncMock(return_value={"success": True, "result": "done"})
        agent._check_response_faithfulness = MagicMock(return_value=None)
        agent._check_introspective_faithfulness = MagicMock(return_value=None)
        agent._store_action_episode = AsyncMock()

        return agent

    def test_handle_intent_cognitive_skill_match(self):
        """Intent not in _handled_intents but in catalog → skill loaded."""
        entry = _make_skill_entry(
            name="comm-discipline",
            intents=["custom_skill_intent"],
        )
        catalog = _make_catalog_mock(
            intent_map={"custom_skill_intent": [entry]},
            instructions={"comm-discipline": "# Full Instructions\nDo the thing."},
        )
        agent = self._make_agent(catalog=catalog)

        intent = IntentMessage(intent="custom_skill_intent", target_agent_id=None)
        result = asyncio.run(agent.handle_intent(intent))

        # Should NOT return None — skill was found
        # decide() was called (cognitive lifecycle ran)
        agent.decide.assert_called_once()

    def test_handle_intent_no_match_returns_none(self):
        """Intent not in _handled_intents and not in catalog → returns None."""
        catalog = _make_catalog_mock()  # empty, no skill matches
        agent = self._make_agent(catalog=catalog)

        intent = IntentMessage(intent="unknown_intent", target_agent_id=None)
        result = asyncio.run(agent.handle_intent(intent))

        assert result is None

    def test_handle_intent_hardcoded_takes_precedence(self):
        """Intent in _handled_intents → hardcoded path used, no catalog check."""
        entry = _make_skill_entry(intents=["direct_message"])
        catalog = _make_catalog_mock(
            intent_map={"direct_message": [entry]},
        )
        agent = self._make_agent(
            catalog=catalog,
            handled_intents={"direct_message", "ward_room_notification"},
        )

        intent = IntentMessage(
            intent="direct_message",
            target_agent_id="test-agent-001",
        )
        result = asyncio.run(agent.handle_intent(intent))

        # Should have gone through normal path, not skill path
        # catalog.find_by_intent should NOT have been called
        catalog.find_by_intent.assert_not_called()

    def test_handle_intent_skill_instructions_injected(self):
        """Observation dict contains cognitive_skill_instructions when skill activated."""
        entry = _make_skill_entry(
            name="test-skill",
            intents=["skill_intent"],
        )
        catalog = _make_catalog_mock(
            intent_map={"skill_intent": [entry]},
            instructions={"test-skill": "# Instructions\nStep 1."},
        )
        agent = self._make_agent(catalog=catalog)

        intent = IntentMessage(intent="skill_intent", target_agent_id=None)
        asyncio.run(agent.handle_intent(intent))

        # Check that decide() received observation with skill instructions
        obs = agent.decide.call_args[0][0]
        assert "cognitive_skill_instructions" in obs
        assert obs["cognitive_skill_instructions"] == "# Instructions\nStep 1."
        assert obs["cognitive_skill_name"] == "test-skill"

    def test_handle_intent_no_catalog_returns_none(self):
        """Agent without catalog set, unhandled intent → returns None."""
        agent = self._make_agent(catalog=None)

        intent = IntentMessage(intent="unknown_intent", target_agent_id=None)
        result = asyncio.run(agent.handle_intent(intent))

        assert result is None


# ===========================================================================
# Onboarding Wiring
# ===========================================================================


class TestOnboardingWiring:
    """Catalog wiring through AgentOnboardingService."""

    def test_wire_agent_sets_catalog_on_agent(self):
        """After wire_agent(), agent has _cognitive_skill_catalog attribute."""
        from probos.agent_onboarding import AgentOnboardingService

        catalog = _make_catalog_mock(entries=[])
        svc = AgentOnboardingService.__new__(AgentOnboardingService)
        svc._cognitive_skill_catalog = catalog
        svc._callsign_registry = MagicMock()
        svc._callsign_registry.get_callsign.return_value = "TestBot"
        svc._intent_bus = MagicMock()
        svc._trust_network = MagicMock()
        svc._trust_network.get_or_create.return_value = None
        svc._trust_network.get_score.return_value = 0.5
        svc._registry = MagicMock()
        svc._ontology = MagicMock()
        svc._ontology.get_agent_department.return_value = "engineering"
        svc._ontology.get_post_for_agent.return_value = None
        svc._ontology.get_assignment.return_value = None
        svc._config = MagicMock()
        svc._config.system = MagicMock()
        svc._config.system.crew_agents = []
        svc._config.onboarding.enabled = False
        svc._capability_registry = MagicMock()
        svc._gossip = MagicMock()
        svc._event_emitter = MagicMock()
        svc._event_log = AsyncMock()
        svc._acm = None
        svc._identity_registry = None
        svc._records_store = None
        svc._ward_room = None
        svc._tool_registry = None
        svc._llm_client = None
        svc._start_time_wall = 0.0
        svc._orientation_service = None
        svc._skill_bridge = None  # AD-596c
        svc._billet_registry = None  # AD-595b
        svc._qualification_store = None  # AD-595d

        agent = MagicMock()
        agent.id = "agent-001"
        agent.agent_type = "builder"
        agent.intent_descriptors = []
        agent.callsign = None
        agent.sovereign_id = None

        asyncio.run(svc.wire_agent(agent))

        assert agent._cognitive_skill_catalog == catalog

    def test_wire_agent_registers_skill_intents_on_bus(self):
        """IntentBus subscription includes cognitive skill intent names."""
        from probos.agent_onboarding import AgentOnboardingService

        entry = _make_skill_entry(intents=["skill_intent_a", "skill_intent_b"])
        catalog = _make_catalog_mock(entries=[entry])

        svc = AgentOnboardingService.__new__(AgentOnboardingService)
        svc._cognitive_skill_catalog = catalog
        svc._callsign_registry = MagicMock()
        svc._callsign_registry.get_callsign.return_value = "TestBot"
        svc._intent_bus = MagicMock()
        svc._trust_network = MagicMock()
        svc._trust_network.get_or_create.return_value = None
        svc._trust_network.get_score.return_value = 0.5
        svc._registry = MagicMock()
        svc._ontology = MagicMock()
        svc._ontology.get_agent_department.return_value = "engineering"
        svc._ontology.get_post_for_agent.return_value = None
        svc._ontology.get_assignment.return_value = None
        svc._config = MagicMock()
        svc._config.system = MagicMock()
        svc._config.system.crew_agents = []
        svc._config.onboarding.enabled = False
        svc._capability_registry = MagicMock()
        svc._gossip = MagicMock()
        svc._event_emitter = MagicMock()
        svc._event_log = AsyncMock()
        svc._acm = None
        svc._identity_registry = None
        svc._records_store = None
        svc._ward_room = None
        svc._tool_registry = None
        svc._llm_client = None
        svc._start_time_wall = 0.0
        svc._orientation_service = None
        svc._skill_bridge = None  # AD-596c
        svc._billet_registry = None  # AD-595b
        svc._qualification_store = None  # AD-595d

        agent = MagicMock()
        agent.id = "agent-001"
        agent.agent_type = "builder"
        agent.intent_descriptors = [
            IntentDescriptor(name="read_file", description="Read a file"),
        ]
        agent.callsign = None
        agent.sovereign_id = None

        asyncio.run(svc.wire_agent(agent))

        # Check subscribe call includes skill intents
        call_args = svc._intent_bus.subscribe.call_args
        intent_names = call_args.kwargs.get("intent_names") or call_args[1].get("intent_names")
        assert "read_file" in intent_names
        assert "skill_intent_a" in intent_names
        assert "skill_intent_b" in intent_names

    def test_wire_agent_no_catalog_unchanged(self):
        """Without catalog, wire_agent() skips skill wiring."""
        from probos.agent_onboarding import AgentOnboardingService

        svc = AgentOnboardingService.__new__(AgentOnboardingService)
        svc._cognitive_skill_catalog = None
        svc._callsign_registry = MagicMock()
        svc._callsign_registry.get_callsign.return_value = "TestBot"
        svc._intent_bus = MagicMock()
        svc._trust_network = MagicMock()
        svc._trust_network.get_or_create.return_value = None
        svc._trust_network.get_score.return_value = 0.5
        svc._registry = MagicMock()
        svc._ontology = MagicMock()
        svc._ontology.get_agent_department.return_value = "engineering"
        svc._ontology.get_post_for_agent.return_value = None
        svc._ontology.get_assignment.return_value = None
        svc._config = MagicMock()
        svc._config.system = MagicMock()
        svc._config.system.crew_agents = []
        svc._config.onboarding.enabled = False
        svc._capability_registry = MagicMock()
        svc._gossip = MagicMock()
        svc._event_emitter = MagicMock()
        svc._event_log = AsyncMock()
        svc._acm = None
        svc._identity_registry = None
        svc._records_store = None
        svc._ward_room = None
        svc._tool_registry = None
        svc._llm_client = None
        svc._start_time_wall = 0.0
        svc._orientation_service = None
        svc._skill_bridge = None  # AD-596c
        svc._billet_registry = None  # AD-595b
        svc._qualification_store = None  # AD-595d

        agent = MagicMock()
        agent.id = "agent-001"
        agent.agent_type = "builder"
        agent.intent_descriptors = []
        agent.callsign = None
        agent.sovereign_id = None

        asyncio.run(svc.wire_agent(agent))

        # Verify catalog was NOT set: wire_agent with None catalog should
        # not have called agent._cognitive_skill_catalog = ...
        # MagicMock auto-creates attributes, so we check the call history
        # by verifying no __setattr__ for '_cognitive_skill_catalog' happened.
        # Simplest: the catalog attr on the mock was never written to.
        setattr_calls = [
            c for c in agent._mock_children.keys()
            if c == '_cognitive_skill_catalog'
        ]
        # If _cognitive_skill_catalog wasn't explicitly set, it won't be in _mock_children
        # because MagicMock creates children lazily on __getattr__, not __setattr__
        assert '_cognitive_skill_catalog' not in agent.__dict__


# ===========================================================================
# Startup/Shutdown
# ===========================================================================


class TestStartupShutdown:
    """Integration: catalog wiring in startup/shutdown lifecycle."""

    def setup_method(self):
        set_skill_catalog(None)

    def teardown_method(self):
        set_skill_catalog(None)

    def test_startup_sets_skill_catalog_on_standing_orders(self):
        """set_skill_catalog() makes catalog available to compose_instructions()."""
        from probos.cognitive.standing_orders import _skill_catalog

        assert _skill_catalog is None

        catalog = _make_catalog_mock()
        set_skill_catalog(catalog)

        from probos.cognitive import standing_orders
        assert standing_orders._skill_catalog is catalog

    def test_shutdown_clears_skill_catalog(self):
        """set_skill_catalog(None) clears the catalog reference."""
        catalog = _make_catalog_mock()
        set_skill_catalog(catalog)

        from probos.cognitive import standing_orders
        assert standing_orders._skill_catalog is catalog

        set_skill_catalog(None)
        assert standing_orders._skill_catalog is None
