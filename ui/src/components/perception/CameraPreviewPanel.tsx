/* BF-302/303 — Operator preview panel for the camera pipeline.
 *
 * Renders a small floating mirror of the live MediaStream + the most recent
 * description from the perception gateway. Captain can:
 *   - Move the panel between four corners independently of the indicator
 *   - Force-describe the next captured frame (supervisor bypass)
 *   - See what the perception gateway last described
 *
 * Privacy note: the mirror reuses the same MediaStream the runtime is
 * already capturing — it does NOT request additional camera access.
 */
import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { useCameraStore, type IndicatorCorner } from '../../store/useCameraStore';
import { forceNextFrame, getCameraStream } from '../../hooks/useCameraStream';

const CORNER_STYLES: Record<IndicatorCorner, CSSProperties> = {
  tl: { top: 8, left: 8 },
  tr: { top: 8, right: 8 },
  bl: { bottom: 8, left: 8 },
  br: { bottom: 8, right: 8 },
};

const CORNER_LABEL: Record<IndicatorCorner, string> = {
  tl: 'top-left',
  tr: 'top-right',
  bl: 'bottom-left',
  br: 'bottom-right',
};

const STROKE_AMBER = '#f0b060';
const STROKE_DIM = '#666680';

interface Observation {
  agent_id: string;
  timestamp: number;
  attachment_ref: string;
  description: string;
  novelty_score: number;
  subject_identity: string;
  session_id: string | null;
}

function _formatAge(seconds: number): string {
  if (seconds < 1) return 'just now';
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

export default function CameraPreviewPanel() {
  const active = useCameraStore((s) => s.active);
  const previewEnabled = useCameraStore((s) => s.previewEnabled);
  const previewCorner = useCameraStore((s) => s.previewCorner);
  const cyclePreviewCorner = useCameraStore((s) => s.cyclePreviewCorner);
  const framesSent = useCameraStore((s) => s.framesSent);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [latest, setLatest] = useState<Observation | null>(null);
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
  useEffect(() => {
    if (!previewEnabled || !active) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const resp = await fetch('/api/perception/recent?limit=1');
        if (!resp.ok || cancelled) return;
        const body = await resp.json();
        const obs: Observation | undefined = body?.observations?.[0];
        if (obs && !cancelled) setLatest(obs);
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

  return (
    <div
      data-testid="camera-preview-panel"
      data-corner={previewCorner}
      style={{
        position: 'fixed',
        ...CORNER_STYLES[previewCorner],
        zIndex: 998,
        width: 300,
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
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 6,
          gap: 6,
        }}
      >
        <span style={{ fontSize: 9, letterSpacing: 1.5, color: STROKE_AMBER, fontWeight: 700 }}>
          PREVIEW
        </span>
        <span style={{ fontSize: 9, color: STROKE_DIM, flex: 1, textAlign: 'right' }}>
          sent: {framesSent}
        </span>
        <button
          data-testid="camera-preview-move"
          onClick={cyclePreviewCorner}
          title={`Move preview (currently ${CORNER_LABEL[previewCorner]}; click to cycle)`}
          aria-label="move camera preview"
          style={{
            padding: '0 4px',
            background: 'transparent',
            border: `1px solid ${STROKE_DIM}`,
            color: STROKE_AMBER,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <svg width={10} height={10} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M8 2 L8 14" />
            <path d="M2 8 L14 8" />
            <path d="M5 5 L8 2 L11 5" />
            <path d="M5 11 L8 14 L11 11" />
            <path d="M5 5 L2 8 L5 11" />
            <path d="M11 5 L14 8 L11 11" />
          </svg>
        </button>
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
