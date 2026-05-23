/**
 * BF-294 — MicIndicator visual-state tests.
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { MicIndicator } from '../MicIndicator';

describe('MicIndicator (BF-294)', () => {
  it('idle state renders no ring overlay', () => {
    const { queryByTestId, getByTestId } = render(<MicIndicator state="idle" />);
    expect(getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
    expect(queryByTestId('mic-indicator-ring-listening')).toBeNull();
    expect(queryByTestId('mic-indicator-ring-processing')).toBeNull();
  });

  it('listening state renders the pulsing ring with amber color', () => {
    const { getByTestId, queryByTestId } = render(<MicIndicator state="listening" />);
    const ring = getByTestId('mic-indicator-ring-listening');
    expect(ring).toBeTruthy();
    // JSDOM normalises hex to rgb(); amber #f0b060 → rgb(240, 176, 96).
    expect(ring.getAttribute('style') || '').toContain('rgb(240, 176, 96)');
    expect(ring.getAttribute('style') || '').toContain('bf294-mic-listen');
    expect(queryByTestId('mic-indicator-ring-processing')).toBeNull();
  });

  it('processing state renders the shimmer ring with dim-amber color', () => {
    const { getByTestId, queryByTestId } = render(<MicIndicator state="processing" />);
    const ring = getByTestId('mic-indicator-ring-processing');
    expect(ring).toBeTruthy();
    // JSDOM normalises hex to rgb(); dim-amber #a08040 → rgb(160, 128, 64).
    expect(ring.getAttribute('style') || '').toContain('rgb(160, 128, 64)');
    expect(ring.getAttribute('style') || '').toContain('bf294-mic-process');
    expect(queryByTestId('mic-indicator-ring-listening')).toBeNull();
  });

  it('state prop drives data-bf294-state attribute on re-render', () => {
    const { getByTestId, rerender } = render(<MicIndicator state="idle" />);
    expect(getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
    rerender(<MicIndicator state="listening" />);
    expect(getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('listening');
    rerender(<MicIndicator state="processing" />);
    expect(getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('processing');
    rerender(<MicIndicator state="idle" />);
    expect(getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
  });

  it('SVG glyph stroke color matches the active state palette', () => {
    const { container, rerender } = render(<MicIndicator state="idle" />);
    const svgIdle = container.querySelector('svg');
    expect(svgIdle?.getAttribute('stroke')).toBe('#8888aa');
    rerender(<MicIndicator state="listening" />);
    expect(container.querySelector('svg')?.getAttribute('stroke')).toBe('#f0b060');
    rerender(<MicIndicator state="processing" />);
    expect(container.querySelector('svg')?.getAttribute('stroke')).toBe('#a08040');
  });
});
