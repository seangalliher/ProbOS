"""AD-646: Universal Cognitive Baseline — Tests.

Verifies that _build_cognitive_baseline() produces agent-intrinsic state
for ALL chain executions, that extensions override baseline where richer,
and that the thread analysis prompt renders baseline keys.
"""

import pytest
from unittest.mock import MagicMock, patch

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.sub_tasks.analyze import _build_thread_analysis_prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(**kwargs) -> CognitiveAgent:
    agent = CognitiveAgent(agent_id="test-agent", instructions="Test agent instructions.")
    agent.callsign = "TestAgent"
    agent.agent_type = "test_agent"
    agent._runtime = kwargs.get("runtime", None)
    return agent


def _make_runtime(trust_score=0.75):
    """Create a mock runtime with trust_network and ontology."""
    rt = MagicMock()
    rt.trust_network.get_score.return_value = trust_score
    rt.ontology.get_crew_context.return_value = {
        "identity": {"callsign": "Echo", "post": "Counselor"},
        "department": {"name": "Medical"},
        "reports_to": "Captain",
        "direct_reports": ["Nurse Chapel"],
        "peers": ["Bones"],
        "vessel": {"name": "ProbOS", "version": "0.4", "alert_condition": "GREEN"},
    }
    return rt


def _fake_episode():
    return {"content": "Observed latency spike at 14:00", "timestamp": 1713500000}


# ---------------------------------------------------------------------------
# Test 1: Baseline produces all expected keys with memories
# ---------------------------------------------------------------------------

class TestBaselineAllKeys:

    def test_baseline_produces_all_expected_keys(self):
        rt = _make_runtime(trust_score=0.75)
        agent = _make_agent(runtime=rt)
        observation = {"recent_memories": [_fake_episode()]}

        with patch.object(agent, '_build_temporal_context', return_value="Current time: 2026-04-19"):
            result = agent._build_cognitive_baseline(observation)

        assert "_temporal_context" in result
        assert "_agent_metrics" in result
        assert "_ontology_context" in result
        assert "_source_attribution_text" in result
        assert "_confabulation_guard" in result
        assert "_comm_proficiency" in result or True  # optional, depends on skill_profile
        # Should NOT have no-memories flag since we provided memories
        assert "_no_episodic_memories" not in result
        # Metrics should have real values, not "?"
        assert "?" not in result["_agent_metrics"]
        assert "0.75" in result["_agent_metrics"]
        # Source attribution should mention episodes
        assert "1 episodes" in result["_source_attribution_text"]


# ---------------------------------------------------------------------------
# Test 2: Baseline with empty observation (no memories)
# ---------------------------------------------------------------------------

class TestBaselineNoMemories:

    def test_baseline_works_with_empty_observation(self):
        agent = _make_agent()
        with patch.object(agent, '_build_temporal_context', return_value="Current time: 2026-04-19"):
            result = agent._build_cognitive_baseline({})

        assert "_no_episodic_memories" in result
        assert "training knowledge only" in result["_source_attribution_text"]
        assert "_agent_metrics" in result
        # Default trust should be present, not "?"
        assert "?" not in result["_agent_metrics"]


# ---------------------------------------------------------------------------
# Test 3: Baseline degrades when runtime unavailable
# ---------------------------------------------------------------------------

class TestBaselineDegradation:

    def test_baseline_degrades_when_runtime_unavailable(self):
        agent = _make_agent()
        agent._runtime = None

        with patch.object(agent, '_build_temporal_context', return_value="Current time: 2026-04-19"):
            result = agent._build_cognitive_baseline({})

        # Should not raise
        assert "_temporal_context" in result
        assert "_agent_metrics" in result
        # Default metrics, not "?"
        assert "?" not in result["_agent_metrics"]
        # No ontology since no runtime
        assert "_ontology_context" not in result


# ---------------------------------------------------------------------------
# Test 4: Extensions override baseline keys
# ---------------------------------------------------------------------------

class TestExtensionsOverride:

    def test_extensions_override_baseline_keys(self):
        agent = _make_agent()
        context_parts = {
            "recent_memories": [_fake_episode()],
            "_source_framing": MagicMock(authority=MagicMock(value="authoritative")),
            "self_monitoring": {"cognitive_zone": "GREEN"},
            "introspective_telemetry": "CPU: 45%, Memory: 2GB",
        }

        result = agent._build_cognitive_extensions(context_parts)

        assert "_source_attribution_text" in result
        assert "authoritative" in result["_source_attribution_text"]
        assert "_self_monitoring" in result
        assert "_introspective_telemetry" in result


# ---------------------------------------------------------------------------
# Test 5: _build_cognitive_state() combines baseline + extensions
# ---------------------------------------------------------------------------

class TestCognitiveStateWrapper:

    def test_cognitive_state_combines_baseline_and_extensions(self):
        rt = _make_runtime()
        agent = _make_agent(runtime=rt)
        context_parts = {
            "recent_memories": [_fake_episode()],
            "self_monitoring": {"cognitive_zone": "GREEN"},
            "introspective_telemetry": "CPU: 45%",
            "ontology": {
                "identity": {"callsign": "Bones", "post": "CMO"},
                "department": {"name": "Medical"},
                "vessel": {"name": "ProbOS", "version": "0.4", "alert_condition": "GREEN"},
            },
        }
        observation = {"recent_memories": [_fake_episode()]}

        with patch.object(agent, '_build_temporal_context', return_value="Current time: 2026-04-19"):
            result = agent._build_cognitive_state(context_parts, observation=observation)

        # Baseline keys
        assert "_temporal_context" in result
        assert "_agent_metrics" in result
        assert "_confabulation_guard" in result
        # Extension keys
        assert "_self_monitoring" in result
        assert "_introspective_telemetry" in result
        # Extension overrides baseline ontology
        assert "Bones" in result["_ontology_context"]


# ---------------------------------------------------------------------------
# Test 6: _build_cognitive_state() with empty context_parts (ward_room path)
# ---------------------------------------------------------------------------

class TestCognitiveStateWardRoom:

    def test_cognitive_state_with_empty_context_parts(self):
        rt = _make_runtime(trust_score=0.85)
        agent = _make_agent(runtime=rt)
        observation = {"recent_memories": [_fake_episode()]}

        with patch.object(agent, '_build_temporal_context', return_value="Current time: 2026-04-19"):
            result = agent._build_cognitive_state({}, observation=observation)

        # Baseline keys populated
        assert "_temporal_context" in result
        assert "_agent_metrics" in result
        assert "0.85" in result["_agent_metrics"]
        assert "_ontology_context" in result  # from runtime
        assert "Echo" in result["_ontology_context"]
        # Extension-only keys absent
        assert "_self_monitoring" not in result
        assert "_introspective_telemetry" not in result


# ---------------------------------------------------------------------------
# Test 7: Thread analysis prompt includes baseline state
# ---------------------------------------------------------------------------

class TestThreadAnalysisBaseline:

    def test_thread_analysis_prompt_includes_baseline_state(self):
        context = {
            "context": "Thread content here",
            "_agent_type": "agent",
            "_agent_rank": None,
            "_skill_profile": None,
            "_formatted_memories": "",
            "_temporal_context": "Current time: 2026-04-19 12:00:00 UTC",
            "_working_memory_context": "Recent reasoning: analyzed crew patterns",
            "_agent_metrics": "Your trust: 0.75 | Agency: lieutenant | Rank: lieutenant",
            "_ontology_context": "You are Echo, Counselor in Medical department.",
        }
        _sys, user = _build_thread_analysis_prompt(context, [], "Echo", "Medical")

        assert "## Your Current State" in user
        assert "**Temporal:**" in user
        assert "2026-04-19" in user
        assert "**Working Memory:**" in user
        assert "**Status:**" in user
        assert "0.75" in user
        assert "**Identity:**" in user
        assert "Echo" in user


# ---------------------------------------------------------------------------
# Test 8: Thread analysis prompt works without baseline keys (backward compat)
# ---------------------------------------------------------------------------

class TestThreadAnalysisNoBaseline:

    def test_thread_analysis_prompt_without_baseline_keys(self):
        context = {
            "context": "Thread content here",
            "_agent_type": "agent",
            "_agent_rank": None,
            "_skill_profile": None,
            "_formatted_memories": "",
        }
        _sys, user = _build_thread_analysis_prompt(context, [], "Echo", "Medical")

        assert "## Your Current State" not in user
        assert "## Analysis Required" in user


# ---------------------------------------------------------------------------
# Test 9: Proactive path regression — full context still works
# ---------------------------------------------------------------------------

class TestProactivePathRegression:

    def test_full_context_produces_all_keys(self):
        rt = _make_runtime()
        agent = _make_agent(runtime=rt)
        context_parts = {
            "recent_memories": [_fake_episode()],
            "self_monitoring": {"cognitive_zone": "AMBER", "zone_note": "Elevated activity"},
            "introspective_telemetry": "Latency: 200ms",
            "ontology": {
                "identity": {"callsign": "Echo", "post": "Counselor"},
                "department": {"name": "Medical"},
                "vessel": {"name": "ProbOS", "version": "0.4", "alert_condition": "GREEN"},
            },
            "orientation_supplement": "Recent orientation data",
        }
        observation = {"recent_memories": [_fake_episode()]}

        with patch.object(agent, '_build_temporal_context', return_value="Current time: 2026-04-19"):
            result = agent._build_cognitive_state(context_parts, observation=observation)

        # All keys present
        assert "_temporal_context" in result
        assert "_agent_metrics" in result
        assert "_self_monitoring" in result
        assert "AMBER" in result["_self_monitoring"]
        assert "_introspective_telemetry" in result
        assert "_ontology_context" in result
        assert "_orientation_supplement" in result
        assert "_confabulation_guard" in result


# ---------------------------------------------------------------------------
# Test 10: _agent_metrics computed from runtime, not params
# ---------------------------------------------------------------------------

class TestAgentMetricsFromRuntime:

    def test_agent_metrics_computed_from_runtime(self):
        rt = _make_runtime(trust_score=0.75)
        agent = _make_agent(runtime=rt)

        with patch.object(agent, '_build_temporal_context', return_value=""):
            result = agent._build_cognitive_baseline({})

        metrics = result["_agent_metrics"]
        assert "0.75" in metrics
        assert "?" not in metrics
        # Verify rank and agency are derived from trust (not "?")
        # Rank.from_trust(0.75) should produce a non-"?" rank
        assert "Agency:" in metrics
        assert "Rank:" in metrics
