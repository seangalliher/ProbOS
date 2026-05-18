/* BF-302 — Operator preview panel for the camera pipeline.
 *
 * Renders a small floating mirror of the live MediaStream when
 * ``useCameraStore.previewEnabled === true``, plus a FORCE button that
 * makes the next captured frame bypass the supervisor's throttle +
 * novelty gate (so the operator can verify the pipeline end-to-end
 * without waiting on visual novelty).
 *
 * Privacy note: the mirror reuses the same MediaStream the runtime is
 * already capturing — it does NOT request additional camera access.
 */
import { useEffect, useRef } from 'react';
import type { CSSProperties } from 'react';
import { useCameraStore, type IndicatorCorner } from '../../store/useCameraStore';
import { forceNextFrame, getCameraStream } from '../../hooks/useCameraStream';

// Anchor opposite the indicator's chosen corner so they don't overlap.
const OPPOSITE: Record<IndicatorCorner, CSSProperties> = {
  tl: { bottom: 8, right: 8 },
  tr: { bottom: 8, left: 8 },
  bl: { top: 8, right: 8 },
  br: { top: 8, left: 8 },
};

const STROKE_AMBER = '#f0b060';
const STROKE_DIM = '#666680';

export default function CameraPreviewPanel() {
  const active = useCameraStore((s) => s.active);
  const previewEnabled = useCameraStore((s) => s.previewEnabled);
  const corner = useCameraStore((s) => s.indicatorCorner);
  const framesSent = useCameraStore((s) => s.framesSent);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (!previewEnabled || !active) return;
    const el = videoRef.current;
    if (!el) return;
    // Mirror the same stream the capture loop is already using. If the
    // capture loop hasn't bound the stream yet, retry briefly.
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

  if (!active || !previewEnabled) return null;

  return (
    <div
      data-testid="camera-preview-panel"
      style={{
        position: 'fixed',
        ...OPPOSITE[corner],
        zIndex: 998,
        width: 280,
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
        }}
      >
        <span style={{ fontSize: 9, letterSpacing: 1.5, color: STROKE_AMBER, fontWeight: 700 }}>
          PREVIEW
        </span>
        <span style={{ fontSize: 9, color: STROKE_DIM }}>
          frames sent: {framesSent}
        </span>
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
          transform: 'scaleX(-1)', // mirror so operator sees themselves naturally
        }}
      />
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, gap: 6 }}>
        <span style={{ fontSize: 8, color: STROKE_DIM, lineHeight: '20px' }}>
          force = bypass novelty
        </span>
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
