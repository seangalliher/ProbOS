// AD-719: lightweight per-message attribution badge.
// 24/32px department-colored circle with first-letter-of-callsign initial.
// NOT to be confused with CrewAvatarPopout.tsx (3D VRM popout).
//
// Used ONLY in IntentSurface multi-reply rendering for v1. Do NOT refactor
// AgentProfilePanel.tsx's inline 8x8 dot to use this — that's scope creep.

import type { CSSProperties } from 'react';

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

interface Props {
  agentId: string;
  callsign: string;
  department?: string;
  size?: 24 | 32;
}

export function AgentAvatarBadge({ agentId: _agentId, callsign, department = '', size = 24 }: Props) {
  const color = DEPT_COLORS[department.toLowerCase()] ?? '#666';
  const initial = (callsign.charAt(0) || '?').toUpperCase();
  const style: CSSProperties = {
    width: size,
    height: size,
    borderRadius: '50%',
    background: color,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#0a0a12',
    fontWeight: 600,
    fontSize: size * 0.5,
    flexShrink: 0,
  };
  return (
    <span style={style} aria-label={`Agent ${callsign}`} data-testid="agent-avatar-badge">
      {initial}
    </span>
  );
}
