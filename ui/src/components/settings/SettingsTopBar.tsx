/* AD-741 — Top bar (DISCARD, APPLY, VIEW YAML) + status bar + YAML modal. */

import { useSettingsStore } from '../../store/useSettingsStore';
import { useCameraStore } from '../../store/useCameraStore';

const STROKE_AMBER = '#f0b060';
const STROKE_DIM = '#666680';
const STROKE_ENGINEERING = '#e08040';

export function SettingsTopBar() {
  const draftCount = useSettingsStore(s => s.draftCount);
  const discardDraft = useSettingsStore(s => s.discardDraft);
  const applyDraft = useSettingsStore(s => s.applyDraft);
  const openYaml = useSettingsStore(s => s.openYaml);
  const closeSettings = useSettingsStore(s => s.closeSettings);
  const applyStatus = useSettingsStore(s => s.applyStatus);
  const cameraActive = useCameraStore(s => s.active);
  const dirty = draftCount > 0;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 14px',
        // BF-300: reserve space on the right for the persistent CAMERA LIVE
        // indicator (position:fixed, top:8, right:8, ~170px wide) so it does
        // not occlude the close (×) button or APPLY/DISCARD.
        paddingRight: cameraActive ? 190 : 14,
        borderBottom: '1px solid rgba(240,176,96,0.15)',
        background: 'rgba(10,10,18,0.7)',
      }}
    >
      <span
        style={{
          color: '#e0c090',
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: 2,
        }}
      >
        SETTINGS
      </span>
      <div style={{ flex: 1 }} />
      <button
        onClick={openYaml}
        data-testid="settings-topbar-view-yaml"
        style={{
          background: 'transparent',
          border: `1px solid ${STROKE_DIM}`,
          color: '#a0a0b0',
          padding: '4px 10px',
          fontSize: 10,
          letterSpacing: 1,
          cursor: 'pointer',
          borderRadius: 3,
        }}
      >
        VIEW YAML
      </button>
      <button
        onClick={discardDraft}
        disabled={!dirty}
        data-testid="settings-topbar-discard"
        style={{
          background: 'transparent',
          border: `1px solid ${dirty ? STROKE_ENGINEERING : 'rgba(102,102,128,0.4)'}`,
          color: dirty ? STROKE_ENGINEERING : 'rgba(102,102,128,0.5)',
          padding: '4px 10px',
          fontSize: 10,
          letterSpacing: 1,
          cursor: dirty ? 'pointer' : 'default',
          borderRadius: 3,
        }}
      >
        DISCARD
      </button>
      <button
        onClick={applyDraft}
        disabled={!dirty}
        data-testid="settings-topbar-apply"
        style={{
          background: dirty ? 'rgba(240,176,96,0.15)' : 'transparent',
          border: `1px solid ${dirty ? STROKE_AMBER : 'rgba(102,102,128,0.4)'}`,
          color: dirty ? STROKE_AMBER : 'rgba(102,102,128,0.5)',
          padding: '4px 12px',
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 1,
          cursor: dirty ? 'pointer' : 'default',
          borderRadius: 3,
        }}
      >
        APPLY ↵
      </button>
      <button
        onClick={closeSettings}
        data-testid="settings-topbar-close"
        style={{
          background: 'transparent',
          border: 'none',
          color: STROKE_DIM,
          fontSize: 18,
          cursor: 'pointer',
          padding: '0 6px',
        }}
        aria-label="Close settings"
      >
        ×
      </button>
      {applyStatus === 'restart_required' && (
        <span
          data-testid="settings-restart-banner"
          style={{
            color: STROKE_ENGINEERING,
            fontSize: 10,
            letterSpacing: 1,
            marginLeft: 8,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <svg
            width="11"
            height="11"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M8 2 L15 14 L1 14 Z" />
            <line x1="8" y1="6" x2="8" y2="10" />
            <line x1="8" y1="12" x2="8" y2="12.5" />
          </svg>
          PROBOS RESTART REQUIRED
        </span>
      )}
    </div>
  );
}

export function SettingsStatusBar() {
  const snapshot = useSettingsStore(s => s.snapshot);
  const draftCount = useSettingsStore(s => s.draftCount);
  const applyStatus = useSettingsStore(s => s.applyStatus);
  const applyMessage = useSettingsStore(s => s.applyMessage);

  if (!snapshot) return null;
  const inSync = draftCount === 0 && applyStatus !== 'rejected';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '4px 14px',
        borderTop: '1px solid rgba(240,176,96,0.10)',
        background: 'rgba(10,10,18,0.6)',
        fontSize: 9,
        letterSpacing: 0.5,
        color: STROKE_DIM,
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      <span style={{ color: inSync ? STROKE_AMBER : STROKE_ENGINEERING }}>●</span>
      <span>config {snapshot.config_path || '(in-memory)'}</span>
      <span style={{ color: inSync ? '#7fa070' : STROKE_ENGINEERING }}>
        {inSync ? 'in sync' : `unsynced (${draftCount} drafts)`}
      </span>
      {applyMessage && (
        <span data-testid="settings-status-message" style={{ color: STROKE_ENGINEERING }}>
          {applyMessage}
        </span>
      )}
    </div>
  );
}

export function YamlModal() {
  const yamlOpen = useSettingsStore(s => s.yamlOpen);
  const yamlText = useSettingsStore(s => s.yamlText);
  const yamlLoading = useSettingsStore(s => s.yamlLoading);
  const closeYaml = useSettingsStore(s => s.closeYaml);

  if (!yamlOpen) return null;
  return (
    <div
      data-testid="settings-yaml-modal"
      style={{
        position: 'absolute',
        inset: 0,
        background: 'rgba(0,0,0,0.7)',
        zIndex: 5,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          width: '80%',
          maxWidth: 800,
          maxHeight: '80%',
          background: '#0a0a12',
          border: `1px solid ${STROKE_AMBER}`,
          padding: 16,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 8,
          }}
        >
          <span style={{ color: STROKE_AMBER, fontSize: 11, letterSpacing: 2 }}>SYSTEM.YAML</span>
          <button
            onClick={closeYaml}
            style={{
              background: 'transparent',
              border: 'none',
              color: STROKE_DIM,
              fontSize: 18,
              cursor: 'pointer',
            }}
          >
            ×
          </button>
        </div>
        <pre
          data-testid="settings-yaml-pre"
          style={{
            margin: 0,
            flex: 1,
            overflow: 'auto',
            background: 'rgba(20,20,32,0.6)',
            color: '#c8c8d8',
            padding: 12,
            fontSize: 10,
            fontFamily: "'JetBrains Mono', monospace",
            lineHeight: 1.5,
          }}
        >
          {yamlLoading ? 'Loading…' : yamlText}
        </pre>
        <div style={{ color: STROKE_DIM, fontSize: 9, marginTop: 6 }}>
          Read-only in v1. Direct editing arrives in AD-741-6. Comments and key
          ordering are NOT preserved on round-trip; the file is auto-stamped
          “# Edited via HXI” on APPLY.
        </div>
      </div>
    </div>
  );
}
