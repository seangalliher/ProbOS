/**
 * BF-294b — MicIndicator intensity-driven ring tests.
 *
 * Verifies the optional ``intensity`` prop drives inline opacity/scale,
 * while the BF-294 keyframe fallback remains intact when ``intensity``
 * is undefined or state !== 'listening'.
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { MicIndicator } from '../MicIndicator';

describe('MicIndicator BF-294b (amplitude-driven ring)', () => {
  it('regression: no intensity prop falls back to BF-294 keyframe animation', () => {
    const { getByTestId } = render(<MicIndicator state="listening" />);
    const ring = getByTestId('mic-indicator-ring-listening');
    const style = ring.getAttribute('style') || '';
    expect(style).toContain('bf294-mic-listen');
    expect(ring.getAttribute('data-bf294b-mode')).toBe('keyframe');
  });

  it('intensity=0.5 applies inline opacity/scale and suppresses keyframe', () => {
    const { getByTestId } = render(<MicIndicator state="listening" intensity={0.5} />);
    const ring = getByTestId('mic-indicator-ring-listening');
    const style = ring.getAttribute('style') || '';
    expect(ring.getAttribute('data-bf294b-mode')).toBe('amplitude');
    expect(style).not.toContain('bf294-mic-listen');
    // 0.35 + 0.65*0.5 = 0.675 opacity; 1.0 + 0.35*0.5 = 1.175 scale
    expect(style).toMatch(/opacity:\s*0\.675/);
    expect(style).toMatch(/scale\(1\.175\)/);
  });

  it('intensity is clamped to [0, 1] — out-of-range values do not break layout', () => {
    const { getByTestId, rerender } = render(<MicIndicator state="listening" intensity={1.5} />);
    let style = getByTestId('mic-indicator-ring-listening').getAttribute('style') || '';
    expect(style).toMatch(/opacity:\s*1(\D|$)/);
    expect(style).toMatch(/scale\(1\.35\)/);

    rerender(<MicIndicator state="listening" intensity={-0.2} />);
    style = getByTestId('mic-indicator-ring-listening').getAttribute('style') || '';
    expect(style).toMatch(/opacity:\s*0\.35/);
    expect(style).toMatch(/scale\(1\)/);
  });

  it('intensity only applies in listening state — processing/idle ignore it', () => {
    const { queryByTestId, rerender } = render(
      <MicIndicator state="processing" intensity={0.9} />,
    );
    expect(queryByTestId('mic-indicator-ring-listening')).toBeNull();
    const procRing = queryByTestId('mic-indicator-ring-processing');
    expect(procRing).not.toBeNull();
    expect(procRing!.getAttribute('style') || '').toContain('bf294-mic-process');

    rerender(<MicIndicator state="idle" intensity={0.9} />);
    expect(queryByTestId('mic-indicator-ring-listening')).toBeNull();
    expect(queryByTestId('mic-indicator-ring-processing')).toBeNull();
  });

  it('NaN / Infinity intensity falls back to keyframe mode', () => {
    const { getByTestId, rerender } = render(<MicIndicator state="listening" intensity={NaN} />);
    let ring = getByTestId('mic-indicator-ring-listening');
    expect(ring.getAttribute('data-bf294b-mode')).toBe('keyframe');
    expect(ring.getAttribute('style') || '').toContain('bf294-mic-listen');

    rerender(<MicIndicator state="listening" intensity={Infinity} />);
    ring = getByTestId('mic-indicator-ring-listening');
    expect(ring.getAttribute('data-bf294b-mode')).toBe('keyframe');
  });
});
