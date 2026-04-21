"""AD-644 Phase 3: Situation Awareness for Cognitive Chain — Tests.

Verifies that _build_situation_awareness() extracts environmental percepts
into observation keys, and that ANALYZE renders them into situation_content.
"""

import pytest
from unittest.mock import MagicMock, patch

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent() -> CognitiveAgent:
    agent = CognitiveAgent(agent_id="test-agent", instructions="Test agent instructions.")
    agent.callsign = "TestAgent"
    agent._runtime = None
    return agent


# ---------------------------------------------------------------------------
# Test 1: Ward Room activity
# ---------------------------------------------------------------------------

class TestBuildSituationAwarenessWardRoom:

    def test_ward_room_activity(self):
        agent = _make_agent()
        result = agent._build_situation_awareness({
            "ward_room_activity": [{
                "type": "thread",
                "author": "Bones",
                "body": "[abc12345] Status update",
                "thread_id": "abc12345678",
                "post_id": "def87654321",
                "net_score": 2,
                "created_at": 1000.0,
            }],
        })
        assert "_ward_room_activity" in result
        wr = result["_ward_room_activity"]
        assert "Bones" in wr
        assert "thread:abc12345" in wr
        assert "[+2]" in wr

    def test_ward_room_with_channel(self):
        agent = _make_agent()
        result = agent._build_situation_awareness({
            "ward_room_activity": [{
                "type": "reply",
                "author": "LaForge",
                "body": "Acknowledged",
                "channel": "All Hands",
                "net_score": 0,
            }],
        })
        assert "_ward_room_activity" in result
        assert "(All Hands)" in result["_ward_room_activity"]


# ---------------------------------------------------------------------------
# Test 3: Alerts
# ---------------------------------------------------------------------------

class TestBuildSituationAwarenessAlerts:

    def test_alerts(self):
        agent = _make_agent()
        result = agent._build_situation_awareness({
            "recent_alerts": [{
                "severity": "WARNING",
                "title": "High latency",
                "source": "VitalsMonitor",
            }],
        })
        assert "_recent_alerts" in result
        alerts = result["_recent_alerts"]
        assert "[WARNING]" in alerts
        assert "High latency" in alerts
        assert "VitalsMonitor" in alerts


# ---------------------------------------------------------------------------
# Test 4: Events
# ---------------------------------------------------------------------------

class TestBuildSituationAwarenessEvents:

    def test_events(self):
        agent = _make_agent()
        result = agent._build_situation_awareness({
            "recent_events": [{
                "category": "TRUST",
                "event": "Trust updated for agent-1",
            }],
        })
        assert "_recent_events" in result
        events = result["_recent_events"]
        assert "[TRUST]" in events
        assert "Trust updated" in events


# ---------------------------------------------------------------------------
# Test 5: Infrastructure
# ---------------------------------------------------------------------------

class TestBuildSituationAwarenessInfrastructure:

    def test_infrastructure(self):
        agent = _make_agent()
        result = agent._build_situation_awareness({
            "infrastructure_status": {
                "llm_status": "degraded",
                "message": "Backend timeout",
            },
        })
        assert "_infrastructure_status" in result
        infra = result["_infrastructure_status"]
        assert "degraded" in infra
        assert "Backend timeout" in infra


# ---------------------------------------------------------------------------
# Test 6: Subordinate stats
# ---------------------------------------------------------------------------

class TestBuildSituationAwarenessSubordinateStats:

    def test_subordinate_stats(self):
        agent = _make_agent()
        result = agent._build_situation_awareness({
            "subordinate_stats": {
                "Kira": {
                    "posts_total": 5,
                    "endorsements_given": 2,
                    "endorsements_received": 3,
                    "credibility_score": 0.75,
                },
            },
        })
        assert "_subordinate_stats" in result
        ss = result["_subordinate_stats"]
        assert "Kira" in ss
        assert "5 posts" in ss
        assert "0.75" in ss
        assert "<subordinate_activity>" in ss
        assert "</subordinate_activity>" in ss


# ---------------------------------------------------------------------------
# Test 7: Cold start
# ---------------------------------------------------------------------------

class TestBuildSituationAwarenessColdStart:

    def test_cold_start(self):
        agent = _make_agent()
        result = agent._build_situation_awareness({
            "system_note": "SYSTEM NOTE: This is a fresh start after reset.",
        })
        assert "_cold_start_note" in result
        assert "fresh start" in result["_cold_start_note"]


# ---------------------------------------------------------------------------
# Test 8-9: Active game
# ---------------------------------------------------------------------------

class TestBuildSituationAwarenessActiveGame:

    def test_active_game_my_turn(self):
        agent = _make_agent()
        result = agent._build_situation_awareness({
            "active_game": {
                "game_type": "tictactoe",
                "opponent": "Chapel",
                "moves_count": 3,
                "board": " X | O | \n-----------\n   |   | X\n-----------\n   | O |  ",
                "is_my_turn": True,
                "valid_moves": [3, 4, 6, 7, 9],
            },
        })
        assert "_active_game" in result
        game = result["_active_game"]
        assert "YOUR turn" in game
        assert "Chapel" in game
        assert "tictactoe" in game

    def test_active_game_not_my_turn(self):
        agent = _make_agent()
        result = agent._build_situation_awareness({
            "active_game": {
                "game_type": "tictactoe",
                "opponent": "Chapel",
                "moves_count": 3,
                "board": " X | O | \n-----------\n   |   | X\n-----------\n   | O |  ",
                "is_my_turn": False,
                "valid_moves": [],
            },
        })
        assert "_active_game" in result
        game = result["_active_game"]
        assert "Waiting for your opponent" in game
        assert "YOUR turn" not in game


# ---------------------------------------------------------------------------
# Test 10: Empty
# ---------------------------------------------------------------------------

class TestBuildSituationAwarenessEmpty:

    def test_empty(self):
        agent = _make_agent()
        result = agent._build_situation_awareness({})
        assert result == {}


# ---------------------------------------------------------------------------
# Test 11-12: ANALYZE prompt integration
# ---------------------------------------------------------------------------

class TestAnalyzePromptSituationContent:

    def test_analyze_prompt_includes_situation_content(self):
        context = {
            "context": "",  # empty, as in real proactive_think
            "_agent_type": "agent",
            "_agent_rank": None,
            "_skill_profile": None,
            "_ward_room_activity": "Recent Ward Room discussion:\n  - [thread] Bones: Status update",
            "_recent_alerts": "Recent bridge alerts:\n  - [WARNING] High latency (from VitalsMonitor)",
            "_cold_start_note": "SYSTEM NOTE: Fresh start after reset.",
        }
        _sys, user = _build_situation_review_prompt(context, [], "Echo", "Medical")

        assert "## Current Situation" in user
        assert "Ward Room discussion" in user
        assert "WARNING" in user
        assert "Fresh start" in user
        assert "## Assessment Required" in user

    def test_analyze_prompt_preserves_raw_context(self):
        context = {
            "context": "Thread about engineering report",
            "_agent_type": "agent",
            "_agent_rank": None,
            "_skill_profile": None,
        }
        _sys, user = _build_situation_review_prompt(context, [], "Echo", "Medical")

        assert "engineering report" in user


# ---------------------------------------------------------------------------
# Test 13: Observation dict integration
# ---------------------------------------------------------------------------

class TestObservationDictIntegration:

    def test_observation_dict_receives_situation_awareness(self):
        """Verify _build_situation_awareness output merges into observation."""
        agent = _make_agent()

        observation: dict = {"params": {"context_parts": {}}}
        _params = observation.get("params", {})
        _context_parts = _params.get("context_parts", {})

        with patch.object(
            agent,
            '_build_situation_awareness',
            return_value={
                "_ward_room_activity": "test-wr",
                "_recent_alerts": "test-alerts",
            },
        ) as mock_build:
            _situation = agent._build_situation_awareness(_context_parts)
            observation.update(_situation)

        mock_build.assert_called_once_with({})
        assert observation["_ward_room_activity"] == "test-wr"
        assert observation["_recent_alerts"] == "test-alerts"
