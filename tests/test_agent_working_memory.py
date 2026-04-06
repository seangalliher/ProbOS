"""AD-573: Tests for AgentWorkingMemory — unified cognitive continuity layer."""

from __future__ import annotations

import time

import pytest

from probos.cognitive.agent_working_memory import (
    ActiveEngagement,
    AgentWorkingMemory,
    WorkingMemoryEntry,
)


class TestWorkingMemoryEntry:
    """WorkingMemoryEntry dataclass basics."""

    def test_age_seconds(self):
        entry = WorkingMemoryEntry(
            content="test",
            category="action",
            source_pathway="dm",
            timestamp=time.time() - 60,
        )
        assert 59 <= entry.age_seconds() <= 62

    def test_token_estimate(self):
        entry = WorkingMemoryEntry(
            content="a" * 40,
            category="action",
            source_pathway="dm",
        )
        assert entry.token_estimate() == 10


class TestActiveEngagement:
    """ActiveEngagement dataclass and render()."""

    def test_render_basic(self):
        eng = ActiveEngagement(
            engagement_type="game",
            engagement_id="g-1",
            summary="Playing tic-tac-toe against Captain",
            state={},
        )
        rendered = eng.render()
        assert "Playing tic-tac-toe against Captain" in rendered

    def test_render_with_state_render(self):
        eng = ActiveEngagement(
            engagement_type="game",
            engagement_id="g-1",
            summary="Playing tic-tac-toe",
            state={"render": "X | O | _\n_ | X | _\n_ | _ | O"},
        )
        rendered = eng.render()
        assert "X | O | _" in rendered


class TestRecordAPIs:
    """Write API: record_action, record_observation, record_conversation, record_event."""

    def test_record_action(self):
        wm = AgentWorkingMemory()
        wm.record_action("Did something", source="dm")
        ctx = wm.render_context()
        assert "Did something" in ctx

    def test_record_observation(self):
        wm = AgentWorkingMemory()
        wm.record_observation("Noticed something", source="proactive")
        ctx = wm.render_context()
        assert "Noticed something" in ctx

    def test_record_conversation(self):
        wm = AgentWorkingMemory()
        wm.record_conversation("Talked about X", partner="Captain", source="dm")
        ctx = wm.render_context()
        assert "Captain" in ctx
        assert "Talked about X" in ctx

    def test_record_event(self):
        wm = AgentWorkingMemory()
        wm.record_event("System rebooted")
        ctx = wm.render_context()
        assert "System rebooted" in ctx

    def test_ring_buffer_eviction(self):
        """Ring buffer drops oldest entries when maxlen is exceeded."""
        wm = AgentWorkingMemory(max_recent_actions=3)
        for i in range(5):
            wm.record_action(f"action-{i}", source="dm")
        ctx = wm.render_context()
        assert "action-0" not in ctx
        assert "action-1" not in ctx
        assert "action-4" in ctx


class TestEngagements:
    """Active engagement management."""

    def test_add_and_has_engagement(self):
        wm = AgentWorkingMemory()
        eng = ActiveEngagement(
            engagement_type="game",
            engagement_id="g-1",
            summary="Playing chess",
            state={},
        )
        wm.add_engagement(eng)
        assert wm.has_engagement("game") is True
        assert wm.has_engagement("task") is False
        assert wm.has_engagement() is True

    def test_remove_engagement(self):
        wm = AgentWorkingMemory()
        eng = ActiveEngagement(
            engagement_type="game",
            engagement_id="g-1",
            summary="Playing chess",
            state={},
        )
        wm.add_engagement(eng)
        wm.remove_engagement("g-1")
        assert wm.has_engagement("game") is False

    def test_remove_nonexistent(self):
        """Removing a nonexistent engagement is a no-op."""
        wm = AgentWorkingMemory()
        wm.remove_engagement("doesnt-exist")  # No error

    def test_update_engagement(self):
        wm = AgentWorkingMemory()
        eng = ActiveEngagement(
            engagement_type="game",
            engagement_id="g-1",
            summary="Playing chess",
            state={"board": "initial"},
        )
        wm.add_engagement(eng)
        wm.update_engagement("g-1", state={"last_move": "e4"}, summary="Chess — move 1")
        updated = wm.get_engagement("g-1")
        assert updated is not None
        assert updated.state["last_move"] == "e4"
        assert updated.summary == "Chess — move 1"

    def test_get_engagement(self):
        wm = AgentWorkingMemory()
        assert wm.get_engagement("nope") is None
        eng = ActiveEngagement(
            engagement_type="task",
            engagement_id="t-1",
            summary="Analyzing logs",
            state={},
        )
        wm.add_engagement(eng)
        assert wm.get_engagement("t-1") is eng

    def test_get_engagements_by_type(self):
        wm = AgentWorkingMemory()
        wm.add_engagement(ActiveEngagement("game", "g-1", "Game 1", {}))
        wm.add_engagement(ActiveEngagement("task", "t-1", "Task 1", {}))
        wm.add_engagement(ActiveEngagement("game", "g-2", "Game 2", {}))
        games = wm.get_engagements_by_type("game")
        assert len(games) == 2


class TestCognitiveState:
    """Cognitive state updates."""

    def test_update_cognitive_state(self):
        wm = AgentWorkingMemory()
        wm.update_cognitive_state(zone="amber", cooldown_reason="High similarity")
        ctx = wm.render_context()
        assert "amber" in ctx
        assert "High similarity" in ctx


class TestRenderContext:
    """render_context() output and budget enforcement."""

    def test_empty_returns_empty_string(self):
        wm = AgentWorkingMemory()
        assert wm.render_context() == ""

    def test_includes_header_footer(self):
        wm = AgentWorkingMemory()
        wm.record_action("test", source="dm")
        ctx = wm.render_context()
        assert "--- Working Memory ---" in ctx
        assert "--- End Working Memory ---" in ctx

    def test_engagement_highest_priority(self):
        """Active engagements (priority 1) included even with tiny budget."""
        wm = AgentWorkingMemory()
        wm.add_engagement(ActiveEngagement("game", "g-1", "Playing", {}))
        wm.record_action("Some action " * 100, source="dm")
        ctx = wm.render_context(budget=50)
        assert "Playing" in ctx

    def test_budget_evicts_low_priority(self):
        """Low-priority sections evicted when budget is tight."""
        wm = AgentWorkingMemory()
        wm.add_engagement(ActiveEngagement("game", "g-1", "Playing chess", {}))
        wm.record_event("System event that should be evicted " * 50)
        ctx = wm.render_context(budget=20)
        assert "Playing chess" in ctx
        # Events (priority 6) should be evicted
        assert "System event" not in ctx

    def test_format_age_seconds(self):
        assert AgentWorkingMemory._format_age(30) == "30s"

    def test_format_age_minutes(self):
        assert AgentWorkingMemory._format_age(120) == "2m"

    def test_format_age_hours(self):
        assert AgentWorkingMemory._format_age(7200) == "2.0h"


class TestSerialization:
    """to_dict() / from_dict() persistence round-trip."""

    def test_round_trip(self):
        wm = AgentWorkingMemory()
        wm.record_action("Action 1", source="dm")
        wm.record_observation("Obs 1", source="proactive")
        wm.record_conversation("Conv 1", partner="Captain", source="dm")
        wm.record_event("Event 1")
        wm.add_engagement(ActiveEngagement("game", "g-1", "Playing", {"board": "X"}))
        wm.update_cognitive_state(zone="green")

        data = wm.to_dict()
        restored = AgentWorkingMemory.from_dict(data)

        ctx = restored.render_context()
        assert "Action 1" in ctx
        assert "Obs 1" in ctx
        assert "Captain" in ctx
        assert "Playing" in ctx

    def test_stale_entries_pruned(self):
        """Entries older than stale_threshold_seconds are dropped on restore."""
        wm = AgentWorkingMemory()
        wm.record_action("Old action", source="dm")
        data = wm.to_dict()
        # Artificially age the entry
        data["recent_actions"][0]["timestamp"] = time.time() - 200

        restored = AgentWorkingMemory.from_dict(data, stale_threshold_seconds=100)
        ctx = restored.render_context()
        assert "Old action" not in ctx

    def test_engagements_preserved(self):
        wm = AgentWorkingMemory()
        wm.add_engagement(ActiveEngagement("game", "g-1", "Chess", {"board": "initial"}))
        data = wm.to_dict()
        restored = AgentWorkingMemory.from_dict(data)
        assert restored.has_engagement("game")
        eng = restored.get_engagement("g-1")
        assert eng is not None
        assert eng.state["board"] == "initial"

    def test_cognitive_state_preserved(self):
        wm = AgentWorkingMemory()
        wm.update_cognitive_state(zone="amber")
        data = wm.to_dict()
        restored = AgentWorkingMemory.from_dict(data)
        ctx = restored.render_context()
        assert "amber" in ctx

    def test_stasis_event_added_on_restore(self):
        """from_dict() adds a 'Restored from stasis' event."""
        wm = AgentWorkingMemory()
        data = wm.to_dict()
        restored = AgentWorkingMemory.from_dict(data)
        ctx = restored.render_context()
        assert "Restored from stasis" in ctx
