// AD-930: Teams-style crew presence dot. Pure presentational.
// Color encodes presence; motion (amber pulse) encodes "working"
// (HXI #4 — motion communicates state). Inline SVG-style circle via a
// styled <span>, NO emoji (HXI #3).
import type { PresenceState } from '../../store/types';

const PRESENCE_COLOR: Record<PresenceState, string> = {
  online: '#60c070',     // alive + idle — calm green
  working: '#f0b060',    // active — amber (HXI active color), pulses
  in_meeting: '#5090d0', // in a meeting room — blue
  offline: '#666680',    // not alive — dim
};

const PRESENCE_LABEL: Record<PresenceState, string> = {
  online: 'Online',
  working: 'Working',
  in_meeting: 'In a meeting',
  offline: 'Offline',
};

export function PresenceDot({ state, size = 8, title }: {
  state: PresenceState;
  size?: number;
  title?: string;
}) {
  const color = PRESENCE_COLOR[state] ?? PRESENCE_COLOR.offline;
  const label = title ?? PRESENCE_LABEL[state] ?? 'Offline';
  const pulsing = state === 'working';
  return (
    <>
      <style>{`@keyframes presenceDotPulse{0%,100%{opacity:1}50%{opacity:.45}}`}</style>
      <span
        data-testid="presence-dot"
        data-presence={state}
        data-pulse={pulsing ? 'true' : undefined}
        role="img"
        aria-label={label}
        title={label}
        style={{
          display: 'inline-block',
          width: size,
          height: size,
          borderRadius: '50%',
          background: color,
          flexShrink: 0,
          boxShadow: pulsing ? `0 0 4px ${color}` : 'none',
          animation: pulsing ? 'presenceDotPulse 1.8s ease-in-out infinite' : 'none',
        }}
      />
    </>
  );
}
