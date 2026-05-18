/* AD-733 — Persistent CAMERA LIVE indicator.
 *
 * Renders top-right of every HXI view when ``useCameraStore.active === true``.
 * Per HXI Design Principle #9 (alert-driven layout): the indicator surfaces
 * above other UI when active and disappears entirely when inactive — never
 * decorative clutter.
 */
import { useCameraStore } from '../../store/useCameraStore';
import { stopCameraStream } from '../../hooks/useCameraStream';

const STROKE_AMBER = '#f0b060';

export default function CameraLiveIndicator() {
  const active = useCameraStore((s) => s.active);
  if (!active) return null;
  return (
    <div
      data-testid="camera-live-indicator"
      style={{
        position: 'fixed',
        top: 8,
        right: 8,
        zIndex: 999,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '4px 10px',
        background: 'rgba(180,40,40,0.15)',
        border: '1px solid #c84030',
        borderRadius: 6,
        fontFamily: "'JetBrains Mono', monospace",
      }}
      role="status"
      aria-label="camera live"
    >
      {/* Inline stroke SVG dot — HXI Principle #3, never an emoji. */}
      <svg width={10} height={10} viewBox="0 0 10 10" aria-hidden="true">
        <circle cx="5" cy="5" r="4" fill="#e04030" stroke={STROKE_AMBER} strokeWidth={0.5}>
          <animate attributeName="opacity" values="1;0.4;1" dur="1s" repeatCount="indefinite" />
        </circle>
      </svg>
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 1.5,
          color: '#e0a0a0',
        }}
      >
        CAMERA LIVE
      </span>
      <button
        data-testid="camera-live-revoke"
        onClick={() => { void stopCameraStream(); }}
        style={{
          fontSize: 9,
          padding: '2px 6px',
          background: 'transparent',
          border: '1px solid #c84030',
          color: '#e0a0a0',
          cursor: 'pointer',
          letterSpacing: 1,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        REVOKE
      </button>
    </div>
  );
}
