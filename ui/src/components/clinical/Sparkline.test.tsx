/** AD-905 vitest — Sparkline primitive. Verifies the ≥2-point polyline, the
 * <2-point dashed baseline, that a caller-supplied [min,max] window is honored
 * over the data's own range, and the HXI no-emoji guard. */
import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { Sparkline } from './Sparkline';

const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F1E6}-\u{1F1FF}]/u;

describe('Sparkline (AD-905)', () => {
  afterEach(() => cleanup());

  it('renders_polyline_for_two_or_more_values', () => {
    const { getByTestId } = render(
      <Sparkline values={[0.2, 0.5, 0.9]} testId="sp" ariaLabel="trend" />,
    );
    const svg = getByTestId('sp');
    expect(svg.querySelector('polyline')).toBeTruthy();
    expect(svg.querySelector('path[stroke-dasharray]')).toBeNull();
  });

  it('renders_dashed_baseline_for_fewer_than_two_values', () => {
    const { getByTestId } = render(
      <Sparkline values={[0.7]} testId="sp" ariaLabel="trend" />,
    );
    const svg = getByTestId('sp');
    expect(svg.querySelector('path[stroke-dasharray]')).toBeTruthy();
    expect(svg.querySelector('polyline')).toBeNull();
  });

  it('honors_fixed_min_max_window_over_data_range', () => {
    // Degenerate series [0.5, 0.5]: with the data's own range it collapses to
    // the baseline y=22; with a fixed 0..1 window it normalizes to mid (y=12).
    const withWindow = render(
      <Sparkline values={[0.5, 0.5]} min={0} max={1} testId="win" ariaLabel="t" />,
    );
    const winPts = withWindow.getByTestId('win').querySelector('polyline')!.getAttribute('points');
    expect(winPts).toContain('12.00');
    cleanup();

    const noWindow = render(<Sparkline values={[0.5, 0.5]} testId="raw" ariaLabel="t" />);
    const rawPts = noWindow.getByTestId('raw').querySelector('polyline')!.getAttribute('points');
    expect(rawPts).toContain('22.00');
    expect(rawPts).not.toContain('12.00');
  });

  it('exposes_aria_label_and_contains_no_emoji', () => {
    const { getByTestId, container } = render(
      <Sparkline values={[0.1, 0.9]} testId="sp" ariaLabel="Trust score trend" />,
    );
    expect(getByTestId('sp').getAttribute('aria-label')).toBe('Trust score trend');
    expect(EMOJI.test(container.innerHTML)).toBe(false);
  });
});
