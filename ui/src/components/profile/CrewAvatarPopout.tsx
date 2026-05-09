/** AD-721 D3: 3D avatar popout — VRM viewer with parametric fallback. */

import { Suspense, useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { CrewVRM } from './CrewVRM';
import { ParametricAvatar } from './ParametricAvatar';
import type { AgentSignals } from './avatarSignals';
import type { AvatarDSLDict } from '../../store/types';

export interface CrewAppearance {
  vrm_url: string;
  expression_overrides: Record<string, number>;
  color_palette_hint: string;
  // AD-721d: agent-authored DSL (optional — not yet rendered).
  dsl?: AvatarDSLDict | null;
}

interface Props {
  agentId: string;
  appearance: CrewAppearance | null;
  departmentColor: string;
  agentSignals: AgentSignals;
  onClose: () => void;
  // AD-721d: when set, surfaces the approval bar with the proposed DSL.
  proposedDsl?: AvatarDSLDict | null;
  onApproveDsl?: (dsl: AvatarDSLDict) => void | Promise<void>;
  onRejectDsl?: () => void;
}

const MIN_W = 220;
const MIN_H = 320;
const DEFAULT_W = 320;
const DEFAULT_H = 480;

export function CrewAvatarPopout({
  agentId,
  appearance,
  departmentColor,
  agentSignals,
  onClose,
  proposedDsl,
  onApproveDsl,
  onRejectDsl,
}: Props) {
  const [loadFailed, setLoadFailed] = useState(false);
  const useVRM = !!appearance?.vrm_url && !loadFailed;
  const tint = appearance?.color_palette_hint || departmentColor;

  // Window position + size state. Initialise to bottom-right (the previous fixed location).
  const [pos, setPos] = useState(() => {
    const vw = typeof window !== 'undefined' ? window.innerWidth : 1024;
    const vh = typeof window !== 'undefined' ? window.innerHeight : 768;
    return { x: Math.max(0, vw - DEFAULT_W - 24), y: Math.max(0, vh - DEFAULT_H - 24) };
  });
  const [size, setSize] = useState({ w: DEFAULT_W, h: DEFAULT_H });

  // Drag/resize gesture state — kept in refs to avoid stale closures.
  const gesture = useRef<
    | { kind: 'drag'; startX: number; startY: number; origX: number; origY: number }
    | { kind: 'resize'; startX: number; startY: number; origW: number; origH: number }
    | null
  >(null);

  const onMouseMove = useCallback((e: MouseEvent) => {
    const g = gesture.current;
    if (!g) return;
    if (g.kind === 'drag') {
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const nx = Math.min(Math.max(0, g.origX + (e.clientX - g.startX)), vw - 40);
      const ny = Math.min(Math.max(0, g.origY + (e.clientY - g.startY)), vh - 40);
      setPos({ x: nx, y: ny });
    } else {
      const nw = Math.max(MIN_W, g.origW + (e.clientX - g.startX));
      const nh = Math.max(MIN_H, g.origH + (e.clientY - g.startY));
      setSize({ w: nw, h: nh });
    }
  }, []);

  const onMouseUp = useCallback(() => {
    gesture.current = null;
    window.removeEventListener('mousemove', onMouseMove);
    window.removeEventListener('mouseup', onMouseUp);
  }, [onMouseMove]);

  useEffect(() => {
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [onMouseMove, onMouseUp]);

  // R3F's ResizeObserver sometimes misses the initial canvas measurement
  // (the popout-in animation puts the wrapper at the wrong size during the
  // first observation). A synthetic window resize after mount forces R3F
  // to re-measure and prevents the "blank until dragged" symptom.
  useEffect(() => {
    const t1 = setTimeout(() => window.dispatchEvent(new Event('resize')), 50);
    const t2 = setTimeout(() => window.dispatchEvent(new Event('resize')), 300);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, []);

  const startDrag = (e: React.MouseEvent) => {
    // Don't start a drag when the close button is clicked.
    if ((e.target as HTMLElement).closest('button[data-avatar-close]')) return;
    gesture.current = { kind: 'drag', startX: e.clientX, startY: e.clientY, origX: pos.x, origY: pos.y };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    e.preventDefault();
  };

  const startResize = (e: React.MouseEvent) => {
    gesture.current = { kind: 'resize', startX: e.clientX, startY: e.clientY, origW: size.w, origH: size.h };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    e.preventDefault();
    e.stopPropagation();
  };

  return createPortal(
    <div
      role="dialog"
      aria-label={`Avatar — ${agentId}`}
      style={{
        position: 'fixed',
        left: pos.x,
        top: pos.y,
        width: size.w,
        height: size.h,
        background: 'rgba(10, 10, 18, 0.92)',
        border: '1px solid rgba(240, 176, 96, 0.2)',
        borderRadius: 12,
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Drag handle / title bar. */}
      <div
        onMouseDown={startDrag}
        style={{
          height: 22,
          flex: '0 0 22px',
          cursor: 'move',
          background: 'rgba(240, 176, 96, 0.06)',
          borderBottom: '1px solid rgba(240, 176, 96, 0.12)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingLeft: 8,
          paddingRight: 4,
          userSelect: 'none',
        }}
      >
        <span style={{ fontSize: 10, color: '#8888a0', fontFamily: "'JetBrains Mono', monospace" }}>
          {agentId}
        </span>
        <button
          data-avatar-close
          onClick={onClose}
          aria-label="Close avatar"
          style={{
            background: 'none',
            border: 'none',
            color: '#8888a0',
            cursor: 'pointer',
            padding: 2,
            display: 'flex',
            alignItems: 'center',
          }}
        >
          {/* Inline SVG close glyph (HXI Design Principle #3 — no emoji). */}
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="1.5" strokeLinecap="round">
            <line x1="3" y1="3" x2="13" y2="13" />
            <line x1="13" y1="3" x2="3" y2="13" />
          </svg>
        </button>
      </div>

      {/* Canvas region. Explicit dimensions because R3F's ResizeObserver
          sometimes misses the initial flex measurement after the popout-in
          animation, leaving the avatar at 0x0 (blank frame) and freezing
          useFrame. Falling back to width/height props keeps the renderer
          synced with our state. */}
      <div style={{
        width: size.w,
        height: Math.max(0, size.h - 22),
        position: 'relative',
      }}>
        <Canvas
          camera={{ position: [0, 1.45, 0.85], fov: 28 }}
          gl={{ antialias: true, toneMappingExposure: 1.0 }}
          flat
          frameloop="always"
        >
          {/* `flat` disables ACES tone mapping which over-brightens MToon.
              Total light kept low so the model doesn't blow out. */}
          <ambientLight intensity={0.4} />
          <directionalLight position={[1, 2, 2]} intensity={0.6} />
          <Suspense fallback={null}>
            {useVRM ? (
              <CrewVRM
                vrmUrl={appearance!.vrm_url}
                agentId={agentId}
                expressionOverrides={appearance!.expression_overrides}
                signals={agentSignals}
                onLoadError={() => setLoadFailed(true)}
                restingExpression={appearance?.dsl?.expression_resting ?? null}
              />
            ) : (
              <ParametricAvatar tint={tint} signals={agentSignals} agentId={agentId} />
            )}
          </Suspense>
          {/* Drag to rotate, scroll to zoom — pivot on the head. */}
          <OrbitControls target={[0, 1.42, 0]} enablePan={false} minDistance={0.3} maxDistance={3} />
        </Canvas>
      </div>

      {/* AD-721d: Captain approval bar — only when a freshly proposed DSL is awaiting review. */}
      {proposedDsl && (
        <div
          data-testid="approval-bar"
          style={{
            flex: '0 0 auto',
            padding: '6px 8px',
            background: 'rgba(240, 176, 96, 0.06)',
            borderTop: '1px solid rgba(240, 176, 96, 0.15)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 11,
            fontFamily: "'JetBrains Mono', monospace",
            color: '#ccccd8',
          }}
        >
          <span style={{ flex: 1 }}>
            Proposed: {proposedDsl.body.type} body, {proposedDsl.outfit.style} outfit,{' '}
            {proposedDsl.expression_resting} resting
          </span>
          <button
            data-testid="approve-dsl-btn"
            onClick={() => onApproveDsl?.(proposedDsl)}
            aria-label="Approve avatar design"
            title="Approve"
            style={{
              background: 'none',
              border: '1px solid rgba(240, 176, 96, 0.4)',
              color: '#f0b060',
              cursor: 'pointer',
              padding: '2px 6px',
              borderRadius: 3,
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                 strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 8l3.5 3.5L13 4.5" />
            </svg>
          </button>
          <button
            data-testid="reject-dsl-btn"
            onClick={() => onRejectDsl?.()}
            aria-label="Reject avatar design"
            title="Reject"
            style={{
              background: 'none',
              border: '1px solid rgba(136, 136, 160, 0.4)',
              color: '#8888a0',
              cursor: 'pointer',
              padding: '2px 6px',
              borderRadius: 3,
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                 strokeWidth="1.5" strokeLinecap="round">
              <line x1="3" y1="3" x2="13" y2="13" />
              <line x1="13" y1="3" x2="3" y2="13" />
            </svg>
          </button>
        </div>
      )}

      {/* Resize handle (bottom-right corner). */}
      <div
        onMouseDown={startResize}
        aria-label="Resize avatar"
        style={{
          position: 'absolute',
          right: 0,
          bottom: 0,
          width: 16,
          height: 16,
          cursor: 'nwse-resize',
          zIndex: 2,
        }}
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#8888a0"
             strokeWidth="1.25" strokeLinecap="round">
          <line x1="5" y1="14" x2="14" y2="5" />
          <line x1="9" y1="14" x2="14" y2="9" />
        </svg>
      </div>
    </div>,
    document.body,
  );
}
