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
import { useEffect, useState } from 'react';
import { useCameraStore, type IndicatorCorner } from '../../store/useCameraStore';
import { useCameraMultiplexerStore } from '../../store/useCameraMultiplexerStore';
import { useScreenStore } from '../../store/useScreenStore';
import { usePerceptionModeStore, type PerceptionMode } from '../../store/usePerceptionModeStore';
import { useSettingsStore } from '../../store/useSettingsStore';
import { stopCameraStream } from '../../hooks/useCameraStream';
import { stopScreenStream } from '../../hooks/useScreenStream';
import { onTranscribing } from '../../audio/whisperStt';

const STROKE_AMBER = '#f0b060';
const STROKE_DIM = '#666680';
// AD-733c-7-5: SPEECH badge flash decay in ms.
const SPEECH_FLASH_MS = 1500;

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
  // AD-733-2: screen subsystem state — independent lifecycle from camera.
  const screenActive = useScreenStore((s) => s.active);
  const corner = useCameraStore((s) => s.indicatorCorner);
  const cycleCorner = useCameraStore((s) => s.cycleIndicatorCorner);
  const previewEnabled = useCameraStore((s) => s.previewEnabled);
  const togglePreview = useCameraStore((s) => s.togglePreview);
  const mode = usePerceptionModeStore((s) => s.mode);
  const perAgent = usePerceptionModeStore((s) => s.perAgent);
  const lastSpeechAt = usePerceptionModeStore((s) => s.lastSpeechAt);
  // AD-742c-6: count distinct devices that have at least one agent bound.
  // Surfaces as a compact ``CAMS:N`` label only when N >= 2 — solo
  // deployments render bit-for-bit identical UI to HEAD.
  const boundDeviceCount = useCameraMultiplexerStore((s) => {
    const distinct = new Set<string>();
    for (const dev of Object.values(s.bindings)) {
      if (dev) distinct.add(dev);
    }
    return distinct.size;
  });
  // AD-733c-7-5: SPEECH badge is conditional on the snapshot toggle.
  // When ``vad_engagement_enabled=false`` (default), the badge does not
  // render — preserves bit-for-bit single-Captain layout.
  const vadEnabled = useSettingsStore(
    (s) => Boolean((s.snapshot?.config as any)?.perception?.vad_engagement_enabled),
  );
  // AD-705a (Wave 179): offline STT badge — hidden when disabled,
  // dim/amber/pulse states gate render below. Independent of vadEnabled
  // since STT can ride the existing browser-native fallback.
  const sttEnabled = useSettingsStore(
    (s) => Boolean((s.snapshot?.config as any)?.cognitive?.offline_stt_enabled),
  );
  const [sttModelLoaded, setSttModelLoaded] = useState(false);
  const [sttTranscribing, setSttTranscribing] = useState(false);
  useEffect(() => {
    if (!sttEnabled) return;
    let cancelled = false;
    // BF-322: post-BF-301 the AD-705a /data/whisper/whisper.js artifact no
    // longer exists, so loadWhisperModel() always 404s. Derive the badge
    // state from /api/voice/health (the actual backend health surface)
    // instead.
    fetch('/api/voice/health')
      .then((r) => r.json())
      .then((j) => {
        if (!cancelled) setSttModelLoaded(Boolean(j?.healthy && j?.backend_available));
      })
      .catch(() => {
        if (!cancelled) setSttModelLoaded(false);
      });
    const unsub = onTranscribing((active) => {
      if (!cancelled) setSttTranscribing(active);
    });
    return () => {
      cancelled = true;
      try { unsub(); } catch { /* Tier-2 */ }
    };
  }, [sttEnabled]);
  // Flash window: amber for SPEECH_FLASH_MS after each event, dim otherwise.
  const [speechFresh, setSpeechFresh] = useState(false);
  useEffect(() => {
    if (lastSpeechAt === null) return;
    setSpeechFresh(true);
    const timer = setTimeout(() => setSpeechFresh(false), SPEECH_FLASH_MS);
    return () => clearTimeout(timer);
  }, [lastSpeechAt]);
  if (!active && !screenActive) return null;
  // AD-733c-5-4: when 2+ agents are registered with the
  // PerceptionEngagementRegistry, render compact per-agent badges in place
  // of the single MODE badge. Single-agent / unconfigured deployments keep
  // the legacy single badge bit-for-bit identical (HXI Principle #5).
  const perAgentEntries = Object.entries(perAgent);
  const showPerAgent = perAgentEntries.length >= 2;
  // AD-733-2: SCREEN LIVE indicator stacks vertically below CAMERA LIVE in
  // the same corner. Offset by +36px on the vertical axis (each indicator
  // is ~28px tall + 8px gap). HXI Principle #4: pulsing dot on the icon;
  // identical motion language to the camera indicator.
  const cornerStyle = CORNER_STYLES[corner];
  const screenCornerStyle: CSSProperties = { ...cornerStyle };
  if ('top' in cornerStyle && typeof cornerStyle.top === 'number') {
    screenCornerStyle.top = (cornerStyle.top as number) + 36;
  } else if ('bottom' in cornerStyle && typeof cornerStyle.bottom === 'number') {
    screenCornerStyle.bottom = (cornerStyle.bottom as number) + 36;
  }
  return (
    <>
    {active && (
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
      {vadEnabled && (
        <span
          data-testid="perception-speech-badge"
          data-fresh={speechFresh ? 'true' : 'false'}
          aria-label={speechFresh ? 'speech detected' : 'no recent speech'}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 3,
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: 1.2,
            color: speechFresh ? STROKE_AMBER : STROKE_DIM,
            fontFamily: "'JetBrains Mono', monospace",
            padding: '1px 5px',
            border: `1px solid ${speechFresh ? STROKE_AMBER : STROKE_DIM}`,
            borderRadius: 2,
            transition: 'color 400ms ease-out, border-color 400ms ease-out',
          }}
        >
          {/* Inline stroke SVG soundwave — HXI Principle #3 (no emoji). */}
          <svg
            width={9}
            height={9}
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M2 8 L2 8.5" />
            <path d="M5 6 L5 10" />
            <path d="M8 4 L8 12" />
            <path d="M11 6 L11 10" />
            <path d="M14 8 L14 8.5" />
          </svg>
          SPK
        </span>
      )}
      {sttEnabled && (
        <span
          data-testid="perception-stt-badge"
          data-model-loaded={sttModelLoaded ? 'true' : 'false'}
          data-transcribing={sttTranscribing ? 'true' : 'false'}
          aria-label={
            !sttModelLoaded
              ? 'offline STT armed; model not loaded'
              : sttTranscribing
                ? 'offline STT transcribing'
                : 'offline STT ready'
          }
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 3,
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: 1.2,
            color: sttModelLoaded ? STROKE_AMBER : STROKE_DIM,
            fontFamily: "'JetBrains Mono', monospace",
            padding: '1px 5px',
            border: `1px solid ${sttModelLoaded ? STROKE_AMBER : STROKE_DIM}`,
            borderRadius: 2,
            transition: 'color 400ms ease-out, border-color 400ms ease-out',
            animation: sttTranscribing
              ? 'sttBadgePulse 1.4s ease-in-out infinite'
              : undefined,
          }}
        >
          {/* HXI #3: inline stroke SVG mic glyph (no emoji). */}
          <svg
            width={9}
            height={9}
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <rect x="6" y="2" width="4" height="8" rx="2" />
            <path d="M3 9 C3 12 5 14 8 14" />
            <path d="M13 9 C13 12 11 14 8 14" />
            <path d="M8 14 L8 15.5" />
          </svg>
          STT
        </span>
      )}
      {boundDeviceCount >= 2 && (
        <span
          data-testid="perception-cams-label"
          data-count={boundDeviceCount}
          title={`${boundDeviceCount} cameras bound to agents`}
          style={{
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: 1.2,
            color: STROKE_AMBER,
            fontFamily: "'JetBrains Mono', monospace",
            padding: '1px 5px',
            border: `1px solid ${STROKE_AMBER}`,
            borderRadius: 2,
          }}
        >
          CAMS:{boundDeviceCount}
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
    )}
    {/* AD-733-2: SCREEN LIVE indicator. Renders independently of the camera
        panel — distinct lifecycle, identical HXI motion language. */}
    {screenActive && (
      <div
        data-testid="screen-live-indicator"
        style={{
          position: 'fixed',
          ...screenCornerStyle,
          zIndex: 999,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '4px 10px',
          background: 'rgba(180,120,40,0.15)',
          border: '1px solid #c87830',
          borderRadius: 6,
          fontFamily: "'JetBrains Mono', monospace",
        }}
        role="status"
        aria-label="screen live"
      >
        {/* Stroke-SVG monitor glyph — HXI #3, no emoji. */}
        <svg width={12} height={12} viewBox="0 0 16 16" fill="none"
          stroke={STROKE_AMBER} strokeWidth={1.5} strokeLinecap="round"
          strokeLinejoin="round" aria-hidden="true">
          <rect x="1.5" y="2.5" width="13" height="9" rx="0.5" />
          <path d="M5 14 L11 14" />
          <path d="M8 11.5 L8 14" />
          {/* HXI #4: pulsing inner rect signals 'active capture'. */}
          <rect x="3.5" y="4.5" width="9" height="5" fill={STROKE_AMBER} opacity="0.25">
            <animate attributeName="opacity" values="0.25;0.55;0.25"
              dur="2s" repeatCount="indefinite" />
          </rect>
        </svg>
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 1.5,
            color: '#e0c0a0',
          }}
        >
          SCREEN LIVE
        </span>
        <button
          data-testid="screen-live-revoke"
          onClick={() => { void stopScreenStream(); }}
          style={{
            fontSize: 9,
            padding: '2px 6px',
            background: 'transparent',
            border: '1px solid #c87830',
            color: '#e0c0a0',
            cursor: 'pointer',
            letterSpacing: 1,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          REVOKE
        </button>
      </div>
    )}
    </>
  );
}
