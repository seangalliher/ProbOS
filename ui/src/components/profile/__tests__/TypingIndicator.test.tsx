// AD-952: TypingIndicator render tests. The text-chat equivalent of the AD-923
// meeting speaking indicator; HXI #3 (no emoji) + #4 (motion = state).
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { TypingIndicator } from '../TypingIndicator';

afterEach(cleanup);

// Matches any emoji / pictographic codepoint (HXI #3 guard).
const EMOJI = /\p{Extended_Pictographic}/u;

describe('AD-952 TypingIndicator', () => {
  it('renders the callsign and the "is typing" label', () => {
    render(<TypingIndicator callsign="Scout" />);
    const el = screen.getByTestId('typing-indicator');
    expect(el.textContent).toContain('Scout');
    expect(el.textContent).toContain('is typing');
  });

  it('exposes an accessible polite live label', () => {
    render(<TypingIndicator callsign="Bones" />);
    const el = screen.getByTestId('typing-indicator');
    expect(el.getAttribute('aria-label')).toBe('Bones is typing');
    expect(el.getAttribute('aria-live')).toBe('polite');
  });

  it('falls back to a generic name when the callsign is blank', () => {
    render(<TypingIndicator callsign="   " />);
    const el = screen.getByTestId('typing-indicator');
    expect(el.getAttribute('aria-label')).toBe('Someone is typing');
  });

  it('uses NO emoji (HXI #3 — stroke/SVG/text only)', () => {
    render(<TypingIndicator callsign="Scout" />);
    const el = screen.getByTestId('typing-indicator');
    expect(EMOJI.test(el.textContent || '')).toBe(false);
    // The whole rendered HTML (incl. the keyframe + dots) carries no emoji.
    expect(EMOJI.test(el.innerHTML)).toBe(false);
  });

  it('carries its own pulse motion (HXI #4 motion = state)', () => {
    render(<TypingIndicator callsign="Scout" />);
    const el = screen.getByTestId('typing-indicator');
    // The self-contained keyframe drives the dots.
    expect(el.innerHTML).toContain('hxi-typing-blink');
  });
});
