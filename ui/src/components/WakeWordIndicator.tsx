/* AD-705 (reframed): Wake-word listening indicator (HXI Design Principle #4).
 *
 * Three visual states map to three system states. Captain MUST never be
 * uncertain about whether the mic is hot.
 *
 *   off              → dim dot, no glow, no animation        (mic cold)
 *   armed            → amber stroke, low glow, slow breathing (mic listening)
 *   capturing        → amber stroke, high glow, fast pulse    (mic capturing)
 *   fallback-*       → same visual as armed/capturing, plus a one-line
 *                      "Voice unavailable: <reason>" label.
 *
 * Inline SVG only. No emoji. No Material icons. HXI Design Principle #3.
 */

import { useEffect, useState } from 'react';
import {
  getWakeWordState,
  onWakeWordState,
  type WakeFallbackReason,
  type WakeWordState,
  type WakeWordStateDetail,
} from '../audio/wakeWord';

const _AMBER = '#f0b060';
const _DIM = '#666680';
const _LABEL = '#aaaabb';

const _REASON_LABEL: Record<WakeFallbackReason, string> = {
  onnx_load_failed: 'ONNX runtime failed to load',
  mic_permission_denied: 'Microphone permission denied',
  speech_recognition_unavailable: 'Speech recognition not supported',
};

export function WakeWordIndicator(): JSX.Element | null {
  const [state, setState] = useState<WakeWordState>(() => getWakeWordState());
  const [detail, setDetail] = useState<WakeWordStateDetail>({});

  useEffect(() => {
    const unsub = onWakeWordState((next, nextDetail) => {
      setState(next);
      setDetail(nextDetail ?? {});
    });
    return unsub;
  }, []);

  if (state === 'off' && !detail.fallbackReason) {
    return null;
  }

  const isCapturing =
    state === 'capturing' || state === 'fallback-capturing';
  const isArmed = state === 'armed' || state === 'fallback-armed';
  const isFallback =
    state === 'fallback-armed' ||
    state === 'fallback-capturing' ||
    (state === 'off' && !!detail.fallbackReason);

  const dotColor = isArmed || isCapturing ? _AMBER : _DIM;
  const glow = isCapturing
    ? `drop-shadow(0 0 6px ${_AMBER}) drop-shadow(0 0 12px rgba(240,176,96,0.5))`
    : isArmed
      ? `drop-shadow(0 0 3px ${_AMBER})`
      : 'none';

  // Motion = state. Fast pulse on capture; slow breathing on armed; static
  // on off. The animation name uses existing project keyframes if present;
  // otherwise the inline `style` falls through gracefully (motion may
  // appear as steady glow on browsers that lack the keyframe). Tier-2
  // log-and-degrade.
  const animation = isCapturing
    ? 'wake-pulse-fast 0.5s ease-in-out infinite'
    : isArmed
      ? 'wake-pulse-slow 2s ease-in-out infinite'
      : undefined;

  const label = detail.fallbackReason
    ? `Voice unavailable: ${_REASON_LABEL[detail.fallbackReason]}`
    : null;

  const triggerLabel =
    isCapturing && detail.trigger ? `→ ${detail.trigger}` : null;

  return (
    <div
      data-testid="wake-word-indicator"
      data-state={state}
      data-fallback-reason={detail.fallbackReason ?? ''}
      style={{
        position: 'absolute',
        bottom: 44,
        right: 16,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        zIndex: 12,
        pointerEvents: 'none',
        fontFamily: 'monospace',
        fontSize: 11,
        color: _LABEL,
      }}
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        stroke={dotColor}
        strokeWidth="1.5"
        strokeLinecap="round"
        style={{
          filter: glow,
          animation,
        }}
        aria-hidden="true"
      >
        <circle cx="8" cy="8" r="3" />
        {(isArmed || isCapturing) && (
          <circle cx="8" cy="8" r="6" strokeOpacity={0.4} />
        )}
      </svg>
      {triggerLabel && (
        <span
          data-testid="wake-word-trigger-label"
          style={{ color: _AMBER, fontSize: 11 }}
        >
          {triggerLabel}
        </span>
      )}
      {label && (
        <span
          data-testid="wake-word-fallback-label"
          style={{ color: _LABEL, fontSize: 11 }}
        >
          {label}
        </span>
      )}
      <style>{`
        @keyframes wake-pulse-fast {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.6; transform: scale(1.18); }
        }
        @keyframes wake-pulse-slow {
          0%, 100% { opacity: 0.7; }
          50% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}
