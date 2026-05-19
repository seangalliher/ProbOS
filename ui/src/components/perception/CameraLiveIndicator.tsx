/* AD-733 — Persistent CAMERA LIVE indicator.
 *
 * Renders in a user-selectable corner of every HXI view when
 * ``useCameraStore.active === true``. Per HXI Design Principle #9
 * (alert-driven layout): the indicator surfaces above other UI when active
 * and disappears entirely when inactive — never decorative clutter. The
 * four-corner snap (BF-301) lets the Captain move it out of whatever menu
 * is currently active. Position persists in localStorage.
 */
import type { CSSProperties } from 'react';
import { useCameraStore, type IndicatorCorner } from '../../store/useCameraStore';
import { usePerceptionModeStore, type PerceptionMode } from '../../store/usePerceptionModeStore';
import { stopCameraStream } from '../../hooks/useCameraStream';

const STROKE_AMBER = '#f0b060';
const STROKE_DIM = '#666680';

const MODE_COLOR: Record<PerceptionMode, string> = {
  engaged: STROKE_AMBER,
  ambient: '#a07840',
  dormant: STROKE_DIM,
};

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

export default function CameraLiveIndicator() {
  const active = useCameraStore((s) => s.active);
  const corner = useCameraStore((s) => s.indicatorCorner);
  const cycleCorner = useCameraStore((s) => s.cycleIndicatorCorner);
  const previewEnabled = useCameraStore((s) => s.previewEnabled);
  const togglePreview = useCameraStore((s) => s.togglePreview);
  const mode = usePerceptionModeStore((s) => s.mode);
  const perAgent = usePerceptionModeStore((s) => s.perAgent);
  if (!active) return null;
  // AD-733c-5-4: when 2+ agents are registered with the
  // PerceptionEngagementRegistry, render compact per-agent badges in place
  // of the single MODE badge. Single-agent / unconfigured deployments keep
  // the legacy single badge bit-for-bit identical (HXI Principle #5).
  const perAgentEntries = Object.entries(perAgent);
  const showPerAgent = perAgentEntries.length >= 2;
  return (
    <div
      data-testid="camera-live-indicator"
      data-corner={corner}
      style={{
        position: 'fixed',
        ...CORNER_STYLES[corner],
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
      {mode && !showPerAgent && (
        <span
          data-testid="perception-mode-badge"
          data-mode={mode}
          style={{
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: 1.5,
            color: MODE_COLOR[mode],
            fontFamily: "'JetBrains Mono', monospace",
            padding: '1px 5px',
            border: `1px solid ${MODE_COLOR[mode]}`,
            borderRadius: 2,
          }}
        >
          {mode.toUpperCase()}
        </span>
      )}
      {showPerAgent && (
        <span
          data-testid="perception-per-agent-badges"
          style={{
            display: 'inline-flex',
            gap: 4,
            alignItems: 'center',
          }}
        >
          {perAgentEntries.map(([agentId, agentMode]) => (
            <span
              key={agentId}
              data-testid={`perception-per-agent-badge-${agentId}`}
              data-mode={agentMode}
              data-agent={agentId}
              title={`${agentId} — ${agentMode}`}
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: 1.2,
                color: MODE_COLOR[agentMode],
                fontFamily: "'JetBrains Mono', monospace",
                padding: '1px 5px',
                border: `1px solid ${MODE_COLOR[agentMode]}`,
                borderRadius: 2,
              }}
            >
              {agentId.toUpperCase()}:{agentMode.slice(0, 3).toUpperCase()}
            </span>
          ))}
        </span>
      )}
      <button
        data-testid="camera-live-move"
        onClick={cycleCorner}
        title={`Move indicator (currently ${CORNER_LABEL[corner]}; click to cycle corners)`}
        aria-label="move camera live indicator"
        style={{
          padding: '0 4px',
          background: 'transparent',
          border: '1px solid #c84030',
          color: '#e0a0a0',
          cursor: 'pointer',
          fontFamily: "'JetBrains Mono', monospace",
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
      <button
        data-testid="camera-live-preview-toggle"
        onClick={togglePreview}
        title={previewEnabled ? 'Hide camera preview' : 'Show camera preview'}
        aria-label="toggle camera preview"
        aria-pressed={previewEnabled}
        style={{
          padding: '0 4px',
          background: previewEnabled ? 'rgba(240,176,96,0.18)' : 'transparent',
          border: '1px solid #c84030',
          color: previewEnabled ? '#f0b060' : '#e0a0a0',
          cursor: 'pointer',
          fontFamily: "'JetBrains Mono', monospace",
          display: 'flex',
          alignItems: 'center',
        }}
      >
        {/* BF-302: eye glyph — inline SVG only, HXI Principle #3 */}
        <svg width={11} height={11} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M1 8 C 3.5 4, 12.5 4, 15 8 C 12.5 12, 3.5 12, 1 8 Z" />
          <circle cx="8" cy="8" r="2.2" />
        </svg>
      </button>
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
