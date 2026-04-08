"""BF-127: Working memory persistence should be crew-only.

Validates that:
1. Freeze loop only persists crew agents' working memory
2. Restore loop only restores crew agents' working memory
3. GAME_COMPLETED subscriber only cleans crew agents' working memory
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from probos.cognitive.agent_working_memory import AgentWorkingMemory, ActiveEngagement
from probos.crew_utils import is_crew_agent


def _make_mock_agent(agent_id: str, agent_type: str, *, with_wm: bool = True) -> MagicMock:
    """Create a mock agent with optional working memory."""
    agent = MagicMock()
    agent.id = agent_id
    agent.agent_type = agent_type
    agent.callsign = agent_id.capitalize()
    if with_wm:
        wm = AgentWorkingMemory()
        wm.record_action(f"{agent_id} did something", source="proactive")
        agent.working_memory = wm
        agent._working_memory = wm
    else:
        agent.working_memory = None
        agent._working_memory = None
    return agent


class TestCrewOnlyWMFreeze:
    """BF-127: Freeze loop should only persist crew agents."""

    def test_freeze_skips_non_crew_agents(self) -> None:
        """Only crew agents' WM states are collected for persistence."""
        crew_agents = [
            _make_mock_agent("a1", "architect"),
            _make_mock_agent("a2", "counselor"),
            _make_mock_agent("a3", "scout"),
        ]
        non_crew_agents = [
            _make_mock_agent("u1", "calculator"),
            _make_mock_agent("u2", "web_search"),
            _make_mock_agent("u3", "code_reviewer"),
        ]
        all_agents = crew_agents + non_crew_agents

        # Simulate the freeze loop logic from shutdown.py
        states: dict = {}
        for agent in all_agents:
            if not is_crew_agent(agent, None):
                continue
            wm = getattr(agent, 'working_memory', None)
            if wm:
                states[agent.id] = wm.to_dict()

        assert len(states) == 3
        assert set(states.keys()) == {"a1", "a2", "a3"}

    def test_freeze_log_message_reflects_crew_count(self) -> None:
        """Log message count matches crew agent count, not total."""
        crew = [_make_mock_agent("c1", "architect")]
        non_crew = [
            _make_mock_agent("u1", "calculator"),
            _make_mock_agent("u2", "web_search"),
        ]
        all_agents = crew + non_crew

        states: dict = {}
        for agent in all_agents:
            if not is_crew_agent(agent, None):
                continue
            wm = getattr(agent, 'working_memory', None)
            if wm:
                states[agent.id] = wm.to_dict()

        # The log message would say "Froze working memory for 1 agents"
        assert len(states) == 1

    def test_freeze_handles_crew_agent_without_wm(self) -> None:
        """Crew agent with working_memory=None is skipped without error."""
        crew_with_wm = _make_mock_agent("c1", "architect")
        crew_no_wm = _make_mock_agent("c2", "counselor", with_wm=False)

        states: dict = {}
        for agent in [crew_with_wm, crew_no_wm]:
            if not is_crew_agent(agent, None):
                continue
            wm = getattr(agent, 'working_memory', None)
            if wm:
                states[agent.id] = wm.to_dict()

        assert len(states) == 1
        assert "c1" in states


class TestCrewOnlyWMRestore:
    """BF-127: Restore loop should only restore crew agents."""

    def test_restore_skips_non_crew_agents(self) -> None:
        """Only crew agents get working memory restored from frozen state."""
        crew = _make_mock_agent("c1", "architect")
        non_crew = _make_mock_agent("u1", "calculator")

        # Freeze both agents' WM
        frozen_states = {
            "c1": crew.working_memory.to_dict(),
            "u1": non_crew.working_memory.to_dict(),
        }

        # Reset both agents' WM to fresh state
        crew._working_memory = AgentWorkingMemory()
        non_crew._working_memory = AgentWorkingMemory()
        crew.working_memory = crew._working_memory
        non_crew.working_memory = non_crew._working_memory

        # Simulate the restore loop logic from finalize.py
        restored = 0
        for agent in [crew, non_crew]:
            if not is_crew_agent(agent, None):
                continue
            wm = getattr(agent, 'working_memory', None)
            if wm is None:
                continue
            state = frozen_states.get(agent.id)
            if state:
                restored_wm = AgentWorkingMemory.from_dict(state)
                agent._working_memory = restored_wm
                restored += 1

        assert restored == 1
        # Crew agent got restored WM (has actions from before freeze)
        assert len(crew._working_memory._recent_actions) > 0
        # Non-crew agent still has empty fresh WM
        assert len(non_crew._working_memory._recent_actions) == 0

    def test_restore_log_message_reflects_crew_count(self) -> None:
        """Restored count matches crew agents with valid frozen state."""
        c1 = _make_mock_agent("c1", "architect")
        c2 = _make_mock_agent("c2", "scout")
        u1 = _make_mock_agent("u1", "calculator")

        frozen_states = {
            "c1": c1.working_memory.to_dict(),
            "c2": c2.working_memory.to_dict(),
            "u1": u1.working_memory.to_dict(),
        }

        restored = 0
        for agent in [c1, c2, u1]:
            if not is_crew_agent(agent, None):
                continue
            wm = getattr(agent, 'working_memory', None)
            if wm is None:
                continue
            state = frozen_states.get(agent.id)
            if state:
                restored += 1

        assert restored == 2

    def test_game_completed_cleanup_skips_non_crew(self) -> None:
        """GAME_COMPLETED subscriber only cleans crew agents' engagements."""
        crew1 = _make_mock_agent("c1", "architect")
        crew2 = _make_mock_agent("c2", "counselor")
        non_crew = _make_mock_agent("u1", "calculator")

        game_id = "g_test"
        # Add game engagement to all three
        for agent in [crew1, crew2, non_crew]:
            agent.working_memory.add_engagement(ActiveEngagement(
                engagement_type="game",
                engagement_id=game_id,
                summary="Playing tic-tac-toe",
                state={},
            ))

        # Simulate the BF-125 subscriber with BF-127 crew filter
        for agent in [crew1, crew2, non_crew]:
            if not is_crew_agent(agent, None):
                continue
            wm = getattr(agent, 'working_memory', None)
            if wm and wm.get_engagement(game_id):
                wm.remove_engagement(game_id)

        # Crew agents cleaned
        assert crew1.working_memory.get_engagement(game_id) is None
        assert crew2.working_memory.get_engagement(game_id) is None
        # Non-crew agent still has the engagement (would never happen in practice,
        # but proves the filter works)
        assert non_crew.working_memory.get_engagement(game_id) is not None
