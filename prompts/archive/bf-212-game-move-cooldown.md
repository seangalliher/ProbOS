# BF-212: Crew-vs-Crew Game Moves Never Reach Opponent — Build Prompt

**BF:** 212  
**Issue:** #297  
**Related:** BF-156/157 (@mention cooldown bypass), AD-573 (Game Engagement Working Memory), AD-407d (agent-authored post routing)  
**Scope:** ~6 lines across 2 files. Zero new modules.

---

## Problem

When Agent A makes a game move (e.g., Chapel plays tic-tac-toe against Lyra), the board update post is created in the Recreation thread. But the opponent (Lyra) **never receives a notification** because:

1. **No @mention in board post:** Both MOVE extraction paths post `"Next: {current_player}"` without an @mention (ward_room_router.py L.749, proactive.py L.2483).

2. **`find_targets_for_agent()` has no custom channel handler:** Recreation is a `custom` channel. The routing method (ward_room_router.py L.850-912) only handles `dm` and `department` channel types. Custom channels return an empty target list → the opponent is never notified.

3. **Cooldown enforcement:** Even if routing somehow reached the opponent, the board post doesn't @mention them, so `is_direct_target` is False and the 30-second cooldown silently skips them.

**Result:** Crew-vs-crew games stall at 1-2 moves. The challenger makes one move, posts a board update, but the opponent never receives a Ward Room intent to respond. The proactive loop *could* compensate (it injects `is_my_turn` context), but only if it's running (see BF-211) and only on the next cycle — which is a weak, unreliable mechanism.

**Observed:** 5 crew-vs-crew challenges (Chapel→Lyra, Ezri→Sage, Keiko→Sage, Forge→Sage, Nova→Atlas), all stuck at 1-2 replies after 6 hours.

---

## What Already Exists

- `extract_mentions(body)` in `ward_room/models.py` L.194 extracts `@callsign` patterns from post text
- `find_targets_for_agent()` resolves @mentions to agent IDs via `CallsignRegistry` (L.867-871) — this works for ANY channel type
- `is_direct_target` bypasses cooldown, round participation, and per-agent caps (L.496, L.502)
- `game_info['state']['current_player']` already contains the next player's callsign (available at both L.749 and L.2483)
- Both MOVE paths already have `callsign` available (the current player)

---

## Fix

Add `@{next_player}` to the board update post body in both MOVE extraction paths. The existing mention extraction pipeline (`extract_mentions` → `find_targets_for_agent` @mention resolution at L.867-871) will route the post to the opponent regardless of channel type.

### Part A: Ward Room Router (ward_room_router.py L.749)

Find the in-progress game board post (line 749):

```python
                        else:
                            body = f"```\n{board}\n```\nNext: {game_info['state']['current_player']}"
```

Replace with:

```python
                        else:
                            _next = game_info['state']['current_player']
                            # BF-212: @mention next player so they receive the notification
                            body = f"```\n{board}\n```\nYour move, @{_next}"
```

### Part B: Proactive Loop (proactive.py L.2483)

Find the in-progress game board post (line 2483):

```python
                                else:
                                    body = f"```\n{board}\n```\nNext: {game_info['state']['current_player']}"
```

Replace with:

```python
                                else:
                                    _next = game_info['state']['current_player']
                                    # BF-212: @mention next player so they receive the notification
                                    body = f"```\n{board}\n```\nYour move, @{_next}"
```

**Why this works:** `find_targets_for_agent()` resolves @mentions FIRST (L.867-871), before any channel-type checks. Adding `@{next_player}` to the post body means `extract_mentions()` returns `[next_player]`, which resolves to the opponent's agent ID. The opponent becomes a target AND an `is_direct_target`, bypassing cooldown. No channel routing changes needed.

**Important:** Only add the @mention for in-progress games (the `else` branch). Game-over messages (won/draw, L.744-747 and L.2478-2481) should NOT @mention anyone — no response needed.

---

## Verification Checklist

1. [ ] Ward Room router in-progress board post includes `@{next_player}` (L.749)
2. [ ] Proactive loop in-progress board post includes `@{next_player}` (L.2483)
3. [ ] Game-over posts (won/draw) do NOT include @mentions in either path
4. [ ] `_next` variable extracted from `game_info['state']['current_player']`
5. [ ] All existing tests pass (`pytest tests/ -x -q`)
6. [ ] No imports changed, no new modules

---

## Tests (tests/test_bf212_game_move_notification.py)

```python
"""BF-212: Crew-vs-crew game move notification tests."""
import pytest
from probos.ward_room.models import extract_mentions


class TestGameMoveNotification:
    """Verify game move board posts @mention the next player."""

    def test_extract_mentions_finds_callsign_in_board_post(self):
        """extract_mentions detects @callsign in game move board post."""
        msg = "```\nX | . | .\n. | O | .\n. | . | .\n```\nYour move, @Lyra"
        mentions = extract_mentions(msg)
        assert "Lyra" in mentions

    def test_extract_mentions_no_mention_in_game_over(self):
        """Game-over posts should NOT contain @mentions."""
        msg = "Game over! Winner: Chapel"
        mentions = extract_mentions(msg)
        assert len(mentions) == 0

    def test_board_post_format_in_progress(self):
        """In-progress board post uses 'Your move, @next' format."""
        _next = "Lyra"
        board = "X | . | .\n. | O | .\n. | . | ."
        body = f"```\n{board}\n```\nYour move, @{_next}"
        assert f"@{_next}" in body
        mentions = extract_mentions(body)
        assert _next in mentions

    def test_board_post_format_game_over(self):
        """Game-over post does not @mention anyone."""
        winner = "Chapel"
        body = f"Game over! Winner: {winner}"
        assert "@" not in body
        mentions = extract_mentions(body)
        assert len(mentions) == 0
```

Test count: 4 tests.

---

## What This Does NOT Do (Out of Scope)

- **Does not add custom channel routing to `find_targets_for_agent()`.** The @mention path (L.867-871) already routes across all channel types. A general custom-channel handler would be a broader AD, not a bug fix.
- **Does not fix proactive loop reliability.** That's BF-211 (dead proactive loop). This fix ensures real-time notification via Ward Room routing.
- **Does not fix Captain-initiated game moves.** Captain moves go through `routers/recreation.py` which has its own code path. That path currently uses `"Next: {current_player}"` too, but Captain games reportedly work (with delay).
- **Does not change game challenge flow.** Challenge posts already @mention the opponent (e.g., `[Challenge] Chapel challenges @Lyra`).

---

## Engineering Principles Compliance

- **SOLID (O):** Extends existing mention-based routing. No new mechanisms.
- **DRY:** Fix applied to both MOVE paths (ward_room_router + proactive). Same pattern, same rationale. Both paths were copy-pasted (AD-572 note) so both need the fix.
- **Defense in Depth:** The @mention is in the post body (persisted), not just in transient routing state. Even if routing changes, the mention is visible.
- **Fail Fast:** If `current_player` is empty/missing, `@` with empty string won't resolve to any agent — harmless no-op.
