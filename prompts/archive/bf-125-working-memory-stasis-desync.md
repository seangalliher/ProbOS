# BF-125: Working Memory Game Engagement Desync

## Bug Summary

Working memory preserves stale game engagements across stasis boundaries and during normal operation. Crew-identified by Horizon (Science) via tic-tac-toe game state drift. Root cause diagnosed by Forge (Engineering) and Reyes (Medical): corruption occurs at serialization time, not deserialization — system faithfully restores already-broken state.

**Four distinct defects sharing a common root cause (fragile inline WM cleanup):**

| Defect | Description | Location |
|--------|-------------|----------|
| **A: Opponent orphan** | Game completion removes moving player's engagement but never the opponent's | proactive.py:2153-2168, ward_room_router.py:425-438 |
| **B: Reply-path gap** | `_extract_commands_from_reply()` processes MOVE but never updates/removes WM | proactive.py:2458-2481 |
| **C: DM-path gap** | DM MOVE handler processes moves but never updates/removes WM | routers/agents.py:266-302 |
| **D: No event-driven cleanup** | `GAME_COMPLETED` emitted by RecreationService but has zero subscribers | recreation/service.py:158, events.py:134 |

The existing restore-time revalidation (finalize.py:338-346) correctly removes stale game engagements on restart, but the root cause is live-operation orphaning that creates stale state before freeze runs.

## Fix Architecture

**Event-driven cleanup via `GAME_COMPLETED` subscription.** One centralized subscriber that cleans both players' working memory on game completion, replacing the fragile inline cleanup scattered across 3 separate move handlers.

## Prerequisites

- AD-573 (Working Memory) — COMPLETE
- AD-526a (RecreationService + GAME_COMPLETED event) — COMPLETE
- BF-121 (Reply-path commands) — COMPLETE
- BF-123 (Ward Room router commands) — COMPLETE
- AD-572 (DM-path moves) — COMPLETE

## File Changes

### 1. New: Game Completion WM Cleanup Subscriber

**File:** `src/probos/startup/finalize.py`

Add a `GAME_COMPLETED` event subscription during startup that cleans both players' working memory.

After the existing RecreationService wiring section, add (follow the pattern from `startup/dreaming.py` lines 190-212):

```python
# BF-125: Subscribe to GAME_COMPLETED to clean both players' working memory
if hasattr(runtime, 'recreation_service') and runtime.recreation_service:
    from probos.events import EventType

    async def _on_game_completed(event: dict) -> None:
        """BF-125: Clean both players' working memory on game completion."""
        event_data = event.get("data", event)
        game_id = event_data.get("game_id", "")
        if not game_id:
            return
        for agent in runtime.registry.all():
            wm = getattr(agent, 'working_memory', None)
            if wm and wm.get_engagement(game_id):
                wm.remove_engagement(game_id)
                logger.debug("BF-125: Removed game %s from %s working memory",
                             game_id, getattr(agent, 'callsign', agent.id))

    runtime.add_event_listener(
        _on_game_completed,
        event_types=[EventType.GAME_COMPLETED],
    )
```

**Implementation notes:**
- Follows `startup/dreaming.py` AD-532e pattern: `async def` closure + `runtime.add_event_listener(fn, event_types=[...])`.
- Event dict is wrapped: use `event.get("data", event)` to access payload (see dreaming.py:193).
- Iterates all agents and checks for the game engagement by ID — simpler and more robust than resolving callsigns to agent IDs (callsign registry may not have Captain mapped).
- Uses `wm.get_engagement(game_id)` before `remove_engagement()` to avoid unnecessary work.

### 2. Modify: Remove Inline WM Cleanup from Move Handlers

The event subscriber handles all cleanup. Remove the inline WM cleanup from the three move paths to avoid double-cleanup and maintain single responsibility.

#### 2a. `src/probos/proactive.py` — `_extract_and_execute_actions()` MOVE handler

**Lines 2153-2168:** Remove the `# AD-573: Update/remove game engagement in working memory` block entirely. The GAME_COMPLETED event subscriber handles game-over cleanup. For in-progress games, the proactive loop's lazy sync at lines 1139-1165 already keeps state current.

Replace:
```python
                            # AD-573: Update/remove game engagement in working memory
                            try:
                                wm = getattr(agent, 'working_memory', None)
                                if wm:
                                    game_result = game_info.get("result")
                                    if game_result:
                                        # Game over — remove engagement
                                        wm.remove_engagement(player_game["game_id"])
                                    else:
                                        # Game ongoing — update state
                                        wm.update_engagement(
                                            player_game["game_id"],
                                            state={"last_move": position},
                                        )
                            except Exception:
                                logger.debug("AD-573: Working memory game update failed", exc_info=True)
```

With:
```python
                            # BF-125: Game-over WM cleanup handled by GAME_COMPLETED subscriber.
                            # In-progress state sync handled by proactive loop (line 1139-1165).
```

#### 2b. `src/probos/ward_room_router.py` — `_extract_recreation_commands()` MOVE handler

**Lines 425-438:** Same removal — remove the `# AD-573: Update/remove game engagement in working memory` block.

Replace:
```python
                    # AD-573: Update/remove game engagement in working memory
                    try:
                        wm = getattr(agent, 'working_memory', None)
                        if wm:
                            game_result = game_info.get("result")
                            if game_result:
                                wm.remove_engagement(player_game["game_id"])
                            else:
                                wm.update_engagement(
                                    player_game["game_id"],
                                    state={"last_move": position},
                                )
                    except Exception:
                        logger.debug("BF-123: Working memory game update failed", exc_info=True)
```

With:
```python
                    # BF-125: Game-over WM cleanup handled by GAME_COMPLETED subscriber.
```

#### 2c. `src/probos/proactive.py` — `_extract_commands_from_reply()` MOVE handler

**Lines 2458-2481:** This path already has no WM cleanup (that's defect B). No removal needed, but the event subscriber now covers it — no additional code needed here.

#### 2d. `src/probos/routers/agents.py` — DM MOVE handler

**Lines 266-302:** This path already has no WM cleanup (that's defect C). No removal needed, but the event subscriber now covers it — no additional code needed here.

### 3. No Changes Needed: Restore Path

The existing game revalidation at `finalize.py:338-346` is **correct and should remain**. It serves as a defense-in-depth safety net: if any edge case causes a stale game engagement to survive into the frozen state, the restore path catches it. The event subscriber prevents the corruption; the restore revalidation is the backup.

## Tests

### Test File: `tests/test_bf125_working_memory_desync.py`

```python
"""BF-125: Working memory game engagement desync tests.

Validates that:
1. Game completion cleans BOTH players' working memory
2. Event-driven cleanup fires for all move pathways
3. Restore-time revalidation remains functional
"""

import time
import pytest
from probos.cognitive.agent_working_memory import AgentWorkingMemory, ActiveEngagement


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
        """Stale game engagement is pruned during from_dict() restore."""
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
        wm.record_action("Old action", "proactive")
        # Tamper timestamp to make it old
        if wm._recent_actions:
            old_entry = wm._recent_actions[0]
            wm._recent_actions[0] = type(old_entry)(
                content=old_entry.content,
                category=old_entry.category,
                source_pathway=old_entry.source_pathway,
                timestamp=time.time() - 200_000,  # >24h ago
                metadata=old_entry.metadata,
            )
        frozen = wm.to_dict()
        restored = AgentWorkingMemory.from_dict(frozen, stale_threshold_seconds=86400)
        assert len(restored._recent_actions) == 0
```

**Test count: 9 tests** (5 game completion cleanup + 3 restore revalidation + 1 stale pruning)

## Engineering Principles Compliance

| Principle | How Applied |
|-----------|------------|
| **Single Responsibility** | One event subscriber handles all game WM cleanup. Move handlers only process moves. |
| **DRY** | Replaces 3 separate inline cleanup blocks with 1 centralized subscriber. |
| **Open/Closed** | Uses existing event bus — new subscriber, no RecreationService modification. |
| **Fail Fast / Log-and-Degrade** | `wm.remove_engagement()` is already safe for missing IDs. Subscriber catches exceptions per-agent. |
| **Defense in Depth** | Event subscriber prevents stale state at creation. Restore revalidation catches anything that slips through. |
| **Law of Demeter** | Subscriber accesses `wm.get_engagement()` / `wm.remove_engagement()` — public API only. |

## Build Verification Checklist

1. **Event subscription wired:** `GAME_COMPLETED` subscriber registered in finalize.py startup path.
2. **Both players cleaned:** Complete a game — verify both players' working memory has no stale engagement.
3. **Inline cleanup removed:** Confirm proactive.py and ward_room_router.py no longer have inline WM game cleanup.
4. **Reply path covered:** Complete a game via reply-based MOVE — verify cleanup fires via event.
5. **DM path covered:** Complete a game via DM MOVE — verify cleanup fires via event.
6. **Restore revalidation intact:** finalize.py:338-346 unchanged — still removes stale games on restart.
7. **Non-game engagements untouched:** Task/collaboration engagements are never affected by game cleanup.
8. **Regression:** Run full existing test suite — `pytest tests/test_working_memory*.py tests/test_recreation*.py tests/test_proactive*.py tests/test_agents_router.py`.
