/**
 * AD-796 — YeoEmptyGreeting tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, act } from '@testing-library/react';
import {
  YeoEmptyGreeting,
  greetingForHour,
} from '../components/YeoEmptyGreeting';
import { useStore } from '../store/useStore';

function reset() {
  useStore.setState({ wardRoomUnread: {} });
}

describe('greetingForHour (AD-796)', () => {
  it('maps hours into morning / afternoon / evening windows', () => {
    expect(greetingForHour(0)).toBe('Good morning');
    expect(greetingForHour(11)).toBe('Good morning');
    expect(greetingForHour(12)).toBe('Good afternoon');
    expect(greetingForHour(17)).toBe('Good afternoon');
    expect(greetingForHour(18)).toBe('Good evening');
    expect(greetingForHour(23)).toBe('Good evening');
  });

  it('falls back gracefully on out-of-range input', () => {
    expect(greetingForHour(-1)).toBe('Hello');
    expect(greetingForHour(24)).toBe('Hello');
  });
});

describe('YeoEmptyGreeting (AD-796)', () => {
  beforeEach(() => {
    reset();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (typeof url === 'string' && url.includes('/api/health')) {
          return {
            ok: true,
            json: async () => ({ crew_agents: 4, agents: 12, health: 0.91 }),
          } as Response;
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    reset();
  });

  it('renders the time-of-day greeting using the supplied name', async () => {
    const morning = new Date('2026-05-21T08:00:00');
    await act(async () => {
      render(<YeoEmptyGreeting captainName="Sean" now={morning} />);
    });
    expect(screen.getByTestId('yeo-empty-greeting-title').textContent).toBe(
      'Good morning, Sean.',
    );
  });

  it('defaults to "Captain" when no name is supplied', async () => {
    const afternoon = new Date('2026-05-21T14:00:00');
    await act(async () => {
      render(<YeoEmptyGreeting now={afternoon} />);
    });
    expect(screen.getByTestId('yeo-empty-greeting-title').textContent).toBe(
      'Good afternoon, Captain.',
    );
  });

  it('renders crew count + unread WardRoom threads when both are available', async () => {
    useStore.setState({ wardRoomUnread: { 'thread-a': 2, 'thread-b': 1 } });
    await act(async () => {
      render(<YeoEmptyGreeting now={new Date('2026-05-21T10:00:00')} />);
    });
    await waitFor(() => {
      const status = screen.getByTestId('yeo-empty-greeting-status').textContent ?? '';
      expect(status).toContain('3 unread WardRoom threads');
      expect(status).toContain('4 crew online');
    });
  });

  it('renders "All quiet." when there is no unread and no crew info', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) } as Response)),
    );
    await act(async () => {
      render(<YeoEmptyGreeting now={new Date('2026-05-21T19:00:00')} />);
    });
    expect(screen.getByTestId('yeo-empty-greeting-status').textContent).toBe('All quiet.');
  });

  it('survives a fetch failure and still renders the greeting', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network down'); }));
    await act(async () => {
      render(<YeoEmptyGreeting captainName="Sean" now={new Date('2026-05-21T09:00:00')} />);
    });
    expect(screen.getByTestId('yeo-empty-greeting-title').textContent).toBe(
      'Good morning, Sean.',
    );
    expect(screen.getByTestId('yeo-empty-greeting-status').textContent).toBe('All quiet.');
  });
});
