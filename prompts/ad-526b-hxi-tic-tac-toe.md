# AD-526b: HXI Tic-Tac-Toe — Captain vs Crew Graphical Game Panel

## What This Builds

A graphical tic-tac-toe panel in the HXI so the Captain can challenge and play against any crew agent. Captain moves are instant via REST API; agent moves arrive in real-time via WebSocket when the agent completes their proactive cycle.

Also fixes **BF-111**: `proactive.py` calls `rt.ward_room.post_message()` and `rt.ward_room.reply_to_thread()` which don't exist on `WardRoomService`. The correct methods are `create_thread()` and `create_post()`. Game challenge threads and board update posts have been silently failing since AD-526a.

## Architecture

```
Captain clicks cell → POST /api/recreation/move → RecreationService.make_move()
                                                        ↓ emits GAME_UPDATE
                                                  WebSocket → HXI store → board updates

Agent's proactive cycle → BF-110 sees board → [MOVE pos] → RecreationService.make_move()
                                                                  ↓ emits GAME_UPDATE
                                                            WebSocket → HXI board updates
```

## Files to Create

### 1. `src/probos/routers/recreation.py` — REST router

Follow `routers/wardroom.py` pattern exactly. Use `APIRouter(prefix="/api/recreation", tags=["recreation"])`. Import `get_runtime` and `get_ws_broadcast` from `routers/deps.py`.

#### `POST /api/recreation/challenge`

Accept JSON body `{"opponent_agent_id": str, "game_type": "tictactoe"}`.

```python
from fastapi import APIRouter, Depends, HTTPException
from probos.routers.deps import get_runtime, get_ws_broadcast
import time, logging

router = APIRouter(prefix="/api/recreation", tags=["recreation"])
logger = logging.getLogger(__name__)

@router.post("/challenge")
async def challenge_agent(body: dict, runtime=Depends(get_runtime), broadcast=Depends(get_ws_broadcast)):
    opponent_id = body.get("opponent_agent_id", "")
    game_type = body.get("game_type", "tictactoe")

    rec_svc = getattr(runtime, 'recreation_service', None)
    if not rec_svc:
        raise HTTPException(status_code=503, detail="Recreation service not available")

    # Resolve agent ID to callsign
    # Agent registry is runtime._agent_registry (dict of agent_type -> agent instance)
    # We need to find the agent by its .id property, then get its callsign
    target_agent = None
    for agent in runtime._agent_registry.values():
        if agent.id == opponent_id:
            target_agent = agent
            break
    if not target_agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    callsign = ""
    if hasattr(runtime, 'callsign_registry'):
        callsign = runtime.callsign_registry.get_callsign(target_agent.agent_type)
    if not callsign:
        raise HTTPException(status_code=400, detail="Agent has no callsign — only crew agents can be challenged")

    # Find Recreation channel
    thread_id = ""
    try:
        channels = await runtime.ward_room.list_channels()
        rec_ch = next((c for c in channels if c.name == "Recreation"), None)
        if rec_ch:
            thread = await runtime.ward_room.create_thread(
                channel_id=rec_ch.id,
                author_id="captain",
                title=f"[Challenge] Captain challenges {callsign} to {game_type}!",
                body=f"The Captain has challenged {callsign} to a game of {game_type}.",
                author_callsign="Captain",
            )
            thread_id = thread.id
    except Exception:
        logger.debug("Ward Room thread creation failed for Captain challenge", exc_info=True)

    # Create game
    game = await rec_svc.create_game(game_type, "Captain", callsign, thread_id)
    state = game.get("state", {})
    board = state.get("board", [""] * 9)
    valid_moves = rec_svc.get_valid_moves(game["game_id"])

    result = {
        "game_id": game["game_id"],
        "game_type": game_type,
        "board": board,
        "current_player": state.get("current_player", "Captain"),
        "status": state.get("status", "in_progress"),
        "winner": "",
        "valid_moves": valid_moves,
        "moves_count": 0,
        "opponent": callsign,
        "opponent_agent_id": opponent_id,
        "thread_id": thread_id,
    }

    broadcast({"type": "game_update", "data": result, "timestamp": time.time()})
    return result
```

#### `POST /api/recreation/move`

Accept JSON body `{"game_id": str, "position": str}`.

```python
@router.post("/move")
async def make_move(body: dict, runtime=Depends(get_runtime), broadcast=Depends(get_ws_broadcast)):
    game_id = body.get("game_id", "")
    position = body.get("position", "")

    rec_svc = getattr(runtime, 'recreation_service', None)
    if not rec_svc:
        raise HTTPException(status_code=503, detail="Recreation service not available")

    try:
        game_info = await rec_svc.make_move(game_id, "Captain", position)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    state = game_info.get("state", {})
    board = state.get("board", [""] * 9)

    # Post board update to Ward Room thread
    thread_id = game_info.get("thread_id", "")
    if thread_id:
        try:
            board_text = rec_svc.render_board(game_id)
            status_text = state.get("status", "in_progress")
            if status_text == "won":
                msg = f"Game over! Winner: {state.get('winner', '?')}\n```\n{board_text}\n```"
            elif status_text == "draw":
                msg = f"Game over! Draw!\n```\n{board_text}\n```"
            else:
                msg = f"Captain played position {position}.\n```\n{board_text}\n```\nNext: {state.get('current_player', '?')}"
            await runtime.ward_room.create_post(
                thread_id=thread_id,
                author_id="captain",
                body=msg,
                author_callsign="Captain",
            )
        except Exception:
            logger.debug("Ward Room post failed for Captain move", exc_info=True)

    valid_moves = rec_svc.get_valid_moves(game_id) if state.get("status") == "in_progress" else []

    return {
        "board": board,
        "current_player": state.get("current_player", ""),
        "status": state.get("status", "in_progress"),
        "winner": state.get("winner", ""),
        "valid_moves": valid_moves,
        "moves_count": game_info.get("moves_count", 0),
    }
```

#### `GET /api/recreation/active`

```python
@router.get("/active")
async def get_active_game(runtime=Depends(get_runtime)):
    rec_svc = getattr(runtime, 'recreation_service', None)
    if not rec_svc:
        return {"game": None}

    for game in rec_svc.get_active_games():
        if "Captain" in [game.get("challenger"), game.get("opponent")]:
            state = game.get("state", {})
            board = state.get("board", [""] * 9)
            valid_moves = rec_svc.get_valid_moves(game["game_id"])
            opponent = game.get("opponent") if game.get("challenger") == "Captain" else game.get("challenger")
            return {
                "game": {
                    "game_id": game["game_id"],
                    "game_type": game.get("game_type", "tictactoe"),
                    "board": board,
                    "current_player": state.get("current_player", ""),
                    "status": state.get("status", "in_progress"),
                    "winner": state.get("winner", ""),
                    "valid_moves": valid_moves,
                    "moves_count": game.get("moves_count", 0),
                    "opponent": opponent,
                    "opponent_agent_id": "",
                    "thread_id": game.get("thread_id", ""),
                }
            }
    return {"game": None}
```

#### `POST /api/recreation/forfeit`

```python
@router.post("/forfeit")
async def forfeit_game(body: dict, runtime=Depends(get_runtime), broadcast=Depends(get_ws_broadcast)):
    game_id = body.get("game_id", "")

    rec_svc = getattr(runtime, 'recreation_service', None)
    if not rec_svc:
        raise HTTPException(status_code=503, detail="Recreation service not available")

    await rec_svc.forfeit_game(game_id, "Captain")

    broadcast({"type": "game_update", "data": {
        "game_id": game_id,
        "status": "forfeited",
        "board": [""] * 9,
        "current_player": "",
        "winner": "",
        "valid_moves": [],
        "moves_count": 0,
    }, "timestamp": time.time()})

    return {"status": "forfeited"}
```

---

### 2. `ui/src/components/GamePanel.tsx` — Floating game panel

Follow `AgentProfilePanel.tsx` pattern for the container (fixed-position, draggable title bar, glassmorphism). Match existing HXI styling exactly.

**Implementation guide:**

```tsx
import { useStore } from '../store/useStore';
import { useRef, useCallback, useState, useEffect } from 'react';

// Win line detection for highlighting
const WIN_LINES = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];
function findWinLine(board: string[]): number[] | null {
  for (const line of WIN_LINES) {
    const [a,b,c] = line;
    if (board[a] && board[a] === board[b] && board[b] === board[c]) return line;
  }
  return null;
}

export function GamePanel() {
  const game = useStore(s => s.activeGame);
  const pos = useStore(s => s.gamePanelPos);
  const makeMove = useStore(s => s.makeGameMove);
  const forfeit = useStore(s => s.forfeitGame);
  const closeGame = useStore(s => s.closeGame);
  const setPos = useStore(s => s.setGamePanelPos);

  // Dragging state (same pattern as AgentProfilePanel)
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragRef.current = { startX: e.clientX, startY: e.clientY, origX: pos.x, origY: pos.y };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      setPos({
        x: dragRef.current.origX + (ev.clientX - dragRef.current.startX),
        y: dragRef.current.origY + (ev.clientY - dragRef.current.startY),
      });
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [pos, setPos]);

  if (!game) return null;

  const isMyTurn = game.currentPlayer === 'Captain';
  const isFinished = game.status !== 'in_progress';
  const winLine = isFinished && game.status === 'won' ? findWinLine(game.board) : null;

  // ... render panel with:
  // Title bar: "Tic-Tac-Toe vs {game.opponent}" + X button (forfeit if in progress, close if finished)
  // Turn indicator pill
  // 3x3 CSS Grid board
  // Status bar with result + buttons
}
```

**Panel styling** (inline, matching HXI glassmorphism):
```typescript
const panelStyle: React.CSSProperties = {
  position: 'fixed',
  left: pos.x,
  top: pos.y,
  width: 340,
  zIndex: 30,
  background: 'rgba(10, 10, 18, 0.94)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  border: '1px solid rgba(240, 176, 96, 0.2)',
  borderRadius: 12,
  boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
  fontFamily: "'JetBrains Mono', monospace",
  color: '#e0dcd4',
  overflow: 'hidden',
};
```

**Title bar:**
```typescript
const titleBarStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '10px 14px',
  borderBottom: '1px solid rgba(255,255,255,0.06)',
  cursor: 'grab',
  userSelect: 'none',
};
```

**3×3 Board:**
```tsx
<div style={{
  display: 'grid',
  gridTemplateColumns: 'repeat(3, 1fr)',
  gap: 4,
  padding: 16,
}}>
  {game.board.map((cell, i) => {
    const isWinCell = winLine?.includes(i);
    const isEmpty = !cell;
    const canClick = isMyTurn && isEmpty && !isFinished;

    return (
      <button
        key={i}
        disabled={!canClick}
        onClick={() => makeMove(String(i))}
        style={{
          width: 80,
          height: 80,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: isWinCell
            ? 'rgba(240, 176, 96, 0.2)'
            : 'rgba(255, 255, 255, 0.03)',
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: 8,
          cursor: canClick ? 'pointer' : 'default',
          fontSize: cell ? 32 : 14,
          fontFamily: "'JetBrains Mono', monospace",
          fontWeight: cell ? 700 : 400,
          color: cell === 'X' ? '#50b0a0'      // teal for X (Captain)
               : cell === 'O' ? '#f0b060'      // amber for O (agent)
               : '#333848',                      // dim for position numbers
          opacity: isFinished && !isWinCell && winLine ? 0.4 : 1,
          boxShadow: isWinCell ? '0 0 16px rgba(240, 176, 96, 0.4)' : 'none',
          transition: 'all 200ms ease',
          // piece-pop animation: use a CSS class or style injection (see below)
        }}
      >
        {cell || String(i)}
      </button>
    );
  })}
</div>
```

**Piece-pop animation** — inject a `<style>` tag in the component:
```tsx
// Add this inside the component return, before the panel div:
<style>{`
  @keyframes piece-pop {
    0% { transform: scale(1.5); opacity: 0; }
    40% { transform: scale(0.85); opacity: 1; }
    70% { transform: scale(1.1); }
    100% { transform: scale(1.0); }
  }
  @media (prefers-reduced-motion: reduce) {
    .piece-animate { animation: none !important; }
  }
`}</style>
```

Apply `className="piece-animate"` and `style={{ animation: 'piece-pop 0.5s ease-out' }}` to cells that have a piece. Track which cell was just played (via `lastMove` in the game state or by comparing previous board to current) and only animate new pieces, not all pieces.

**Turn indicator:**
```tsx
<div style={{
  padding: '6px 12px',
  textAlign: 'center',
  fontSize: 12,
  color: isMyTurn ? '#f0b060' : '#6a6a7a',
  // Subtle pulse for waiting state
}}>
  {isFinished
    ? game.status === 'won'
      ? game.winner === 'Captain' ? 'You won!' : `${game.opponent} wins`
      : game.status === 'draw' ? 'Draw!' : 'Game forfeited'
    : isMyTurn ? '▶ Your turn' : `Waiting for ${game.opponent}...`
  }
</div>
```

For the "waiting" state, add a CSS animation:
```css
@keyframes pulse-dim {
  0%, 100% { opacity: 0.6; }
  50% { opacity: 1; }
}
```
Apply when `!isMyTurn && !isFinished`: `animation: 'pulse-dim 2s ease-in-out infinite'`.

**Post-game buttons:**
```tsx
{isFinished && (
  <div style={{ display: 'flex', gap: 8, padding: '0 16px 12px', justifyContent: 'center' }}>
    <button onClick={closeGame} style={/* ghost button style */}>Close</button>
  </div>
)}
```

**Forfeit button** — in title bar, show when game is in progress:
```tsx
{!isFinished && (
  <button onClick={forfeit} title="Forfeit" style={/* small X button */}>✕</button>
)}
{isFinished && (
  <button onClick={closeGame} title="Close" style={/* small X button */}>✕</button>
)}
```

---

## Files to Modify

### 3. `src/probos/events.py` — Add GAME_UPDATE event type

After line 133 (`GAME_COMPLETED = "game_completed"`), add:

```python
    GAME_UPDATE = "game_update"  # AD-526b: game state changed (move made)
```

### 4. `src/probos/recreation/service.py` — Emit GAME_UPDATE + forfeit method

**In `make_move()`**, after updating game state (after `game_info["state"] = new_state` around line 126), emit `GAME_UPDATE`:

```python
        # AD-526b: Emit game state update for HXI WebSocket
        if self._emit:
            try:
                from probos.events import EventType
                self._emit(EventType.GAME_UPDATE, {
                    "game_id": game_id,
                    "board": new_state["board"],
                    "current_player": new_state.get("current_player", ""),
                    "status": new_state["status"],
                    "winner": new_state.get("winner", ""),
                    "valid_moves": engine.get_valid_moves(new_state) if new_state["status"] == "in_progress" else [],
                    "moves_count": game_info["moves_count"],
                    "last_move": {"player": player, "position": move},
                    "thread_id": game_info.get("thread_id", ""),
                })
            except Exception:
                pass
```

**Add `forfeit_game()` method** to `RecreationService`:

```python
    async def forfeit_game(self, game_id: str, player: str) -> None:
        """Forfeit/abandon an active game."""
        game_info = self._active_games.get(game_id)
        if not game_info:
            return

        thread_id = game_info.get("thread_id", "")
        if thread_id and thread_id in self._thread_games:
            del self._thread_games[thread_id]
        del self._active_games[game_id]

        if self._emit:
            try:
                from probos.events import EventType
                self._emit(EventType.GAME_UPDATE, {
                    "game_id": game_id,
                    "status": "forfeited",
                    "board": [],
                    "current_player": "",
                    "winner": "",
                    "valid_moves": [],
                    "moves_count": 0,
                })
            except Exception:
                pass
```

### 5. `src/probos/api.py` — Register recreation router

At line 192-196, add `recreation` to the import:

```python
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, counselor, procedures, gaps,
        recreation,
    )
```

At line 197-201, add `recreation` to the for loop:

```python
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, counselor, procedures, gaps,
        recreation,
    ):
```

### 6. `ui/src/store/types.ts` — Add GameState interface

Add after the existing interfaces (find a suitable location, e.g., after `AgentProfileData`):

```typescript
// AD-526b: Recreation Game state (Captain vs Crew)
export interface GameState {
  gameId: string;
  gameType: string;
  board: string[];           // 9 cells: "" | "X" | "O"
  currentPlayer: string;     // callsign whose turn ("Captain" or agent callsign)
  status: 'in_progress' | 'won' | 'draw' | 'forfeited';
  winner: string;
  validMoves: string[];
  movesCount: number;
  opponent: string;          // agent callsign
  opponentAgentId: string;
  threadId: string;
}
```

### 7. `ui/src/store/useStore.ts` — Game state slice + WebSocket handler

**Add to the HXIState interface** (find it near line 182):

```typescript
  // AD-526b: Recreation Game (Captain vs Crew)
  activeGame: GameState | null;
  gamePanelPos: { x: number; y: number };
  challengeAgent: (agentId: string) => Promise<void>;
  makeGameMove: (position: string) => Promise<void>;
  forfeitGame: () => Promise<void>;
  closeGame: () => void;
  setGamePanelPos: (pos: { x: number; y: number }) => void;
```

Import `GameState` from `./types`.

**Add initial state values** (in the `create()` call):

```typescript
    activeGame: null,
    gamePanelPos: { x: 200, y: 120 },
```

**Add action implementations:**

```typescript
    challengeAgent: async (agentId: string) => {
      try {
        const resp = await fetch('/api/recreation/challenge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ opponent_agent_id: agentId, game_type: 'tictactoe' }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          console.warn('Challenge failed:', err.detail || resp.statusText);
          return;
        }
        const data = await resp.json();
        set({
          activeGame: {
            gameId: data.game_id,
            gameType: data.game_type || 'tictactoe',
            board: data.board || Array(9).fill(''),
            currentPlayer: data.current_player || 'Captain',
            status: data.status || 'in_progress',
            winner: data.winner || '',
            validMoves: data.valid_moves || [],
            movesCount: data.moves_count || 0,
            opponent: data.opponent || '',
            opponentAgentId: data.opponent_agent_id || agentId,
            threadId: data.thread_id || '',
          },
        });
      } catch (e) {
        console.warn('Challenge error:', e);
      }
    },

    makeGameMove: async (position: string) => {
      const game = get().activeGame;
      if (!game) return;
      try {
        const resp = await fetch('/api/recreation/move', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: game.gameId, position }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          console.warn('Move failed:', err.detail || resp.statusText);
          return;
        }
        const data = await resp.json();
        set({
          activeGame: {
            ...game,
            board: data.board || game.board,
            currentPlayer: data.current_player || '',
            status: data.status || game.status,
            winner: data.winner || '',
            validMoves: data.valid_moves || [],
            movesCount: data.moves_count || game.movesCount,
          },
        });
      } catch (e) {
        console.warn('Move error:', e);
      }
    },

    forfeitGame: async () => {
      const game = get().activeGame;
      if (!game) return;
      try {
        await fetch('/api/recreation/forfeit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ game_id: game.gameId }),
        });
      } catch { /* swallow */ }
      set({ activeGame: null });
    },

    closeGame: () => {
      set({ activeGame: null });
    },

    setGamePanelPos: (pos) => {
      set({ gamePanelPos: pos });
    },
```

**Add WebSocket handler** — find the `handleEvent` function's switch/case block and add:

```typescript
      case 'game_update': {
        const game = get().activeGame;
        const d = data as Record<string, unknown>;
        if (game && d.game_id === game.gameId) {
          set({
            activeGame: {
              ...game,
              board: (d.board as string[]) || game.board,
              currentPlayer: (d.current_player as string) || '',
              status: (d.status as GameState['status']) || game.status,
              winner: (d.winner as string) || '',
              validMoves: (d.valid_moves as string[]) || [],
              movesCount: (d.moves_count as number) || game.movesCount,
            },
          });
        }
        break;
      }
```

**Add rehydration** — in the `state_snapshot` handler (find it in handleEvent), after the main hydration, add:

```typescript
      // AD-526b: Rehydrate active game on page refresh
      try {
        const gameResp = await fetch('/api/recreation/active');
        if (gameResp.ok) {
          const gameData = await gameResp.json();
          if (gameData.game) {
            const g = gameData.game;
            set({
              activeGame: {
                gameId: g.game_id,
                gameType: g.game_type || 'tictactoe',
                board: g.board || Array(9).fill(''),
                currentPlayer: g.current_player || '',
                status: g.status || 'in_progress',
                winner: g.winner || '',
                validMoves: g.valid_moves || [],
                movesCount: g.moves_count || 0,
                opponent: g.opponent || '',
                opponentAgentId: g.opponent_agent_id || '',
                threadId: g.thread_id || '',
              },
            });
          }
        }
      } catch { /* swallow */ }
```

Note: The `state_snapshot` handler may need to become async if it isn't already. If it is not async, use a fire-and-forget pattern instead: `fetch('/api/recreation/active').then(r => r.json()).then(data => { if (data.game) { set({...}) } }).catch(() => {})`.

### 8. `ui/src/components/profile/ProfileInfoTab.tsx` — Challenge button

After the Recent Communications section (before the closing `</div>` at line 183), add:

```tsx
      {/* AD-526b: Challenge to game */}
      {agent.isCrew && (
        <div style={{ marginTop: 12, paddingTop: 8, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <button
            onClick={() => useStore.getState().challengeAgent(agent.id)}
            disabled={!!useStore(s => s.activeGame)}
            style={{
              width: '100%',
              padding: '8px 0',
              background: 'rgba(240, 176, 96, 0.1)',
              border: '1px solid rgba(240, 176, 96, 0.25)',
              borderRadius: 6,
              color: '#f0b060',
              fontSize: 12,
              fontFamily: "'JetBrains Mono', monospace",
              cursor: 'pointer',
              fontWeight: 500,
              letterSpacing: 0.5,
              opacity: useStore.getState().activeGame ? 0.4 : 1,
            }}
          >
            Challenge to Tic-Tac-Toe
          </button>
        </div>
      )}
```

Note: The `disabled` check needs to be reactive. Use `useStore(s => s.activeGame)` as a hook at the top of the component, not `.getState()` inline. The `onClick` can use `.getState()` since it's an event handler. Example:

```tsx
export function ProfileInfoTab({ profileData, agent }: Props) {
  // ... existing hooks ...
  const activeGame = useStore(s => s.activeGame);
  const challengeAgent = useStore(s => s.challengeAgent);

  // ... existing render ...

  // In the JSX:
  {agent.isCrew && (
    <div style={{ marginTop: 12, paddingTop: 8, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
      <button
        onClick={() => challengeAgent(agent.id)}
        disabled={!!activeGame}
        style={{
          width: '100%',
          padding: '8px 0',
          background: activeGame ? 'rgba(100, 100, 100, 0.1)' : 'rgba(240, 176, 96, 0.1)',
          border: `1px solid ${activeGame ? 'rgba(100, 100, 100, 0.15)' : 'rgba(240, 176, 96, 0.25)'}`,
          borderRadius: 6,
          color: activeGame ? '#666' : '#f0b060',
          fontSize: 12,
          fontFamily: "'JetBrains Mono', monospace",
          cursor: activeGame ? 'default' : 'pointer',
          fontWeight: 500,
          letterSpacing: 0.5,
        }}
      >
        {activeGame ? 'Game in progress...' : 'Challenge to Tic-Tac-Toe'}
      </button>
    </div>
  )}
```

### 9. `ui/src/App.tsx` — Mount GamePanel

Import and add alongside other floating panels (near `AgentProfilePanel`):

```tsx
import { GamePanel } from './components/GamePanel';

// In the JSX, alongside AgentProfilePanel:
<GamePanel />
```

### 10. BF-111 Fix: `src/probos/proactive.py` — Ward Room API mismatch

**CHALLENGE section (lines ~1880-1908):**

Replace the `post_message` call. Before the challenge action block, find the Recreation channel:

```python
                        # Find Recreation channel
                        rec_channel = None
                        try:
                            channels = await rt.ward_room.list_channels()
                            rec_channel = next((c for c in channels if c.name == "Recreation"), None)
                        except Exception:
                            logger.debug("AD-526a: Failed to find Recreation channel", exc_info=True)
```

Replace `rt.ward_room.post_message(...)` (the call that creates the game thread) with:

```python
                        thread_id = ""
                        if rec_channel:
                            try:
                                thread = await rt.ward_room.create_thread(
                                    channel_id=rec_channel.id,
                                    author_id=agent.id,
                                    title=f"[Challenge] {callsign} challenges {target_callsign} to {game_type}!",
                                    body=f"{callsign} has challenged {target_callsign} to a game of {game_type}.",
                                    author_callsign=callsign,
                                )
                                thread_id = thread.id
                            except Exception:
                                logger.debug("AD-526a: Ward Room thread creation failed", exc_info=True)
```

Then pass `thread_id` to `create_game()`.

**MOVE section (lines ~1948-1955):**

Replace `rt.ward_room.reply_to_thread(...)` with:

```python
                            try:
                                await rt.ward_room.create_post(
                                    thread_id=game_info["thread_id"],
                                    author_id=agent.id,
                                    body=board_msg,
                                    author_callsign=callsign,
                                )
                            except Exception:
                                logger.debug("AD-526a: Ward Room board post failed", exc_info=True)
```

Where `board_msg` is the board text already constructed earlier in the MOVE handler.

---

## Tests

### `tests/test_recreation_router.py`

```python
"""Tests for AD-526b: Recreation API router."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_runtime():
    rt = MagicMock()
    rt.recreation_service = MagicMock()
    rt.ward_room = AsyncMock()
    rt.callsign_registry = MagicMock()
    rt._agent_registry = {}
    return rt


class TestChallengeEndpoint:
    """POST /api/recreation/challenge"""

    async def test_challenge_creates_game(self, mock_runtime):
        """Challenge creates game and returns state."""
        # Setup: mock agent in registry
        agent = MagicMock()
        agent.id = "test-agent-id"
        agent.agent_type = "science_officer"
        mock_runtime._agent_registry = {"science_officer": agent}
        mock_runtime.callsign_registry.get_callsign.return_value = "Lynx"
        mock_runtime.ward_room.list_channels.return_value = [
            MagicMock(id="rec-ch", name="Recreation"),
        ]
        mock_runtime.ward_room.create_thread.return_value = MagicMock(id="thread-1")
        mock_runtime.recreation_service.create_game = AsyncMock(return_value={
            "game_id": "game-1",
            "state": {"board": [""] * 9, "current_player": "Captain", "status": "in_progress"},
        })
        mock_runtime.recreation_service.get_valid_moves.return_value = ["0","1","2","3","4","5","6","7","8"]
        # Test should verify the endpoint returns proper game state

    async def test_challenge_rejects_non_crew(self, mock_runtime):
        """Challenge rejects agents without callsigns (non-crew)."""
        agent = MagicMock()
        agent.id = "infra-id"
        agent.agent_type = "vitals_monitor"
        mock_runtime._agent_registry = {"vitals_monitor": agent}
        mock_runtime.callsign_registry.get_callsign.return_value = ""
        # Should return 400

    async def test_challenge_rejects_unknown_agent(self, mock_runtime):
        """Challenge rejects unknown agent IDs."""
        mock_runtime._agent_registry = {}
        # Should return 404


class TestMoveEndpoint:
    """POST /api/recreation/move"""

    async def test_move_updates_board(self, mock_runtime):
        """Valid move updates board and returns new state."""
        mock_runtime.recreation_service.make_move = AsyncMock(return_value={
            "state": {"board": ["X","","","","","","","",""], "current_player": "Lynx", "status": "in_progress"},
            "thread_id": "t-1",
            "moves_count": 1,
        })
        mock_runtime.recreation_service.render_board.return_value = " X | 1 | 2 \n---+---+---\n 3 | 4 | 5 \n---+---+---\n 6 | 7 | 8 "
        mock_runtime.recreation_service.get_valid_moves.return_value = ["1","2","3","4","5","6","7","8"]

    async def test_move_rejects_invalid(self, mock_runtime):
        """Invalid move returns 400."""
        mock_runtime.recreation_service.make_move = AsyncMock(side_effect=ValueError("Not your turn"))
        # Should return 400


class TestActiveEndpoint:
    """GET /api/recreation/active"""

    async def test_active_returns_captain_game(self, mock_runtime):
        """Returns Captain's active game."""
        mock_runtime.recreation_service.get_active_games.return_value = [
            {"game_id": "g-1", "challenger": "Captain", "opponent": "Lynx", "state": {"board": ["X","O","","","","","","",""], "current_player": "Captain", "status": "in_progress"}, "game_type": "tictactoe", "moves_count": 2},
        ]
        mock_runtime.recreation_service.get_valid_moves.return_value = ["2","3","4","5","6","7","8"]

    async def test_active_returns_null_when_no_game(self, mock_runtime):
        """Returns null game when no active game."""
        mock_runtime.recreation_service.get_active_games.return_value = []
        # Should return {"game": None}


class TestForfeitEndpoint:
    """POST /api/recreation/forfeit"""

    async def test_forfeit_removes_game(self, mock_runtime):
        """Forfeit removes game and broadcasts event."""
        mock_runtime.recreation_service.forfeit_game = AsyncMock()


class TestGameUpdateEmission:
    """RecreationService emits GAME_UPDATE on moves."""

    async def test_move_emits_game_update(self):
        """make_move() emits GAME_UPDATE event."""
        # Create real RecreationService with mock emit
        from probos.recreation.service import RecreationService
        from probos.recreation.engine import TicTacToeEngine

        emit_fn = MagicMock()
        svc = RecreationService(emit_event_fn=emit_fn)
        svc.register_engine(TicTacToeEngine())

        game = await svc.create_game("tictactoe", "Captain", "Lynx")
        game_id = game["game_id"]

        await svc.make_move(game_id, "Captain", "4")

        # Verify GAME_UPDATE was emitted
        assert emit_fn.called
        call_args = emit_fn.call_args
        # First arg is EventType, second is data dict
        event_data = call_args[0][1]
        assert event_data["game_id"] == game_id
        assert event_data["board"][4] == "X"
        assert event_data["current_player"] == "Lynx"


class TestForfeitMethod:
    """RecreationService.forfeit_game()"""

    async def test_forfeit_removes_from_active(self):
        """forfeit_game() removes game from active games."""
        from probos.recreation.service import RecreationService
        from probos.recreation.engine import TicTacToeEngine

        svc = RecreationService()
        svc.register_engine(TicTacToeEngine())

        game = await svc.create_game("tictactoe", "Captain", "Lynx")
        game_id = game["game_id"]

        assert len(svc.get_active_games()) == 1
        await svc.forfeit_game(game_id, "Captain")
        assert len(svc.get_active_games()) == 0
```

Write real, executable pytest tests following these patterns. Aim for ~15 tests covering:
- Challenge: success, non-crew rejection, unknown agent, no recreation service
- Move: success, invalid move, game over result
- Active: with game, without game
- Forfeit: removes game, broadcasts event
- GAME_UPDATE emission on moves
- forfeit_game() method

### `ui/src/__tests__/GamePanel.test.tsx` (optional)

If time permits, add Vitest tests for the GamePanel component:
- Renders nothing when activeGame is null
- Renders 9 cells when game is active
- Cells clickable only when Captain's turn
- Correct symbols and colors for X/O
- Win line cells get glow styling

---

## Verification Checklist

1. `cd ui && npm run build` — TypeScript compiles clean, no errors
2. `pytest tests/test_recreation_router.py -v` — all tests pass
3. `pytest tests/test_recreation_service.py tests/test_recreation_engine.py -v` — existing tests still pass
4. Manual test flow:
   a. Start ProbOS
   b. Open HXI, click a crew agent in 3D view to open profile
   c. See "Challenge to Tic-Tac-Toe" button at bottom of Profile tab
   d. Click it → GamePanel appears with empty 3×3 board
   e. Click a cell → X appears with pop animation, status changes to "Waiting for {opponent}..."
   f. Wait for agent's proactive cycle → O appears via WebSocket event
   g. Continue until game ends → winning cells glow, result shown
   h. Check Recreation channel in Ward Room → game thread with moves
5. Page refresh mid-game → game rehydrates from `/api/recreation/active`
6. Forfeit mid-game → panel closes, game removed
