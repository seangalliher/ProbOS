"""AD-644 Phase 2: Innate Faculties for Cognitive Chain — Tests.

Verifies that _build_cognitive_state() extracts innate faculties into
observation keys, and that ANALYZE and COMPOSE prompt builders render them.
"""

import pytest
from unittest.mock import MagicMock, patch

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
from probos.cognitive.sub_tasks.compose import _build_user_prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent() -> CognitiveAgent:
    agent = CognitiveAgent(agent_id="test-agent", instructions="Test agent instructions.")
    agent.callsign = "TestAgent"
    agent._runtime = None
    return agent


# ---------------------------------------------------------------------------
# Test 1: Temporal context
# ---------------------------------------------------------------------------

class TestBuildCognitiveStateTemporal:

    def test_build_cognitive_state_temporal(self):
        agent = _make_agent()
        with patch.object(agent, '_build_temporal_context', return_value="Current time: 2026-04-18 12:00:00 UTC"):
            result = agent._build_cognitive_state({})
        assert "_temporal_context" in result
        assert "2026-04-18" in result["_temporal_context"]


# ---------------------------------------------------------------------------
# Test 2: Working memory
# ---------------------------------------------------------------------------

class TestBuildCognitiveStateWorkingMemory:

    def test_build_cognitive_state_working_memory(self):
        agent = _make_agent()
        mock_wm = MagicMock()
        mock_wm.render_context.return_value = "Recent: discussed baselines"
        agent._working_memory = mock_wm
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_state({})
        assert "_working_memory_context" in result
        assert "discussed baselines" in result["_working_memory_context"]
        mock_wm.render_context.assert_called_once_with(budget=1500)


# ---------------------------------------------------------------------------
# Test 3: Self-monitoring
# ---------------------------------------------------------------------------

class TestBuildCognitiveStateSelfMonitoring:

    def test_build_cognitive_state_self_monitoring(self):
        agent = _make_agent()
        context_parts = {
            "self_monitoring": {
                "cognitive_zone": "green",
                "recent_posts": [{"age": "5m", "body": "test post"}],
                "self_similarity": 0.6,
            },
        }
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_state(context_parts)
        assert "_self_monitoring" in result
        sm = result["_self_monitoring"]
        assert "GREEN" in sm  # zone uppercased
        assert "test post" in sm
        assert "WARNING" in sm  # sim >= 0.5


# ---------------------------------------------------------------------------
# Test 4-5: Confabulation guard
# ---------------------------------------------------------------------------

class TestBuildCognitiveStateConfabulationGuard:

    def test_confabulation_guard_no_memories(self):
        agent = _make_agent()
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_state({})
        assert "_confabulation_guard" in result
        assert "_no_episodic_memories" in result
        assert "Do not reference or invent past experiences" in result["_no_episodic_memories"]

    def test_confabulation_guard_with_memories(self):
        agent = _make_agent()
        context_parts = {"recent_memories": [{"content": "test"}]}
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_state(context_parts)
        assert "_confabulation_guard" in result
        assert "_no_episodic_memories" not in result


# ---------------------------------------------------------------------------
# Test 6: Ontology
# ---------------------------------------------------------------------------

class TestBuildCognitiveStateOntology:

    def test_build_cognitive_state_ontology(self):
        agent = _make_agent()
        context_parts = {
            "ontology": {
                "identity": {"callsign": "Echo", "post": "Counselor"},
                "department": {"name": "Medical"},
                "reports_to": "Captain",
                "peers": ["Bones"],
                "vessel": {"name": "ProbOS", "version": "0.4", "alert_condition": "GREEN"},
            },
        }
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_state(context_parts)
        assert "_ontology_context" in result
        onto = result["_ontology_context"]
        assert "Echo" in onto
        assert "Counselor" in onto
        assert "Medical" in onto
        assert "Captain" in onto
        assert "Bones" in onto
        assert "Alert Condition GREEN" in onto


# ---------------------------------------------------------------------------
# Test 7-8: Source attribution
# ---------------------------------------------------------------------------

class TestBuildCognitiveStateSourceAttribution:

    def test_source_attribution_with_memories(self):
        agent = _make_agent()
        context_parts = {"recent_memories": [{"a": 1}, {"b": 2}]}
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_state(context_parts)
        assert "_source_attribution_text" in result
        assert "episodic memory (2 episodes)" in result["_source_attribution_text"]

    def test_source_attribution_no_memories(self):
        agent = _make_agent()
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_state({})
        assert "_source_attribution_text" in result
        assert "training knowledge only" in result["_source_attribution_text"]


# ---------------------------------------------------------------------------
# Test 9: Communication proficiency
# ---------------------------------------------------------------------------

class TestBuildCognitiveStateCommProficiency:

    def test_build_cognitive_state_comm_proficiency(self):
        agent = _make_agent()
        with (
            patch.object(agent, '_build_temporal_context', return_value=""),
            patch.object(agent, '_get_comm_proficiency_guidance', return_value="Tier 2: Be concise."),
        ):
            result = agent._build_cognitive_state({})
        assert "_comm_proficiency" in result
        assert "Tier 2" in result["_comm_proficiency"]


# ---------------------------------------------------------------------------
# Test 10: Empty returns minimal
# ---------------------------------------------------------------------------

class TestBuildCognitiveStateEmpty:

    def test_build_cognitive_state_empty_returns_minimal(self):
        agent = _make_agent()
        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_state({})
        # Always present
        assert "_confabulation_guard" in result
        assert "_source_attribution_text" in result
        # Empty string excluded
        assert "_temporal_context" not in result


# ---------------------------------------------------------------------------
# Test 11: ANALYZE prompt includes innate faculties
# ---------------------------------------------------------------------------

class TestAnalyzePromptInnateFaculties:

    def test_analyze_prompt_includes_innate_faculties(self):
        context = {
            "context": "Some ward room activity",
            "_agent_type": "agent",
            "_agent_rank": None,
            "_skill_profile": None,
            "_formatted_memories": "",
            "_temporal_context": "Current time: 2026-04-18 12:00:00 UTC",
            "_ontology_context": "You are Echo, Counselor in Medical department.",
            "_self_monitoring": "<cognitive_zone>GREEN</cognitive_zone>",
        }
        _sys, user = _build_situation_review_prompt(context, [], "Echo", "Medical")

        assert "## Temporal Awareness" in user
        assert "2026-04-18" in user
        assert "## Your Identity" in user
        assert "Echo, Counselor" in user
        assert "## Self-Monitoring" in user
        assert "GREEN" in user
        assert "## Assessment Required" in user  # existing structure preserved


# ---------------------------------------------------------------------------
# Test 12: COMPOSE user prompt includes confabulation guard
# ---------------------------------------------------------------------------

class TestComposeUserPromptInnateFaculties:

    def test_compose_user_prompt_includes_confabulation_guard(self):
        context = {
            "context": "",
            "_confabulation_guard": "IMPORTANT: Do NOT fabricate specific numbers.",
            "_no_episodic_memories": "You have no stored episodic memories yet.",
            "_source_attribution_text": "[Source awareness: training knowledge only.]",
            "_comm_proficiency": "Tier 2: Be concise.",
            "_temporal_context": "Current time: 2026-04-18 12:00:00 UTC",
        }
        result = _build_user_prompt(context, [])

        assert "## Knowledge Boundaries" in result
        assert "Do NOT fabricate" in result
        assert "Source awareness" in result
        assert "## Communication Guidance" in result
        assert "## Temporal Awareness" in result


# ---------------------------------------------------------------------------
# Test 13: Observation dict receives cognitive state (integration)
# ---------------------------------------------------------------------------

class TestObservationDictIntegration:

    def test_observation_dict_receives_cognitive_state(self):
        """Verify _build_cognitive_state output merges into observation."""
        agent = _make_agent()

        # Simulate the injection logic from _execute_chain_with_intent_routing
        observation: dict = {"params": {"context_parts": {}}}
        _params = observation.get("params", {})
        _context_parts = _params.get("context_parts", {})

        with (
            patch.object(
                agent,
                '_build_cognitive_state',
                return_value={
                    "_temporal_context": "test-temporal",
                    "_confabulation_guard": "test-guard",
                },
            ) as mock_build,
        ):
            _cognitive_state = agent._build_cognitive_state(_context_parts)
            observation.update(_cognitive_state)

        mock_build.assert_called_once_with({})
        assert observation["_temporal_context"] == "test-temporal"
        assert observation["_confabulation_guard"] == "test-guard"
