/**
 * AD-742e: VisionBudgetBadge tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';

import { VisionBudgetBadge } from '../VisionBudgetBadge';

function mockFetch(snapshot: Record<string, unknown>) {
  return vi.spyOn(globalThis, 'fetch' as any).mockResolvedValue({
    ok: true,
    json: async () => snapshot,
  } as Response);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('VisionBudgetBadge (AD-742e)', () => {
  it('renders nothing when fetch returns total_session=0', async () => {
    mockFetch({
      session_id: 's',
      calls_this_session: { vision: 0, vision_fast: 0 },
      calls_today: { vision: 0, vision_fast: 0 },
      total_session: 0,
      total_today: 0,
      session_ceiling_estimate: 120,
      next_allowed_in_seconds: 0,
      consumer_wired: true,
    });
    render(<VisionBudgetBadge />);
    await waitFor(() => {
      expect(screen.queryByTestId('vision-budget-badge')).toBeNull();
    });
  });

  it('renders badge when total_session > 0', async () => {
    mockFetch({
      session_id: 's',
      calls_this_session: { vision: 12, vision_fast: 0 },
      calls_today: { vision: 12, vision_fast: 0 },
      total_session: 12,
      total_today: 12,
      session_ceiling_estimate: 120,
      next_allowed_in_seconds: 0,
      consumer_wired: true,
    });
    render(<VisionBudgetBadge />);
    await waitFor(() => {
      expect(screen.getByTestId('vision-budget-badge')).toBeTruthy();
      expect(screen.getByText('12/120')).toBeTruthy();
    });
  });

  it('renders amber when below 80% ceiling', async () => {
    mockFetch({
      session_id: 's',
      calls_this_session: { vision: 10, vision_fast: 0 },
      calls_today: { vision: 10, vision_fast: 0 },
      total_session: 10,
      total_today: 10,
      session_ceiling_estimate: 120,
      next_allowed_in_seconds: 0,
      consumer_wired: true,
    });
    render(<VisionBudgetBadge />);
    await waitFor(() => {
      const text = screen.getByText('10/120') as HTMLElement;
      expect(text.style.color).toBe('rgb(240, 176, 96)'); // #f0b060
    });
  });

  it('renders dim-red when 80-100%', async () => {
    mockFetch({
      session_id: 's',
      calls_this_session: { vision: 100, vision_fast: 0 },
      calls_today: { vision: 100, vision_fast: 0 },
      total_session: 100,
      total_today: 100,
      session_ceiling_estimate: 120,
      next_allowed_in_seconds: 0,
      consumer_wired: true,
    });
    render(<VisionBudgetBadge />);
    await waitFor(() => {
      const text = screen.getByText('100/120') as HTMLElement;
      expect(text.style.color).toBe('rgb(200, 64, 48)'); // #c84030
    });
  });

  it('renders bright-red when at/above ceiling', async () => {
    mockFetch({
      session_id: 's',
      calls_this_session: { vision: 120, vision_fast: 0 },
      calls_today: { vision: 120, vision_fast: 0 },
      total_session: 120,
      total_today: 120,
      session_ceiling_estimate: 120,
      next_allowed_in_seconds: 0,
      consumer_wired: true,
    });
    render(<VisionBudgetBadge />);
    await waitFor(() => {
      const text = screen.getByText('120/120') as HTMLElement;
      expect(text.style.color).toBe('rgb(224, 64, 48)'); // #e04030
    });
  });

  it('hover-title shows per-tier breakdown', async () => {
    mockFetch({
      session_id: 's',
      calls_this_session: { vision: 8, vision_fast: 4 },
      calls_today: { vision: 10, vision_fast: 5 },
      total_session: 12,
      total_today: 15,
      session_ceiling_estimate: 120,
      next_allowed_in_seconds: 1.5,
      consumer_wired: true,
    });
    render(<VisionBudgetBadge />);
    await waitFor(() => {
      const badge = screen.getByTestId('vision-budget-badge');
      const title = badge.getAttribute('title') || '';
      expect(title).toContain('vision: 8 calls');
      expect(title).toContain('vision_fast: 4 calls');
      expect(title).toContain('today: 15');
      expect(title).toContain('next in 1.5s');
    });
  });
});
