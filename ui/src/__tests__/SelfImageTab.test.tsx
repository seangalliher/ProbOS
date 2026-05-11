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
  // AD-722a-5: the new PanelDivergenceHistory fetches /divergence-history
  // on mount. Return 503 for that URL so the panel auto-hides; the
  // returned vi.fn still records the call (one extra on initial mount).
  // Existing call-count assertions filter via ``mainTelemetryCalls``.
  return vi.fn((url: string) => {
    if (typeof url === 'string' && url.includes('/divergence-history')) {
      return Promise.resolve({
        ok: false,
        status: 503,
        json: () => Promise.resolve({ detail: 'divergence_detection_disabled' }),
      } as Response);
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(snapshot),
    } as Response);
  });
}

// AD-722a-5: count only main-telemetry fetches (filters divergence-history).
function mainTelemetryCalls(m: ReturnType<typeof vi.fn>): number {
  return m.mock.calls.filter(
    (c) => !(typeof c[0] === 'string' && c[0].includes('/divergence-history')),
  ).length;
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
    expect(mainTelemetryCalls(fetchMock)).toBe(1);
    await act(async () => {
      vi.advanceTimersByTime(2000);
      await Promise.resolve();
    });
    expect(mainTelemetryCalls(fetchMock)).toBe(2);
  });

  it('stops polling when isActive flips to false', async () => {
    const fetchMock = mockFetch(HAPPY_SNAPSHOT);
    vi.stubGlobal('fetch', fetchMock);
    const { rerender } = render(
      <SelfImageTab agentId="agent-007" isActive={true} />,
    );
    await flushMicrotasks();
    expect(mainTelemetryCalls(fetchMock)).toBe(1);
    rerender(<SelfImageTab agentId="agent-007" isActive={false} />);
    await act(async () => {
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
    });
    expect(mainTelemetryCalls(fetchMock)).toBe(1);
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
      expect(mainTelemetryCalls(fetchMock)).toBe(0);
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
      expect(mainTelemetryCalls(fetchMock)).toBe(0);
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
      expect(mainTelemetryCalls(fetchMock)).toBe(1);
      await act(async () => {
        vi.advanceTimersByTime(2000);
        await Promise.resolve();
      });
      expect(mainTelemetryCalls(fetchMock)).toBe(2);
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
      expect(mainTelemetryCalls(fetchMock)).toBe(0);
      await act(async () => {
        ws.simulateClose();
        await Promise.resolve();
      });
      // Poll fallback fires immediately on close.
      expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── AD-722b-6: WS reconnect with capped exponential backoff ──────────

  describe('AD-722b-6 reconnect with backoff', () => {
    beforeEach(() => {
      MockWebSocket.instances = [];
    });

    it('schedules reconnect at 1s after first close', async () => {
      const fetchMock = mockFetch(HAPPY_SNAPSHOT);
      vi.stubGlobal('fetch', fetchMock);
      vi.stubGlobal('WebSocket', MockWebSocket);
      render(<SelfImageTab agentId="agent-007" isActive={true} />);
      await flushMicrotasks();
      expect(MockWebSocket.instances.length).toBe(1);
      const ws = MockWebSocket.instances[0];
      await act(async () => {
        ws.simulateOpen();
        ws.simulateClose();
        await Promise.resolve();
      });
      // Just before 1 s — no reconnect yet.
      await act(async () => {
        vi.advanceTimersByTime(999);
        await Promise.resolve();
      });
      expect(MockWebSocket.instances.length).toBe(1);
      // Cross 1 s — reconnect fires.
      await act(async () => {
        vi.advanceTimersByTime(2);
        await Promise.resolve();
      });
      expect(MockWebSocket.instances.length).toBe(2);
    });

    it('uses exponential schedule 1s/2s/4s/8s', async () => {
      const fetchMock = mockFetch(HAPPY_SNAPSHOT);
      vi.stubGlobal('fetch', fetchMock);
      vi.stubGlobal('WebSocket', MockWebSocket);
      render(<SelfImageTab agentId="agent-007" isActive={true} />);
      await flushMicrotasks();
      // initial connect
      expect(MockWebSocket.instances.length).toBe(1);
      const expectedDelays = [1000, 2000, 4000, 8000];
      for (let i = 0; i < expectedDelays.length; i++) {
        const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
        await act(async () => {
          ws.simulateClose();
          await Promise.resolve();
        });
        // Just below the expected delay — no new connection.
        await act(async () => {
          vi.advanceTimersByTime(expectedDelays[i] - 1);
          await Promise.resolve();
        });
        expect(MockWebSocket.instances.length).toBe(i + 1);
        // Cross the threshold — reconnect fires.
        await act(async () => {
          vi.advanceTimersByTime(2);
          await Promise.resolve();
        });
        expect(MockWebSocket.instances.length).toBe(i + 2);
      }
    });

    it('stops reconnecting after 10 failed attempts', async () => {
      const fetchMock = mockFetch(HAPPY_SNAPSHOT);
      vi.stubGlobal('fetch', fetchMock);
      vi.stubGlobal('WebSocket', MockWebSocket);
      // eslint-disable-next-line @typescript-eslint/no-empty-function
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      render(<SelfImageTab agentId="agent-007" isActive={true} />);
      await flushMicrotasks();
      // Cycle: close -> advance 30s -> reconnect. 10 reconnect attempts max.
      for (let i = 0; i < 11; i++) {
        const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
        await act(async () => {
          ws.simulateClose();
          await Promise.resolve();
        });
        await act(async () => {
          vi.advanceTimersByTime(30_000);
          await Promise.resolve();
        });
      }
      // 1 initial + 10 reconnects = 11. 11th close exhausts; no 12th connect.
      expect(MockWebSocket.instances.length).toBe(11);
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('AD-722b-6: WS reconnect exhausted'),
      );
      warnSpy.mockRestore();
    });

    it('resets attempt counter on successful reconnect', async () => {
      const fetchMock = mockFetch(HAPPY_SNAPSHOT);
      vi.stubGlobal('fetch', fetchMock);
      vi.stubGlobal('WebSocket', MockWebSocket);
      render(<SelfImageTab agentId="agent-007" isActive={true} />);
      await flushMicrotasks();
      // Cycle 1: close at attempt=0 -> reconnect after 1 s.
      const ws1 = MockWebSocket.instances[0];
      await act(async () => {
        ws1.simulateClose();
        await Promise.resolve();
      });
      await act(async () => {
        vi.advanceTimersByTime(1001);
        await Promise.resolve();
      });
      expect(MockWebSocket.instances.length).toBe(2);
      // Successful open resets the counter.
      const ws2 = MockWebSocket.instances[1];
      await act(async () => {
        ws2.simulateOpen();
        await Promise.resolve();
      });
      // Cycle 2: close again; reconnect should be 1 s (not 2 s) because reset.
      await act(async () => {
        ws2.simulateClose();
        await Promise.resolve();
      });
      await act(async () => {
        vi.advanceTimersByTime(999);
        await Promise.resolve();
      });
      // Counter was reset → schedule is 1 s, not 2 s. At 999 ms no new conn.
      expect(MockWebSocket.instances.length).toBe(2);
      await act(async () => {
        vi.advanceTimersByTime(2);
        await Promise.resolve();
      });
      expect(MockWebSocket.instances.length).toBe(3);
    });
  });
});
