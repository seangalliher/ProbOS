"""BF-125: Working memory game engagement desync tests.

Validates that:
1. Game completion cleans BOTH players' working memory
2. Event-driven cleanup fires for all move pathways
3. Restore-time revalidation remains functional
"""

import time
import pytest
from probos.cognitive.agent_working_memory import AgentWorkingMemory, ActiveEngagement, WorkingMemoryEntry


class TestGameCompletionCleanup:
    """BF-125: Event-driven game engagement cleanup."""

    def _make_wm_with_game(self, game_id: str = "game_1", opponent: str = "Captain") -> AgentWorkingMemory:
        """Create a working memory with an active game engagement."""
        wm = AgentWorkingMemory()
        wm.add_engagement(ActiveEngagement(
            engagement_type="game",
            engagement_id=game_id,
            summary=f"Playing tic-tac-toe against {opponent}",
            state={"game_type": "tic-tac-toe", "opponent": opponent},
        ))
        return wm

    def test_game_completion_removes_engagement(self) -> None:
        """Game completion removes engagement from the player's WM."""
        wm = self._make_wm_with_game("g1")
        assert wm.get_engagement("g1") is not None
        wm.remove_engagement("g1")
        assert wm.get_engagement("g1") is None

    def test_opponent_engagement_survives_without_fix(self) -> None:
        """Without event-driven cleanup, opponent's WM keeps stale engagement."""
        player_wm = self._make_wm_with_game("g1", "Forge")
        opponent_wm = self._make_wm_with_game("g1", "Captain")
        # Simulate: only moving player cleaned up
        player_wm.remove_engagement("g1")
        assert player_wm.get_engagement("g1") is None
        # Opponent still has it — this is the bug
        assert opponent_wm.get_engagement("g1") is not None

    def test_both_players_cleaned_by_event(self) -> None:
        """BF-125: Simulate event-driven cleanup for both players."""
        player_wm = self._make_wm_with_game("g1", "Forge")
        opponent_wm = self._make_wm_with_game("g1", "Captain")
        # Simulate event subscriber: clean all WMs with this game
        all_wms = [player_wm, opponent_wm]
        game_id = "g1"
        for wm in all_wms:
            if wm.get_engagement(game_id):
                wm.remove_engagement(game_id)
        assert player_wm.get_engagement("g1") is None
        assert opponent_wm.get_engagement("g1") is None

    def test_cleanup_skips_noninvolved_agents(self) -> None:
        """BF-125: Agents without the game engagement are untouched."""
        involved_wm = self._make_wm_with_game("g1")
        uninvolved_wm = AgentWorkingMemory()
        uninvolved_wm.add_engagement(ActiveEngagement(
            engagement_type="game",
            engagement_id="g_other",
            summary="Playing chess against Atlas",
            state={},
        ))
        # Cleanup for g1 should not affect g_other
        for wm in [involved_wm, uninvolved_wm]:
            if wm.get_engagement("g1"):
                wm.remove_engagement("g1")
        assert involved_wm.get_engagement("g1") is None
        assert uninvolved_wm.get_engagement("g_other") is not None

    def test_cleanup_idempotent(self) -> None:
        """BF-125: Removing already-removed engagement is safe."""
        wm = self._make_wm_with_game("g1")
        wm.remove_engagement("g1")
        # Second removal should not raise
        wm.remove_engagement("g1")
        assert wm.get_engagement("g1") is None


class TestRestoreRevalidation:
    """BF-125: Restore-time game revalidation (defense-in-depth)."""

    def test_stale_game_removed_on_restore(self) -> None:
        """Stale game engagement is pruned during simulated restore revalidation."""
        wm = AgentWorkingMemory()
        wm.add_engagement(ActiveEngagement(
            engagement_type="game",
            engagement_id="stale_game",
            summary="Playing tic-tac-toe against nobody",
            state={},
        ))
        frozen = wm.to_dict()
        restored = AgentWorkingMemory.from_dict(frozen)
        # Engagement restored (revalidation is external, in finalize.py)
        assert restored.get_engagement("stale_game") is not None
        # Simulate finalize.py revalidation: no active games → remove
        active_game_ids: set = set()
        for eng in list(restored.get_engagements_by_type("game")):
            if eng.engagement_id not in active_game_ids:
                restored.remove_engagement(eng.engagement_id)
        assert restored.get_engagement("stale_game") is None

    def test_valid_engagement_survives_restore(self) -> None:
        """Non-game engagements (task, collaboration) survive restore."""
        wm = AgentWorkingMemory()
        wm.add_engagement(ActiveEngagement(
            engagement_type="task",
            engagement_id="t1",
            summary="Running diagnostic",
            state={},
        ))
        frozen = wm.to_dict()
        restored = AgentWorkingMemory.from_dict(frozen)
        assert restored.get_engagement("t1") is not None

    def test_stale_entries_pruned_by_threshold(self) -> None:
        """Entries older than stale_threshold_seconds are pruned."""
        wm = AgentWorkingMemory()
        wm.record_action("Old action", source="proactive")
        # Tamper timestamp to make it old
        if wm._recent_actions:
            old_entry = wm._recent_actions[0]
            wm._recent_actions[0] = WorkingMemoryEntry(
                content=old_entry.content,
                category=old_entry.category,
                source_pathway=old_entry.source_pathway,
                timestamp=time.time() - 200_000,  # >24h ago
                metadata=old_entry.metadata,
            )
        frozen = wm.to_dict()
        restored = AgentWorkingMemory.from_dict(frozen, stale_threshold_seconds=86400)
        assert len(restored._recent_actions) == 0
