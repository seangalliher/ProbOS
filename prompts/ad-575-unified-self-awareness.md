# AD-575: Unified Self-Awareness — Cross-Context Identity Recognition

## Problem

When an agent encounters references to their own callsign in Ward Room thread content, they respond as a spectator rather than recognizing themselves as a participant. Observed: Echo (Counselor) plays tic-tac-toe against the Captain via DM with full game awareness (AD-572/573), but when the game is broadcast to the Recreation channel, Echo responds in the Ward Room thread with: *"I love watching how different minds approach strategy games"* and *"it's going to be fascinating to see how Echo responds"* — referring to herself in third person as an observer.

**Root cause:** The Ward Room notification path in `_build_user_message()` injects identity context via `_orientation_rendered` in `_build_temporal_context()`, but does NOT perform self-mention detection on the thread content being responded to. The agent knows who she IS (orientation narrative) but fails to connect that identity to references of her callsign in the thread she's responding to.

This is NOT a game-specific bug. It affects all cross-context scenarios:
- An agent could comment on their own Ward Room post as if someone else wrote it
- An agent could fail to recognize when a crew discussion references them by callsign
- An agent could spectate an activity they're actively participating in

**Prior art:** BF-102 commissioning awareness (`_build_temporal_context()` lines 1801-1808) injects `"If someone mentions your name, they are talking about YOU"` — but gated to agents < 300 seconds old. This confirms the concept is established; AD-575 generalizes it.

**Desired behavior (per Captain):** The participant should be aware the game is being broadcast. They should naturally suppress spectator commentary on their own game. It would be totally normal for Echo to reply to a spectator's comment in the thread — but she must do so knowing they are watching *her*. She should have that awareness as the player.

## Architecture

### Deliverables

1. **`_detect_self_in_content()` method** on `CognitiveAgent` — scans text for the agent's own callsign using word-boundary matching
2. **Self-recognition cue injection** in the Ward Room branch of `_build_user_message()` — when self-mention is detected in thread content
3. **Cross-context engagement binding** — when self-mentioned AND has matching active engagement (game, task), inject specific participatory awareness
4. **Tests** — 8+ new tests

### Non-goals
- Hard-coded response suppression (violates agent autonomy — the agent should *naturally* respond as a participant, not be blocked from responding)
- Changes to `WardRoomRouter` targeting logic (routing is correct; the agent IS correctly targeted — the issue is cognitive, not routing)
- Changes to game engine or `RecreationService`
- DM path changes (1:1 context, identity is implicit)
- Proactive path changes (already has explicit identity grounding at lines 2068-2084)

## Implementation

### File 1: `src/probos/cognitive/cognitive_agent.py`

#### Change A: New method `_detect_self_in_content()`

Add after `_resolve_callsign()` (currently at line ~1695). This method detects when the agent's own callsign appears in thread content and returns a grounding cue string.

```python
def _detect_self_in_content(self, content: str) -> str:
    """Detect if agent's own callsign appears in content and return grounding cue.

    AD-575: Cross-context self-recognition. When the agent's callsign
    appears in Ward Room thread content, return a grounding note so the
    agent recognizes itself as a participant, not an observer.

    Returns a grounding string, or empty string if no self-mention detected.
    """
    callsign = self._resolve_callsign()
    if not callsign:
        return ""

    import re
    if not re.search(rf"\b{re.escape(callsign)}\b", content, re.IGNORECASE):
        return ""

    # Self-mention detected — build grounding cue
    cue_parts: list[str] = [
        f"IMPORTANT: Your callsign is {callsign}. References to"
        f" '{callsign}' in the thread above refer to YOU."
        f" You are a participant in what is being discussed, not an"
        f" outside observer. Respond from your perspective as a participant.",
    ]

    # Cross-context engagement binding (AD-572/573)
    _wm = getattr(self, "_working_memory", None)
    if _wm and _wm.has_engagement("game"):
        games = _wm.get_engagements_by_type("game")
        if games:
            g = games[0]
            game_type = g.state.get("game_type", "game")
            opponent = g.state.get("opponent", "")
            cue_parts.append(
                f"You have an active {game_type} game"
                + (f" against {opponent}" if opponent else "")
                + ". Spectators are watching your game in this thread."
                + " Engage from your perspective as the player."
            )

    return "\n".join(cue_parts)
```

**Signature verification:**
- `_resolve_callsign(self) -> str | None` — confirmed at line 1681, checks `self.callsign` then birth certificate fallback
- `self._working_memory: AgentWorkingMemory` — confirmed at line 69, property at line 87
- `AgentWorkingMemory.has_engagement(engagement_type: str | None = None) -> bool` — confirmed at `agent_working_memory.py` line 251
- `AgentWorkingMemory.get_engagements_by_type(engagement_type: str) -> list[ActiveEngagement]` — confirmed at line 264
- `ActiveEngagement.state: dict[str, Any]` — confirmed at line 54, keys include `"game_type"`, `"opponent"`

**Design notes:**
- Word-boundary regex (`\b`) prevents false positives: "Echo" won't match "Echoing" or "echoed"
- Case-insensitive matching handles "echo" vs "Echo"
- Returns empty string (not None) for clean conditional: `if cue: parts.append(cue)`
- `getattr(self, "_working_memory", None)` follows the existing safety pattern used elsewhere in this class (e.g., line 1986)
- Move `import re` to top of file if not already imported (it is — verify)

#### Change B: Inject self-recognition cue in Ward Room branch of `_build_user_message()`

In the `ward_room_notification` branch of `_build_user_message()` (currently starting at line ~1967):

**Insertion point:** After the conversation context block and BEFORE the author attribution block. Currently the flow is:

```python
# ~line 2007-2008 (existing)
if context:
    wr_parts.append(f"\nConversation so far:\n{context}")

# >>> INSERT AD-575 HERE <<<

# ~line 2009 (existing)
author_id = params.get("author_id", "")
```

**Code to insert:**

```python
# AD-575: Self-recognition in Ward Room threads
self_cue = self._detect_self_in_content(context)
if self_cue:
    wr_parts.append(self_cue)
```

**Variables available at insertion point:**
- `context: str` — thread body + last 5 posts with callsign prefixes (line 1971). Already contains the thread title (formatted as `"Thread: {title}\n{body}\n{callsign}: {post}..."` by `WardRoomRouter`).
- `self._resolve_callsign()` — available on self
- `self._working_memory` — available on self

**Why this placement:** The self-recognition cue appears AFTER the agent has seen the thread content (so the LLM knows what was said) and BEFORE the response instructions (so the LLM applies the grounding when formulating its response).

### File 2: Tests

Add to an appropriate test file (`tests/test_cognitive_agent.py` or a new focused `tests/test_ad575_self_awareness.py` — use whichever pattern is consistent with AD-572/573 test placement).

**Required tests (minimum 8):**

```
1. test_detect_self_callsign_found
   - Agent with callsign "Echo", content contains "Captain challenges Echo to tictactoe"
   - Assert: returns non-empty string containing "Echo" and "participant"

2. test_detect_self_callsign_not_found
   - Agent with callsign "Echo", content contains "Captain played position 0"
   - Assert: returns empty string ""

3. test_detect_self_callsign_in_title_area
   - Content starts with "Thread: [Challenge] Captain challenges Echo\n..."
   - Assert: returns non-empty string (title is part of context string)

4. test_detect_self_case_insensitive
   - Agent with callsign "Echo", content contains "ECHO" or "echo"
   - Assert: returns non-empty string

5. test_detect_self_word_boundary
   - Agent with callsign "Echo", content contains "Echoing" and "echoed" but NOT bare "Echo"
   - Assert: returns empty string (word boundary prevents partial match)

6. test_detect_self_no_callsign
   - Agent with no callsign set (_resolve_callsign returns None)
   - Assert: returns empty string, no exception

7. test_detect_self_with_game_engagement
   - Agent with callsign "Echo", content contains "Echo", agent has active game engagement
   - Assert: returned string contains "game" and "player" and "Spectators"

8. test_detect_self_without_game_engagement
   - Agent with callsign "Echo", content contains "Echo", NO active engagements
   - Assert: returned string contains "participant" but NOT "game"

9. test_ward_room_message_includes_self_cue
   - Build a ward_room_notification observation with thread content mentioning agent's callsign
   - Call _build_user_message()
   - Assert: result contains "Your callsign is" and "participant"

10. test_ward_room_message_excludes_self_cue_when_not_mentioned
    - Build a ward_room_notification observation with thread content NOT mentioning agent
    - Call _build_user_message()
    - Assert: result does NOT contain "Your callsign is"
```

**Test patterns:** Follow the existing mock patterns used for `_build_user_message()` tests (mock `_runtime`, `_working_memory`, `_resolve_callsign`, `_orientation_rendered`). Check AD-572/573 tests for the exact mocking pattern.

## Engineering Principles Compliance

| Principle | Compliance |
|-----------|-----------|
| **SRP** | `_detect_self_in_content()` has one job — detect self-references and format a grounding cue. No side effects, no state mutation. |
| **OCP** | Extends `_build_user_message()` via additive insertion. No modification of existing logic. |
| **DRY** | Reuses existing `_resolve_callsign()` and `AgentWorkingMemory` APIs. No duplication. |
| **Law of Demeter** | Accesses `self._working_memory` via existing `getattr` safety pattern. No reaching through objects (`g.state.get()` is dict access on a public field). |
| **Fail Fast** | Returns empty string on missing callsign — graceful degradation. Regex failure on malformed callsign would raise (visible, not silent). |
| **Defense in Depth** | Word-boundary regex prevents false positives on substrings. `re.escape()` prevents regex injection from callsign strings. |

## Dependencies
- AD-513 Phase 1 (crew complement grounding) — COMPLETE
- AD-573 (unified working memory in all paths) — COMPLETE
- AD-572 (game context injection) — COMPLETE

## Deferred
- **AD-575b:** Proactive path self-mention detection — scan `context["ward_room_activity"]` for self-references in proactive think cycle. Lower priority since proactive already has explicit identity grounding.
- **AD-575c:** Self-mention in DM forwarded content — if a DM includes quoted Ward Room content mentioning the agent. Edge case.

## Verification
1. Run targeted AD-575 tests — all must pass
2. Run full test suite — zero regressions
3. **Manual validation:** Start a game with an agent in HXI. When the game is broadcast to the Recreation channel, verify the agent responds to spectator comments *as the player*, not as another spectator.
