/**
 * AD-930: PresenceDot — Teams-style crew presence indicator.
 *
 * Pure presentational SVG-style dot. Color encodes presence; the amber
 * "working" state pulses (HXI #4 — motion communicates state). Tests assert
 * the data-presence contract per state, the working-only data-pulse marker,
 * and the HXI no-emoji guard (rendered output + source).
 */
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

import { PresenceDot } from '../PresenceDot';
import PresenceDotSource from '../PresenceDot?raw';

const EMOJI_RE = /\p{Extended_Pictographic}/u;

afterEach(() => {
  cleanup();
});

describe('PresenceDot (AD-930)', () => {
  it('renders online as a green dot', () => {
    render(<PresenceDot state="online" />);
    const dot = screen.getByTestId('presence-dot');
    expect(dot.getAttribute('data-presence')).toBe('online');
    expect(dot).toHaveStyle({ background: '#60c070' });
  });

  it('renders working as an amber pulsing dot', () => {
    render(<PresenceDot state="working" />);
    const dot = screen.getByTestId('presence-dot');
    expect(dot.getAttribute('data-presence')).toBe('working');
    expect(dot.getAttribute('data-pulse')).toBe('true');
    expect(dot).toHaveStyle({ background: '#f0b060' });
  });

  it('renders in_meeting as a blue dot', () => {
    render(<PresenceDot state="in_meeting" />);
    const dot = screen.getByTestId('presence-dot');
    expect(dot.getAttribute('data-presence')).toBe('in_meeting');
    expect(dot).toHaveStyle({ background: '#5090d0' });
  });

  it('renders offline as a dim dot', () => {
    render(<PresenceDot state="offline" />);
    const dot = screen.getByTestId('presence-dot');
    expect(dot.getAttribute('data-presence')).toBe('offline');
    expect(dot).toHaveStyle({ background: '#666680' });
  });

  it('only the working state carries the data-pulse marker', () => {
    const { rerender } = render(<PresenceDot state="working" />);
    expect(screen.getByTestId('presence-dot').getAttribute('data-pulse')).toBe('true');
    for (const state of ['online', 'in_meeting', 'offline'] as const) {
      rerender(<PresenceDot state={state} />);
      expect(screen.getByTestId('presence-dot').getAttribute('data-pulse')).toBeNull();
    }
  });

  it('renders no emoji (HXI Design Principle #3 — stroke/SVG icons only)', () => {
    const { container } = render(<PresenceDot state="working" />);
    expect(container.innerHTML).not.toMatch(EMOJI_RE);
    expect(PresenceDotSource).not.toMatch(EMOJI_RE);
  });
});
