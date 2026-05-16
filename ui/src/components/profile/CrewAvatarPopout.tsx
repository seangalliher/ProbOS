/** AD-721 D3: 3D avatar popout — VRM viewer with parametric fallback. */

import { Suspense, useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { CrewVRM } from './CrewVRM';
import { ParametricAvatar } from './ParametricAvatar';
import { diffAvatarDsl } from './avatarDslDiff';
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
  // AD-721d-1: revision-cycle wiring.
  previousDsl?: AvatarDSLDict | null;     // for diff highlighting
  iteration?: number;                      // 1-based; defaults to 1 when absent
  maxIterations?: number;                  // defaults to 3
  onRequestRevision?: (note: string) => void | Promise<void>;
  // AD-721d-2c: Counselor-mediated revision wiring.
  onMediateRevision?: (note: string) => Promise<{
    refined_hint?: string;
    proposal_iteration?: number;
    error?: string;
  }>;
  counselorOnline?: boolean;
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
  previousDsl,
  iteration,
  maxIterations,
  onRequestRevision,
  onMediateRevision,
  counselorOnline,
}: Props) {
  const [loadFailed, setLoadFailed] = useState(false);
  const useVRM = !!appearance?.vrm_url && !loadFailed;
  const tint = appearance?.color_palette_hint || departmentColor;
  // AD-721d-1: revision-flow local UI state.
  const [revisionOpen, setRevisionOpen] = useState(false);
  const [revisionNote, setRevisionNote] = useState('');
  // AD-721d-2c: Counselor-mediated revision local state.
  const [mediating, setMediating] = useState(false);
  const [mediateRefined, setMediateRefined] = useState<string | null>(null);
  const [mediateError, setMediateError] = useState<string | null>(null);
  const [mediateIteration, setMediateIteration] = useState<number | null>(null);

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

      {/* AD-721d + AD-721d-1: Captain approval bar with revision-cycle support. */}
      {proposedDsl && (() => {
        const changed = diffAvatarDsl(previousDsl ?? null, proposedDsl);
        const iter = iteration ?? 1;
        const maxIter = maxIterations ?? 3;
        const atCap = iter >= maxIter;
        const labelStyle: React.CSSProperties = {
          color: '#8888a0', fontSize: 10, marginRight: 4,
        };
        const valueStyle = (path: string): React.CSSProperties => ({
          color: changed.has(path) ? '#f0b060' : '#ccccd8',
          background: changed.has(path) ? 'rgba(240, 176, 96, 0.12)' : 'transparent',
          padding: changed.has(path) ? '0 4px' : 0,
          borderRadius: 2,
        });
        const prevStyle: React.CSSProperties = {
          color: '#666680', fontSize: 9, textDecoration: 'line-through', marginLeft: 4,
        };
        const renderField = (path: string, label: string, curr: unknown, prev: unknown) => (
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, lineHeight: 1.4 }}>
            <span style={labelStyle}>{label}</span>
            <span style={valueStyle(path)} data-diff-path={path}>{String(curr)}</span>
            {changed.has(path) && prev !== undefined && prev !== null && (
              <span style={prevStyle} data-diff-prev={path}>{String(prev)}</span>
            )}
          </div>
        );

        return (
          <div
            data-testid="approval-bar"
            data-iteration={iter}
            data-max-iterations={maxIter}
            style={{
              flex: '0 0 auto',
              padding: '6px 8px',
              background: 'rgba(240, 176, 96, 0.06)',
              borderTop: '1px solid rgba(240, 176, 96, 0.15)',
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
              fontSize: 11,
              fontFamily: "'JetBrains Mono', monospace",
              color: '#ccccd8',
            }}
          >
            {/* Structured parametric description (with diff highlights) */}
            <div data-testid="parametric-description" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ color: '#f0b060', fontSize: 10 }}>
                  Proposal {iter} / {maxIter}
                </span>
                {/* Hair-color swatch (small SVG square, no emoji) */}
                <svg width="10" height="10" viewBox="0 0 10 10" aria-label="hair color">
                  <rect
                    x="0" y="0" width="10" height="10" rx="2"
                    fill={`hsl(${proposedDsl.hair?.color_hsl?.[0] ?? 0}, ${proposedDsl.hair?.color_hsl?.[1] ?? 0}%, ${proposedDsl.hair?.color_hsl?.[2] ?? 0}%)`}
                  />
                </svg>
                {/* Outfit-color swatch */}
                <svg width="10" height="10" viewBox="0 0 10 10" aria-label="outfit color">
                  <rect
                    x="0" y="0" width="10" height="10" rx="2"
                    fill={proposedDsl.outfit?.primary_color ?? '#2a4a6a'}
                  />
                </svg>
              </div>
              {renderField('body.type',            'body',     proposedDsl.body?.type,            previousDsl?.body?.type)}
              {renderField('body.height_cm',       'h(cm)',    proposedDsl.body?.height_cm,       previousDsl?.body?.height_cm)}
              {renderField('hair.style',           'hair',     proposedDsl.hair?.style,           previousDsl?.hair?.style)}
              {renderField('face.warmth',          'warmth',   proposedDsl.face?.warmth,          previousDsl?.face?.warmth)}
              {renderField('face.jaw',             'jaw',      proposedDsl.face?.jaw,             previousDsl?.face?.jaw)}
              {renderField('face.eyes',            'eyes',     proposedDsl.face?.eyes,            previousDsl?.face?.eyes)}
              {renderField('outfit.style',         'outfit',   proposedDsl.outfit?.style,         previousDsl?.outfit?.style)}
              {renderField('expression_resting',   'resting',  proposedDsl.expression_resting,    previousDsl?.expression_resting)}
              {proposedDsl.notes && (
                <div style={{ color: '#8888a0', fontSize: 10, marginTop: 2, fontStyle: 'italic' }}>
                  {proposedDsl.notes}
                </div>
              )}
            </div>

            {/* Action row: Approve / Request revision / Reject */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ flex: 1 }} />
              <button
                data-testid="approve-dsl-btn"
                onClick={() => onApproveDsl?.(proposedDsl)}
                aria-label="Approve avatar design"
                title="Approve"
                style={{
                  background: 'none', border: '1px solid rgba(240, 176, 96, 0.4)',
                  color: '#f0b060', cursor: 'pointer', padding: '2px 6px',
                  borderRadius: 3, display: 'flex', alignItems: 'center',
                }}
              >
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                     strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 8l3.5 3.5L13 4.5" />
                </svg>
              </button>
              <button
                data-testid="request-revision-btn"
                onClick={() => setRevisionOpen((v) => !v)}
                aria-label="Request avatar design revision"
                aria-disabled={atCap}
                disabled={atCap}
                title={atCap
                  ? `Maximum revisions reached (${maxIter}). Approve or reject.`
                  : 'Request revision'}
                style={{
                  background: 'none',
                  border: `1px solid ${atCap ? 'rgba(136, 136, 160, 0.25)' : 'rgba(240, 176, 96, 0.4)'}`,
                  color: atCap ? '#666680' : '#f0b060',
                  cursor: atCap ? 'not-allowed' : 'pointer',
                  padding: '2px 6px', borderRadius: 3, display: 'flex', alignItems: 'center',
                }}
              >
                {/* Curved arrow / revise glyph — stroke-based, no emoji. */}
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                     strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M2 8a6 6 0 0 1 10.5-4" />
                  <path d="M13 2v3h-3" />
                  <path d="M14 8a6 6 0 0 1-10.5 4" />
                  <path d="M3 14v-3h3" />
                </svg>
              </button>
              <button
                data-testid="reject-dsl-btn"
                onClick={() => { setRevisionOpen(false); onRejectDsl?.(); }}
                aria-label="Reject avatar design"
                title="Reject"
                style={{
                  background: 'none', border: '1px solid rgba(136, 136, 160, 0.4)',
                  color: '#8888a0', cursor: 'pointer', padding: '2px 6px',
                  borderRadius: 3, display: 'flex', alignItems: 'center',
                }}
              >
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                     strokeWidth="1.5" strokeLinecap="round">
                  <line x1="3" y1="3" x2="13" y2="13" />
                  <line x1="13" y1="3" x2="3" y2="13" />
                </svg>
              </button>
            </div>

            {/* Inline revision textarea (expands when Request revision is clicked) */}
            {revisionOpen && !atCap && (
              <div data-testid="revision-textarea-wrap" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <textarea
                  data-testid="revision-note"
                  value={revisionNote}
                  onChange={(e) => setRevisionNote(e.target.value.slice(0, 280))}
                  placeholder="What should the agent change? (≤ 280 chars)"
                  rows={2}
                  style={{
                    width: '100%', resize: 'vertical', fontSize: 11,
                    fontFamily: "'JetBrains Mono', monospace",
                    background: 'rgba(0, 0, 0, 0.3)',
                    color: '#ccccd8',
                    border: '1px solid rgba(240, 176, 96, 0.25)',
                    borderRadius: 3, padding: 4,
                  }}
                />
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span
                    data-testid="revision-counter"
                    style={{
                      fontSize: 9,
                      color: revisionNote.length >= 280
                        ? '#cc6666'
                        : revisionNote.length >= 250 ? '#f0b060' : '#666680',
                    }}
                  >
                    {revisionNote.length} / 280
                  </span>
                  <span style={{ flex: 1 }} />
                  {onMediateRevision && counselorOnline && (
                    <button
                      data-testid="mediate-revision-btn"
                      onClick={async () => {
                        const note = revisionNote.trim();
                        if (!note || mediating) return;
                        setMediating(true);
                        setMediateError(null);
                        try {
                          const result = await onMediateRevision(note);
                          if (result.error) {
                            setMediateError(result.error);
                          } else {
                            setMediateRefined(result.refined_hint ?? null);
                            setMediateIteration(result.proposal_iteration ?? null);
                            if (result.refined_hint) {
                              setRevisionNote(result.refined_hint.slice(0, 280));
                            }
                          }
                        } catch (e: any) {
                          setMediateError(String(e?.message || e));
                        } finally {
                          setMediating(false);
                        }
                      }}
                      disabled={!revisionNote.trim() || mediating}
                      aria-label="Counselor-mediate revision"
                      title="Refine through Counselor before submitting"
                      style={{
                        background: 'none',
                        border: '1px solid rgba(240, 176, 96, 0.4)',
                        color: revisionNote.trim() && !mediating ? '#f0b060' : '#666680',
                        cursor: revisionNote.trim() && !mediating ? 'pointer' : 'not-allowed',
                        padding: '2px 6px', borderRadius: 3, display: 'flex', alignItems: 'center',
                        marginRight: 4,
                      }}
                    >
                      {/* Mediator / connector glyph — stroke-based. Two circles + bridge. */}
                      <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                           strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="4" cy="8" r="2" />
                        <circle cx="12" cy="8" r="2" />
                        <path d="M6 8h4" />
                      </svg>
                    </button>
                  )}
                  <button
                    data-testid="submit-revision-btn"
                    onClick={async () => {
                      const note = revisionNote.trim();
                      if (!note) return;
                      await onRequestRevision?.(note);
                      setRevisionNote('');
                      setRevisionOpen(false);
                    }}
                    disabled={!revisionNote.trim()}
                    aria-label="Submit revision request"
                    title="Submit revision"
                    style={{
                      background: 'none',
                      border: '1px solid rgba(240, 176, 96, 0.4)',
                      color: revisionNote.trim() ? '#f0b060' : '#666680',
                      cursor: revisionNote.trim() ? 'pointer' : 'not-allowed',
                      padding: '2px 6px', borderRadius: 3, display: 'flex', alignItems: 'center',
                    }}
                  >
                    {/* Paper-plane / send glyph — stroke-based. */}
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                         strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M2 8l12-5-5 12-2-5z" />
                      <path d="M7 10l5-7" />
                    </svg>
                  </button>
                </div>
                {mediateRefined && (
                  <div
                    data-testid="mediate-refined-panel"
                    style={{
                      fontSize: 10, color: '#aaaac0',
                      background: 'rgba(0, 0, 0, 0.2)',
                      padding: 4, borderRadius: 3,
                      border: '1px solid rgba(240, 176, 96, 0.2)',
                    }}
                  >
                    <strong style={{ color: '#f0b060' }}>Counselor refined:</strong>{' '}
                    {mediateRefined}
                    {mediateIteration != null && (
                      <span
                        data-testid="mediate-iteration-chip"
                        style={{ marginLeft: 6, color: '#666680' }}
                      >
                        (iter {mediateIteration})
                      </span>
                    )}
                  </div>
                )}
                {mediateError && (
                  <div
                    data-testid="mediate-error"
                    style={{ fontSize: 10, color: '#cc6666' }}
                  >
                    Mediation error: {mediateError}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })()}

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
