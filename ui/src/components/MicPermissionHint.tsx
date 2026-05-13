/** AD-736: Captain-visible mic permission state surface.
 *
 *  Subscribes to ``onMicPermissionState`` and renders one of:
 *    - 'pending' → nothing (loop will probe on first activation)
 *    - 'granted' → nothing (default operational state)
 *    - 'denied' → mic SVG + one-line dismissible hint
 *    - 'unavailable' → dim mic SVG + one-line non-dismissible label
 *
 *  Dismissal is sticky via ``localStorage`` so refresh keeps it.
 */
import { useEffect, useState } from 'react';
import {
  onMicPermissionState,
  type MicPermissionState,
} from '../audio/wakeWord';

const DISMISS_KEY = 'hxi_mic_hint_dismissed';

export function MicPermissionHint(): JSX.Element | null {
  const [state, setState] = useState<MicPermissionState>('pending');
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(DISMISS_KEY) === '1';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    return onMicPermissionState(setState);
  }, []);

  if (state === 'pending' || state === 'granted') return null;
  if (state === 'denied' && dismissed) return null;

  const isDenied = state === 'denied';
  const stroke = isDenied ? '#f0b060' : '#666680';
  const message = isDenied
    ? "Voice input blocked. Click the microphone icon in your browser's address bar to enable it, then refresh."
    : 'No microphone detected. Voice input is disabled.';

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Voice input unavailable"
      data-testid="mic-permission-hint"
      data-state={state}
      style={{
        position: 'fixed',
        bottom: 12,
        right: 12,
        maxWidth: 320,
        padding: '8px 10px',
        background: 'rgba(20, 20, 32, 0.92)',
        border: `1px solid ${stroke}33`,
        borderRadius: 4,
        color: '#e0dcd4',
        fontSize: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        zIndex: 1000,
      }}
    >
      {/* AD-736: inline SVG mic glyph (HXI Design Principle #3 — no emoji). */}
      <svg
        width="14"
        height="14"
        viewBox="0 0 16 16"
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        aria-hidden="true"
        style={{ flexShrink: 0 }}
      >
        <rect x="6" y="2" width="4" height="8" rx="2" />
        <path d="M3 7v1a5 5 0 0 0 10 0V7" />
        <path d="M8 13v2" />
        {!isDenied && <path d="M3 3l10 10" />}
      </svg>
      <span style={{ flex: 1 }}>{message}</span>
      {isDenied && (
        <button
          type="button"
          aria-label="Dismiss hint"
          data-testid="mic-permission-dismiss"
          onClick={() => {
            try {
              localStorage.setItem(DISMISS_KEY, '1');
            } catch {
              // Tier-1 swallow: localStorage unavailable (private mode).
            }
            setDismissed(true);
          }}
          style={{
            border: 'none',
            background: 'transparent',
            color: '#8888a0',
            cursor: 'pointer',
            fontSize: 14,
            padding: '0 4px',
          }}
        >
          ×
        </button>
      )}
    </div>
  );
}
