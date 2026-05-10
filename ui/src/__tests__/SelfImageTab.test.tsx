/**
 * AD-722: SelfImageTab tests — agent-observable avatar telemetry surface.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';
import { SelfImageTab } from '../components/profile/SelfImageTab';

// AD-722b: minimal in-tree WebSocket mock — records connect URL,
// surfaces onopen/onmessage/onerror/onclose so tests can simulate the
// browser's connection lifecycle.
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
  close() {
    this.closed = true;
    if (this.onclose) this.onclose();
  }
  simulateOpen() { if (this.onopen) this.onopen(); }
  simulateMessage(data: unknown) {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(data) });
  }
  simulateError() { if (this.onerror) this.onerror(); }
  simulateClose() { if (this.onclose) this.onclose(); }
}

const HAPPY_SNAPSHOT = {
  agent_id: 'agent-007',
  expression_resting: 'neutral',
  current_signals: {
    trust_delta: 0.12,
    load: 1.0,
    working_state: 'responding',
    tier3_alert: false,
  },
  mouth_active: true,
  applied_modulation: {
    pitch_factor: 0.9,
    rate_factor: 1.05,
    volume_factor: 0.8,
    fired_rules: ['responding_rate'],
  },
  dsl_summary: {
    body_type: 'average',
    hair_style: 'medium',
    primary_color: '#2a4a6a',
    outfit_style: 'uniform',
    color_palette_hint: 'warm',
  },
  last_observed_at: 1700000000.0,
  degraded_reasons: [],
};

function mockFetch(snapshot: unknown) {
  return vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve(snapshot),
    } as Response),
  );
}

async function flushMicrotasks() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('SelfImageTab (AD-722)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('renders all panel headers on happy snapshot', async () => {
    const fetchMock = mockFetch(HAPPY_SNAPSHOT);
    vi.stubGlobal('fetch', fetchMock);
    render(<SelfImageTab agentId="agent-007" isActive={true} />);
    await flushMicrotasks();
    expect(screen.getByTestId('panel-header-dsl-summary')).toBeTruthy();
    expect(screen.getByTestId('panel-header-current-signals')).toBeTruthy();
    expect(screen.getByTestId('panel-header-voice-modulation')).toBeTruthy();
    expect(screen.getByTestId('panel-header-mouth-active')).toBeTruthy();
  });

  it('polls every 2000ms when active', async () => {
    const fetchMock = mockFetch(HAPPY_SNAPSHOT);
    vi.stubGlobal('fetch', fetchMock);
    render(<SelfImageTab agentId="agent-007" isActive={true} />);
    await flushMicrotasks();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('stops polling when isActive flips to false', async () => {
    const fetchMock = mockFetch(HAPPY_SNAPSHOT);
    vi.stubGlobal('fetch', fetchMock);
    const { rerender } = render(
      <SelfImageTab agentId="agent-007" isActive={true} />,
    );
    await flushMicrotasks();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    rerender(<SelfImageTab agentId="agent-007" isActive={false} />);
    await act(async () => {
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('renders degraded-reasons strip when degraded_reasons present', async () => {
    const degraded = { ...HAPPY_SNAPSHOT, degraded_reasons: ['dsl_invalid'] };
    vi.stubGlobal('fetch', mockFetch(degraded));
    render(<SelfImageTab agentId="agent-007" isActive={true} />);
    await flushMicrotasks();
    expect(screen.getByTestId('degraded-strip')).toBeTruthy();
    expect(screen.getByTestId('degraded-reason-dsl_invalid')).toBeTruthy();
  });

  it('renders modulation factors as numbers (no formatted unit strings)', async () => {
    vi.stubGlobal('fetch', mockFetch(HAPPY_SNAPSHOT));
    render(<SelfImageTab agentId="agent-007" isActive={true} />);
    await flushMicrotasks();
    const rate = screen.getByTestId('mod-rate');
    expect(rate.textContent).toContain('1.05');
    expect(rate.textContent).not.toMatch(/x|×|%/);
  });

  it('mouth_active=true applies amber-active pulse class', async () => {
    vi.stubGlobal('fetch', mockFetch(HAPPY_SNAPSHOT));
    render(<SelfImageTab agentId="agent-007" isActive={true} />);
    await flushMicrotasks();
    const indicator = screen.getByTestId('mouth-active-indicator');
    expect(indicator.className).toContain('ad722-pulse-amber');
  });

  it('mouth_active=false omits the pulse class', async () => {
    const silent = { ...HAPPY_SNAPSHOT, mouth_active: false };
    vi.stubGlobal('fetch', mockFetch(silent));
    render(<SelfImageTab agentId="agent-007" isActive={true} />);
    await flushMicrotasks();
    const indicator = screen.getByTestId('mouth-active-indicator');
    expect(indicator.className).not.toContain('ad722-pulse-amber');
  });

  // ── AD-722b: WebSocket-first with poll fallback ─────────────────────

  describe('AD-722b WebSocket push channel', () => {
    beforeEach(() => {
      MockWebSocket.instances = [];
    });

    it('WS connects on mount and renders the first frame', async () => {
      const fetchMock = mockFetch(HAPPY_SNAPSHOT);
      vi.stubGlobal('fetch', fetchMock);
      vi.stubGlobal('WebSocket', MockWebSocket);
      render(<SelfImageTab agentId="agent-007" isActive={true} />);
      await flushMicrotasks();
      expect(MockWebSocket.instances.length).toBe(1);
      const ws = MockWebSocket.instances[0];
      await act(async () => {
        ws.simulateOpen();
        ws.simulateMessage(HAPPY_SNAPSHOT);
        await Promise.resolve();
      });
      expect(screen.getByTestId('panel-header-current-signals')).toBeTruthy();
      expect(fetchMock).toHaveBeenCalledTimes(0);
    });

    it('WS open suppresses poll path', async () => {
      const fetchMock = mockFetch(HAPPY_SNAPSHOT);
      vi.stubGlobal('fetch', fetchMock);
      vi.stubGlobal('WebSocket', MockWebSocket);
      render(<SelfImageTab agentId="agent-007" isActive={true} />);
      await flushMicrotasks();
      const ws = MockWebSocket.instances[0];
      await act(async () => {
        ws.simulateOpen();
        ws.simulateMessage(HAPPY_SNAPSHOT);
        await Promise.resolve();
      });
      await act(async () => {
        vi.advanceTimersByTime(5000);
        await Promise.resolve();
      });
      expect(fetchMock).toHaveBeenCalledTimes(0);
    });

    it('WS error before open falls back to poll', async () => {
      const fetchMock = mockFetch(HAPPY_SNAPSHOT);
      vi.stubGlobal('fetch', fetchMock);
      vi.stubGlobal('WebSocket', MockWebSocket);
      render(<SelfImageTab agentId="agent-007" isActive={true} />);
      await flushMicrotasks();
      const ws = MockWebSocket.instances[0];
      await act(async () => {
        ws.simulateError();
        await Promise.resolve();
      });
      // Initial poll fired by startPollFallback.
      expect(fetchMock).toHaveBeenCalledTimes(1);
      await act(async () => {
        vi.advanceTimersByTime(2000);
        await Promise.resolve();
      });
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it('WS close after open falls back to poll', async () => {
      const fetchMock = mockFetch(HAPPY_SNAPSHOT);
      vi.stubGlobal('fetch', fetchMock);
      vi.stubGlobal('WebSocket', MockWebSocket);
      render(<SelfImageTab agentId="agent-007" isActive={true} />);
      await flushMicrotasks();
      const ws = MockWebSocket.instances[0];
      await act(async () => {
        ws.simulateOpen();
        ws.simulateMessage(HAPPY_SNAPSHOT);
        await Promise.resolve();
      });
      expect(fetchMock).toHaveBeenCalledTimes(0);
      await act(async () => {
        ws.simulateClose();
        await Promise.resolve();
      });
      // Poll fallback fires immediately on close.
      expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(1);
    });
  });
});
