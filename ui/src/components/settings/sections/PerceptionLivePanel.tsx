/**
 * AD-733: SettingsMain side-panel for the ``perception`` section.
 *
 * Renders ABOVE the standard generic-field rows so the operator can flip
 * the camera live without waiting for APPLY. Toggling
 * ``perception.camera.enabled`` calls ``startCameraStream`` / ``stopCameraStream``
 * directly — camera is a live thing, not just config.
 */
import { useCameraStore } from '../../../store/useCameraStore';
import { useSettingsStore } from '../../../store/useSettingsStore';
import { startCameraStream, stopCameraStream } from '../../../hooks/useCameraStream';

const STROKE_AMBER = '#f0b060';
const STROKE_DIM = '#666680';
const STROKE_ENGINEERING = '#e08040';

export default function PerceptionLivePanel() {
  const snapshot = useSettingsStore((s) => s.snapshot);
  const cameraActive = useCameraStore((s) => s.active);
  const cameraError = useCameraStore((s) => s.error);
  const framesSent = useCameraStore((s) => s.framesSent);

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
