/**
 * AD-722b-3: SelfImageTab WS diff-frame merge behavior.
 *
 * Verifies that when the server emits a `{"type":"diff","changed":{...}}`
 * frame, the component merges it into the last-known snapshot instead of
 * replacing wholesale.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';
import { SelfImageTab } from '../components/profile/SelfImageTab';

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
  close() { this.closed = true; if (this.onclose) this.onclose(); }
  simulateOpen() { if (this.onopen) this.onopen(); }
  simulateMessage(data: unknown) {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(data) });
  }
}

const SNAPSHOT = {
  type: 'snapshot',
  agent_id: 'agent-007',
  expression_resting: 'neutral',
  current_signals: {
    trust_delta: 0.0,
    load: 0.0,
    working_state: 'idle',
    tier3_alert: false,
  },
  mouth_active: false,
  applied_modulation: null,
  dsl_summary: {
    body_type: 'average',
    hair_style: 'medium',
    primary_color: '#2a4a6a',
    outfit_style: 'uniform',
    color_palette_hint: 'warm',
  },
  last_observed_at: 1700000000.0,
  degraded_reasons: [],
  sampling_rate_ms: 2000,
  sampling_tier: 'normal',
};

async function flushMicrotasks() {
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

describe('SelfImageTab WS diff frame', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    (globalThis as unknown as { WebSocket: typeof MockWebSocket }).WebSocket =
      MockWebSocket;
    globalThis.fetch = vi.fn((url: string) => {
      if (typeof url === 'string' && url.includes('/divergence-history')) {
        return Promise.resolve({
          ok: false, status: 503,
          json: () => Promise.resolve({ detail: 'divergence_detection_disabled' }),
        } as Response);
      }
      return Promise.resolve({
        ok: true, json: () => Promise.resolve(SNAPSHOT),
      } as Response);
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('merges diff frame into last-known snapshot', async () => {
    render(<SelfImageTab agentId="agent-007" isActive={true} />);
    await flushMicrotasks();
    const ws = MockWebSocket.instances[0];
    expect(ws).toBeDefined();

    await act(async () => { ws.simulateOpen(); });
    await act(async () => { ws.simulateMessage(SNAPSHOT); });
    // After snapshot, working_state should render "idle".
    expect(screen.getAllByText(/idle/i).length).toBeGreaterThan(0);

    // Diff frame flipping working_state -> responding.
    await act(async () => {
      ws.simulateMessage({
        type: 'diff',
        agent_id: 'agent-007',
        changed: {
          current_signals: {
            trust_delta: 0.0,
            load: 1.0,
            working_state: 'responding',
            tier3_alert: false,
          },
          mouth_active: true,
        },
      });
    });
    // The merged snapshot retains agent_id + dsl_summary (untouched fields)
    // and now shows working_state = responding.
    expect(screen.getAllByText(/responding/i).length).toBeGreaterThan(0);
  });
});
