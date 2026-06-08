/**
 * AD-930: AgentAvatarBadge optional presence overlay.
 *
 * The badge gains an optional `presence?` prop. When provided it overlays a
 * corner PresenceDot; when omitted it stays byte-identical to the pre-AD-930
 * single-span badge (backward compatible — existing call sites are unchanged).
 * Includes the HXI no-emoji guard.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

import { AgentAvatarBadge } from '../AgentAvatarBadge';

const EMOJI_RE = /\p{Extended_Pictographic}/u;

afterEach(() => {
  cleanup();
});

describe('AgentAvatarBadge presence overlay (AD-930)', () => {
  it('overlays a presence dot when the presence prop is provided', () => {
    render(
      <AgentAvatarBadge agentId="forge-1" callsign="Forge" department="engineering" presence="in_meeting" />,
    );
    expect(screen.getByTestId('agent-avatar-badge')).toBeTruthy();
    const dot = screen.getByTestId('presence-dot');
    expect(dot.getAttribute('data-presence')).toBe('in_meeting');
  });

  it('renders no presence dot when the prop is omitted (backward-compatible)', () => {
    render(
      <AgentAvatarBadge agentId="forge-1" callsign="Forge" department="engineering" />,
    );
    expect(screen.getByTestId('agent-avatar-badge')).toBeTruthy();
    expect(screen.queryByTestId('presence-dot')).toBeNull();
  });

  it('renders no emoji (HXI Design Principle #3)', () => {
    const { container } = render(
      <AgentAvatarBadge agentId="forge-1" callsign="Forge" department="engineering" presence="working" />,
    );
    expect(container.textContent || '').not.toMatch(EMOJI_RE);
  });
});
