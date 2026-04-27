/* AD-526b: Floating Tic-Tac-Toe game panel — Captain vs Crew */

import { useStore } from '../store/useStore';
import { useRef, useCallback, useState, useEffect } from 'react';
import { Close, PlayArrow } from './icons/Glyphs';
import type { GameState } from '../store/types';

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

  // Track previous board to animate only new pieces
  const [prevBoard, setPrevBoard] = useState<string[]>(Array(9).fill(''));
  useEffect(() => {
    if (game) {
      // Delay updating prevBoard so the new piece animates first
      const timer = setTimeout(() => setPrevBoard([...game.board]), 600);
      return () => clearTimeout(timer);
    }
  }, [game?.board.join(',')]);

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
        @media (prefers-reduced-motion: reduce) {
          .piece-animate { animation: none !important; }
        }
      `}</style>
      <div style={panelStyle}>
        {/* Title bar */}
        <div style={titleBarStyle} onMouseDown={onMouseDown}>
          <span style={{ fontSize: 12, fontWeight: 600, letterSpacing: 0.5 }}>
            Tic-Tac-Toe vs {game.opponent}
          </span>
          {!isFinished ? (
            <button onClick={forfeit} title="Forfeit" style={closeBtnStyle}><Close size={14} /></button>
          ) : (
            <button onClick={closeGame} title="Close" style={closeBtnStyle}><Close size={14} /></button>
          )}
        </div>

        {/* Turn indicator */}
        <div style={{
          padding: '6px 12px',
          textAlign: 'center',
          fontSize: 12,
          color: isMyTurn ? '#f0b060' : '#6a6a7a',
          ...(!isMyTurn && !isFinished ? { animation: 'pulse-dim 2s ease-in-out infinite' } : {}),
        }}>
          {isFinished
            ? game.status === 'won'
              ? game.winner === 'Captain' ? 'You won!' : `${game.opponent} wins`
              : game.status === 'draw' ? 'Draw!' : 'Game forfeited'
            : isMyTurn ? <><PlayArrow size={12} /> Your turn</> : `Waiting for ${game.opponent}...`
          }
        </div>

        {/* Board */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 4,
          padding: '4px 16px 16px',
        }}>
          {game.board.map((cell, i) => {
            const isWinCell = winLine?.includes(i);
            const isEmpty = !cell;
            const canClick = isMyTurn && isEmpty && !isFinished;
            const isNewPiece = cell && !prevBoard[i];

            return (
              <button
                key={i}
                disabled={!canClick}
                onClick={() => makeMove(String(i))}
                className={isNewPiece ? 'piece-animate' : ''}
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
                  color: cell === 'X' ? '#50b0a0'
                       : cell === 'O' ? '#f0b060'
                       : '#333848',
                  opacity: isFinished && !isWinCell && winLine ? 0.4 : 1,
                  boxShadow: isWinCell ? '0 0 16px rgba(240, 176, 96, 0.4)' : 'none',
                  transition: 'all 200ms ease',
                  ...(isNewPiece ? { animation: 'piece-pop 0.5s ease-out' } : {}),
                }}
              >
                {cell || String(i)}
              </button>
            );
          })}
        </div>

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
      </div>
    </>
  );
}
