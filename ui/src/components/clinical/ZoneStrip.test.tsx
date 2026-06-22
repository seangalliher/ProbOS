/** AD-905 vitest — ZoneStrip primitive. Verifies one colored segment per zone
 * (green/amber/red), the dim fallback for an unknown zone, the single baseline
 * rect for an empty history, and that the aria-label is present. */
import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { ZoneStrip } from './ZoneStrip';

describe('ZoneStrip (AD-905)', () => {
  afterEach(() => cleanup());

  it('renders_one_colored_segment_per_zone', () => {
    const { getByTestId } = render(
      <ZoneStrip
        zones={[
          { zone: 'green', timestamp: 1 },
          { zone: 'amber', timestamp: 2 },
          { zone: 'red', timestamp: 3 },
        ]}
        testId="zs"
        ariaLabel="zones"
      />,
    );
    const rects = getByTestId('zs').querySelectorAll('rect');
    expect(rects.length).toBe(3);
    expect(rects[0].getAttribute('fill')).toBe('#60c070');
    expect(rects[1].getAttribute('fill')).toBe('#f0b060');
    expect(rects[2].getAttribute('fill')).toBe('#d05050');
  });

  it('uses_dim_fill_for_unknown_zone', () => {
    const { getByTestId } = render(
      <ZoneStrip zones={[{ zone: 'teal', timestamp: 1 }]} testId="zs" ariaLabel="zones" />,
    );
    const rects = getByTestId('zs').querySelectorAll('rect');
    expect(rects.length).toBe(1);
    expect(rects[0].getAttribute('fill')).toBe('#666680');
  });

  it('renders_single_baseline_rect_when_empty', () => {
    const { getByTestId } = render(<ZoneStrip zones={[]} testId="zs" ariaLabel="zones" />);
    const rects = getByTestId('zs').querySelectorAll('rect');
    expect(rects.length).toBe(1);
    expect(rects[0].getAttribute('fill')).toBe('#222230');
  });

  it('exposes_aria_label', () => {
    const { getByTestId } = render(
      <ZoneStrip zones={[{ zone: 'green', timestamp: 1 }]} testId="zs" ariaLabel="Cognitive zone history" />,
    );
    expect(getByTestId('zs').getAttribute('aria-label')).toBe('Cognitive zone history');
  });
});
