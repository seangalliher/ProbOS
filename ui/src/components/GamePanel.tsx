/* AD-526b: Floating Tic-Tac-Toe game panel — Captain vs Crew */

import { useStore } from '../store/useStore';
import { useRef, useCallback, useState, useEffect } from 'react';
import { Close, PlayArrow } from './icons/Glyphs';

const TURN_REASONS: Record<string, string> = {
  deadline_expired: 'Opponent turn timed out. Retry when ready.',
  actor_unavailable: 'Opponent is unavailable. Retry or forfeit.',
  dispatch_rejected: 'Opponent turn was not admitted. Retry when ready.',
  dispatch_failed: 'Opponent turn could not be delivered. Retry when ready.',
  dispatcher_unavailable: 'Turn delivery is unavailable. Retry or forfeit.',
  invalid_move: 'Opponent returned an invalid move. Retry the turn.',
  no_usable_move: 'Opponent returned no move. Retry the turn.',
  cognitive_failed: 'Opponent could not process the turn. Retry when ready.',
  cognitive_cancelled: 'Opponent turn was interrupted. Retry when ready.',
  service_stopped: 'Recreation has stopped. Reconnect to refresh.',
};

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
  const retry = useStore(s => s.retryGame);
  const pending = useStore(s => s.gamePending);
  const error = useStore(s => s.gameError);
  const syncing = useStore(s => s.gameSyncing);
  const connected = useStore(s => s.connected);
  const forfeit = useStore(s => s.forfeitGame);
  const closeGame = useStore(s => s.closeGame);
  const setPos = useStore(s => s.setGamePanelPos);
  const board = game?.gameType === 'tictactoe' && game.board.every((cell): cell is string => typeof cell === 'string')
    ? game.board : null;

  // Track previous board to animate only new pieces
  const [prevBoard, setPrevBoard] = useState<string[]>(Array(9).fill(''));
  useEffect(() => {
    if (board) {
      // Delay updating prevBoard so the new piece animates first
      const timer = setTimeout(() => setPrevBoard([...board]), 600);
      return () => clearTimeout(timer);
    }
  }, [board?.join(',')]);

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

  if ((!game && !error && !pending) || (game && game.gameType !== 'tictactoe')) return null;

  const isMyTurn = game?.currentPlayer === 'Captain';
  const isFinished = !!game && game.status !== 'in_progress';
  const busy = pending !== null || syncing || !connected;
  const recoverable = !isFinished && !isMyTurn && game?.opponentTurnStatus === 'recoverable';
  const thinking = !isFinished && game?.opponentTurnStatus === 'thinking';
  const winLine = game?.status === 'won' && board ? findWinLine(board) : null;
  const status = isFinished
    ? game.status === 'won'
      ? game.winner === 'Captain' ? 'You won!' : `${game.opponent} wins`
      : game.status === 'draw' ? 'Draw!' : 'Game forfeited'
    : !connected ? 'Disconnected. Waiting to reconnect.'
    : syncing ? 'Refreshing game...'
    : pending === 'challenge' ? 'Sending challenge...'
    : pending === 'forfeit' ? 'Forfeiting game...'
    : pending === 'retry' ? 'Requesting another attempt...'
    : pending === 'move' && isMyTurn ? 'Submitting move...'
    : recoverable ? TURN_REASONS[game.opponentTurnReason] || 'Opponent could not complete the turn. Retry or forfeit.'
    : isMyTurn ? 'Your turn'
    : thinking ? `${game?.opponent} is thinking...`
    : game?.opponentTurnStatus === 'queued' ? `Turn queued for ${game.opponent}.`
    : 'Waiting for game state.';

  const panelStyle: React.CSSProperties = {
    position: 'fixed',
    left: `clamp(8px, ${pos.x}px, max(8px, calc(100vw - 348px)))`,
    top: `clamp(8px, ${pos.y}px, max(8px, calc(100dvh - 480px)))`,
    width: 'min(340px, calc(100vw - 16px))',
    maxHeight: 'calc(100dvh - 16px)',
    boxSizing: 'border-box',
    zIndex: 30,
    background: 'rgba(10, 10, 18, 0.94)',
    backdropFilter: 'blur(16px)',
    WebkitBackdropFilter: 'blur(16px)',
    border: '1px solid rgba(240, 176, 96, 0.2)',
    borderRadius: 12,
    boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    fontFamily: "'JetBrains Mono', monospace",
    color: '#e0dcd4',
    overflow: 'auto',
    overflowWrap: 'anywhere',
  };

  const titleBarStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 14px',
    borderBottom: '1px solid rgba(255,255,255,0.06)',
    cursor: 'grab',
    userSelect: 'none',
  };

  const closeBtnStyle: React.CSSProperties = {
    background: 'none',
    border: 'none',
    color: '#8888a0',
    cursor: 'pointer',
    fontSize: 14,
    padding: '2px 6px',
    borderRadius: 4,
    lineHeight: 1,
    width: 36,
    height: 36,
    flexShrink: 0,
  };

  return (
    <>
      <style>{`
        @keyframes piece-pop {
          0% { transform: scale(1.5); opacity: 0; }
          40% { transform: scale(0.85); opacity: 1; }
          70% { transform: scale(1.1); }
          100% { transform: scale(1.0); }
        }
        @keyframes pulse-dim {
          0%, 100% { opacity: 0.6; }
          50% { opacity: 1; }
        }
        .game-panel button:focus-visible {
          outline: 2px solid #f0b060;
          outline-offset: 2px;
        }
        .game-panel button:disabled { color: #666680; cursor: default; }
        .game-panel button:not(:disabled):hover { filter: drop-shadow(0 0 4px rgba(240,176,96,0.4)); }
        @media (prefers-reduced-motion: reduce) {
          .game-panel * { animation: none !important; }
        }
      `}</style>
      <section className="game-panel" aria-label="Tic-Tac-Toe game" style={panelStyle}>
        {/* Title bar */}
        <div style={titleBarStyle} onMouseDown={onMouseDown}>
          <span style={{ fontSize: 12, fontWeight: 600, minWidth: 0 }}>
            Tic-Tac-Toe{game ? ` vs ${game.opponent}` : ''}
          </span>
          {game && !isFinished ? (
            <button onMouseDown={event => event.stopPropagation()} onClick={forfeit}
              disabled={busy} aria-label="Forfeit game" title="Forfeit game" style={closeBtnStyle}><Close size={14} /></button>
          ) : (
            <button onMouseDown={event => event.stopPropagation()} onClick={closeGame}
              disabled={pending !== null} aria-label="Close game" title="Close game" style={closeBtnStyle}><Close size={14} /></button>
          )}
        </div>

        {/* Turn indicator */}
        <div role="status" aria-live="polite" aria-atomic="true" style={{
          padding: '6px 12px',
          textAlign: 'center',
          fontSize: 12,
          minHeight: 44,
          boxSizing: 'border-box',
          color: isMyTurn || recoverable ? '#f0b060' : '#aaaabc',
          ...(thinking && connected ? { animation: 'pulse-dim 2s ease-in-out infinite' } : {}),
        }}>
          {status}
        </div>
        {error && <div role="alert" style={{ color: '#f0b060', padding: '0 16px 12px', fontSize: 12 }}>{error}</div>}

        {/* Board */}
        {game && <div role="group" aria-label="Game board" aria-busy={pending === 'move'} style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
          gap: 4,
          padding: '4px 16px 16px',
        }}>
          {board?.map((cell, index) => {
            const isWinCell = winLine?.includes(index);
            const isEmpty = !cell;
            const canClick = isMyTurn && isEmpty && !isFinished && !busy && game.validMoves.includes(String(index));
            const isNewPiece = cell && !prevBoard[index];

            return (
              <button
                key={index}
                aria-label={`Row ${Math.floor(index / 3) + 1}, column ${index % 3 + 1}, ${cell || 'empty'}`}
                disabled={!canClick}
                onClick={() => makeMove(String(index))}
                className={isNewPiece ? 'piece-animate' : ''}
                style={{
                  width: '100%',
                  minWidth: 0,
                  aspectRatio: '1',
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
                  color: cell === 'X' ? '#50b0a0'
                       : cell === 'O' ? '#f0b060'
                       : '#333848',
                  opacity: isFinished && !isWinCell && winLine ? 0.4 : 1,
                  boxShadow: isWinCell ? '0 0 16px rgba(240, 176, 96, 0.4)' : 'none',
                  transition: 'all 200ms ease',
                  ...(isNewPiece ? { animation: 'piece-pop 0.5s ease-out' } : {}),
                }}
              >
                {cell}
              </button>
            );
          })}
        </div>}
        {game && !isFinished && <div style={{ minHeight: 44, padding: '0 16px 8px', boxSizing: 'border-box' }}>
          {recoverable && <button onClick={retry} disabled={busy} aria-label="Retry opponent turn"
            title="Retry opponent turn" style={{ ...closeBtnStyle, width: '100%', color: busy ? '#666680' : '#f0b060',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, fontSize: 12 }}>
            <PlayArrow size={14} /> Retry turn
          </button>}
        </div>}

        {/* Post-game buttons */}
        {isFinished && (
          <div style={{ display: 'flex', gap: 8, padding: '0 16px 12px', justifyContent: 'center' }}>
            <button
              onClick={closeGame}
              style={{
                padding: '6px 20px',
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 6,
                color: '#8888a0',
                fontSize: 11,
                fontFamily: "'JetBrains Mono', monospace",
                cursor: 'pointer',
              }}
            >
              Close
            </button>
          </div>
        )}
      </section>
    </>
  );
}
