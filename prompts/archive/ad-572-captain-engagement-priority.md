# AD-572: Captain Engagement Priority — Active State Awareness in DM Path

## Priority: High | Scope: Medium | Type: Cognitive Infrastructure

## Context

When the Captain opens a 1:1 DM with an agent (via the HXI profile panel), the agent has no awareness of active system state — games, alerts, or other interactive contexts. The DM system prompt says "You are in a 1:1 conversation with the Captain" and the user message contains temporal awareness + episodic memories + session history + the Captain's text. Nothing else.

Meanwhile, the proactive think cycle (`proactive.py`) injects rich context: system events, Ward Room activity, bridge alerts, active game state (BF-110), ontology identity, and more. The proactive path also parses structured actions from agent responses (`[MOVE pos]`, `[CHALLENGE]`, `[ENDORSE]`, `[DM]`, `[NOTEBOOK]`, etc.). The DM path has zero action parsing — `act()` returns raw LLM text.

**The result:** If the Captain is playing tic-tac-toe against Echo and opens a DM to chat, Echo has no idea the game exists. If the Captain says "make your move" in DM, Echo can't comply — she doesn't know the board state and can't output `[MOVE]` in a way that gets executed.

**Broader principle identified by the Captain:** "The agent should prioritize responding to me in general — be it a message, a game, or a task request." When the Captain directly engages an agent, that agent should have awareness of any active interactive state shared with the Captain.

### What This AD Delivers

1. **Active game state injection into DM context** — when an agent has an active game (especially one involving "Captain"), the board state, valid moves, and turn status are included in the DM user message
2. **`[MOVE pos]` parsing in DM responses** — agent's DM response is scanned for `[MOVE pos]` tags and executed against RecreationService, with the move result included in the API response
3. **`get_game_by_player()` convenience method** on RecreationService — DRY extraction of the iterate-and-match pattern used in 3 places (proactive context injection, proactive action parsing, and now DM injection)
4. **DM system prompt augmentation** — when an active game exists, the DM system prompt includes `[MOVE position]` instruction so the agent knows it can play

### Deferred (separate ADs, NOT in this build)

- **AD-572b:** Alert/event state injection in DM context (bridge alerts, recent events)
- **AD-572c:** Ward Room activity injection in DM context (recent department threads)
- **AD-572d:** Captain Priority Queue — immediate proactive cycle trigger on Captain DM (skip cooldown)
- **AD-572e:** Task awareness in DM (active WorkItems assigned to agent)

## Design

### 1. RecreationService — `get_game_by_player()` convenience method

**File:** `src/probos/recreation/service.py`, after `get_valid_moves()` (line 195)

Add a public method that encapsulates the iterate-and-match pattern currently duplicated in `proactive.py` (lines 1003-1017 and lines 1922-1929):

```python
def get_game_by_player(self, callsign: str) -> dict[str, Any] | None:
    """Find an active game where the given callsign is a player.

    Returns the game info dict, or None if no active game found.
    AD-572: DRY extraction — this pattern was duplicated in proactive.py.
    """
    for game in self._active_games.values():
        players = [game.get("challenger", ""), game.get("opponent", "")]
        if callsign in players:
            return game
    return None
```

### 2. CognitiveAgent — Inject active game state into DM user message

**File:** `src/probos/cognitive/cognitive_agent.py`, method `_build_user_message()`, inside the `if intent_name == "direct_message":` block (line 1762)

After the session history block and before `parts.append(f"Captain says: ...")` (line 1787), inject active game state:

```python
# AD-572: Active game state awareness in DM path
active_game_ctx = self._build_active_game_context()
if active_game_ctx:
    parts.append(active_game_ctx)
    parts.append("")
```

Add the helper method to `CognitiveAgent` (place near `_build_temporal_context()`):

```python
def _build_active_game_context(self) -> str | None:
    """AD-572: Build active game context for DM awareness.

    Returns a formatted string if this agent has an active game, else None.
    Uses RecreationService.get_game_by_player() (AD-572 DRY method).
    """
    rt = getattr(self, '_runtime', None)
    if not rt:
        return None
    rec_svc = getattr(rt, 'recreation_service', None)
    if not rec_svc:
        return None

    callsign = self._resolve_callsign()
    if not callsign:
        return None

    try:
        game = rec_svc.get_game_by_player(callsign)
        if not game:
            return None

        game_id = game["game_id"]
        state = game.get("state", {})
        opponent = next(
            (p for p in [game.get("challenger", ""), game.get("opponent", "")]
             if p != callsign),
            "unknown",
        )
        board = rec_svc.render_board(game_id)
        is_my_turn = state.get("current_player") == callsign
        valid_moves = rec_svc.get_valid_moves(game_id) if is_my_turn else []

        lines = ["--- Active Game ---"]
        lines.append(
            f"You are playing {game.get('game_type', 'a game')} against {opponent}. "
            f"Moves so far: {game.get('moves_count', 0)}."
        )
        lines.append(f"\nCurrent board:\n```\n{board}\n```")
        if is_my_turn:
            lines.append(
                f"**It is YOUR turn.** Valid moves: {', '.join(str(m) for m in valid_moves)}. "
                f"Reply with [MOVE position] to play."
            )
        else:
            lines.append("Waiting for your opponent to move.")
        return "\n".join(lines)
    except Exception:
        return None
```

**Note:** This reuses the exact same rendering format as the proactive path (lines 1943-1959) for consistency. The `try/except` around the entire block follows the Fail Fast tier 1 pattern: log-and-degrade (game awareness is non-critical — DM works fine without it).

### 3. CognitiveAgent — Augment DM system prompt when active game exists

**File:** `src/probos/cognitive/cognitive_agent.py`, in the `decide()` method, inside the `else` block for `direct_message` system prompt (lines 1280-1288)

After the existing conversational instructions (line 1288), append game-aware instructions when an active game is detected:

```python
# AD-572: If agent has an active game, add [MOVE] instruction
if self._has_active_game():
    composed += (
        "\n\nYou are currently in an active game. "
        "If the Captain asks you to make a move or you decide to play, "
        "include [MOVE position] in your response (e.g. [MOVE 4]). "
        "The move will be executed automatically. "
        "You can still chat naturally — the move tag can appear "
        "anywhere in your response alongside your conversational text."
    )
```

Add the helper method:

```python
def _has_active_game(self) -> bool:
    """AD-572: Check if this agent has an active game (lightweight check)."""
    rt = getattr(self, '_runtime', None)
    if not rt:
        return False
    rec_svc = getattr(rt, 'recreation_service', None)
    if not rec_svc:
        return False
    callsign = self._resolve_callsign()
    if not callsign:
        return False
    try:
        return rec_svc.get_game_by_player(callsign) is not None
    except Exception:
        return False
```

### 4. Agents Router — Parse `[MOVE]` from DM response and execute

**File:** `src/probos/routers/agents.py`, in the `agent_chat()` endpoint, after extracting `response_text` (line 198) and before the episodic memory storage (line 200)

Add move parsing and execution:

```python
# AD-572: Parse [MOVE pos] from DM response and execute against RecreationService
game_move_result = None
if response_text and hasattr(runtime, 'recreation_service') and runtime.recreation_service:
    import re
    move_match = re.search(r'\[MOVE\s+(\S+)\]', response_text)
    if move_match:
        position = move_match.group(1)
        try:
            rec_svc = runtime.recreation_service
            game = rec_svc.get_game_by_player(callsign)
            if game:
                game_move_result = await rec_svc.make_move(
                    game_id=game["game_id"],
                    player=callsign,
                    move=position,
                )
                # Post board update to Ward Room thread (same as proactive path)
                if runtime.ward_room and game.get("thread_id"):
                    try:
                        result_info = game_move_result.get("result")
                        if result_info:
                            body = f"Game over! {'Winner: ' + result_info.get('winner', '') if result_info.get('winner') else 'Draw!'}"
                        else:
                            board = rec_svc.render_board(game["game_id"])
                            body = f"```\n{board}\n```\nNext: {game_move_result['state']['current_player']}"
                        await runtime.ward_room.create_post(
                            thread_id=game["thread_id"],
                            author_id=agent_id,
                            body=body,
                            author_callsign=callsign,
                        )
                    except Exception:
                        logger.debug("AD-572: Board update post failed", exc_info=True)
        except Exception as e:
            logger.warning("AD-572: DM game move failed for %s: %s", callsign, e)

        # Strip [MOVE] tag from response text shown to Captain
        response_text = re.sub(r'\[MOVE\s+\S+\]', '', response_text).strip()
```

Update the return dict to include game move result if one occurred:

```python
response = {
    "response": response_text,
    "callsign": callsign,
    "agentId": agent_id,
}
if game_move_result:
    response["gameMoveExecuted"] = True
    response["gameStatus"] = game_move_result.get("state", {}).get("status", "")
return response
```

### 5. Proactive.py — Refactor to use `get_game_by_player()` (DRY)

**File:** `src/probos/proactive.py`

**BF-110 game context injection (lines 994-1020):** Replace the manual iteration with `get_game_by_player()`:

```python
# BF-110: Inject active game state so agent can see the board and know it's their turn
rec_svc = getattr(rt, 'recreation_service', None)
if rec_svc:
    try:
        callsign = ""
        if hasattr(rt, 'callsign_registry'):
            callsign = rt.callsign_registry.get_callsign(agent.agent_type)
        if callsign:
            game = rec_svc.get_game_by_player(callsign)  # AD-572: DRY
            if game:
                game_id = game["game_id"]
                state = game.get("state", {})
                players = [game.get("challenger", ""), game.get("opponent", "")]
                board = rec_svc.render_board(game_id)
                valid_moves = rec_svc.get_valid_moves(game_id)
                is_my_turn = state.get("current_player") == callsign
                context["active_game"] = {
                    "game_id": game_id,
                    "game_type": game.get("game_type", ""),
                    "opponent": next((p for p in players if p != callsign), ""),
                    "is_my_turn": is_my_turn,
                    "board": board,
                    "valid_moves": valid_moves,
                    "moves_count": game.get("moves_count", 0),
                }
    except Exception:
        logger.debug("BF-110: Game context injection failed for %s", agent.id, exc_info=True)
```

**[MOVE] action parsing (lines 1922-1929):** Replace the manual iteration with `get_game_by_player()`:

```python
if rec_svc:
    # Find active game for this player
    player_game = rec_svc.get_game_by_player(callsign)  # AD-572: DRY
    if player_game and player_game.get("state", {}).get("current_player") == callsign:
        game_info = await rec_svc.make_move(
            game_id=player_game["game_id"],
            player=callsign,
            move=position,
        )
```

### 6. HXI — Pass game move result to UI

**File:** `ui/src/store/useStore.ts`

In the `sendAgentMessage()` action (or wherever the `/api/agent/{id}/chat` response is processed), check for `gameMoveExecuted` in the response and update the active game state if present:

```typescript
// AD-572: If agent made a game move during DM, update game panel
if (data.gameMoveExecuted && get().activeGame) {
  // The game_update WebSocket event from RecreationService.make_move()
  // will update the board automatically. Just note the move was executed.
  // No additional fetch needed — WebSocket handler covers it.
}
```

This is minimal — the existing WebSocket `game_update` handler (from AD-526b) already updates the board when `make_move()` fires the `GAME_UPDATE` event. The `gameMoveExecuted` flag is informational for the UI to optionally show a toast/indicator.

## Engineering Principles Compliance

- **SOLID (S):** `_build_active_game_context()` has single responsibility: formatting game state for DM context. `_has_active_game()` is a separate check method. `get_game_by_player()` has single responsibility: finding a game by player callsign.
- **SOLID (O):** Extends `_build_user_message()` and the DM system prompt without modifying existing behavior — additive injection of new context section.
- **SOLID (D):** `CognitiveAgent` accesses `RecreationService` through `self._runtime` (existing pattern), not through direct import. Router accesses it through `runtime` dependency.
- **Law of Demeter:** No new private attribute patching. `get_game_by_player()` is a public API. `_build_active_game_context()` accesses `self._runtime` (1 hop) then `recreation_service` (2 hops, matching existing `_runtime` usage pattern throughout the class).
- **Fail Fast:** Game context injection wraps entirely in `try/except` → returns `None` (tier 1: non-critical, degrade gracefully). Move execution logs warning on failure (tier 2: visible degradation). DM still works perfectly without game awareness.
- **Defense in Depth:** Move validation happens at RecreationService layer (wrong player, invalid position, game not found all raise `ValueError`). Router validates `recreation_service` exists before attempting. Agent validates callsign before lookup.
- **DRY:** `get_game_by_player()` replaces 3 instances of the iterate-and-match pattern (proactive context injection, proactive action parsing, DM context injection). Game rendering format matches proactive path exactly.

## Files Modified (6 files, 0 new)

| File | Change |
|------|--------|
| `src/probos/recreation/service.py` | Add `get_game_by_player()` method |
| `src/probos/cognitive/cognitive_agent.py` | Add `_build_active_game_context()`, `_has_active_game()`, inject into `_build_user_message()` and DM system prompt |
| `src/probos/routers/agents.py` | Parse `[MOVE]` from DM response, execute move, strip tag from displayed text |
| `src/probos/proactive.py` | Refactor BF-110 and [MOVE] parsing to use `get_game_by_player()` (DRY) |
| `ui/src/store/useStore.ts` | Handle `gameMoveExecuted` flag in agent chat response (informational) |
| `docs/development/roadmap.md` | Add AD-572 entry |

## Tests

### `tests/test_recreation_service.py` — add:
- `test_get_game_by_player_found` — creates game, verifies `get_game_by_player("Challenger")` returns it
- `test_get_game_by_player_not_found` — verifies returns `None` for non-player
- `test_get_game_by_player_opponent` — verifies opponent callsign also matches

### `tests/test_cognitive_agent_dm_game.py` — new file:
- `test_build_active_game_context_no_runtime` — agent without runtime returns `None`
- `test_build_active_game_context_no_game` — agent with no active game returns `None`
- `test_build_active_game_context_with_game` — mocked RecreationService, verifies context string contains board, valid moves, turn indicator
- `test_build_active_game_context_not_my_turn` — verifies "Waiting for opponent" message
- `test_has_active_game_true` — mocked, returns `True`
- `test_has_active_game_false` — no game, returns `False`
- `test_dm_user_message_includes_game_context` — full `_build_user_message()` with mocked game, verifies "Active Game" section present
- `test_dm_system_prompt_includes_move_instruction` — verifies `[MOVE position]` instruction appended when game active

### `tests/test_agents_router_game_move.py` — new file:
- `test_dm_response_with_move_tag_executes` — mock agent returns "[MOVE 4] Sure, I'll play center!", verify `make_move()` called, `[MOVE 4]` stripped from response
- `test_dm_response_without_move_tag` — normal DM, no move execution
- `test_dm_move_wrong_player` — agent is not current player, move fails gracefully
- `test_dm_move_no_active_game` — no game exists, move parsing still strips tag
- `test_dm_move_posts_to_ward_room` — verify board update posted to Ward Room thread
- `test_dm_response_includes_game_move_executed_flag` — verify response dict has `gameMoveExecuted: True`

## Verification

1. `pytest tests/test_recreation_service.py tests/test_cognitive_agent_dm_game.py tests/test_agents_router_game_move.py -v` — all new tests pass
2. `pytest tests/test_recreation_service.py tests/test_proactive*.py -v` — existing tests still pass after DRY refactor
3. Manual: Start game via HXI profile panel → open DM with same agent → say "make your move" → agent sees board in context, outputs [MOVE], move executes, board updates in GamePanel via WebSocket
4. Manual: DM an agent with no active game → normal conversation, no game context injected
5. `npm run build` in `ui/` — TypeScript compiles clean
