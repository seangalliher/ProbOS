/**
 * BF-294 — Three-state mic affordance.
 *
 * States:
 *   - idle:       static mic glyph, neutral grey
 *   - listening:  amber glyph + pulsing amber ring (CSS @keyframes)
 *   - processing: dim-amber glyph + shimmer ring (CSS @keyframes)
 *
 * HXI compliance:
 *   - #3 No emoji — inline SVG glyph only, strokeWidth 1.5, strokeLinecap round.
 *   - #4 Motion communicates state — distinct animations per state.
 *   - Trust-spectrum palette: #f0b060 active amber, #a08040 dim amber.
 *
 * The component is presentational only. Parent supplies `state` and the
 * usual ``onClick`` / ``aria-label`` / ``title`` props for the button
 * wrapper. ``MicIndicator`` renders the SVG glyph + animated ring overlay,
 * NOT the <button> element itself — parents wrap it in a <button> so they
 * keep ownership of click handling, aria-haspopup, refs, etc.
 */
import React from 'react';

export type MicIndicatorState = 'idle' | 'listening' | 'processing';

export interface MicIndicatorProps {
  state: MicIndicatorState;
  /** Size of the rendered SVG glyph in px. Default 14 to match the
   *  existing mic button in ProfileChatTab. */
  size?: number;
}

const PALETTE = {
  idle: '#8888aa',
  listening: '#f0b060',
  processing: '#a08040',
} as const;

export function MicIndicator({ state, size = 14 }: MicIndicatorProps): React.ReactElement {
  const color = PALETTE[state];
  // data-bf294-state lets tests assert state without DOM-traversal heuristics.
  return (
    <span
      data-testid="mic-indicator"
      data-bf294-state={state}
      style={{
        position: 'relative',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: size,
        height: size,
      }}
    >
      {state === 'listening' && (
        <span
          data-testid="mic-indicator-ring-listening"
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: -4,
            borderRadius: '50%',
            border: `1.5px solid ${PALETTE.listening}`,
            animation: 'bf294-mic-listen 1.1s ease-in-out infinite',
            pointerEvents: 'none',
          }}
        />
      )}
      {state === 'processing' && (
        <span
          data-testid="mic-indicator-ring-processing"
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: -4,
            borderRadius: '50%',
            border: `1.5px dashed ${PALETTE.processing}`,
            animation: 'bf294-mic-process 1.4s linear infinite',
            pointerEvents: 'none',
          }}
        />
      )}
      <svg
        width={size}
        height={size}
        viewBox="0 0 16 16"
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <line x1="8" y1="2" x2="8" y2="9" />
        <path d="M5 7c0 1.7 1.3 3 3 3s3-1.3 3-3" />
        <line x1="8" y1="12" x2="8" y2="14" />
        <line x1="6" y1="14" x2="10" y2="14" />
      </svg>
    </span>
  );
}
