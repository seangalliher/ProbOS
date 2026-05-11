/**
 * AD-722a-5: divergence history surface tests for SelfImageTab.
 *
 * Tests the PanelDivergenceHistory subcomponent. WebSocket is stubbed to
 * undefined so the main telemetry channel falls through to poll, leaving
 * fetch as the only mocked transport — divergence-history then routes
 * through fetch as designed.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';
import { SelfImageTab } from '../components/profile/SelfImageTab';

// Minimal main-telemetry snapshot so the parent component renders
// (the divergence panel is rendered alongside the main panels).
const TELEMETRY_SNAPSHOT = {
  agent_id: 'agent-007',
  expression_resting: 'neutral',
  current_signals: {
    trust_delta: 0.0,
    load: 0.5,
    working_state: 'idle',
    tier3_alert: false,
  },
  mouth_active: false,
  applied_modulation: null,
  dsl_summary: null,
  last_observed_at: 1700000000.0,
  degraded_reasons: [],
};

const HISTORY_PAYLOAD = {
  agent_id: 'agent-007',
  history: [
    {
      timestamp: 1700000010.0,
      result: {
        intent_emotion: 'warm',
        applied_fired_rules: ['intent_warm'],
        match_score: 1.0,
        signed_divergence: 0.0,
        magnitude: 0.0,
      },
      note: 'Reply intended as `warm` came out as `intent_warm` (signed divergence: +0.00, match score: 1.00).',
    },
    {
      timestamp: 1700000020.0,
      result: {
        intent_emotion: 'concerned',
        applied_fired_rules: ['intent_warm'],
        match_score: 0.0,
        signed_divergence: -1.0,
        magnitude: 1.0,
      },
      note: 'Reply intended as `concerned` came out as `intent_warm` (signed divergence: -1.00, match score: 0.00).',
    },
  ],
  aggregate: {
    window_size: 2,
    total: 2,
    diverged: 2,
    percentage: 1.0,
  },
};

const EMPTY_HISTORY_PAYLOAD = {
  agent_id: 'agent-007',
  history: [],
  aggregate: {
    window_size: 0,
    total: 0,
    diverged: 0,
    percentage: 0.0,
  },
};

function makeFetch(historyResponse: {
  status: number;
  body?: unknown;
}) {
  return vi.fn((url: string) => {
    if (typeof url === 'string' && url.includes('/divergence-history')) {
      if (historyResponse.status === 503) {
        return Promise.resolve({
          ok: false,
          status: 503,
          json: () => Promise.resolve({ detail: 'divergence_detection_disabled' }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(historyResponse.body),
      } as Response);
    }
    // Main telemetry endpoint.
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(TELEMETRY_SNAPSHOT),
    } as Response);
  });
}

async function flushMicrotasks() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('SelfImageTab divergence history (AD-722a-5)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Disable WebSocket so the main telemetry path falls through to fetch
    // and the divergence-history panel's fetch is the focus.
    vi.stubGlobal('WebSocket', undefined);
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('renders entries + aggregate percentage when history is non-empty', async () => {
    const fetchMock = makeFetch({ status: 200, body: HISTORY_PAYLOAD });
    vi.stubGlobal('fetch', fetchMock);
    render(<SelfImageTab agentId="agent-007" isActive={true} />);
    await flushMicrotasks();

    const aggregate = screen.getByTestId('divergence-aggregate');
    expect(aggregate).toBeTruthy();
    expect(aggregate.textContent).toContain('100%');
    const entries = screen.getAllByTestId('divergence-history-entry');
    expect(entries.length).toBe(2);
  });

  it('renders "no divergences recorded" fallback on empty history', async () => {
    const fetchMock = makeFetch({ status: 200, body: EMPTY_HISTORY_PAYLOAD });
    vi.stubGlobal('fetch', fetchMock);
    render(<SelfImageTab agentId="agent-007" isActive={true} />);
    await flushMicrotasks();

    const aggregate = screen.getByTestId('divergence-aggregate');
    expect(aggregate.textContent).toContain('no divergences recorded');
    expect(screen.queryAllByTestId('divergence-history-entry').length).toBe(0);
  });

  it('hides panel entirely on 503 (feature off)', async () => {
    const fetchMock = makeFetch({ status: 503 });
    vi.stubGlobal('fetch', fetchMock);
    render(<SelfImageTab agentId="agent-007" isActive={true} />);
    await flushMicrotasks();

    expect(screen.queryByTestId('divergence-aggregate')).toBeNull();
    expect(screen.queryByTestId('divergence-history-list')).toBeNull();
    expect(screen.queryByTestId('divergence-loading')).toBeNull();
  });
});
