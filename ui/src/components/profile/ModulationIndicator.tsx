import { useEffect, useState } from 'react';
import { onSpeechEvent } from '../../audio/voice';

interface Props {
  agentId: string;
}

/**
 * AD-718d-1: small SVG dim-pulse overlay that signals when the voice
 * modulation logic from AD-718d is actively shaping a speech utterance
 * for the given agent. Subscribes to onSpeechEvent — pulses on `start`,
 * fades on `end`. Tier-2 log-and-degrade: subscription failures fall
 * through silently and the indicator stays in idle state.
 *
 * HXI principles:
 *  - No emoji; stroke-only SVG glyph.
 *  - Motion communicates state (pulse = active, fade = idle).
 *  - Amber active (#f0b060), dim inactive (#666680).
 *
 * Forward marker: onSpeechEvent has no agent_id-keyed registry; every
 * mount adds a global listener that filters internally. Acceptable at
 * v1 — future optimization site is `voice.ts:_fire` (per-agent bucket).
 */
export function ModulationIndicator({ agentId }: Props) {
  const [active, setActive] = useState(false);

  useEffect(() => {
    const unsub = onSpeechEvent((evt) => {
      if (evt.agent_id !== agentId) return;
      if (evt.type === 'start') setActive(true);
      if (evt.type === 'end') setActive(false);
    });
    return () => {
      try { unsub(); } catch { /* unsub registry was reinitialized; tolerable */ }
    };
  }, [agentId]);

  const stroke = active ? '#f0b060' : '#666680';
  const filter = active ? 'drop-shadow(0 0 4px #f0b060)' : 'none';
  return (
    <span
      data-testid="modulation-indicator"
      data-active={active ? 'true' : 'false'}
      title={active ? 'voice modulation active' : 'voice modulation idle'}
      style={{
        display: 'inline-flex',
        width: 14,
        height: 14,
        marginLeft: 6,
        opacity: active ? 1 : 0.5,
        transition: 'opacity 200ms ease',
        animation: active ? 'modulation-pulse 1.2s ease-in-out infinite' : 'none',
        filter,
      }}
    >
      {/* Audio-bars glyph: three vertical strokes, middle tallest.
          Generic enough that future locales/themes don't need translation. */}
      <svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true">
        <line x1="3"  y1="9"  x2="3"  y2="5" stroke={stroke} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="7"  y1="11" x2="7"  y2="3" stroke={stroke} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="11" y1="9"  x2="11" y2="5" stroke={stroke} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <style>{`
        @keyframes modulation-pulse {
          0%, 100% { transform: scale(1); }
          50%      { transform: scale(1.18); }
        }
      `}</style>
    </span>
  );
}
