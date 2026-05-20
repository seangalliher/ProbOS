/**
 * AD-733: SettingsMain side-panel for the ``perception`` section.
 *
 * Renders ABOVE the standard generic-field rows so the operator can flip
 * the camera live without waiting for APPLY. Toggling
 * ``perception.camera.enabled`` calls ``startCameraStream`` / ``stopCameraStream``
 * directly — camera is a live thing, not just config.
 */
import { useEffect, useState } from 'react';
import { useCameraStore } from '../../../store/useCameraStore';
import { useCameraMultiplexerStore } from '../../../store/useCameraMultiplexerStore';
import {
  useSourceBindingsStore,
  ALL_SOURCES,
  type SourceName,
} from '../../../store/useSourceBindingsStore';
import { useSettingsStore } from '../../../store/useSettingsStore';
import {
  usePerceptionModeStore,
  type PerceptionMode,
} from '../../../store/usePerceptionModeStore';
import { startCameraStream, stopCameraStream } from '../../../hooks/useCameraStream';
import { startScreenStream, stopScreenStream } from '../../../hooks/useScreenStream';
import { useScreenStore } from '../../../store/useScreenStore';

const STROKE_AMBER = '#f0b060';
const STROKE_DIM = '#666680';
const STROKE_ENGINEERING = '#e08040';

const MODE_COLOR: Record<PerceptionMode, string> = {
  engaged: STROKE_AMBER,
  ambient: '#a07840',
  dormant: STROKE_DIM,
};

const MODE_ORDER: PerceptionMode[] = ['dormant', 'ambient', 'engaged'];

export default function PerceptionLivePanel() {
  const snapshot = useSettingsStore((s) => s.snapshot);
  const cameraActive = useCameraStore((s) => s.active);
  const cameraError = useCameraStore((s) => s.error);
  const framesSent = useCameraStore((s) => s.framesSent);
  const mode = usePerceptionModeStore((s) => s.mode);
  const modeTransitions = usePerceptionModeStore((s) => s.transitions);
  const setPerceptionMode = usePerceptionModeStore((s) => s.setMode);
  const perAgent = usePerceptionModeStore((s) => s.perAgent);

  // AD-742c-6: camera multiplexer bindings + browser-enumerated devices.
  // Section is collapsible (HXI Principle #5: progressive disclosure) so
  // single-camera deployments never see the table unless they expand it.
  const bindings = useCameraMultiplexerStore((s) => s.bindings);
  const devices = useCameraMultiplexerStore((s) => s.devices);
  const refreshBindings = useCameraMultiplexerStore((s) => s.refresh);
  const bindAgent = useCameraMultiplexerStore((s) => s.bindAgent);
  const clearAgent = useCameraMultiplexerStore((s) => s.clearAgent);
  const [bindingsExpanded, setBindingsExpanded] = useState(false);
  // AD-746 Layer 2: per-agent source bindings (camera/screen pills).
  const sourceBindings = useSourceBindingsStore((s) => s.bindings);
  const refreshSourceBindings = useSourceBindingsStore((s) => s.refresh);
  const toggleSourceForAgent = useSourceBindingsStore((s) => s.toggleSource);
  // AD-733-2: screen subsystem state (separate slice from camera).
  const screenActive = useScreenStore((s) => s.active);
  const screenError = useScreenStore((s) => s.error);
  const screenFramesSent = useScreenStore((s) => s.framesSent);
  const [screenSectionExpanded, setScreenSectionExpanded] = useState(false);
  useEffect(() => {
    if (bindingsExpanded) {
      void refreshBindings();
      void refreshSourceBindings();
    }
  }, [bindingsExpanded, refreshBindings, refreshSourceBindings]);

  if (!snapshot) return null;

  // Vision tier honest-degrade: if cognitive.llm_base_url_vision is empty,
  // frames will be stored but no agent observes them.
  const cognitive = (snapshot.config as any).cognitive ?? {};
  const visionConfigured = Boolean(cognitive.llm_base_url_vision && cognitive.llm_model_vision);

  // HTTPS warning: localhost is exempt by browser spec; production deployment
  // behind a public hostname needs HTTPS for getUserMedia.
  const httpsWarn =
    typeof window !== 'undefined' &&
    window.location.protocol !== 'https:' &&
    window.location.hostname !== 'localhost' &&
    window.location.hostname !== '127.0.0.1';

  // BF-298: status badge — compute from live snapshot + camera-store state.
  const perceptionEnabled = Boolean(
    (snapshot.config as any).perception?.enabled,
  );
  let badgeText: string;
  let badgeColor: string;
  if (!perceptionEnabled) {
    badgeText = 'subsystem: OFF';
    badgeColor = STROKE_DIM;
  } else if (cameraActive) {
    badgeText = 'subsystem: ON · camera live';
    badgeColor = STROKE_AMBER;
  } else {
    badgeText = 'subsystem: ON · 0 modalities active';
    badgeColor = STROKE_ENGINEERING;
  }

  return (
    <div
      data-testid="perception-live-panel"
      style={{
        marginBottom: 18,
        padding: 12,
        border: `1px solid ${cameraActive ? STROKE_AMBER : STROKE_DIM}`,
        borderRadius: 4,
        background: cameraActive ? 'rgba(240,176,96,0.06)' : 'transparent',
      }}
    >
      <div
        data-testid="perception-status-badge"
        style={{
          fontSize: 9,
          fontFamily: "'JetBrains Mono', monospace",
          letterSpacing: 1.5,
          color: badgeColor,
          marginBottom: 8,
          textTransform: 'uppercase',
        }}
      >
        {badgeText}
      </div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          marginBottom: 10,
        }}
      >
        <div style={{ flex: 1 }}>
          <div style={{ color: '#c8c8d8', fontSize: 12, fontWeight: 700, letterSpacing: 1 }}>
            Live camera
          </div>
          <div style={{ color: STROKE_DIM, fontSize: 9, marginTop: 2 }}>
            Captain holds explicit consent. Browser prompts on first start.
          </div>
        </div>
        <button
          data-testid="perception-camera-toggle"
          onClick={() => {
            if (cameraActive) {
              void stopCameraStream();
            } else {
              void startCameraStream({ fps: 1 });
            }
          }}
          style={{
            background: cameraActive ? 'rgba(180,40,40,0.15)' : 'rgba(240,176,96,0.12)',
            border: `1px solid ${cameraActive ? '#c84030' : STROKE_AMBER}`,
            color: cameraActive ? '#e0a0a0' : STROKE_AMBER,
            padding: '6px 14px',
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 1.5,
            cursor: 'pointer',
            borderRadius: 3,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {cameraActive ? 'STOP' : 'START'}
        </button>
      </div>

      <div style={{ display: 'flex', gap: 16, fontSize: 9, color: STROKE_DIM }}>
        <span>
          status:{' '}
          <span style={{ color: cameraActive ? STROKE_AMBER : STROKE_DIM }}>
            {cameraActive ? 'LIVE' : 'idle'}
          </span>
        </span>
        <span>frames sent: {framesSent}</span>
      </div>

      {/* AD-733c-2: PerceptionModeController status + manual override. */}
      <div
        data-testid="perception-mode-section"
        style={{
          marginTop: 12,
          paddingTop: 10,
          borderTop: `1px solid ${STROKE_DIM}`,
        }}
      >
        <div
          style={{
            color: '#c8c8d8',
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 1.5,
            marginBottom: 6,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          MODE
        </div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          {MODE_ORDER.map((candidate) => (
            <button
              key={candidate}
              data-testid={`perception-mode-button-${candidate}`}
              onClick={() => { void setPerceptionMode(candidate); }}
              aria-pressed={mode === candidate}
              style={{
                flex: 1,
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: 1.5,
                color: mode === candidate ? MODE_COLOR[candidate] : STROKE_DIM,
                background:
                  mode === candidate
                    ? `${MODE_COLOR[candidate]}22`
                    : 'transparent',
                border: `1px solid ${
                  mode === candidate ? MODE_COLOR[candidate] : STROKE_DIM
                }`,
                padding: '4px 6px',
                cursor: 'pointer',
                fontFamily: "'JetBrains Mono', monospace",
                borderRadius: 2,
              }}
            >
              {candidate.toUpperCase()}
            </button>
          ))}
        </div>
        {modeTransitions.length > 0 && (
          <div
            data-testid="perception-mode-transitions"
            style={{
              fontSize: 9,
              color: STROKE_DIM,
              fontFamily: "'JetBrains Mono', monospace",
              lineHeight: 1.5,
            }}
          >
            {modeTransitions.slice(0, 3).map((t, idx) => (
              <div key={`${t.at}-${idx}`}>
                {t.from_mode} {'->'} {t.to_mode}{' '}
                <span style={{ color: '#888' }}>({t.trigger})</span>
              </div>
            ))}
          </div>
        )}
        {/* AD-733c-5-4: per-agent MODE table (read-only). Surfaces only
            when the PerceptionEngagementRegistry has at least one entry. */}
        {Object.keys(perAgent).length > 0 && (
          <div
            data-testid="perception-per-agent-table"
            style={{
              marginTop: 8,
              paddingTop: 8,
              borderTop: `1px dashed ${STROKE_DIM}`,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            <div
              style={{
                fontSize: 9,
                color: STROKE_DIM,
                letterSpacing: 1.5,
                marginBottom: 4,
              }}
            >
              PER-AGENT
            </div>
            {Object.entries(perAgent).map(([agentId, agentMode]) => (
              <div
                key={agentId}
                data-testid={`perception-per-agent-row-${agentId}`}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontSize: 9,
                  padding: '2px 0',
                }}
              >
                <span style={{ color: '#c8c8d8', letterSpacing: 1 }}>
                  {agentId.toUpperCase()}
                </span>
                <span
                  data-mode={agentMode}
                  style={{
                    color: MODE_COLOR[agentMode],
                    border: `1px solid ${MODE_COLOR[agentMode]}`,
                    borderRadius: 2,
                    padding: '1px 5px',
                    letterSpacing: 1.2,
                    fontWeight: 700,
                  }}
                >
                  {agentMode.toUpperCase()}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {!visionConfigured && (
        <div
          data-testid="perception-vision-unconfigured"
          style={{ fontSize: 9, color: STROKE_ENGINEERING, marginTop: 8, lineHeight: 1.4 }}
        >
          Vision tier not configured. Frames will be stored, but no agent will
          observe them. Configure under LLM Tiers → Vision tier — AD-733a adds
          the observer agent.
        </div>
      )}

      {/* AD-742c-6: CAMERA BINDINGS section (collapsible). */}
      <div
        data-testid="perception-camera-bindings-section"
        style={{
          marginTop: 12,
          paddingTop: 10,
          borderTop: `1px solid ${STROKE_DIM}`,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        <button
          data-testid="perception-camera-bindings-toggle"
          onClick={() => setBindingsExpanded((v) => !v)}
          aria-expanded={bindingsExpanded}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            width: '100%',
            background: 'transparent',
            border: 'none',
            color: '#c8c8d8',
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 1.5,
            cursor: 'pointer',
            padding: 0,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {/* Inline chevron — HXI Principle #3 (no emoji). */}
          <svg
            width={10}
            height={10}
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            style={{
              transform: bindingsExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
              transition: 'transform 200ms ease-out',
            }}
          >
            <path d="M5 3 L11 8 L5 13" />
          </svg>
          SOURCE BINDINGS
        </button>
        {bindingsExpanded && (
          <div
            data-testid="perception-camera-bindings-table"
            style={{ marginTop: 8 }}
          >
            <button
              data-testid="perception-camera-bindings-refresh"
              onClick={() => { void refreshBindings(); }}
              style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: 1.2,
                color: STROKE_DIM,
                background: 'transparent',
                border: `1px solid ${STROKE_DIM}`,
                padding: '2px 6px',
                cursor: 'pointer',
                fontFamily: "'JetBrains Mono', monospace",
                borderRadius: 2,
                marginBottom: 6,
              }}
            >
              REFRESH DEVICES
            </button>
            {Object.keys(bindings).length === 0 && (
              <div
                data-testid="perception-camera-bindings-empty"
                style={{ fontSize: 9, color: STROKE_DIM, lineHeight: 1.4 }}
              >
                No crew agents configured for camera binding.
              </div>
            )}
            {Object.entries(bindings).map(([agentId, deviceId]) => {
              const bound = Boolean(deviceId);
              // AD-746 Layer 2: per-agent source bindings. Default
              // (absent key) = both sources; matches backend default.
              const agentSources = sourceBindings[agentId] ?? [...ALL_SOURCES];
              return (
                <div
                  key={agentId}
                  data-testid={`perception-camera-binding-row-${agentId}`}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4,
                    fontSize: 9,
                    padding: '3px 0',
                    color: bound ? STROKE_AMBER : STROKE_DIM,
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                    }}
                  >
                    <span style={{ flex: '0 0 auto', minWidth: 50, letterSpacing: 1 }}>
                      {agentId.toUpperCase()}
                    </span>
                  <select
                    data-testid={`perception-camera-binding-select-${agentId}`}
                    value={deviceId ?? ''}
                    onChange={(e) => { void bindAgent(agentId, e.target.value); }}
                    style={{
                      flex: 1,
                      fontSize: 9,
                      background: 'transparent',
                      color: bound ? STROKE_AMBER : STROKE_DIM,
                      border: `1px solid ${bound ? STROKE_AMBER : STROKE_DIM}`,
                      padding: '2px 4px',
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    <option value="">(unbound)</option>
                    {devices.map((d) => (
                      <option key={d.deviceId} value={d.deviceId}>
                        {d.label || d.deviceId.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                  {bound && (
                    <button
                      data-testid={`perception-camera-binding-clear-${agentId}`}
                      onClick={() => { void clearAgent(agentId); }}
                      aria-label={`clear binding for ${agentId}`}
                      title="clear binding"
                      style={{
                        background: 'transparent',
                        border: `1px solid ${STROKE_DIM}`,
                        color: STROKE_DIM,
                        padding: '2px 4px',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                      }}
                    >
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
                        <path d="M3 3 L13 13" />
                        <path d="M13 3 L3 13" />
                      </svg>
                    </button>
                  )}
                  </div>
                  {/* AD-746 Layer 2: SOURCE BINDINGS pills (camera/screen). */}
                  <div
                    data-testid={`perception-source-bindings-row-${agentId}`}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4,
                      marginLeft: 50,
                      fontSize: 8,
                      letterSpacing: 1,
                    }}
                  >
                    <span style={{ color: STROKE_DIM, marginRight: 4 }}>
                      SOURCES:
                    </span>
                    {ALL_SOURCES.map((src) => {
                      const isBound = agentSources.includes(src);
                      return (
                        <button
                          key={src}
                          type="button"
                          data-testid={`perception-source-pill-${agentId}-${src}`}
                          aria-pressed={isBound}
                          onClick={() => {
                            void toggleSourceForAgent(agentId, src as SourceName);
                          }}
                          style={{
                            background: 'transparent',
                            color: isBound ? STROKE_AMBER : STROKE_DIM,
                            border: `1px solid ${isBound ? STROKE_AMBER : STROKE_DIM}`,
                            padding: '1px 5px',
                            cursor: 'pointer',
                            fontSize: 8,
                            letterSpacing: 1,
                            fontFamily: "'JetBrains Mono', monospace",
                            borderRadius: 2,
                          }}
                        >
                          {src.toUpperCase()}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* AD-733-2: SCREEN SOURCES section (collapsible). Mirrors the
          AD-742c-6 CAMERA BINDINGS layout — same chevron, same border,
          same letter-spacing. Renders independently from camera state. */}
      <div
        data-testid="perception-screen-sources-section"
        style={{
          marginTop: 12,
          paddingTop: 10,
          borderTop: `1px solid ${STROKE_DIM}`,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        <button
          data-testid="perception-screen-sources-toggle"
          onClick={() => setScreenSectionExpanded((v) => !v)}
          aria-expanded={screenSectionExpanded}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            width: '100%',
            background: 'transparent',
            border: 'none',
            color: '#c8c8d8',
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 1.5,
            cursor: 'pointer',
            padding: 0,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          <svg
            width={10}
            height={10}
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            style={{
              transform: screenSectionExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
              transition: 'transform 200ms ease-out',
            }}
          >
            <path d="M5 3 L11 8 L5 13" />
          </svg>
          SCREEN SOURCES
        </button>
        {screenSectionExpanded && (
          <div
            data-testid="perception-screen-sources-body"
            style={{ marginTop: 8 }}
          >
            {!Boolean((snapshot.config as any).perception?.screen?.enabled) && (
              <div
                data-testid="perception-screen-disabled-banner"
                style={{
                  fontSize: 9,
                  color: STROKE_ENGINEERING,
                  marginBottom: 8,
                  lineHeight: 1.4,
                }}
              >
                Screen streaming disabled. Toggle{' '}
                <code style={{ color: STROKE_AMBER }}>
                  perception.screen.enabled
                </code>{' '}
                below + APPLY to enable. Captain must opt in.
              </div>
            )}
            {httpsWarn && (
              <div
                data-testid="perception-screen-https-warn"
                style={{
                  fontSize: 9,
                  color: STROKE_ENGINEERING,
                  marginBottom: 8,
                  lineHeight: 1.4,
                }}
              >
                Non-localhost host without HTTPS — getDisplayMedia will be
                rejected by the browser.
              </div>
            )}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                marginBottom: 6,
              }}
            >
              <div style={{ flex: 1 }}>
                <div
                  style={{
                    color: '#c8c8d8',
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: 1,
                  }}
                >
                  Live screen share
                </div>
                <div style={{ color: STROKE_DIM, fontSize: 9, marginTop: 2 }}>
                  Browser picker opens on START. "Stop sharing" pill auto-revokes.
                </div>
              </div>
              <button
                data-testid="perception-screen-toggle"
                onClick={() => {
                  if (screenActive) {
                    void stopScreenStream();
                  } else {
                    void startScreenStream({ fps: 1 });
                  }
                }}
                disabled={
                  !screenActive &&
                  !Boolean((snapshot.config as any).perception?.screen?.enabled)
                }
                style={{
                  background: screenActive
                    ? 'rgba(180,40,40,0.15)'
                    : 'rgba(240,176,96,0.12)',
                  border: `1px solid ${
                    screenActive ? '#c84030' : STROKE_AMBER
                  }`,
                  color: screenActive ? '#e0a0a0' : STROKE_AMBER,
                  padding: '6px 14px',
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: 1.5,
                  cursor:
                    !screenActive &&
                    !Boolean(
                      (snapshot.config as any).perception?.screen?.enabled,
                    )
                      ? 'not-allowed'
                      : 'pointer',
                  borderRadius: 3,
                  fontFamily: "'JetBrains Mono', monospace",
                  opacity:
                    !screenActive &&
                    !Boolean(
                      (snapshot.config as any).perception?.screen?.enabled,
                    )
                      ? 0.5
                      : 1,
                }}
              >
                {screenActive ? 'STOP' : 'START'}
              </button>
            </div>
            <div
              style={{
                display: 'flex',
                gap: 16,
                fontSize: 9,
                color: STROKE_DIM,
              }}
            >
              <span>
                status:{' '}
                <span
                  style={{
                    color: screenActive ? STROKE_AMBER : STROKE_DIM,
                  }}
                >
                  {screenActive ? 'LIVE' : 'idle'}
                </span>
              </span>
              <span>frames sent: {screenFramesSent}</span>
            </div>
            {screenError && (
              <div
                data-testid="perception-screen-error"
                style={{
                  fontSize: 9,
                  color: '#e0a0a0',
                  marginTop: 6,
                  lineHeight: 1.4,
                }}
              >
                {screenError}
              </div>
            )}
          </div>
        )}
      </div>

      {httpsWarn && (
        <div
          data-testid="perception-https-warn"
          style={{ fontSize: 9, color: STROKE_ENGINEERING, marginTop: 8, lineHeight: 1.4 }}
        >
          getUserMedia requires HTTPS on non-localhost hostnames.
        </div>
      )}

      {cameraError && (
        <div
          data-testid="perception-camera-error"
          style={{ fontSize: 9, color: '#e07060', marginTop: 8 }}
        >
          {cameraError}
        </div>
      )}
    </div>
  );
}
