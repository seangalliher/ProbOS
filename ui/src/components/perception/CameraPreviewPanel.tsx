/* BF-302/303/305 — Operator preview panel for the camera pipeline.
 *
 * Renders a small floating mirror of the live MediaStream + the most recent
 * description from the perception gateway. Captain can:
 *   - Drag the panel anywhere on screen (free positioning, BF-305)
 *   - Double-click the header to reset to default corner
 *   - Force-describe the next captured frame (supervisor bypass)
 *   - See what the perception gateway last described
 *
 * Privacy note: the mirror reuses the same MediaStream the runtime is
 * already capturing — it does NOT request additional camera access.
 */
import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react';
import { useCameraStore } from '../../store/useCameraStore';
import { forceNextFrame, getCameraStream } from '../../hooks/useCameraStream';

const STROKE_AMBER = '#f0b060';
const STROKE_DIM = '#666680';
const PANEL_WIDTH = 300;
const PANEL_HEIGHT_ESTIMATE = 360; // approx — used only for default position clamping

interface Observation {
  agent_id: string;
  timestamp: number;
  attachment_ref: string;
  description: string;
  novelty_score: number;
  subject_identity: string;
  session_id: string | null;
}

interface Decision {
  timestamp: number;
  reason: string; // 'first_frame' | 'novel' | 'low_novelty' | 'throttled' | 'forced' | 'busy'
  sha: string;
  novelty_score: number;
}

interface DecisionSummary {
  total: number;
  described: number;
  dropped: number;
  lastDropReason: string | null;
  lastDropNovelty: number | null;
}

function _formatAge(seconds: number): string {
  if (seconds < 1) return 'just now';
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

function _clamp(value: number, lo: number, hi: number): number {
  if (Number.isNaN(value)) return lo;
  return Math.max(lo, Math.min(hi, value));
}

function _defaultPosition(): { x: number; y: number } {
  // Default: bottom-left corner with 8px inset.
  const w = typeof window !== 'undefined' ? window.innerWidth : 1024;
  const h = typeof window !== 'undefined' ? window.innerHeight : 768;
  return { x: 8, y: Math.max(8, h - PANEL_HEIGHT_ESTIMATE - 8) };
}

export default function CameraPreviewPanel() {
  const active = useCameraStore((s) => s.active);
  const previewEnabled = useCameraStore((s) => s.previewEnabled);
  const previewPosition = useCameraStore((s) => s.previewPosition);
  const setPreviewPosition = useCameraStore((s) => s.setPreviewPosition);
  const resetPreviewPosition = useCameraStore((s) => s.resetPreviewPosition);
  const framesSent = useCameraStore((s) => s.framesSent);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<{ startX: number; startY: number; panelX: number; panelY: number } | null>(null);
  const [latest, setLatest] = useState<Observation | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [now, setNow] = useState(() => Date.now() / 1000);

  // Mirror the live stream (BF-302).
  useEffect(() => {
    if (!previewEnabled || !active) return;
    const el = videoRef.current;
    if (!el) return;
    let cancelled = false;
    const attach = () => {
      const stream = getCameraStream();
      if (stream && !cancelled) {
        el.srcObject = stream;
        el.muted = true;
        el.playsInline = true;
        void el.play().catch(() => undefined);
      }
    };
    attach();
    const t = window.setInterval(() => {
      if (!cancelled && (!el.srcObject || (el.srcObject as MediaStream)?.active !== true)) {
        attach();
      } else {
        window.clearInterval(t);
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearInterval(t);
      if (el) el.srcObject = null;
    };
  }, [previewEnabled, active]);

  // BF-303: poll /api/perception/recent for the latest description.
  // BF-306: same endpoint now returns recent supervisor decisions too.
  useEffect(() => {
    if (!previewEnabled || !active) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const resp = await fetch('/api/perception/recent?limit=16');
        if (!resp.ok || cancelled) return;
        const body = await resp.json();
        const obs: Observation | undefined = body?.observations?.[0];
        if (obs && !cancelled) setLatest(obs);
        const dec: Decision[] | undefined = body?.recent_decisions;
        if (Array.isArray(dec) && !cancelled) setDecisions(dec);
      } catch {
        // ignore — preview is best-effort
      }
    };
    void tick();
    const id = window.setInterval(() => { void tick(); }, 2000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [previewEnabled, active]);

  // BF-303: tick "age" label every second.
  useEffect(() => {
    if (!previewEnabled || !active) return;
    const id = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(id);
  }, [previewEnabled, active]);

  if (!active || !previewEnabled) return null;

  const ageSec = latest ? Math.max(0, now - latest.timestamp) : null;
  const pos = previewPosition ?? _defaultPosition();

  // BF-306: derive an at-a-glance summary of supervisor activity.
  const _DESCRIBED = new Set(['first_frame', 'novel', 'forced']);
  let described = 0;
  let dropped = 0;
  let lastDropReason: string | null = null;
  let lastDropNovelty: number | null = null;
  for (const d of decisions) {
    if (_DESCRIBED.has(d.reason)) {
      described++;
    } else {
      dropped++;
      if (lastDropReason === null) {
        lastDropReason = d.reason;
        lastDropNovelty = d.novelty_score;
      }
    }
  }
  const summary: DecisionSummary = {
    total: decisions.length,
    described,
    dropped,
    lastDropReason,
    lastDropNovelty,
  };

  const onHeaderPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    // Ignore drag-start when the click landed on a button inside the header.
    if ((e.target as HTMLElement).closest('button')) return;
    e.preventDefault();
    // BF-305: anchor the drag at the current rendered position (which is
    // exactly the store position). We use the store value directly rather
    // than getBoundingClientRect() so the math is deterministic regardless
    // of layout engine state (real browsers + jsdom in tests both work).
    dragStateRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      panelX: pos.x,
      panelY: pos.y,
    };

    const onMove = (ev: PointerEvent) => {
      const start = dragStateRef.current;
      if (!start) return;
      const w = window.innerWidth;
      const h = window.innerHeight;
      const dx = ev.clientX - start.startX;
      const dy = ev.clientY - start.startY;
      const rectNow = panelRef.current?.getBoundingClientRect();
      const panelH = (rectNow && rectNow.height > 0) ? rectNow.height : PANEL_HEIGHT_ESTIMATE;
      const next = {
        x: _clamp(start.panelX + dx, 0, Math.max(0, w - PANEL_WIDTH)),
        y: _clamp(start.panelY + dy, 0, Math.max(0, h - panelH)),
      };
      setPreviewPosition(next);
    };
    const onUp = () => {
      dragStateRef.current = null;
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
  };

  const headerStyle: CSSProperties = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
    gap: 6,
    cursor: 'grab',
    userSelect: 'none',
    touchAction: 'none',
  };

  return (
    <div
      ref={panelRef}
      data-testid="camera-preview-panel"
      style={{
        position: 'fixed',
        top: pos.y,
        left: pos.x,
        zIndex: 998,
        width: PANEL_WIDTH,
        background: 'rgba(10,10,18,0.92)',
        border: `1px solid ${STROKE_DIM}`,
        borderRadius: 6,
        padding: 8,
        fontFamily: "'JetBrains Mono', monospace",
        boxShadow: '0 4px 16px rgba(0,0,0,0.6)',
      }}
      role="region"
      aria-label="camera preview"
    >
      <div
        data-testid="camera-preview-header"
        style={headerStyle}
        onPointerDown={onHeaderPointerDown}
        onDoubleClick={() => resetPreviewPosition()}
        title="Drag to move · double-click to reset position"
      >
        <span style={{ fontSize: 9, letterSpacing: 1.5, color: STROKE_AMBER, fontWeight: 700 }}>
          PREVIEW
        </span>
        <span style={{ fontSize: 9, color: STROKE_DIM, flex: 1, textAlign: 'right' }}>
          sent: {framesSent}
        </span>
        {/* Drag-handle SVG glyph — purely decorative, header is the drag surface */}
        <svg width={10} height={10} viewBox="0 0 16 16" fill="none" stroke={STROKE_DIM} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="5" cy="4" r="0.5" fill={STROKE_DIM} />
          <circle cx="11" cy="4" r="0.5" fill={STROKE_DIM} />
          <circle cx="5" cy="8" r="0.5" fill={STROKE_DIM} />
          <circle cx="11" cy="8" r="0.5" fill={STROKE_DIM} />
          <circle cx="5" cy="12" r="0.5" fill={STROKE_DIM} />
          <circle cx="11" cy="12" r="0.5" fill={STROKE_DIM} />
        </svg>
      </div>
      <video
        ref={videoRef}
        data-testid="camera-preview-video"
        style={{
          width: '100%',
          aspectRatio: '4 / 3',
          background: '#000',
          borderRadius: 3,
          objectFit: 'cover',
          transform: 'scaleX(-1)',
        }}
      />
      <div
        data-testid="camera-preview-description"
        style={{
          marginTop: 6,
          padding: '6px 8px',
          background: 'rgba(0,0,0,0.4)',
          border: `1px solid ${STROKE_DIM}`,
          borderRadius: 3,
          minHeight: 48,
          fontSize: 10,
          color: '#c0c0d0',
          lineHeight: 1.4,
        }}
      >
        {latest ? (
          <>
            <div style={{ fontSize: 8, color: STROKE_DIM, marginBottom: 3, letterSpacing: 1 }}>
              LAST DESCRIBED · {ageSec !== null ? _formatAge(ageSec) : '—'} · novelty {latest.novelty_score.toFixed(2)}
            </div>
            <div>{latest.description}</div>
          </>
        ) : (
          <div style={{ color: STROKE_DIM, fontStyle: 'italic' }}>
            Waiting for first description… force a frame or wait for novelty.
          </div>
        )}
      </div>
      <div
        data-testid="camera-preview-supervisor"
        style={{
          marginTop: 4,
          fontSize: 9,
          color: STROKE_DIM,
          display: 'flex',
          justifyContent: 'space-between',
          gap: 6,
        }}
      >
        <span>
          supervisor: {summary.described} described · {summary.dropped} dropped
        </span>
        <span style={{ color: summary.lastDropReason ? '#e08040' : STROKE_DIM }}>
          {summary.lastDropReason
            ? `last drop: ${summary.lastDropReason}${summary.lastDropNovelty !== null ? ` ${summary.lastDropNovelty.toFixed(2)}` : ''}`
            : 'no drops yet'}
        </span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
        <button
          data-testid="camera-preview-force"
          onClick={() => forceNextFrame()}
          style={{
            fontSize: 9,
            padding: '2px 8px',
            background: 'transparent',
            border: `1px solid ${STROKE_AMBER}`,
            color: STROKE_AMBER,
            cursor: 'pointer',
            letterSpacing: 1,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          FORCE DESCRIBE ↵
        </button>
      </div>
    </div>
  );
}
