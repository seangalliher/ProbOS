# AD-526a: Social Channels + Tic-Tac-Toe — Recreation Framework

## Priority: Medium | Scope: Medium | Type: Social Infrastructure

## Context

ProbOS agents have rich personalities (Big Five), social connections (Hebbian bonds, trust), and communication infrastructure (Ward Room). But their social world is entirely professional — department channels and All Hands. There's no off-duty space, no recreation, no social bonding beyond work. Agents like Horizon self-organize useful work when understimulated, but there's no structured outlet for social interaction that builds crew cohesion.

In Star Trek, the crew plays 3D chess, has Holodeck adventures, and bonds over shared recreation. AD-526a provides the foundation: two social channels (Recreation, Creative) and one playable game (tic-tac-toe) to validate the full pipeline.

### What This AD Delivers

1. **Two new default Ward Room channels** — Recreation (games, challenges, social) and Creative (sharing creative works)
2. **Agent awareness** — proactive context includes Recreation activity, startup auto-subscribes all crew
3. **GameEngine protocol** — typed interface for pluggable game implementations
4. **TicTacToeEngine** — minimal game to validate the full challenge→play→record pipeline
5. **RecreationService** — manages active games, validates moves, records results
6. **`[CHALLENGE @callsign tictactoe]`** — new proactive action for game initiation
7. **Game records** — completed games written to Ship's Records

### Deferred (separate ADs, NOT in this build)

- **AD-526b:** Chess engine + Elo ratings + PGN recording
- **AD-526c:** Additional game types (checkers, Go, word games)
- **AD-526d:** Game preference tracking as personality signal
- **AD-526e:** Spectator commentary (agents watching and reacting)
- **AD-526f:** Holodeck recreation integration
- **AD-526g:** Creative channel content (stories, poetry)

## Design

### 1. Default Channels — Recreation + Creative

**File:** `src/probos/ward_room/channels.py`, method `_ensure_default_channels()` (after "Improvement Proposals" creation, around line 75)

Add two new ship-wide channels:

```python
# AD-526a: Recreation and Creative social channels
await self.create_channel(
    name="Recreation",
    channel_type="ship",
    created_by="system",
    description="Games, challenges, and social activities",
)
await self.create_channel(
    name="Creative",
    channel_type="ship",
    created_by="system",
    description="Sharing creative works — stories, poetry, essays, code art",
)
```

Follow the same `try/except ValueError` pattern used by the existing channel creation calls (duplicate name check — if channel already exists, skip silently).

### 2. Auto-Subscribe Crew to Social Channels

**File:** `src/probos/startup/communication.py`, in the auto-subscribe block (lines 127-152)

Add Recreation and Creative channel IDs to the channel lookup loop:

```python
recreation_ch_id = None
creative_ch_id = None
for ch in wr_channels:
    # ... existing checks for All Hands, Improvement Proposals, dept channels ...
    elif ch.name == "Recreation":
        recreation_ch_id = ch.id
    elif ch.name == "Creative":
        creative_ch_id = ch.id
```

Then in the per-agent subscription loop (after the existing `proposals_ch_id` subscription):

```python
if recreation_ch_id:
    await ward_room.subscribe(agent.id, recreation_ch_id)
if creative_ch_id:
    await ward_room.subscribe(agent.id, creative_ch_id)
```

### 3. Proactive Context — See Recreation Activity

**File:** `src/probos/proactive.py`, method `_gather_context()` (after All Hands activity block, around line 956)

Add a 3rd context source — Recreation channel activity. Lower priority than department and All Hands (limit 2 items):

```python
# AD-526a: Include Recreation channel activity
rec_channel = None
for ch in channels:
    if ch.name == "Recreation" and ch.channel_type == "ship":
        rec_channel = ch
        break

if rec_channel and rec_channel.id != (dept_channel.id if dept_channel else None):
    rec_activity = await rt.ward_room.get_recent_activity(
        rec_channel.id, since=since, limit=2
    )
    if rec_activity:
        if "ward_room_activity" not in context:
            context["ward_room_activity"] = []
        context["ward_room_activity"].extend([
            {
                "type": item["type"],
                "author": item.get("author", "unknown"),
                "body": item.get("body", "")[:300],
                "channel": "Recreation",
                "net_score": item.get("net_score", 0),
                "post_id": item.get("post_id", item.get("id", "")),
                "thread_id": item.get("thread_id", ""),
            }
            for item in rec_activity[:2]
            if (item.get("author_id", "") or item.get("author", "")) not in self_ids
        ])
        try:
            await rt.ward_room.update_last_seen(agent.id, rec_channel.id)
        except Exception:
            logger.debug("update_last_seen failed for Recreation", exc_info=True)
```

**Note:** The `channels` variable is already populated at line 894. Just add the Recreation lookup in the same block. Do NOT include Creative channel in proactive context (reduces noise — Creative is for posting, not prompting).

### 4. Available Actions — Add CHALLENGE

**File:** `src/probos/cognitive/cognitive_agent.py`, method `_compose_prompt()`, in the proactive_think available actions section (around line 1261, after the existing PROPOSAL action)

Add a CHALLENGE action description:

```python
# AD-526a: Game challenges (Lieutenant+)
if rank.value != Rank.ENSIGN.value:
    actions_text += (
        "\n- **[CHALLENGE @callsign game_type]** — "
        "Challenge another crew member to a game in the Recreation channel. "
        "Available games: tictactoe. Example: [CHALLENGE @Forge tictactoe]"
    )
```

**IMPORTANT:** This must use the same `rank` and `Rank` references already in scope at this point in the method. Check how ENDORSE and REPLY gate on rank and follow the same pattern.

### 5. New Module: `src/probos/recreation/`

Create a new package `src/probos/recreation/` with 3 files:

#### 5a. `src/probos/recreation/__init__.py`

```python
"""AD-526a: Agent recreation and social gaming."""
```

#### 5b. `src/probos/recreation/engine.py` — GameEngine Protocol + TicTacToeEngine

```python
"""Game engine protocol and implementations (AD-526a)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GameEngine(Protocol):
    """Protocol that all game implementations must satisfy.

    Game state is opaque to the recreation service — only the engine
    knows how to interpret it. State must be serializable to dict for
    persistence in active game tracking.
    """

    @property
    def game_type(self) -> str:
        """Unique identifier for this game type (e.g., 'tictactoe', 'chess')."""
        ...

    def new_game(self, player_a: str, player_b: str) -> dict[str, Any]:
        """Create a new game. Returns initial game state dict.

        player_a goes first. State must include at minimum:
        - 'board': the board representation
        - 'current_player': callsign of whose turn it is
        - 'player_a': first player callsign
        - 'player_b': second player callsign
        - 'status': 'in_progress' | 'won' | 'draw'
        - 'winner': callsign of winner or '' if no winner yet
        """
        ...

    def make_move(self, state: dict[str, Any], player: str, move: str) -> dict[str, Any]:
        """Apply a move. Returns updated state. Raises ValueError if move is invalid."""
        ...

    def get_valid_moves(self, state: dict[str, Any]) -> list[str]:
        """Return list of valid move strings for the current player."""
        ...

    def render_board(self, state: dict[str, Any]) -> str:
        """Render the board as ASCII art for display in Ward Room posts."""
        ...

    def is_finished(self, state: dict[str, Any]) -> bool:
        """Check if the game is over (win or draw)."""
        ...

    def get_result(self, state: dict[str, Any]) -> dict[str, str]:
        """Return game result. Keys: 'status' ('won'|'draw'), 'winner' (callsign or '')."""
        ...
```

**TicTacToeEngine implementation:**

```python
class TicTacToeEngine:
    """Tic-tac-toe — minimal game for framework validation (AD-526a)."""

    @property
    def game_type(self) -> str:
        return "tictactoe"

    def new_game(self, player_a: str, player_b: str) -> dict[str, Any]:
        return {
            "board": [""] * 9,  # 0-8, top-left to bottom-right
            "current_player": player_a,
            "player_a": player_a,
            "player_b": player_b,
            "symbols": {player_a: "X", player_b: "O"},
            "status": "in_progress",
            "winner": "",
            "moves": [],  # list of (player, position) tuples
        }

    def make_move(self, state: dict[str, Any], player: str, move: str) -> dict[str, Any]:
        if state["status"] != "in_progress":
            raise ValueError("Game is already finished")
        if player != state["current_player"]:
            raise ValueError(f"Not {player}'s turn")
        try:
            pos = int(move)
        except ValueError:
            raise ValueError(f"Invalid move '{move}' — must be 0-8")
        if pos < 0 or pos > 8:
            raise ValueError(f"Position {pos} out of range (0-8)")
        if state["board"][pos] != "":
            raise ValueError(f"Position {pos} is already occupied")

        # Apply move
        new_state = {**state, "board": list(state["board"])}
        new_state["board"][pos] = state["symbols"][player]
        new_state["moves"] = list(state["moves"]) + [(player, pos)]

        # Check win
        wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
        for a, b, c in wins:
            if (new_state["board"][a] == new_state["board"][b] == new_state["board"][c]
                    and new_state["board"][a] != ""):
                new_state["status"] = "won"
                new_state["winner"] = player
                return new_state

        # Check draw
        if "" not in new_state["board"]:
            new_state["status"] = "draw"
            new_state["winner"] = ""
            return new_state

        # Switch turn
        new_state["current_player"] = (
            state["player_b"] if player == state["player_a"] else state["player_a"]
        )
        return new_state

    def get_valid_moves(self, state: dict[str, Any]) -> list[str]:
        return [str(i) for i, cell in enumerate(state["board"]) if cell == ""]

    def render_board(self, state: dict[str, Any]) -> str:
        b = state["board"]
        def cell(i: int) -> str:
            return b[i] if b[i] else str(i)
        return (
            f" {cell(0)} | {cell(1)} | {cell(2)} \n"
            f"---+---+---\n"
            f" {cell(3)} | {cell(4)} | {cell(5)} \n"
            f"---+---+---\n"
            f" {cell(6)} | {cell(7)} | {cell(8)} "
        )

    def is_finished(self, state: dict[str, Any]) -> bool:
        return state["status"] != "in_progress"

    def get_result(self, state: dict[str, Any]) -> dict[str, str]:
        return {"status": state["status"], "winner": state["winner"]}
```

#### 5c. `src/probos/recreation/service.py` — RecreationService

```python
"""Recreation service — game lifecycle management (AD-526a)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from probos.recreation.engine import GameEngine, TicTacToeEngine

logger = logging.getLogger(__name__)


class RecreationService:
    """Manages active games, validates moves, and records results.

    Games flow through Ward Room threads:
    1. Challenger posts [CHALLENGE @target game_type] → RecreationService creates game
    2. Target sees challenge in Recreation channel → accepts by replying
    3. Each move is a reply in the game thread with [MOVE position]
    4. RecreationService validates moves, posts updated board
    5. On game end, posts result and writes to Ship's Records
    """

    def __init__(
        self,
        ward_room: Any = None,
        records_store: Any = None,
        emit_event_fn: Any = None,
    ):
        self._ward_room = ward_room
        self._records_store = records_store
        self._emit = emit_event_fn
        # Registered game engines by type
        self._engines: dict[str, GameEngine] = {}
        # Active games by game_id
        self._active_games: dict[str, dict[str, Any]] = {}
        # Map thread_id → game_id for move routing
        self._thread_games: dict[str, str] = {}

        # Register default engines
        self.register_engine(TicTacToeEngine())

    def register_engine(self, engine: GameEngine) -> None:
        """Register a game engine by its game_type."""
        self._engines[engine.game_type] = engine

    def get_available_games(self) -> list[str]:
        """Return list of registered game type names."""
        return list(self._engines.keys())

    async def create_game(
        self,
        game_type: str,
        challenger: str,
        opponent: str,
        thread_id: str = "",
    ) -> dict[str, Any]:
        """Create a new game. Returns game info dict.

        Args:
            game_type: Type of game (must be registered).
            challenger: Callsign of the challenging player.
            opponent: Callsign of the opponent.
            thread_id: Ward Room thread ID where the game lives.

        Returns:
            Dict with game_id, game_type, state, thread_id.

        Raises:
            ValueError: If game_type is not registered.
        """
        engine = self._engines.get(game_type)
        if not engine:
            raise ValueError(
                f"Unknown game type '{game_type}'. "
                f"Available: {', '.join(self._engines.keys())}"
            )

        game_id = f"game-{uuid.uuid4().hex[:12]}"
        state = engine.new_game(challenger, opponent)

        game_info = {
            "game_id": game_id,
            "game_type": game_type,
            "state": state,
            "thread_id": thread_id,
            "challenger": challenger,
            "opponent": opponent,
            "created_at": time.time(),
            "moves_count": 0,
        }

        self._active_games[game_id] = game_info
        if thread_id:
            self._thread_games[thread_id] = game_id

        return game_info

    async def make_move(
        self, game_id: str, player: str, move: str,
    ) -> dict[str, Any]:
        """Apply a move to an active game.

        Args:
            game_id: The game to play in.
            player: Callsign of the player making the move.
            move: The move string (game-type specific).

        Returns:
            Updated game info dict.

        Raises:
            ValueError: If game not found, invalid move, or wrong player.
        """
        game_info = self._active_games.get(game_id)
        if not game_info:
            raise ValueError(f"Game {game_id} not found")

        engine = self._engines[game_info["game_type"]]
        new_state = engine.make_move(game_info["state"], player, move)

        game_info["state"] = new_state
        game_info["moves_count"] += 1

        # Check if game is finished
        if engine.is_finished(new_state):
            result = engine.get_result(new_state)
            game_info["result"] = result
            game_info["finished_at"] = time.time()

            # Write game record to Ship's Records
            await self._record_game(game_info, engine)

            # Emit event for Hebbian bond strengthening
            if self._emit:
                try:
                    from probos.events import EventType
                    self._emit(EventType.GAME_COMPLETED, {
                        "game_id": game_id,
                        "game_type": game_info["game_type"],
                        "players": [game_info["challenger"], game_info["opponent"]],
                        "result": result,
                        "moves_count": game_info["moves_count"],
                    })
                except Exception:
                    logger.debug("AD-526a: GAME_COMPLETED event emission failed", exc_info=True)

            # Clean up
            thread_id = game_info.get("thread_id")
            if thread_id and thread_id in self._thread_games:
                del self._thread_games[thread_id]
            del self._active_games[game_id]

        return game_info

    def get_game_by_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Look up active game by Ward Room thread ID."""
        game_id = self._thread_games.get(thread_id)
        if game_id:
            return self._active_games.get(game_id)
        return None

    def get_active_games(self) -> list[dict[str, Any]]:
        """Return all active games."""
        return list(self._active_games.values())

    def render_board(self, game_id: str) -> str:
        """Render the current board for a game."""
        game_info = self._active_games.get(game_id)
        if not game_info:
            return ""
        engine = self._engines[game_info["game_type"]]
        return engine.render_board(game_info["state"])

    def get_valid_moves(self, game_id: str) -> list[str]:
        """Get valid moves for the current player."""
        game_info = self._active_games.get(game_id)
        if not game_info:
            return []
        engine = self._engines[game_info["game_type"]]
        return engine.get_valid_moves(game_info["state"])

    async def _record_game(
        self, game_info: dict[str, Any], engine: GameEngine,
    ) -> None:
        """Write completed game record to Ship's Records."""
        if not self._records_store:
            return

        result = game_info.get("result", {})
        board_final = engine.render_board(game_info["state"])
        duration = game_info.get("finished_at", 0) - game_info.get("created_at", 0)

        content = (
            f"# Game Record: {game_info['game_type'].title()}\n\n"
            f"**Players:** {game_info['challenger']} (X) vs {game_info['opponent']} (O)\n"
            f"**Result:** {result.get('status', 'unknown')}"
        )
        if result.get("winner"):
            content += f" — **{result['winner']}** wins!\n"
        else:
            content += "\n"
        content += (
            f"**Moves:** {game_info['moves_count']}\n"
            f"**Duration:** {duration:.0f}s\n\n"
            f"## Final Board\n\n```\n{board_final}\n```\n\n"
            f"## Move History\n\n"
        )
        for i, (player, pos) in enumerate(game_info["state"].get("moves", []), 1):
            content += f"{i}. {player} → {pos}\n"

        try:
            path = f"recreation/games/{game_info['game_type']}/{game_info['game_id']}.md"
            await self._records_store.write_entry(
                author="system",
                path=path,
                content=content,
                message=f"AD-526a: Game record {game_info['game_id']}",
                classification="ship",
                tags=["game", game_info["game_type"]],
            )
        except Exception:
            logger.debug("AD-526a: Failed to record game to Ship's Records", exc_info=True)
```

### 6. GAME_COMPLETED Event Type

**File:** `src/probos/events.py`, in the `EventType` enum

Add a new event type for game completion:

```python
GAME_COMPLETED = "game_completed"  # AD-526a: Game finished
```

Add it in the appropriate alphabetical position near other social/Ward Room events.

### 7. Challenge Action Extraction + Game Move Handling

**File:** `src/probos/proactive.py`, method `_extract_and_execute_actions()` (after the Notebook writes section, around line 1600)

Add a new section for CHALLENGE extraction:

```python
# --- Game Challenges (AD-526a) ---
if rank.value != Rank.ENSIGN.value:
    text, challenge_actions = await self._extract_and_execute_challenges(agent, text)
    actions_executed.extend(challenge_actions)
```

**New method on `ProactiveCognitiveLoop`:**

```python
async def _extract_and_execute_challenges(
    self, agent: Any, text: str,
) -> tuple[str, list[dict]]:
    """AD-526a: Extract [CHALLENGE @callsign game_type] and create games."""
    import re
    rt = self._runtime
    actions: list[dict] = []

    if not hasattr(rt, 'recreation_service') or not rt.recreation_service:
        return text, actions

    pattern = re.compile(
        r'\[CHALLENGE\s+@?(\S+)\s+(\S+)\]',
        re.IGNORECASE,
    )

    for match in pattern.finditer(text):
        target_callsign = match.group(1)
        game_type = match.group(2).lower()

        # Resolve challenger callsign
        challenger_callsign = ""
        if hasattr(rt, 'callsign_registry'):
            challenger_callsign = rt.callsign_registry.get_callsign(agent.agent_type)
        if not challenger_callsign:
            challenger_callsign = agent.agent_type

        # Don't challenge yourself
        if target_callsign.lower() == challenger_callsign.lower():
            continue

        # Find Recreation channel
        channels = await rt.ward_room.list_channels()
        rec_channel = None
        for ch in channels:
            if ch.name == "Recreation" and ch.channel_type == "ship":
                rec_channel = ch
                break
        if not rec_channel:
            continue

        try:
            # Create the game
            game_info = await rt.recreation_service.create_game(
                game_type=game_type,
                challenger=challenger_callsign,
                opponent=target_callsign,
            )

            # Post challenge thread in Recreation channel
            board = rt.recreation_service.render_board(game_info["game_id"])
            valid_moves = rt.recreation_service.get_valid_moves(game_info["game_id"])

            thread = await rt.ward_room.create_thread(
                channel_id=rec_channel.id,
                author_id=agent.id,
                title=f"[Game] {challenger_callsign} challenges {target_callsign} to {game_type}!",
                body=(
                    f"@{target_callsign}, you've been challenged to a game of "
                    f"{game_type} by @{challenger_callsign}!\n\n"
                    f"**Current board:**\n```\n{board}\n```\n\n"
                    f"@{target_callsign}'s turn. Valid moves: {', '.join(valid_moves)}\n\n"
                    f"Reply with `[MOVE position]` to make your move."
                ),
                author_callsign=challenger_callsign,
            )

            # Link thread to game
            if thread:
                game_info["thread_id"] = thread.id
                rt.recreation_service._thread_games[thread.id] = game_info["game_id"]

            actions.append({
                "type": "challenge",
                "game_type": game_type,
                "target": target_callsign,
                "game_id": game_info["game_id"],
            })
            logger.info(
                "AD-526a: %s challenged %s to %s (game %s)",
                challenger_callsign, target_callsign, game_type, game_info["game_id"],
            )

        except ValueError as e:
            logger.debug("AD-526a: Challenge failed: %s", e)
        except Exception as e:
            logger.warning("AD-526a: Challenge error: %s", e)

    # Clean matched tags from text
    text = pattern.sub("", text).strip()
    return text, actions
```

### 8. Game Move Handling via Ward Room Notifications

**File:** `src/probos/ward_room_router.py`, in the notification dispatch path

When a `ward_room_notification` arrives on a game thread, the WardRoomRouter already dispatches it to subscribed agents. The agent's LLM response may contain `[MOVE position]`.

**New method on `ProactiveCognitiveLoop`** — add to the `_extract_and_execute_actions()` flow:

```python
# --- Game Moves (AD-526a) ---
text, move_actions = await self._extract_and_execute_game_moves(agent, text)
actions_executed.extend(move_actions)
```

```python
async def _extract_and_execute_game_moves(
    self, agent: Any, text: str,
) -> tuple[str, list[dict]]:
    """AD-526a: Extract [MOVE position] from responses in game threads."""
    import re
    rt = self._runtime
    actions: list[dict] = []

    if not hasattr(rt, 'recreation_service') or not rt.recreation_service:
        return text, actions

    pattern = re.compile(r'\[MOVE\s+(\S+)\]', re.IGNORECASE)

    for match in pattern.finditer(text):
        move_str = match.group(1)

        # Get agent's callsign
        callsign = ""
        if hasattr(rt, 'callsign_registry'):
            callsign = rt.callsign_registry.get_callsign(agent.agent_type)
        if not callsign:
            callsign = agent.agent_type

        # Find which game this agent is in
        # Look through active games for one involving this player whose turn it is
        for game_info in rt.recreation_service.get_active_games():
            state = game_info.get("state", {})
            if state.get("current_player") != callsign:
                continue
            if callsign not in (game_info.get("challenger"), game_info.get("opponent")):
                continue

            try:
                updated = await rt.recreation_service.make_move(
                    game_info["game_id"], callsign, move_str,
                )

                # Post updated board to game thread
                thread_id = updated.get("thread_id")
                if thread_id and rt.ward_room:
                    engine = rt.recreation_service._engines[updated["game_type"]]
                    board = engine.render_board(updated["state"])

                    if engine.is_finished(updated["state"]):
                        result = engine.get_result(updated["state"])
                        if result["status"] == "won":
                            body = (
                                f"@{callsign} plays {move_str}!\n\n"
                                f"```\n{board}\n```\n\n"
                                f"**{result['winner']} wins!** Good game."
                            )
                        else:
                            body = (
                                f"@{callsign} plays {move_str}!\n\n"
                                f"```\n{board}\n```\n\n"
                                f"**It's a draw!** Well played."
                            )
                    else:
                        next_player = updated["state"]["current_player"]
                        valid = engine.get_valid_moves(updated["state"])
                        body = (
                            f"@{callsign} plays {move_str}.\n\n"
                            f"```\n{board}\n```\n\n"
                            f"@{next_player}'s turn. Valid moves: {', '.join(valid)}"
                        )

                    await rt.ward_room.create_post(
                        thread_id=thread_id,
                        author_id=agent.id,
                        body=body,
                        author_callsign=callsign,
                    )

                actions.append({
                    "type": "game_move",
                    "game_id": game_info["game_id"],
                    "move": move_str,
                })
                logger.info(
                    "AD-526a: %s played %s in game %s",
                    callsign, move_str, game_info["game_id"],
                )
                break  # Only handle one game per [MOVE]

            except ValueError as e:
                logger.debug("AD-526a: Invalid move: %s", e)
            except Exception as e:
                logger.warning("AD-526a: Game move error: %s", e)

    text = pattern.sub("", text).strip()
    return text, actions
```

### 9. Runtime Wiring

**File:** `src/probos/runtime.py`

Add `recreation_service` attribute. In the constructor (near other service attributes):

```python
self.recreation_service: RecreationService | None = None
```

**File:** `src/probos/startup/cognitive_services.py` (or whichever startup module initializes runtime services)

After Ward Room and Records Store are initialized, create the RecreationService:

```python
# AD-526a: Recreation service
from probos.recreation.service import RecreationService
runtime.recreation_service = RecreationService(
    ward_room=runtime.ward_room,
    records_store=runtime._records_store,
    emit_event_fn=runtime._emit_event_fn,
)
```

Find the appropriate location in the startup sequence — it needs Ward Room and Records Store to be ready. Check existing patterns for service initialization order.

## Files Summary

| File | Change |
|---|---|
| `src/probos/recreation/__init__.py` | New — package init |
| `src/probos/recreation/engine.py` | New — GameEngine protocol + TicTacToeEngine |
| `src/probos/recreation/service.py` | New — RecreationService |
| `src/probos/ward_room/channels.py` | Add Recreation + Creative to `_ensure_default_channels()` |
| `src/probos/startup/communication.py` | Auto-subscribe crew to Recreation + Creative |
| `src/probos/proactive.py` | `_gather_context()` Recreation activity, `_extract_and_execute_challenges()`, `_extract_and_execute_game_moves()` |
| `src/probos/cognitive/cognitive_agent.py` | CHALLENGE in proactive available actions |
| `src/probos/events.py` | GAME_COMPLETED event type |
| `src/probos/runtime.py` | `recreation_service` attribute |
| `src/probos/startup/cognitive_services.py` | RecreationService initialization |

**Total: 3 new files, 7 modified files.**

## Test Requirements

### File: `tests/test_recreation_engine.py`

**TicTacToeEngine tests (12 tests):**

1. **test_new_game** — Verify initial state: empty board, player_a is current_player, status in_progress.
2. **test_make_move** — Valid move updates board and switches turn.
3. **test_make_move_invalid_position** — Position out of range raises ValueError.
4. **test_make_move_occupied** — Move to occupied square raises ValueError.
5. **test_make_move_wrong_turn** — Wrong player raises ValueError.
6. **test_make_move_game_finished** — Move after game over raises ValueError.
7. **test_win_detection_row** — Three in a row detected as win.
8. **test_win_detection_col** — Three in a column detected as win.
9. **test_win_detection_diagonal** — Diagonal win detected.
10. **test_draw_detection** — Full board with no winner is draw.
11. **test_render_board** — ASCII board output format correct, empty cells show position numbers.
12. **test_get_valid_moves** — Returns only unoccupied positions.

### File: `tests/test_recreation_service.py`

**RecreationService tests (12 tests, async):**

13. **test_register_engine** — TicTacToe registered by default, available_games includes it.
14. **test_create_game** — Creates game with correct state, players, game_id.
15. **test_create_game_unknown_type** — Unknown game type raises ValueError.
16. **test_make_move** — Valid move updates game state.
17. **test_make_move_game_not_found** — Invalid game_id raises ValueError.
18. **test_game_completion** — Game removed from active after completion.
19. **test_get_game_by_thread** — Thread ID lookup returns correct game.
20. **test_get_active_games** — Lists all in-progress games.
21. **test_render_board** — Delegates to engine render.
22. **test_get_valid_moves** — Delegates to engine valid moves.
23. **test_game_record_to_records_store** — Mock records_store, verify `write_entry` called with correct path and content on game completion.
24. **test_game_completed_event** — Mock emit function, verify GAME_COMPLETED event emitted on finish.

### File: `tests/test_recreation_channels.py`

**Channel and proactive integration tests (8 tests, async):**

25. **test_default_channels_include_recreation** — After `_ensure_default_channels()`, Recreation and Creative channels exist.
26. **test_default_channels_are_ship_type** — Both channels have channel_type "ship".
27. **test_default_channels_idempotent** — Calling `_ensure_default_channels()` twice doesn't create duplicates.
28. **test_crew_subscribed_to_recreation** — After startup, a crew agent is subscribed to Recreation channel.
29. **test_crew_subscribed_to_creative** — After startup, a crew agent is subscribed to Creative channel.
30. **test_challenge_action_extraction** — Text with `[CHALLENGE @Forge tictactoe]` creates a game and posts to Recreation.
31. **test_challenge_self_rejected** — Challenging yourself is silently skipped.
32. **test_move_action_extraction** — Text with `[MOVE 4]` applies move to active game.

**Total: 32 tests.**

## Verification

After building:

```bash
uv run pytest tests/test_recreation_engine.py tests/test_recreation_service.py tests/test_recreation_channels.py -v
```

Then run the full proactive/ward_room test suites to ensure no regressions:

```bash
uv run pytest tests/test_proactive*.py tests/test_ward_room*.py tests/test_channel*.py -v
```

## Principles Compliance

- **SOLID (S):** GameEngine = game rules (stateless). RecreationService = game lifecycle. ProactiveCognitiveLoop = action extraction. Clean separation.
- **SOLID (O):** Open for extension — new games register via `register_engine()`. Protocol-based — any class satisfying `GameEngine` protocol works.
- **SOLID (I):** GameEngine protocol is minimal (7 methods). RecreationService depends on the protocol, not specific implementations.
- **DRY:** Channel creation follows existing pattern. Action extraction follows DM/NOTEBOOK pattern. Event emission follows existing WARD_ROOM_POST_CREATED pattern.
- **Fail Fast:** Invalid moves raise ValueError. Unknown game types raise ValueError. Missing services return gracefully.
- **Law of Demeter:** RecreationService accesses Ward Room and Records Store via public APIs. No private member patching.
- **Cloud-Ready:** No direct SQLite. Game state in memory (active games are transient). Completed games persist to Ship's Records (Git-backed).
